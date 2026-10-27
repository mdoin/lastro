"""Web app do Lastro de ponta a ponta, com um worker do mentor falso num socket Unix real."""
import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.web import Settings, create_app, today

H = {"X-Lastro": "1"}
PASSWORD = "uma senha longa e boa"
SNAP = {"as_of": "2026-10-26", "net_monthly_income": "4200.00", "essential_expenses": "2600.00",
        "variable_expenses": "700.00", "liquid_reserve": "200.00", "available_this_month": "300.00",
        "debts": [{"name": "Cartão", "balance": "2400.00", "monthly_rate": "0.12", "monthly_payment": "400.00"}]}


class FakeMentor:
    """Servidor de socket que imita o worker do mentor."""

    def __init__(self, path):
        self.path, self.requests = path, []
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    async def handle(self, reader, writer):
        req = json.loads(await reader.readline())
        self.requests.append(req)
        op = req["op"]
        if op == "turn":
            events = [{"type": "tool", "name": "diagnostico", "input": {}}, {"type": "delta", "text": "Pague "},
                      {"type": "delta", "text": "o cartão."},
                      {"type": "done", "text": "Pague o cartão.", "status": "ok", "session_id": "sess-xyz",
                       "tools": [{"name": "diagnostico", "input": {}}]}]
        elif op == "panel":
            events = [{"type": "plan", "agents": [{"role": "riscos", "label": "Riscos"}]},
                      {"type": "agent_start", "role": "riscos"}, {"type": "agent_done", "role": "riscos", "text": "ok"},
                      {"type": "synthesis_delta", "text": "Síntese"}, {"type": "audit", "verdict": "PASSA", "reasons": ["ok"]},
                      {"type": "done", "text": "Síntese", "audit": {"verdict": "PASSA", "reasons": ["ok"]},
                       "reports": {"riscos": "ok"}}]
        elif op == "ephemeral":
            events = [{"type": "done", "text": "Relatório do mês.", "quiet": False}]
        elif op == "status":
            events = [{"type": "done", "busy": 0, "queued": 0, "limit_until": None, "logged_in": True, "subscription": "team"}]
        else:
            events = [{"type": "done"}]
        for e in events:
            writer.write(json.dumps(e).encode() + b"\n")
            await writer.drain()
        writer.close()

    def __enter__(self):
        self.thread.start()
        asyncio.run_coroutine_threadsafe(asyncio.start_unix_server(self.handle, path=str(self.path)), self.loop).result()
        return self

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture
def env(tmp_path):
    with FakeMentor(tmp_path / "mentor.sock") as mentor:
        app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "mentor.sock",
                                  cookie_secure=False, run_scheduler=False))
        with TestClient(app, base_url="http://lastro.test") as client:
            yield client, app, mentor


def login(client, app):
    auth.set_password(app.state.conn, PASSWORD)
    assert client.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 204


def sse_events(response):
    events, name = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            events.append((name, json.loads(line[6:])))
    return events


# ---------- autenticação e proteções ----------

def test_auth_flow_and_protections(env):
    client, app, _ = env
    assert client.get("/api/auth/state").json() == {"authenticated": False, "setup_required": True}
    assert client.get("/api/snapshot/latest").status_code == 401
    auth.set_password(app.state.conn, PASSWORD)
    assert client.post("/api/auth/login", json={"password": "errada"}, headers=H).status_code == 401
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 403  # sem X-Lastro
    r = client.post("/api/auth/login", json={"password": PASSWORD}, headers=H)
    assert r.status_code == 204 and "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/state").json()["authenticated"] is True
    evil = client.post("/api/snapshot", json=SNAP, headers={**H, "Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert client.post("/api/auth/logout", headers=H).status_code == 204
    assert client.get("/api/snapshot/latest").status_code == 401


def test_login_rate_limited_per_client(env):
    client, app, _ = env
    auth.set_password(app.state.conn, PASSWORD)
    attacker = TestClient(app, client=("203.0.113.9", 40000))
    owner = TestClient(app, client=("198.51.100.7", 40001))
    for _ in range(auth.MAX_FAILURES):
        assert attacker.post("/api/auth/login", json={"password": "x"}, headers=H).status_code == 401
    # Quem errou fica bloqueado, inclusive com a senha certa...
    assert attacker.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 429
    # ...mas não consegue bloquear o dono, que entra de outro endereço.
    assert owner.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 204


def test_login_lock_recovery(env):
    _, app, _ = env
    conn = app.state.conn
    auth.set_password(conn, PASSWORD)
    for _ in range(auth.MAX_FAILURES):
        auth.attempt_login(conn, "x", "203.0.113.9")
    assert auth.too_many_failures(conn, "203.0.113.9")
    auth.unlock(conn)
    assert not auth.too_many_failures(conn, "203.0.113.9")
    for _ in range(auth.MAX_FAILURES):
        auth.attempt_login(conn, "x", "203.0.113.9")
    auth.set_password(conn, PASSWORD)  # trocar a senha também destrava
    assert not auth.too_many_failures(conn, "203.0.113.9")


def test_login_global_failures_only_delay(env, monkeypatch):
    _, app, _ = env
    conn = app.state.conn
    auth.set_password(conn, PASSWORD)
    for i in range(auth.GLOBAL_SLOWDOWN_AFTER + 30):  # ataque espalhado por muitos endereços
        auth.attempt_login(conn, "x", f"203.0.113.{i % 250}")
    assert 0 < auth.global_delay(conn) <= auth.MAX_GLOBAL_DELAY_SECONDS
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("app.web.asyncio.sleep", fake_sleep)
    owner = TestClient(app, client=("198.51.100.7", 40001))
    assert owner.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 204
    assert slept and slept[0] <= auth.MAX_GLOBAL_DELAY_SECONDS


def test_login_client_key():
    assert auth.client_key("203.0.113.9") == "203.0.113.9"
    assert auth.client_key("2001:db8:1:2:aaaa::1") == auth.client_key("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert auth.client_key("::ffff:203.0.113.9") == "203.0.113.9"
    assert auth.client_key(None) == "desconhecido"


def test_security_headers(env):
    client, _, _ = env
    r = client.get("/api/auth/state")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


# ---------- dados ----------

def test_snapshot_diagnosis_projection_goals(env):
    client, app, _ = env
    login(client, app)
    assert client.get("/api/diagnosis").status_code == 404  # sem dados ainda
    assert client.post("/api/snapshot", json=SNAP, headers=H).status_code == 201
    assert client.post("/api/snapshot", json={**SNAP, "liquid_reserve": "-5"}, headers=H).status_code == 422
    diag = client.get("/api/diagnosis").json()
    assert diag["guidance"]["stage"] == "priorizar_divida" and diag["free_cash_flow"] == "500.00"
    proj = client.post("/api/projection", json={"initial": "0", "contribution": "150", "months": 120}, headers=H).json()
    assert [p["scenario"] for p in proj["projections"]] == ["conservador", "base", "otimista"]
    assert proj["assumptions_are_default"] is True
    deadline = today().replace(year=today().year + 2)  # shortcut: quebra em 29/02, trocar por cálculo de mês se incomodar
    goal = client.post("/api/goals", json={"name": "Reserva", "target_real_value": "15600", "deadline": deadline.isoformat(),
                                           "priority": 1, "liquidity": "diaria"}, headers=H).json()
    assert goal["months_left"] == 24 and set(goal["required_monthly"]) == {"conservador", "base", "otimista"}
    assert client.put("/api/assumptions", json={"scenarios": [{"name": "meu", "annual_return": "0.09",
                                                               "annual_inflation": "0.04"}]}, headers=H).status_code == 200
    assert list(client.get("/api/goals").json()[0]["required_monthly"]) == ["meu"]
    assert client.delete(f"/api/goals/{goal['id']}", headers=H).status_code == 204


def test_decisions_and_export(env):
    client, app, _ = env
    login(client, app)
    d = client.post("/api/decisions", json={"question": "Reserva onde?", "user_choice": "Liquidez diária",
                                            "planned_amount": "150", "confirmed": True}, headers=H).json()
    assert d["confirmed"] is True and client.get("/api/decisions").json()[0]["id"] == d["id"]
    r = client.get("/api/export")
    assert "attachment" in r.headers["content-disposition"] and r.json()["decisions"][0]["id"] == d["id"]


# ---------- mentor ----------

def test_chat_streams_and_persists(env):
    client, app, mentor = env
    login(client, app)
    conv = client.post("/api/conversations", json={"title": "Teste"}, headers=H).json()
    with client.stream("POST", f"/api/conversations/{conv['id']}/messages", json={"text": "O que faço?"}, headers=H) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = sse_events(r)
    names = [n for n, _ in events]
    assert names == ["tool", "delta", "delta", "done"]
    assert events[-1][1]["message"]["content"] == "Pague o cartão."
    msgs = client.get(f"/api/conversations/{conv['id']}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["tools"][0]["name"] == "diagnostico"
    # segundo turno retoma a sessão do Claude e manda o histórico para o caso de ela ter sumido
    with client.stream("POST", f"/api/conversations/{conv['id']}/messages", json={"text": "E depois?"}, headers=H) as r:
        sse_events(r)
    last = mentor.requests[-1]
    assert last["session_id"] == "sess-xyz" and last["history"][0]["content"] == "O que faço?"


def test_panel_streams_and_saves_with_audit(env):
    client, app, _ = env
    login(client, app)
    with client.stream("POST", "/api/panels", json={"question": "Invisto ou quito?"}, headers=H) as r:
        events = sse_events(r)
    names = [n for n, _ in events]
    assert names[0] == "plan" and "audit" in names and names[-1] == "done"
    conv_id = events[-1][1]["conversation_id"]
    saved = client.get(f"/api/conversations/{conv_id}/messages").json()[-1]
    assert "Parecer do Auditor: PASSA" in saved["content"]
    assert saved["audit"] == {"verdict": "PASSA", "reasons": ["ok"]}  # veredito sobrevive ao recarregar
    chat = client.post("/api/conversations", json={}, headers=H).json()
    assert client.post("/api/panels", json={"question": "x", "conversation_id": chat["id"]}, headers=H).status_code == 409


def test_mentor_unavailable_is_reported(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "x.db", mentor_socket=tmp_path / "nao-existe.sock",
                              cookie_secure=False, run_scheduler=False))
    with TestClient(app) as client:
        login(client, app)
        conv = client.post("/api/conversations", json={}, headers=H).json()
        with client.stream("POST", f"/api/conversations/{conv['id']}/messages", json={"text": "oi"}, headers=H) as r:
            events = sse_events(r)
        assert events[-1][0] == "error" and "indisponível" in events[-1][1]["message"]
        assert client.get("/api/status").json()["mentor"]["available"] is False


def test_status(env):
    client, app, _ = env
    login(client, app)
    s = client.get("/api/status").json()
    assert "Não é ordem" in s["disclaimer"]
    assert s["mentor"] == {"available": True, "logged_in": True, "subscription": "team", "busy": 0, "queued": 0,
                           "limit_until": None}


# ---------- rotinas ----------

def test_routines_crud_and_manual_run(env):
    client, app, _ = env
    login(client, app)
    bad = client.post("/api/routines", json={"name": "x", "instruction": "y", "schedule": {"kind": "hourly"}}, headers=H)
    assert bad.status_code == 422
    r = client.post("/api/routines", json={"name": "Resumo mensal", "instruction": "Resuma o mês.",
                                           "schedule": {"kind": "monthly", "time": "08:30", "day": 5}}, headers=H).json()
    assert r["next_run_at"] and r["timezone"] == "America/Sao_Paulo"
    run = client.post(f"/api/routines/{r['id']}/run", headers=H)
    assert run.status_code == 202
    for _ in range(50):
        runs = client.get(f"/api/routines/{r['id']}/runs").json()
        if runs[0]["status"] == "succeeded":
            break
        time.sleep(0.05)
    assert runs[0]["status"] == "succeeded" and runs[0]["summary"] == "Relatório do mês."
    inbox = client.get("/api/inbox").json()
    assert inbox[0]["id"] == runs[0]["id"] and inbox[0]["read"] is False
    assert inbox[0]["routine_name"] == "Resumo mensal"
    assert client.post(f"/api/inbox/{inbox[0]['id']}/read", headers=H).status_code == 204
    assert client.delete(f"/api/routines/{r['id']}", headers=H).status_code == 204


# ---------- API de leitura do mentor com dados reais ----------

def test_agent_api_owner_routes_are_read_only(tmp_path):
    from app import db, store
    from app.agent_api import create_app as create_agent_api

    conn = db.connect(tmp_path / "lastro.db")
    db.migrate(conn)
    store.create_snapshot(conn, SNAP)
    token = "t" * 40
    api = TestClient(create_agent_api(token=token, data_dir=tmp_path, db_path=tmp_path / "lastro.db"))
    h = {"Authorization": f"Bearer {token}"}
    assert api.get("/v1/me/diagnosis", headers=h).json()["guidance"]["stage"] == "priorizar_divida"
    assert api.get("/v1/me/situation", headers=h).json()["latest"]["debts"][0]["name"] == "Cartão"
    assert api.get("/v1/me/projection?contribution=150&months=12", headers=h).status_code == 200
    assert api.get("/v1/me/goals", headers=h).json()["goals"] == []
    assert api.get("/v1/me/diagnosis").status_code == 401
    assert api.post("/v1/me/diagnosis", headers=h).status_code == 405


def test_all_route_handlers_and_dependencies_are_async(env):
    """A conexão SQLite é única e do laço de eventos: nada pode rodar em thread (bug achado no e2e)."""
    import inspect

    from fastapi.routing import APIRoute

    _, app, _ = env

    def walk(dependant):
        yield dependant.call
        for sub in dependant.dependencies:
            yield from walk(sub)

    for route in app.routes:
        if isinstance(route, APIRoute):
            for fn in walk(route.dependant):
                if fn is not None and not isinstance(fn, type):
                    assert inspect.iscoroutinefunction(fn), f"{route.path}: {getattr(fn, '__name__', fn)} não é async"


def test_projection_extreme_inputs_are_422_not_500(env):
    client, app, _ = env
    login(client, app)
    for body in ({"initial": "1e1000", "contribution": "150", "months": 12},
                 {"initial": "0", "contribution": "150", "months": 12, "contribution_annual_increase": "-1"}):
        assert client.post("/api/projection", json=body, headers=H).status_code == 422, body
