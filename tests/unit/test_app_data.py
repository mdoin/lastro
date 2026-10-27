import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import auth, db, routines, store


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "lastro.db")
    assert db.migrate(c) == db.LATEST_VERSION
    yield c
    c.close()


SNAP = {"as_of": "2026-10-26", "net_monthly_income": "4200.00", "essential_expenses": "2600.00",
        "variable_expenses": "700.00", "liquid_reserve": "200.00", "available_this_month": "300.00",
        "debts": [{"name": "Cartão", "balance": "2400.00", "monthly_rate": "0.12", "monthly_payment": "400.00"}]}


# ---------- migrações ----------

def test_migrations_are_idempotent(conn):
    assert db.migrate(conn) == db.LATEST_VERSION
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = 'owner'").fetchone()[0] == 1


def test_readonly_connection_cannot_write(tmp_path, conn):
    store.create_snapshot(conn, SNAP)
    ro = db.connect_readonly(tmp_path / "lastro.db")
    assert store.latest_snapshot(ro)["as_of"] == "2026-10-26"
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM goals")


# ---------- snapshots ----------

def test_snapshot_roundtrip_and_history(conn):
    first = store.create_snapshot(conn, SNAP)
    assert first["debts"][0]["monthly_rate"] == "0.12"
    second = store.create_snapshot(conn, {**SNAP, "as_of": "2026-11-26", "liquid_reserve": "500.00", "debts": []})
    assert store.latest_snapshot(conn)["id"] == second["id"]
    history = store.snapshot_history(conn)
    assert [h["as_of"] for h in history] == ["2026-10-26", "2026-11-26"]
    assert history[0]["total_debt"] == "2400.00" and history[0]["free_cash_flow"] == "500.00"


def test_snapshots_are_append_only(conn):
    snap = store.create_snapshot(conn, SNAP)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE financial_snapshots SET liquid_reserve = '999' WHERE id = ?", (snap["id"],))


@pytest.mark.parametrize("bad", [{"liquid_reserve": "-1"}, {"liquid_reserve": "abc"}, {"liquid_reserve": 1.5}])
def test_snapshot_rejects_invalid_money(conn, bad):
    with pytest.raises(ValueError):
        store.create_snapshot(conn, {**SNAP, **bad})


def test_failed_snapshot_leaves_nothing_behind(conn):
    with pytest.raises(ValueError):
        store.create_snapshot(conn, {**SNAP, "debts": [{"name": "", "balance": "1", "monthly_rate": "0", "monthly_payment": "0"}]})
    assert store.latest_snapshot(conn) is None


# ---------- premissas e metas ----------

def test_assumptions_default_then_saved(conn):
    assert store.get_assumptions(conn)["is_default"] is True
    saved = store.save_assumptions(conn, [{"name": "meu", "annual_return": "0.09", "annual_inflation": "0.04", "annual_fee": "0"}])
    assert saved["is_default"] is False and saved["scenarios"][0]["name"] == "meu"
    with pytest.raises(ValueError):
        store.save_assumptions(conn, [{"name": "x", "annual_return": "0.1", "annual_inflation": "0.04", "annual_fee": "1"}])


def test_goals_crud(conn):
    goal = store.create_goal(conn, {"name": "Reserva", "target_real_value": "15000", "deadline": "2028-12-31",
                                    "priority": 1, "liquidity": "diaria"}, today="2026-10-26")
    assert store.update_goal(conn, goal["id"], {**goal, "current_amount": "1000"})["current_amount"] == "1000"
    assert store.delete_goal(conn, goal["id"]) and store.list_goals(conn) == []


# ---------- conversas e decisões ----------

def test_conversation_messages(conn):
    conv = store.create_conversation(conn, "Primeira")
    store.add_message(conn, conv["id"], "user", "Oi")
    store.add_message(conn, conv["id"], "assistant", "Olá", tools=[{"name": "diagnostico", "input": {}}])
    msgs = store.list_messages(conn, conv["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["tools"][0]["name"] == "diagnostico"
    assert store.delete_conversation(conn, conv["id"]) and store.list_messages(conn, conv["id"]) == []


def test_decisions_append_only_with_review(conn):
    d1 = store.create_decision(conn, {"question": "Onde guardar a reserva?", "alternatives": ["A", "B"],
                                      "user_choice": "A", "planned_amount": "150"}, today="2026-10-26")
    d2 = store.create_decision(conn, {"question": "Revisão", "user_choice": "Mantive A", "review_of_id": d1["id"]},
                               today="2026-11-26")
    assert d2["review_of_id"] == d1["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE decision_log SET user_choice = 'B' WHERE id = ?", (d1["id"],))


def test_export_contains_everything(conn):
    store.create_snapshot(conn, SNAP)
    data = store.export_all(conn)
    assert data["snapshots"] and "conversations" in data and "routines" in data


# ---------- autenticação ----------

def test_password_rules_and_login(conn):
    with pytest.raises(ValueError):
        auth.set_password(conn, "curta")
    auth.set_password(conn, "uma senha longa e boa")
    assert auth.attempt_login(conn, "errada", "203.0.113.9") is None
    token = auth.attempt_login(conn, "uma senha longa e boa", "203.0.113.9")
    assert token and auth.session_is_valid(conn, token)
    assert conn.execute("SELECT COUNT(*) FROM auth_sessions WHERE token_hash = ?", (token,)).fetchone()[0] == 0
    auth.logout(conn, token)
    assert not auth.session_is_valid(conn, token)


def test_password_change_revokes_sessions(conn):
    auth.set_password(conn, "uma senha longa e boa")
    token = auth.attempt_login(conn, "uma senha longa e boa", "203.0.113.9")
    auth.set_password(conn, "outra senha longa e boa")
    assert not auth.session_is_valid(conn, token)


def test_login_rate_limit(conn):
    auth.set_password(conn, "uma senha longa e boa")
    for _ in range(auth.MAX_FAILURES):
        auth.attempt_login(conn, "errada", "203.0.113.9")
    assert auth.too_many_failures(conn, "203.0.113.9")
    assert not auth.too_many_failures(conn, "198.51.100.7")


# ---------- rotinas ----------

UTC = timezone.utc


def test_next_occurrence_respects_timezone():
    # 08:30 em São Paulo (UTC-3) = 11:30 UTC
    nxt = routines.next_occurrence({"kind": "daily", "time": "08:30"}, "America/Sao_Paulo",
                                   datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 10, 27, 11, 30, tzinfo=UTC)


def test_weekly_monthly_once():
    after = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)  # segunda-feira
    weekly = routines.next_occurrence({"kind": "weekly", "time": "09:00", "weekday": 4}, "UTC", after)
    assert weekly == datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    monthly = routines.next_occurrence({"kind": "monthly", "time": "09:00", "day": 5}, "UTC", after)
    assert monthly == datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
    assert routines.next_occurrence({"kind": "once", "time": "09:00", "date": "2026-10-01"}, "UTC", after) is None


@pytest.mark.parametrize("schedule", [{"kind": "hourly", "time": "09:00"}, {"kind": "daily", "time": "25:00"},
                                      {"kind": "weekly", "time": "09:00", "weekday": 9},
                                      {"kind": "monthly", "time": "09:00", "day": 31}])
def test_invalid_schedules(schedule):
    with pytest.raises(ValueError):
        routines.validate_schedule(schedule, "UTC")


def _routine(conn, now, **overrides):
    data = {"name": "Resumo", "instruction": "Resuma meu mês.", "schedule": {"kind": "daily", "time": "09:00"},
            "timezone": "UTC", **overrides}
    return routines.create_routine(conn, data, now=now)


def test_due_routine_runs_once_per_occurrence(conn):
    t0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    r = _routine(conn, t0)
    at = datetime(2026, 10, 26, 9, 0, 30, tzinfo=UTC)
    runs = routines.plan_due(conn, at)
    assert len(runs) == 1 and runs[0]["status"] == "queued"
    assert routines.plan_due(conn, at) == []  # mesma ocorrência não dispara de novo
    assert routines.get_routine(conn, r["id"])["next_run_at"] == "2026-10-27T09:00:00+00:00"


def test_missed_occurrences_skip_policy(conn):
    r = _routine(conn, datetime(2026, 10, 20, 8, 0, tzinfo=UTC))
    runs = routines.plan_due(conn, datetime(2026, 10, 26, 12, 0, tzinfo=UTC))  # servidor ficou 6 dias fora
    assert runs == []
    history = routines.list_runs(conn, r["id"])
    assert len(history) == 1 and history[0]["status"] == "missed" and "7 execução" in history[0]["summary"]


def test_missed_occurrences_run_once_policy(conn):
    _routine(conn, datetime(2026, 10, 20, 8, 0, tzinfo=UTC), missed_policy="run_once")
    runs = routines.plan_due(conn, datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
    assert len(runs) == 1 and runs[0]["scheduled_for"] == "2026-10-26T09:00:00+00:00"


def test_overlapping_run_is_skipped(conn):
    r = _routine(conn, datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    first = routines.plan_due(conn, datetime(2026, 10, 26, 9, 0, 1, tzinfo=UTC))[0]
    routines.start_run(conn, first["id"])
    assert routines.plan_due(conn, datetime(2026, 10, 27, 9, 0, 1, tzinfo=UTC)) == []
    assert routines.list_runs(conn, r["id"])[0]["status"] == "skipped"


def test_quiet_and_success_results(conn):
    r = _routine(conn, datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    run = routines.plan_due(conn, datetime(2026, 10, 26, 9, 0, 1, tzinfo=UTC))[0]
    done = routines.finish_run(conn, run, status="quiet", text="")
    assert done["status"] == "quiet" and done["read"] is True and routines.inbox(conn) == []
    run2 = routines.queue_manual_run(conn, r["id"])
    done2 = routines.finish_run(conn, run2, status="succeeded", text="Seu mês: tudo certo.")
    assert routines.inbox(conn)[0]["id"] == done2["id"] and done2["conversation_id"]
    assert routines.mark_read(conn, done2["id"]) and routines.inbox(conn)[0]["read"] is True


def test_recover_interrupted_never_reruns(conn):
    r = _routine(conn, datetime(2026, 10, 26, 8, 0, tzinfo=UTC))
    run = routines.queue_manual_run(conn, r["id"])
    routines.start_run(conn, run["id"])
    assert routines.recover_interrupted(conn) == 1
    assert routines.list_runs(conn, r["id"])[0]["status"] == "failed"


def test_inactive_routine_has_no_next_run(conn):
    r = _routine(conn, datetime(2026, 10, 26, 8, 0, tzinfo=UTC), active=False)
    assert r["next_run_at"] is None
    assert routines.plan_due(conn, datetime(2026, 12, 1, tzinfo=UTC)) == []


async def _fake_executor(run, routine):
    return "succeeded", f"ok: {routine['name']}"


def test_scheduler_executes_and_survives_errors(conn):
    import asyncio

    async def scenario():
        r = _routine(conn, datetime.now(UTC) - timedelta(days=1))
        conn.execute("UPDATE routines SET next_run_at = ? WHERE id = ?",
                     ((datetime.now(UTC) - timedelta(seconds=5)).isoformat(timespec="seconds"), r["id"]))
        sched = routines.Scheduler(conn, _fake_executor, poll_seconds=0.05)
        loop_task = asyncio.create_task(sched.run_forever())
        await asyncio.sleep(0.3)
        loop_task.cancel()
        return routines.list_runs(conn, r["id"])

    runs = asyncio.run(scenario())
    assert runs[0]["status"] == "succeeded" and runs[0]["summary"] == "ok: Resumo"
