# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotinas agendadas: cálculo da agenda, persistência e o laço do agendador.

Regras (inspiradas no desenho de rotinas do OpenBot, implementação própria):
- uma execução por ocorrência: UNIQUE(routine_id, scheduled_for);
- ocorrências perdidas (servidor desligado) nunca são todas reexecutadas:
  `skip` registra uma execução "missed"; `run_once` roda só a mais recente;
- se a rotina já tem execução em andamento, a nova ocorrência vira "skipped";
- a execução pode terminar "quiet" (sem novidade): fica registrada, mas não notifica.
"""

import asyncio
import json
import logging
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import utcnow
from .store import add_message, create_conversation, new_id

log = logging.getLogger("lastro.routines")

KINDS = ("daily", "weekly", "monthly", "once")
LATE_TOLERANCE = timedelta(minutes=10)  # atraso aceito antes de considerar a ocorrência "perdida"
SUMMARY_LIMIT = 1500


# ---------- agenda ----------

def validate_schedule(schedule: dict, tz_name: str) -> dict:
    kind = schedule.get("kind")
    if kind not in KINDS:
        raise ValueError(f"schedule.kind: use {', '.join(KINDS)}.")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone inválido.") from exc
    try:
        hh, mm = (int(x) for x in str(schedule.get("time", "")).split(":"))
        time(hh, mm)
    except ValueError as exc:
        raise ValueError("schedule.time: use HH:MM.") from exc
    clean = {"kind": kind, "time": f"{hh:02d}:{mm:02d}"}
    if kind == "weekly":
        weekday = int(schedule.get("weekday", -1))
        if not 0 <= weekday <= 6:
            raise ValueError("schedule.weekday: de 0 (segunda) a 6 (domingo).")
        clean["weekday"] = weekday
    if kind == "monthly":
        day = int(schedule.get("day", 0))
        if not 1 <= day <= 28:
            raise ValueError("schedule.day: de 1 a 28.")
        clean["day"] = day
    if kind == "once":
        clean["date"] = date.fromisoformat(str(schedule.get("date"))).isoformat()
    return clean


def next_occurrence(schedule: dict, tz_name: str, after: datetime) -> datetime | None:
    """Primeira ocorrência estritamente depois de `after` (UTC), em UTC."""
    tz = ZoneInfo(tz_name)
    hh, mm = (int(x) for x in schedule["time"].split(":"))
    local_after = after.astimezone(tz)
    kind = schedule["kind"]

    def at(day: date) -> datetime:
        return datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(timezone.utc)

    if kind == "once":
        candidate = at(date.fromisoformat(schedule["date"]))
        return candidate if candidate > after else None
    day = local_after.date()
    for _ in range(400):  # no máximo ~13 meses de busca
        matches = (kind == "daily"
                   or (kind == "weekly" and day.weekday() == schedule["weekday"])
                   or (kind == "monthly" and day.day == schedule["day"]))
        if matches and at(day) > after:
            return at(day)
        day += timedelta(days=1)
    return None


# ---------- persistência ----------

def _row_to_routine(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    last = conn.execute("SELECT * FROM routine_runs WHERE routine_id = ? ORDER BY scheduled_for DESC LIMIT 1",
                        (row["id"],)).fetchone()
    return {"id": row["id"], "name": row["name"], "instruction": row["instruction"],
            "schedule": json.loads(row["schedule_json"]), "timezone": row["timezone"], "active": bool(row["active"]),
            "missed_policy": row["missed_policy"], "use_panel": bool(row["use_panel"]),
            "next_run_at": row["next_run_at"], "last_run": run_to_dict(last) if last else None}


def run_to_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "routine_id": row["routine_id"],
            "routine_name": row["routine_name"] if "routine_name" in row.keys() else None,
            "scheduled_for": row["scheduled_for"],
            "started_at": row["started_at"], "finished_at": row["finished_at"], "status": row["status"],
            "summary": row["summary"], "conversation_id": row["conversation_id"], "read": bool(row["read"])}


def _values(data: dict) -> dict:
    name = str(data.get("name", "")).strip()[:120]
    instruction = str(data.get("instruction", "")).strip()[:4000]
    if not name or not instruction:
        raise ValueError("name e instruction são obrigatórios.")
    tz_name = str(data.get("timezone") or "America/Sao_Paulo")
    missed = data.get("missed_policy", "skip")
    if missed not in ("skip", "run_once"):
        raise ValueError("missed_policy: use skip ou run_once.")
    return {"name": name, "instruction": instruction, "schedule": validate_schedule(data.get("schedule") or {}, tz_name),
            "timezone": tz_name, "active": bool(data.get("active", True)), "missed_policy": missed,
            "use_panel": bool(data.get("use_panel", False))}


def _next_run(v: dict, now: datetime) -> str | None:
    if not v["active"]:
        return None
    nxt = next_occurrence(v["schedule"], v["timezone"], now)
    return nxt.isoformat(timespec="seconds") if nxt else None


def create_routine(conn: sqlite3.Connection, data: dict, now: datetime | None = None) -> dict:
    v, rid, stamp = _values(data), new_id(), utcnow()
    now = now or datetime.now(timezone.utc)
    conn.execute("INSERT INTO routines (id, name, instruction, schedule_json, timezone, active, missed_policy, use_panel, "
                 "next_run_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (rid, v["name"], v["instruction"], json.dumps(v["schedule"]), v["timezone"], int(v["active"]),
                  v["missed_policy"], int(v["use_panel"]), _next_run(v, now), stamp, stamp))
    return get_routine(conn, rid)


def update_routine(conn: sqlite3.Connection, rid: str, data: dict, now: datetime | None = None) -> dict | None:
    v = _values(data)
    now = now or datetime.now(timezone.utc)
    cur = conn.execute("UPDATE routines SET name=?, instruction=?, schedule_json=?, timezone=?, active=?, missed_policy=?, "
                       "use_panel=?, next_run_at=?, updated_at=? WHERE id=?",
                       (v["name"], v["instruction"], json.dumps(v["schedule"]), v["timezone"], int(v["active"]),
                        v["missed_policy"], int(v["use_panel"]), _next_run(v, now), utcnow(), rid))
    return get_routine(conn, rid) if cur.rowcount else None


def get_routine(conn: sqlite3.Connection, rid: str) -> dict | None:
    row = conn.execute("SELECT * FROM routines WHERE id = ?", (rid,)).fetchone()
    return _row_to_routine(conn, row) if row else None


def list_routines(conn: sqlite3.Connection) -> list[dict]:
    return [_row_to_routine(conn, r) for r in conn.execute("SELECT * FROM routines ORDER BY name").fetchall()]


def delete_routine(conn: sqlite3.Connection, rid: str) -> bool:
    return conn.execute("DELETE FROM routines WHERE id = ?", (rid,)).rowcount > 0


def list_runs(conn: sqlite3.Connection, rid: str, limit: int = 50) -> list[dict]:
    rows = conn.execute("SELECT rr.*, r.name AS routine_name FROM routine_runs rr JOIN routines r ON r.id = rr.routine_id "
                        "WHERE rr.routine_id = ? ORDER BY rr.scheduled_for DESC LIMIT ?", (rid, limit)).fetchall()
    return [run_to_dict(r) for r in rows]


def inbox(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute("SELECT rr.*, r.name AS routine_name FROM routine_runs rr JOIN routines r ON r.id = rr.routine_id "
                        "WHERE rr.status IN ('succeeded', 'failed', 'missed') "
                        "ORDER BY rr.read, COALESCE(rr.finished_at, rr.scheduled_for) DESC LIMIT ?", (limit,)).fetchall()
    return [run_to_dict(r) for r in rows]


def mark_read(conn: sqlite3.Connection, run_id: str) -> bool:
    return conn.execute("UPDATE routine_runs SET read = 1 WHERE id = ?", (run_id,)).rowcount > 0


def _record_run(conn: sqlite3.Connection, rid: str, scheduled_for: str, status: str, summary: str | None = None) -> dict | None:
    run_id = new_id()
    finished = utcnow() if status in ("missed", "skipped") else None
    try:
        conn.execute("INSERT INTO routine_runs (id, routine_id, scheduled_for, status, summary, finished_at) "
                     "VALUES (?,?,?,?,?,?)", (run_id, rid, scheduled_for, status, summary, finished))
    except sqlite3.IntegrityError:
        return None  # essa ocorrência já foi registrada (idempotência)
    return run_to_dict(conn.execute("SELECT * FROM routine_runs WHERE id = ?", (run_id,)).fetchone())


def plan_due(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    """Decide o que fazer com cada rotina vencida. Retorna as execuções a disparar (status queued)."""
    to_start = []
    rows = conn.execute("SELECT * FROM routines WHERE active = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
                        (now.isoformat(timespec="seconds"),)).fetchall()
    for row in rows:
        schedule, tz_name = json.loads(row["schedule_json"]), row["timezone"]
        occurrences, cursor = [], datetime.fromisoformat(row["next_run_at"])
        while cursor and cursor <= now and len(occurrences) < 1000:
            occurrences.append(cursor)
            cursor = next_occurrence(schedule, tz_name, cursor)
        latest = occurrences[-1]
        running = conn.execute("SELECT 1 FROM routine_runs WHERE routine_id = ? AND status IN ('queued', 'running')",
                               (row["id"],)).fetchone()
        late = now - latest > LATE_TOLERANCE
        if running:
            _record_run(conn, row["id"], latest.isoformat(timespec="seconds"), "skipped",
                        "Execução anterior ainda em andamento.")
        elif late and row["missed_policy"] == "skip":
            _record_run(conn, row["id"], latest.isoformat(timespec="seconds"), "missed",
                        f"{len(occurrences)} execução(ões) perdida(s) enquanto o servidor estava indisponível.")
        else:
            grouped = len(occurrences) - 1
            run = _record_run(conn, row["id"], latest.isoformat(timespec="seconds"), "queued",
                              f"{grouped} ocorrência(s) anterior(es) foram agrupadas nesta execução." if grouped else None)
            if run:
                to_start.append(run)
        conn.execute("UPDATE routines SET next_run_at = ? WHERE id = ?",
                     (cursor.isoformat(timespec="seconds") if cursor else None, row["id"]))
    return to_start


def queue_manual_run(conn: sqlite3.Connection, rid: str) -> dict | None:
    if not conn.execute("SELECT 1 FROM routines WHERE id = ?", (rid,)).fetchone():
        return None
    return _record_run(conn, rid, utcnow(), "queued")


def start_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute("UPDATE routine_runs SET status = 'running', started_at = ? WHERE id = ?", (utcnow(), run_id))


def finish_run(conn: sqlite3.Connection, run: dict, *, status: str, text: str) -> dict:
    """Grava o resultado; resultados com conteúdo também viram mensagem na conversa da rotina."""
    routine = get_routine(conn, run["routine_id"])
    conv_id = None
    if status in ("succeeded", "failed") and text and routine:
        conv = conn.execute("SELECT id FROM conversations WHERE kind = 'routine' AND title = ?", (routine["name"],)).fetchone()
        conv_id = conv["id"] if conv else create_conversation(conn, routine["name"], kind="routine")["id"]
        add_message(conn, conv_id, "assistant", text, status="ok" if status == "succeeded" else "error")
    conn.execute("UPDATE routine_runs SET status = ?, finished_at = ?, summary = ?, conversation_id = ?, read = ? WHERE id = ?",
                 (status, utcnow(), (text or "")[:SUMMARY_LIMIT] or None, conv_id, 1 if status == "quiet" else 0, run["id"]))
    return run_to_dict(conn.execute("SELECT * FROM routine_runs WHERE id = ?", (run["id"],)).fetchone())


def recover_interrupted(conn: sqlite3.Connection) -> int:
    """No boot: execuções que estavam rodando viram 'failed' (nunca são repetidas às cegas)."""
    return conn.execute("UPDATE routine_runs SET status = 'failed', finished_at = ?, "
                        "summary = COALESCE(summary, 'Interrompida por reinício do servidor.') "
                        "WHERE status IN ('queued', 'running')", (utcnow(),)).rowcount


# ---------- laço do agendador ----------

class Scheduler:
    """Um único laço assíncrono. `executor(run, routine)` devolve (status, texto)."""

    def __init__(self, conn: sqlite3.Connection, executor, poll_seconds: float = 30):
        self.conn, self.executor, self.poll_seconds = conn, executor, poll_seconds
        self._wake = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    def wake(self) -> None:
        self._wake.set()

    def submit(self, run: dict) -> None:
        task = asyncio.create_task(self._execute(run))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run: dict) -> None:
        routine = get_routine(self.conn, run["routine_id"])
        if not routine:
            return
        start_run(self.conn, run["id"])
        try:
            status, text = await self.executor(run, routine)
        except Exception as exc:  # noqa: BLE001 — a falha vira registro, nunca derruba o agendador
            log.exception("rotina %s falhou", run["routine_id"])
            status, text = "failed", f"A rotina falhou: {type(exc).__name__}."
        finish_run(self.conn, run, status=status, text=text)

    async def run_forever(self) -> None:
        recovered = recover_interrupted(self.conn)
        if recovered:
            log.warning("%d execução(ões) interrompida(s) marcadas como falha", recovered)
        while True:
            try:
                for run in plan_due(self.conn, datetime.now(timezone.utc)):
                    self.submit(run)
            except Exception:  # noqa: BLE001
                log.exception("erro ao planejar rotinas")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
