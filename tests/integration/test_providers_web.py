"""Web app: assistente inicial (token de instalação), conexões de IA e provedor/modelo por agente.

O worker é falso (TCP de loopback); o foco é o que o web app aceita, repassa, registra e devolve.
"""

import asyncio
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, setup, store
from app.web import Settings, create_app

H = {"X-Lastro": "1"}
PASSWORD = "uma senha longa e boa"
LEAK = "VALOR-QUE-NUNCA-PODE-SAIR"


class FakeWorker:
    def __init__(self):
        self.requests = []
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.connections = [{"id": "anthropic-1", "type": "anthropic", "label": "Claude API", "configured": True,
                             "default": True, "secret_hint": "…1234", "secret": {"api_key": LEAK}}]

    async def handle(self, reader, writer):
        req = json.loads(await reader.readline())
        self.requests.append(req)
        action = req.get("action")
        if req["op"] == "status":
            reply = {"type": "done", "busy": 0, "queued": 0, "ai_configured": True}
        elif action == "types":
            reply = {"type": "done", "types": [{"type": "anthropic", "label": "Anthropic"}]}
        elif action == "list":
            reply = {"type": "done", "connections": self.connections, "default": "anthropic-1"}
        elif action == "save":
            reply = {"type": "done", "ok": True, "connection": {"id": "anthropic-2", "type": req["type"],
                                                                 "api_key": LEAK}}
        elif action == "login_start":
            reply = {"type": "done", "ok": True, "kind": "paste", "state": "waiting_code",
                     "url": "https://claude.ai/oauth/authorize?x=1"}
        elif action == "login_submit":
            reply = {"type": "done", "ok": True, "state": "done", "url": None, "error": None}
        else:
            reply = {"type": "done", "ok": True, "detail": "ok", "access_token": LEAK}
        writer.write(json.dumps(reply).encode() + b"\n")
        await writer.drain()
        writer.close()

    def __enter__(self):
        self.thread.start()
        server = asyncio.run_coroutine_threadsafe(asyncio.start_server(self.handle, "127.0.0.1", 0), self.loop).result()
        self.address = Path(f"tcp:127.0.0.1:{server.sockets[0].getsockname()[1]}")
        return self

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("LASTRO_SETUP_TOKEN", raising=False)
    with FakeWorker() as worker:
        app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=worker.address, cookie_secure=False,
                                  run_scheduler=False, run_orchestrator=False))
        with TestClient(app, base_url="http://lastro.test") as client:
            yield client, app, worker, tmp_path


def login(client, app):
    auth.set_password(app.state.conn, PASSWORD)
    assert client.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 204


# ---------- assistente inicial ----------

def test_first_password_requires_the_installation_token(env):
    client, app, _, data_dir = env
    token_file = data_dir / setup.TOKEN_FILE
    token = token_file.read_text().strip()
    assert len(token) >= 24
    assert client.get("/api/auth/state").json()["setup_required"] is True
    wrong = client.post("/api/setup/password", json={"token": "x" * 24, "password": PASSWORD}, headers=H)
    assert wrong.status_code == 403
    no_header = client.post("/api/setup/password", json={"token": token, "password": PASSWORD})
    assert no_header.status_code == 403                               # CSRF continua valendo
    short = client.post("/api/setup/password", json={"token": token, "password": "curta"}, headers=H)
    assert short.status_code == 422
    ok = client.post("/api/setup/password", json={"token": token, "password": PASSWORD}, headers=H)
    assert ok.status_code == 204 and "httponly" in ok.headers["set-cookie"].lower()
    assert not token_file.exists()                                    # o token morre com o primeiro uso
    assert client.get("/api/auth/state").json() == {"authenticated": True, "setup_required": False,
                                                    "onboarding_done": False}
    again = client.post("/api/setup/password", json={"token": token, "password": "outra senha bem longa"}, headers=H)
    assert again.status_code == 409                                   # nunca troca a senha pela web
    state = client.get("/api/setup/state").json()
    assert state["currency"] == "BRL" and state["timezone"]
    assert client.post("/api/setup/complete", headers=H).status_code == 204
    assert client.get("/api/auth/state").json()["onboarding_done"] is True


def test_setup_token_is_rate_limited(env):
    client, *_ = env
    for _ in range(auth.MAX_FAILURES):
        client.post("/api/setup/password", json={"token": "y" * 24, "password": PASSWORD}, headers=H)
    assert client.post("/api/setup/password", json={"token": "y" * 24, "password": PASSWORD},
                       headers=H).status_code == 429


def test_setup_token_file_is_private(tmp_path, monkeypatch):
    monkeypatch.delenv("LASTRO_SETUP_TOKEN", raising=False)
    token = setup.ensure_token(tmp_path)
    assert setup.ensure_token(tmp_path) == token                      # estável entre reinícios
    if hasattr(__import__("os"), "getuid"):
        assert (tmp_path / setup.TOKEN_FILE).stat().st_mode & 0o077 == 0
    assert setup.token_matches(token, f" {token} ") and not setup.token_matches(None, token)


def test_existing_installation_skips_onboarding(tmp_path):
    from app import db

    conn = db.connect(tmp_path / "old.db")
    for number, path in db.MIGRATIONS[:-1]:
        script = path.read_text(encoding="utf-8")
        for statement in db._split_statements(script):
            conn.execute(statement)
        if number > 1:
            conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (number, db.utcnow()))
    auth.set_password(conn, PASSWORD)
    conn.execute("INSERT INTO conversations (id, kind, title, claude_session_id, created_at, updated_at) "
                 "VALUES ('c1', 'chat', 'antiga', 'sess-antiga', '2026-10-01', '2026-10-01')")
    assert db.migrate(conn) == db.LATEST_VERSION
    assert store.get_setting(conn, "onboarding_done") == "1"
    conv = store.get_conversation(conn, "c1")
    assert conv["claude_session_id"] == "sess-antiga" and conv["session_connection"] is None  # nada se perde


# ---------- conexões e agentes ----------

def test_provider_routes_require_login(env):
    client, *_ = env
    for method, path in (("GET", "/api/providers"), ("POST", "/api/providers"), ("PUT", "/api/agents/models"),
                         ("POST", "/api/providers/anthropic-1/test")):
        assert client.request(method, path, json={}, headers=H).status_code in (401, 422)
    assert client.get("/api/providers").status_code == 401


def test_secrets_never_come_back_from_the_web_app(env):
    client, app, worker, _ = env
    login(client, app)
    listing = client.get("/api/providers")
    saved = client.post("/api/providers", json={"type": "anthropic", "api_key": "chave-ficticia-0000000000"},
                        headers=H)
    tested = client.post("/api/providers/anthropic-1/test", headers=H)
    for response in (listing, saved, tested):
        assert response.status_code in (200, 201) and LEAK not in response.text
    assert worker.requests[-2]["api_key"] == "chave-ficticia-0000000000"  # a chave seguiu só para o worker
    log = app.state.conn.execute("SELECT action, resource FROM audit_log").fetchall()
    assert all("chave-ficticia" not in r["resource"] for r in log)


def test_claude_login_code_goes_only_to_the_worker(env):
    client, app, worker, _ = env
    login(client, app)
    started = client.post("/api/providers/claude-code/login_start", headers=H).json()
    assert started["url"].startswith("https://claude.ai/")
    done = client.post("/api/providers/claude-code/login_submit", json={"code": "CODIGO#SECRETO"}, headers=H)
    assert done.json()["state"] == "done" and "CODIGO" not in done.text
    assert worker.requests[-1]["code"] == "CODIGO#SECRETO"
    rows = app.state.conn.execute("SELECT resource FROM audit_log").fetchall()
    assert all("CODIGO" not in r["resource"] for r in rows)


@pytest.mark.parametrize("path", ["/api/providers/..%2Fx/test", "/api/providers/anthropic-1/apagar_tudo",
                                  "/api/providers/a b/test"])
def test_provider_actions_are_allowlisted(env, path):
    client, app, *_ = env
    login(client, app)
    assert client.post(path, headers=H).status_code == 404


def test_agent_models_are_validated_and_routed(env):
    client, app, worker, _ = env
    login(client, app)
    bad_agent = client.put("/api/agents/models", json={"models": {"hacker": {"connection": "anthropic-1"}}}, headers=H)
    bad_conn = client.put("/api/agents/models", json={"models": {"riscos": {"connection": "nao-existe"}}}, headers=H)
    bad_model = client.put("/api/agents/models", json={"models": {"riscos": {"connection": "anthropic-1",
                                                                             "model": "x; rm -rf"}}}, headers=H)
    assert {bad_agent.status_code, bad_conn.status_code, bad_model.status_code} == {422}
    ok = client.put("/api/agents/models", json={"models": {"riscos": {"connection": "anthropic-1",
                                                                      "model": "claude-opus-5-5"},
                                                           "mentor": {"connection": "anthropic-1"}}}, headers=H)
    assert ok.status_code == 200 and ok.json()["riscos"]["model"] == "claude-opus-5-5"
    conn = app.state.conn
    assert store.ai_route(conn, "riscos") == {"connection": "anthropic-1", "model": "claude-opus-5-5"}
    assert store.ai_route(conn, "analista") == {}                    # sem escolha: conexão padrão
    client.put("/api/agents/models", json={"models": {"riscos": {"connection": ""}}}, headers=H)
    assert store.ai_route(conn, "riscos") == {}
    # o chat do Mentor leva a conexão escolhida e a conexão da sessão anterior
    conv = client.post("/api/conversations", json={}, headers=H).json()
    with client.stream("POST", f"/api/conversations/{conv['id']}/messages", json={"text": "oi"}, headers=H) as r:
        r.read()
    turn = next(req for req in worker.requests if req["op"] == "turn")
    assert turn["connection"] == "anthropic-1" and "session_connection" in turn


def test_deleting_a_connection_clears_agent_choices(env):
    client, app, *_ = env
    login(client, app)
    store.set_agent_model(app.state.conn, "riscos", "anthropic-1", "m")
    assert client.delete("/api/providers/anthropic-1", headers=H).status_code == 204
    assert store.agent_models(app.state.conn) == {}
