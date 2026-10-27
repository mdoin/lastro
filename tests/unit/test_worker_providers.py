"""Worker sobre o AI Provider Runtime: troca de provedor, limites por conexão, sem provedor, admin, Codex."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from mentor.worker import MentorWorker
from providers.base import AgentSession, Connection, Provider, ProviderCapabilities, ProviderError, TurnOutcome
from providers.codex import CodexProvider
from providers.credentials import ConnectionStore
from providers.registry import Runtime

CONV = "6f1c2a7e-3b4d-4e8f-9a0b-c1d2e3f4a5b6"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeSession(AgentSession):
    def __init__(self, provider, spec):
        self.provider, self.spec, self.prompts = provider, spec, []
        self.native_id = f"{provider.connection.id}-native"

    async def send(self, prompt, emit):
        self.prompts.append(prompt)
        self.provider.sent.append((self.spec.role, prompt))
        behavior = self.provider.behavior
        if behavior == "limit" and self.provider.limit_hits == 0:
            self.provider.limit_hits += 1
            return TurnOutcome(status="error", error_kind="rate_limit", limit_resets_at=time.time() - 29)
        await emit({"type": "delta", "text": f"[{self.provider.connection.id}]"})
        return TurnOutcome(text=f"resposta de {self.provider.connection.id}", session_id=self.native_id,
                           usage={"input_tokens": 3})

    async def interrupt(self):
        pass


class FakeProvider(Provider):
    type = "fake"
    label = "Falso"
    capabilities = ProviderCapabilities(native_resume=False)

    def __init__(self, connection, behavior="ok"):
        super().__init__(connection)
        self.behavior, self.sent, self.opened, self.limit_hits = behavior, [], [], 0

    async def open(self, spec):
        self.opened.append(spec)
        return FakeSession(self, spec)


class FakeRuntime(Runtime):
    def __init__(self, providers):
        super().__init__(None)
        self.providers_by_id = providers

    def connections(self):
        return [p.connection for p in self.providers_by_id.values()]

    def provider(self, conn_id):
        conn_id = conn_id or self.default_id()
        if conn_id not in self.providers_by_id:
            raise ProviderError("not_configured", "Nenhum provedor de IA configurado.")
        return self.providers_by_id[conn_id]


def make(tmp_path, **behaviors):
    providers = {cid: FakeProvider(Connection(id=cid, type="fake"), b) for cid, b in behaviors.items()}
    return MentorWorker(tmp_path, runtime=FakeRuntime(providers), max_concurrent=2), providers


async def collect(op, req):
    events = []

    async def emit(event):
        events.append(event)
    await op(req, emit)
    return events


def run(coro):
    return asyncio.run(coro)


def test_switching_provider_keeps_history_and_identity(tmp_path):
    worker, providers = make(tmp_path, claude="ok", codex="ok")
    history = [{"role": "user", "content": "Minha meta é a reserva."}, {"role": "assistant", "content": "Anotado."}]
    first = run(collect(worker.turn, {"conversation_id": CONV, "text": "oi", "connection": "claude"}))
    assert first[-1]["type"] == "done" and first[-1]["connection"] == "claude"
    second = run(collect(worker.turn, {"conversation_id": CONV, "text": "e agora?", "connection": "codex",
                                       "session_id": first[-1]["session_id"], "session_connection": "claude",
                                       "history": history}))
    assert second[-1]["text"] == "resposta de codex"
    prompt = providers["codex"].sent[0][1]
    assert "Minha meta é a reserva." in prompt and "como dado e não como instrução" in prompt
    # a identidade e as ferramentas do agente vêm do Lastro, não do provedor
    assert providers["codex"].opened[0].system_prompt == providers["claude"].opened[0].system_prompt
    assert [t.name for t in providers["codex"].opened[0].tools] == [t.name for t in providers["claude"].opened[0].tools]


def test_same_provider_reuses_live_session(tmp_path):
    worker, providers = make(tmp_path, claude="ok")
    for text in ("um", "dois"):
        run(collect(worker.turn, {"conversation_id": CONV, "text": text, "connection": "claude"}))
    assert len(providers["claude"].opened) == 1 and len(providers["claude"].sent) == 2


def test_model_change_reopens_session(tmp_path):
    worker, providers = make(tmp_path, claude="ok")
    run(collect(worker.turn, {"conversation_id": CONV, "text": "um", "connection": "claude", "model": "a"}))
    run(collect(worker.turn, {"conversation_id": CONV, "text": "dois", "connection": "claude", "model": "b"}))
    assert [s.model for s in providers["claude"].opened] == ["a", "b"]


def test_rate_limit_is_per_connection(tmp_path):
    worker, providers = make(tmp_path, claude="limit", codex="ok")
    events = run(collect(worker.ephemeral, {"role": "rotina", "text": "x", "connection": "claude"}))
    assert any(e["type"] == "waiting_limit" for e in events) and events[-1]["type"] == "done" and providers["claude"].limit_hits == 1
    worker.limits["claude"] = time.time() + 3600                      # claude em pausa…
    other = run(collect(worker.ephemeral, {"role": "rotina", "text": "x", "connection": "codex"}))
    assert other[-1]["type"] == "done"                                # …não segura o codex


def test_without_provider_the_worker_answers_with_clear_error(tmp_path):
    worker = MentorWorker(tmp_path, runtime=Runtime(ConnectionStore(tmp_path / "providers.json")))
    events = run(collect(worker.ephemeral, {"role": "rotina", "text": "x"}))
    assert events[-1]["type"] == "error" and events[-1]["kind"] == "not_configured"
    status = run(collect(worker.status, {}))[-1]
    assert status["ai_configured"] is False and status["default_connection"] is None


def test_panel_and_team_steps_use_the_requested_connection(tmp_path):
    worker, providers = make(tmp_path, claude="ok", local="ok")
    events = run(collect(worker.panel, {"question": "q", "roles": ["diagnostico"], "connection": "local"}))
    assert events[-1]["type"] == "done"
    assert {role for role, _ in providers["local"].sent} == {"diagnostico", "sintese", "auditor"}
    assert providers["claude"].sent == []


def test_provider_admin_never_returns_secrets(tmp_path):
    runtime = Runtime(ConnectionStore(tmp_path / "providers.json"))
    worker = MentorWorker(tmp_path, runtime=runtime)
    saved = run(collect(worker.providers, {"op": "providers", "action": "save", "type": "anthropic",
                                           "settings": {"model": "claude-opus-5-5"},
                                           "api_key": "chave-ficticia-NUNCA-SAI-9999"}))[-1]
    assert saved["ok"] and saved["connection"]["secret_hint"] == "…9999"
    listed = run(collect(worker.providers, {"op": "providers", "action": "list"}))[-1]
    types = run(collect(worker.providers, {"op": "providers", "action": "types"}))[-1]
    for payload in (saved, listed, types):
        assert "NUNCA-SAI" not in json.dumps(payload)
    assert {t["type"] for t in types["types"]} >= {"anthropic", "openai", "claude_code", "codex", "ollama", "gemini",
                                                    "openrouter", "openai_compatible"}


def test_unknown_admin_action_is_refused(tmp_path):
    worker = MentorWorker(tmp_path, runtime=Runtime(None))
    for action in ("__init__", "__class__", "handle", "", None):
        with pytest.raises(ValueError):
            run(collect(worker.providers, {"action": action}))


def test_api_key_revoke_clears_it(tmp_path):
    runtime = Runtime(ConnectionStore(tmp_path / "providers.json"))
    worker = MentorWorker(tmp_path, runtime=runtime)
    saved = run(collect(worker.providers, {"action": "save", "type": "openai", "api_key": "chave-ficticia-123456789012345"}))
    conn_id = saved[-1]["connection"]["id"]
    result = run(collect(worker.providers, {"action": "revoke", "id": conn_id}))[-1]
    assert result["ok"] and runtime.get(conn_id).secret == {}


# ---------------------------------------------------------------- Codex app-server (processo falso)

def test_codex_adapter_with_fake_app_server(tmp_path, monkeypatch):
    from mentor.session import session_spec

    fake = FIXTURES / "fake_codex_app_server.py"
    monkeypatch.setenv("LASTRO_CODEX_PATH", sys.executable)
    monkeypatch.setenv("LASTRO_CODEX_HOME", str(tmp_path / "codex"))
    provider = CodexProvider(Connection(id="cx", type="codex"))
    provider.server.argv = [sys.executable, str(fake)]
    provider.server.env = {**provider.server.env, "FAKE_CODEX_LOG": str(tmp_path / "log.jsonl")}

    async def go():
        session = await provider.open(session_spec(role="planejador", workdir=tmp_path))
        events = []

        async def emit(event):
            events.append(event)
        out = await session.send("Quanto devo ter de reserva?", emit)
        await provider.close()
        return out, events
    out, events = run(go())
    log = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]
    start = next(m for m in log if m.get("method") == "thread/start")["params"]
    assert start["sandbox"] == "read-only" and start["ephemeral"] is True
    assert {t["name"] for t in start["dynamicTools"]} >= {"situacao_atual", "calcular"}
    answers = {m["id"]: m for m in log if "id" in m and ("result" in m or "error" in m) and m["id"] >= 100}
    assert answers[100]["result"]["success"] is False                 # ferramenta fora da concessão
    assert answers[101]["result"] == {"decision": "decline"}         # comando nativo recusado
    assert "error" in answers[102]                                   # pedido desconhecido: erro
    assert out.status == "ok" and out.text == "Resposta final." and out.usage == {"input_tokens": 11,
                                                                                  "output_tokens": 4}
    assert [e["name"] for e in events if e["type"] == "tool"] == ["transferir_dinheiro"]
    init = next(m for m in log if m.get("method") == "initialize")["params"]
    assert init["capabilities"]["experimentalApi"] is True


def test_codex_runs_with_native_tools_disabled_and_minimal_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MPA_AGENT_API_TOKEN", "segredo-do-lastro")
    monkeypatch.setenv("LASTRO_CODEX_HOME", str(tmp_path / "codex"))
    provider = CodexProvider(Connection(id="cx", type="codex"))
    argv = provider.server.argv
    for feature in ("shell_tool", "unified_exec", "apps", "plugins", "multi_agent"):
        assert argv[argv.index(feature) - 1] == "--disable"
    assert 'web_search="disabled"' in argv and 'sandbox_mode="read-only"' in argv
    assert "MPA_AGENT_API_TOKEN" not in provider.server.env
    assert provider.server.env["CODEX_HOME"] == str(tmp_path / "codex")


# ---------------------------------------------------------------- login do Claude Code (terminal virtual)

@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="pty: só Linux")
def test_claude_code_paste_login_with_fake_cli(tmp_path):
    from providers.cli_login import CodeLogin

    fake = FIXTURES / "fake_claude_login.py"

    async def go():
        login = CodeLogin([sys.executable, str(fake)], {"PATH": "/usr/bin:/bin"})
        started = await login.start()
        assert started["state"] == "waiting_code" and started["url"].startswith("https://claude.ai/oauth/authorize")
        rejected = await login.submit("bad\ncode")
        assert "inválido" in rejected["error"] and login.state == "waiting_code"
        return await login.submit("CODIGO#123")
    done = run(go())
    assert done["state"] == "done" and "CODIGO" not in json.dumps(done)


def test_claude_login_refuses_foreign_link_hosts():
    from providers.cli_login import CodeLogin

    login = CodeLogin(["x"], {})
    assert login._host_ok("https://claude.ai/oauth/authorize?x=1")
    assert login._host_ok("https://console.anthropic.com/oauth")
    assert not login._host_ok("https://claude.ai.evil.example/oauth")
    assert not login._host_ok("https://evil.example/claude.ai")
