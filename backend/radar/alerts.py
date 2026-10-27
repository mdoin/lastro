# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alertas do Radar: decisão de alertar, deduplicação, cooldown, silêncio, limites e histórico de entrega.

O alerta dentro do Lastro é persistente (tabela radar_alerts) e sempre registrado. Canais externos (e-mail,
Telegram, push PWA) exigem configuração e consentimento; enquanto o transporte não estiver configurado, a entrega
fica registrada como "não configurado" — nunca é fingida.
"""

import re
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import journal

EXTERNAL_CHANNELS = ("email", "telegram", "webpush")
# Transportes implementados: nenhum externo ainda (ver docs/RADAR.md §Notificações). Um transporte novo entra aqui.
TRANSPORTS: dict = {}
DEFAULT_PREFS = {"min_priority": 3, "quiet_start": "22:00", "quiet_end": "07:00", "max_per_day": 5,
                 "cooldown_hours": 72, "max_analyses_per_day": 4}


def prefs(conn, user_id: str) -> dict:
    row = conn.execute("SELECT * FROM radar_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return {**DEFAULT_PREFS, **({k: row[k] for k in DEFAULT_PREFS} if row else {})}


def _hhmm(text: str) -> str:
    time.fromisoformat(text)
    return text[:5]


def save_prefs(conn, user_id: str, data: dict, now: str) -> dict:
    merged = {**prefs(conn, user_id), **{k: v for k, v in data.items() if k in DEFAULT_PREFS}}
    checks = {"min_priority": (1, 5), "max_per_day": (0, 100), "cooldown_hours": (0, 24 * 60),
              "max_analyses_per_day": (0, 50)}
    for key, (lo, hi) in checks.items():
        merged[key] = int(merged[key])
        if not lo <= merged[key] <= hi:
            raise ValueError(f"{key}: entre {lo} e {hi}.")
    merged["quiet_start"], merged["quiet_end"] = _hhmm(merged["quiet_start"]), _hhmm(merged["quiet_end"])
    conn.execute("INSERT INTO radar_prefs (user_id, min_priority, quiet_start, quiet_end, max_per_day, cooldown_hours, "
                 "max_analyses_per_day, updated_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                 "min_priority = excluded.min_priority, quiet_start = excluded.quiet_start, quiet_end = excluded.quiet_end, "
                 "max_per_day = excluded.max_per_day, cooldown_hours = excluded.cooldown_hours, "
                 "max_analyses_per_day = excluded.max_analyses_per_day, updated_at = excluded.updated_at",
                 (user_id, merged["min_priority"], merged["quiet_start"], merged["quiet_end"], merged["max_per_day"],
                  merged["cooldown_hours"], merged["max_analyses_per_day"], now))
    return prefs(conn, user_id)


def channels(conn, user_id: str) -> list[dict]:
    rows = {r["channel"]: dict(r) for r in conn.execute("SELECT * FROM radar_channels WHERE user_id = ?", (user_id,))}
    return [{"channel": c, "enabled": bool(rows.get(c, {}).get("enabled")), "consent_at": rows.get(c, {}).get("consent_at"),
             "transport_ready": c in TRANSPORTS} for c in EXTERNAL_CHANNELS]


def set_channel(conn, user_id: str, channel: str, enabled: bool, consent: bool, now: str) -> list[dict]:
    if channel not in EXTERNAL_CHANNELS:
        raise ValueError("canal desconhecido")
    if enabled and not consent:
        raise ValueError("Ativar um canal externo exige seu consentimento explícito.")
    conn.execute("INSERT INTO radar_channels (user_id, channel, enabled, consent_at, updated_at) VALUES (?,?,?,?,?) "
                 "ON CONFLICT(user_id, channel) DO UPDATE SET enabled = excluded.enabled, "
                 "consent_at = excluded.consent_at, updated_at = excluded.updated_at",
                 (user_id, channel, 1 if enabled else 0, now if enabled else None, now))
    return channels(conn, user_id)


def in_quiet_hours(moment: datetime, p: dict, tz: ZoneInfo) -> bool:
    local = moment.astimezone(tz).time()
    start, end = time.fromisoformat(p["quiet_start"]), time.fromisoformat(p["quiet_end"])
    return start <= local or local < end if start > end else start <= local < end


_TD_FAMILY = re.compile(r"^(td_[a-z_]+?)_\d{4}-\d{2}-\d{2}_")


def group_key(opp: dict) -> str:
    """Alertas semelhantes: mesma regra e mesmo ativo — para títulos do Tesouro, a mesma família (todos os
    vencimentos do Tesouro IPCA+ contam como um só assunto), senão a mesma notícia vira dez alertas."""
    series = opp["series_id"] or "-"
    match = _TD_FAMILY.match(series)
    return f"{opp['rule_id']}:{match.group(1) if match else series}"


def mute(conn, user_id: str, key: str, days: int, now: datetime) -> dict:
    if not 1 <= days <= 365:
        raise ValueError("days: entre 1 e 365.")
    rec = {"id": str(uuid.uuid4()), "user_id": user_id, "group_key": key,
           "until": (now + timedelta(days=days)).isoformat(timespec="seconds"), "created_at": now.isoformat(timespec="seconds")}
    conn.execute("INSERT INTO radar_mutes (id, user_id, group_key, until, created_at) VALUES "
                 "(:id,:user_id,:group_key,:until,:created_at)", rec)
    return rec


def _muted(conn, user_id: str, key: str, now: str) -> bool:
    return conn.execute("SELECT 1 FROM radar_mutes WHERE user_id = ? AND group_key = ? AND until > ?",
                        (user_id, key, now)).fetchone() is not None


def _title(opp: dict, condition: str) -> str:
    return f"{opp['asset_label']}: {condition}"[:200]


def process(conn, opp: dict, condition: str, now: datetime, tz: ZoneInfo) -> dict:
    """Decide e registra o alerta de uma oportunidade avaliada. Retorna {'action': ..., 'alert_id': ...}."""
    stamp = now.isoformat(timespec="seconds")
    p = prefs(conn, opp["user_id"])
    key = group_key(opp)
    if opp["classification"] < p["min_priority"] and opp["classification"] != 5:
        return {"action": "sem_alerta", "reason": f"classificação abaixo do mínimo configurado ({p['min_priority']})"}
    if _muted(conn, opp["user_id"], key, stamp):
        journal.event(conn, opp["id"], "alerta_silenciado", stamp, grupo=key)
        return {"action": "silenciado", "reason": "alertas semelhantes silenciados por você"}
    since = (now - timedelta(hours=p["cooldown_hours"])).isoformat(timespec="seconds")
    recent = conn.execute("SELECT * FROM radar_alerts WHERE user_id = ? AND group_key = ? AND last_occurrence_at >= ? "
                          "ORDER BY created_at DESC LIMIT 1", (opp["user_id"], key, since)).fetchone()
    if recent:
        conn.execute("UPDATE radar_alerts SET occurrences = occurrences + 1, last_occurrence_at = ?, updated_at = ? "
                     "WHERE id = ?", (stamp, stamp, recent["id"]))
        conn.execute("UPDATE radar_opportunities SET redundant_of = ? WHERE id = ?", (recent["opportunity_id"], opp["id"]))
        _deliver(conn, recent["id"], "inapp", "suprimido", "agrupado com alerta recente (cooldown)", stamp)
        journal.event(conn, opp["id"], "alerta_agrupado", stamp, alerta=recent["id"])
        return {"action": "agrupado", "alert_id": recent["id"]}
    alert_id = str(uuid.uuid4())
    conn.execute("INSERT INTO radar_alerts (id, user_id, opportunity_id, group_key, title, priority, status, occurrences, "
                 "last_occurrence_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (alert_id, opp["user_id"], opp["id"], key, _title(opp, condition), opp["classification"], "novo", 1,
                  stamp, stamp, stamp))
    day_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    delivered_today = conn.execute(
        "SELECT COUNT(*) FROM radar_deliveries d JOIN radar_alerts a ON a.id = d.alert_id WHERE a.user_id = ? AND "
        "d.channel = 'inapp' AND d.status = 'entregue' AND d.at >= ?", (opp["user_id"], day_start)).fetchone()[0]
    over_limit = delivered_today >= p["max_per_day"] and opp["classification"] != 5
    _deliver(conn, alert_id, "inapp", "suprimido" if over_limit else "entregue",
             "limite diário de notificações atingido (o alerta fica na lista)" if over_limit else "", stamp)
    quiet = in_quiet_hours(now, p, tz)
    for ch in channels(conn, opp["user_id"]):
        if not ch["enabled"]:
            continue
        if not ch["transport_ready"]:
            _deliver(conn, alert_id, ch["channel"], "nao_configurado", "transporte do canal ainda não configurado", stamp)
        elif quiet and opp["classification"] != 5:
            _deliver(conn, alert_id, ch["channel"], "adiado", "horário de silêncio", stamp)
        else:
            try:
                TRANSPORTS[ch["channel"]](alert_id)
                _deliver(conn, alert_id, ch["channel"], "entregue", "", stamp)
            except Exception as exc:  # noqa: BLE001
                _deliver(conn, alert_id, ch["channel"], "falhou", type(exc).__name__, stamp)
    return {"action": "alerta", "alert_id": alert_id}


def _deliver(conn, alert_id: str, channel: str, status: str, reason: str, at: str) -> None:
    conn.execute("INSERT INTO radar_deliveries (id, alert_id, channel, status, reason, at) VALUES (?,?,?,?,?,?)",
                 (str(uuid.uuid4()), alert_id, channel, status, reason, at))


def get(conn, alert_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM radar_alerts WHERE id = ?", (alert_id,)).fetchone()
    return dict(row) if row else None


def deliveries(conn, alert_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT channel, status, reason, at FROM radar_deliveries WHERE alert_id = ? "
                                          "ORDER BY at", (alert_id,))]


def set_status(conn, alert_id: str, status: str, now: str) -> None:
    if status not in ("visto", "analisado", "silenciado"):
        raise ValueError("status inválido")
    conn.execute("UPDATE radar_alerts SET status = ?, updated_at = ? WHERE id = ?", (status, now, alert_id))
    journal.event(conn, get(conn, alert_id)["opportunity_id"], f"alerta_{status}", now)


def set_feedback(conn, alert_id: str, feedback: str, now: str) -> None:
    if feedback not in ("util", "irrelevante"):
        raise ValueError("feedback: util ou irrelevante")
    conn.execute("UPDATE radar_alerts SET feedback = ?, updated_at = ? WHERE id = ?", (feedback, now, alert_id))
    journal.event(conn, get(conn, alert_id)["opportunity_id"], "avaliacao_da_pessoa", now, utilidade=feedback)


def list_for(conn, user_id: str, *, status: str | None = None, limit: int = 100) -> list[dict]:
    sql, args = ("SELECT a.*, o.category, o.asset_label, o.series_id, o.state, o.classification, s.condition_text, "
                 "s.reference_date, s.detected_at FROM radar_alerts a JOIN radar_opportunities o ON o.id = "
                 "a.opportunity_id JOIN radar_signals s ON s.id = o.signal_id WHERE a.user_id = ?", [user_id])
    if status:
        sql, args = sql + " AND a.status = ?", [*args, status]
    rows = conn.execute(sql + " ORDER BY a.created_at DESC LIMIT ?", [*args, limit]).fetchall()
    return [dict(r) for r in rows]


def unread_count(conn, user_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM radar_alerts WHERE user_id = ? AND status = 'novo'", (user_id,)).fetchone()[0]

