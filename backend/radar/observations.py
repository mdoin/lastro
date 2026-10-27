"""Observações de mercado versionadas e leitura "como era conhecido em" (point-in-time).

Uma revisão do valor publicado pela fonte vira nova linha (revision + 1, supersedes_id); a anterior continua lá.
Assim um registro do Diário sempre consegue mostrar o dado que existia no momento da detecção.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_engine.money import to_decimal

# Duas séries que medem a mesma coisa: divergência marca a observação nova como "suspeita".
CROSS_CHECKS = {"ipca_sidra": "ipca_mensal", "ipca_mensal": "ipca_sidra"}
CROSS_TOLERANCE = Decimal("0.005")


@dataclass(frozen=True)
class Point:
    reference_date: str
    value: Decimal
    obs_id: int
    revision: int
    fetched_at: str
    quality: str

    def as_dict(self) -> dict:
        return {"reference_date": self.reference_date, "value": str(self.value), "observation_id": self.obs_id,
                "revision": self.revision, "fetched_at": self.fetched_at, "quality": self.quality}


def ensure_series(conn: sqlite3.Connection, series_id: str, *, source: str, label: str, unit: str, frequency: str,
                  category: str, max_age_days: int, now: str, currency: str | None = None, url: str = "",
                  meta: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO market_series (series_id, source, label, unit, currency, frequency, category, max_age_days, url, "
        "meta_json, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET "
        "last_seen = excluded.last_seen",
        (series_id, source, label, unit, currency, frequency, category, max_age_days, url,
         json.dumps(meta or {}, ensure_ascii=False, sort_keys=True), now, now))


def series_meta(conn: sqlite3.Connection, series_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM market_series WHERE series_id = ?", (series_id,)).fetchone()
    if not row:
        return None
    return {**dict(row), "meta": json.loads(row["meta_json"])}


def list_series(conn: sqlite3.Connection, *, source: str | None = None, category: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM market_series WHERE 1=1", []
    if source:
        sql, args = sql + " AND source = ?", [*args, source]
    if category:
        sql, args = sql + " AND category = ?", [*args, category]
    return [{**dict(r), "meta": json.loads(r["meta_json"])} for r in conn.execute(sql + " ORDER BY series_id", args)]


def _current(conn, series_id: str, reference_date: str):
    return conn.execute("SELECT * FROM market_observations WHERE series_id = ? AND reference_date = ? "
                        "ORDER BY revision DESC LIMIT 1", (series_id, reference_date)).fetchone()


def record(conn: sqlite3.Connection, series_id: str, reference_date: str, value, *, fetched_at: str) -> str:
    """Grava uma observação. Retorna 'nova', 'revisao' ou 'igual' (nada gravado)."""
    meta = series_meta(conn, series_id)
    if meta is None:
        raise ValueError(f"série desconhecida: {series_id[:60]}")
    date.fromisoformat(reference_date)
    number = to_decimal(value)
    current = _current(conn, series_id, reference_date)
    if current is not None and to_decimal(current["value"]) == number:
        return "igual"
    quality, info = ("revisado", {"valor_anterior": current["value"], "revisao_anterior": current["revision"]}) \
        if current is not None else ("ok", {})
    other = CROSS_CHECKS.get(series_id)
    if other:
        twin = _current(conn, other, reference_date)
        if twin is not None and abs(to_decimal(twin["value"]) - number) > CROSS_TOLERANCE:
            quality, info = "suspeito", {**info, "diverge_de": other, "valor_da_outra_fonte": twin["value"]}
    conn.execute(
        "INSERT INTO market_observations (source, series_id, reference_date, value, unit, currency, frequency, revision, "
        "supersedes_id, fetched_at, quality, quality_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (meta["source"], series_id, reference_date, str(number), meta["unit"], meta["currency"], meta["frequency"],
         (current["revision"] + 1) if current is not None else 1, current["id"] if current is not None else None,
         fetched_at, quality, json.dumps(info, ensure_ascii=False, sort_keys=True)))
    return "revisao" if current is not None else "nova"


def history(conn: sqlite3.Connection, series_id: str, *, until: str | None = None, known_at: str | None = None,
            since: str | None = None) -> list[Point]:
    """Série em ordem de data. `until` corta datas de referência; `known_at` usa só o que já tinha sido coletado
    naquele instante (a revisão vigente na época), para que nenhum cálculo histórico use informação futura."""
    known = known_at or "9999-12-31T99"
    rows = conn.execute(
        "SELECT o.* FROM market_observations o WHERE o.series_id = ? AND o.reference_date <= ? AND o.reference_date >= ? "
        "AND o.fetched_at <= ? AND o.revision = (SELECT MAX(i.revision) FROM market_observations i WHERE "
        "i.series_id = o.series_id AND i.reference_date = o.reference_date AND i.fetched_at <= ?) "
        "ORDER BY o.reference_date",
        (series_id, until or "9999-12-31", since or "0000-01-01", known, known)).fetchall()
    return [Point(r["reference_date"], to_decimal(r["value"]), r["id"], r["revision"], r["fetched_at"], r["quality"])
            for r in rows]


def get_observation(conn: sqlite3.Connection, obs_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM market_observations WHERE id = ?", (obs_id,)).fetchone()
    return {**dict(row), "quality_info": json.loads(row["quality_json"])} if row else None


def revisions_after(conn: sqlite3.Connection, obs_id: int) -> list[dict]:
    """Revisões publicadas depois de uma observação (para saber se o dado que disparou o sinal mudou)."""
    base = get_observation(conn, obs_id)
    if not base:
        return []
    rows = conn.execute("SELECT * FROM market_observations WHERE series_id = ? AND reference_date = ? AND revision > ? "
                        "ORDER BY revision", (base["series_id"], base["reference_date"], base["revision"])).fetchall()
    return [dict(r) for r in rows]


def validity(meta: dict, reference_date: str | None, today: date) -> str:
    if not reference_date:
        return "indisponivel"
    return "valido" if (today - date.fromisoformat(reference_date)).days <= meta["max_age_days"] else "desatualizado"


def prune(conn: sqlite3.Connection, *, older_than: str) -> int:
    """Retenção: apaga observações antigas que nenhum sinal usa (os sinais e o Diário guardam o que usaram)."""
    # Apaga a data inteira (todas as revisões) ou nada: nunca deixa uma revisão antiga parecendo a vigente.
    cur = conn.execute("DELETE FROM market_observations WHERE reference_date < ? AND (series_id, reference_date) NOT IN "
                       "(SELECT o.series_id, o.reference_date FROM market_observations o "
                       "JOIN radar_signals s ON s.observation_id = o.id)", (older_than,))
    return cur.rowcount
