# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI Provider Runtime: contrato, barreira de ferramentas, adaptadores HTTP, credenciais e erros.

Nenhum teste chama um provedor de verdade: os SDKs oficiais recebem um transporte HTTP simulado.
"""

import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path

import httpx2
import pytest

from providers.anthropic_api import AnthropicProvider
from providers.base import Connection, ProviderError, SessionSpec
from providers.credentials import ConnectionStore
from providers.openai_api import OllamaProvider, OpenAIProvider
from providers.registry import Runtime
from providers.toolspec import DENIED, run_tool, tool

CALLS = []
FAKE_KEY = "chave-ficticia-SEGREDO-abcd1234"


@tool("metas", "Metas do usuário", {})
async def metas(_args):
    CALLS.append("metas")
    return {"content": [{"type": "text", "text": '{"metas": []}'}]}


@tool("calcular", "Calcula", {"type": "object", "properties": {"operacao": {"type": "string"}},
                               "required": ["operacao"]})
async def calcular(args):
    return {"content": [{"type": "text", "text": f"ok {args['operacao']}"}]}


def spec(tmp_path, tools=(metas,), **kw):
    return SessionSpec(role="mentor", system_prompt="Você é o Mentor.", tools=list(tools), workdir=tmp_path,
                       model="modelo-teste", max_turns=kw.pop("max_turns", 5), **kw)


async def collect(session, prompt="oi"):
    events = []

    async def emit(event):
        events.append(event)
    return await session.send(prompt, emit), events


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- barreira de ferramentas

def test_run_tool_denies_unknown_and_validates_input():
    CALLS.clear()
    granted = {"metas": metas, "calcular": calcular}
    assert run(run_tool(granted, "Bash", {"cmd": "rm -rf /"})) == (DENIED, True)
    assert run(run_tool(granted, "transferir", {})) == (DENIED, True)
    assert run(run_tool(granted, "calcular", {}))[1] is True          # campo obrigatório ausente
    assert run(run_tool(granted, "calcular", "não é json"))[1] is True
    assert run(run_tool(granted, "calcular", '{"operacao": "x"}')) == ("ok x", False)
    assert CALLS == []


def test_failing_tool_becomes_error_result():
    @tool("quebra", "x", {})
    async def quebra(_):
        raise RuntimeError("segredo interno")
    text, is_error = run(run_tool({"quebra": quebra}, "quebra", {}))
    assert is_error and "RuntimeError" in text and "segredo" not in text


# ---------------------------------------------------------------- Anthropic (Messages API)

def anthropic_sse(blocks, stop_reason, usage=(10, 5)):
    events = [("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "modelo-teste", "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": usage[0], "output_tokens": 1}}})]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events.append(("content_block_start", {"type": "content_block_start", "index": i,
                                                   "content_block": {"type": "text", "text": ""}}))
            events.append(("content_block_delta", {"type": "content_block_delta", "index": i,
                                                   "delta": {"type": "text_delta", "text": block["text"]}}))
        else:
            events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": {
                "type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}}))
            events.append(("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                "type": "input_json_delta", "partial_json": json.dumps(block["input"])}}))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason,
                                                                        "stop_sequence": None},
                                     "usage": {"output_tokens": usage[1]}}))
    events.append(("message_stop", {"type": "message_stop"}))
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def mock_client(responses, seen):
    def handler(request):
        seen.append(request)
        status, body, headers = responses.pop(0)
        return httpx2.Response(status, content=body, headers={"content-type": "text/event-stream", **headers})
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def anthropic(responses, seen, **settings):
    conn = Connection(id="a", type="anthropic", settings={"model": "modelo-teste", **settings},
                      secret={"api_key": "chave-ficticia-anthropic-0000"})
    return AnthropicProvider(conn, http_client=mock_client(responses, seen))


def test_anthropic_tool_loop_streams_and_keeps_history(tmp_path):
    CALLS.clear()
    seen = []
    provider = anthropic([
        (200, anthropic_sse([{"type": "text", "text": "Vou consultar."},
                             {"type": "tool_use", "id": "tu_1", "name": "metas", "input": {}},
                             {"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {"cmd": "ls"}}], "tool_use"), {}),
        (200, anthropic_sse([{"type": "text", "text": "Você não tem metas."}], "end_turn"), {}),
    ], seen)

    async def go():
        session = await provider.open(spec(tmp_path))
        return await collect(session), session
    (out, events), session = run(go())
    assert out.status == "ok" and out.text == "Você não tem metas."
    assert CALLS == ["metas"]                                         # Bash nunca executa
    assert [e["name"] for e in events if e["type"] == "tool"] == ["metas", "Bash"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Vou consultar.Você não tem metas."
    assert out.usage == {"input_tokens": 20, "output_tokens": 10}
    second = json.loads(seen[1].content)
    results = second["messages"][2]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_1", "tu_2"]   # todos os resultados numa mensagem
    assert results[1]["is_error"] is True and results[1]["content"] == DENIED
    assert second["system"] == "Você é o Mentor." and second["tools"][0]["name"] == "metas"
    assert seen[0].headers["x-api-key"] == "chave-ficticia-anthropic-0000"
    assert len(session.messages) == 4


@pytest.mark.parametrize("status,headers,kind", [
    (401, {}, "auth"), (403, {}, "auth"), (429, {"retry-after": "120"}, "rate_limit"),
    (500, {}, "network"), (400, {}, "unsupported"),
])
def test_anthropic_errors_are_normalized(tmp_path, status, headers, kind):
    body = json.dumps({"type": "error", "error": {"type": "x", "message": "chave-ficticia-anthropic-0000"}}).encode()
    provider = anthropic([(status, body, {"content-type": "application/json", **headers})], [])

    async def go():
        return await collect(await provider.open(spec(tmp_path)))
    out, _ = run(go())
    assert out.status == "error" and out.error_kind == kind
    assert "chave-ficticia" not in out.error_message                          # mensagem nunca ecoa a credencial
    if kind == "rate_limit":
        assert out.limit_resets_at and out.limit_resets_at > time.time() + 100


def test_provider_without_credentials_or_model_is_not_configured(tmp_path):
    no_key = AnthropicProvider(Connection(id="a", type="anthropic", settings={"model": "m"}))
    assert not no_key.is_configured()
    with pytest.raises(ProviderError) as exc:
        no_key.client()
    assert exc.value.kind == "not_configured"
    no_model = AnthropicProvider(Connection(id="a", type="anthropic", secret={"api_key": "k"}))
    with pytest.raises(ProviderError):
        run(no_model.open(SessionSpec(role="mentor", system_prompt="", tools=[], workdir=tmp_path)))


def test_interrupt_cancels_and_leaves_consistent_history(tmp_path):
    release = asyncio.Event()

    async def slow(_args):
        await release.wait()
        return {"content": [{"type": "text", "text": "x"}]}
    lento = tool("lento", "demora", {})(slow)
    provider = anthropic([(200, anthropic_sse([{"type": "tool_use", "id": "t", "name": "lento", "input": {}}],
                                              "tool_use"), {})], [])

    async def go():
        session = await provider.open(spec(tmp_path, tools=(lento,)))
        task = asyncio.create_task(collect(session))
        await asyncio.sleep(0.2)
        await session.interrupt()
        out, _ = await task
        return out, session
    out, session = run(go())
    assert out.status == "interrupted"
    assert [m["role"] for m in session.messages] == ["user", "assistant"]  # sem tool_use pendurado
    assert isinstance(session.messages[1]["content"], str)


def test_max_turns_is_enforced(tmp_path):
    loop = anthropic_sse([{"type": "tool_use", "id": "t", "name": "metas", "input": {}}], "tool_use")
    provider = anthropic([(200, loop, {}), (200, loop, {})], [])

    async def go():
        return await collect(await provider.open(spec(tmp_path, max_turns=2)))
    out, _ = run(go())
    assert out.status == "error" and out.error_kind == "max_turns"


# ---------------------------------------------------------------- OpenAI Responses

def openai_sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def response_obj(output, status="completed"):
    return {"id": "resp_1", "object": "response", "created_at": 1, "model": "modelo-teste", "status": status,
            "output": output, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}


def test_openai_responses_tool_loop_without_server_storage(tmp_path):
    CALLS.clear()
    seen = []
    call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "metas", "arguments": "{}",
            "status": "completed"}
    message = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "Pronto.", "annotations": []}]}
    responses = [
        (200, openai_sse([{"type": "response.completed", "sequence_number": 1, "response": response_obj([call])}]), {}),
        (200, openai_sse([{"type": "response.output_text.delta", "sequence_number": 1, "item_id": "msg_1",
                           "output_index": 0, "content_index": 0, "delta": "Pronto.", "logprobs": []},
                          {"type": "response.completed", "sequence_number": 2, "response": response_obj([message])}]),
         {}),
    ]
    conn = Connection(id="o", type="openai", settings={"model": "modelo-teste"}, secret={"api_key": "chave-ficticia-openai"})
    provider = OpenAIProvider(conn, http_client=mock_client(responses, seen))

    async def go():
        return await collect(await provider.open(spec(tmp_path)))
    out, events = run(go())
    assert out.status == "ok" and out.text == "Pronto." and CALLS == ["metas"]
    first, second = (json.loads(r.content) for r in seen)
    assert first["store"] is False and first["instructions"] == "Você é o Mentor."
    assert second["input"][-1] == {"type": "function_call_output", "call_id": "call_1", "output": '{"metas": []}'}
    assert seen[0].headers["authorization"] == "Bearer chave-ficticia-openai"


# ---------------------------------------------------------------- Chat Completions (Ollama e compatíveis)

def chat_sse(chunks):
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def chunk(delta, finish=None):
    return {"id": "c", "object": "chat.completion.chunk", "created": 1, "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def test_ollama_tool_calls_and_context_window(tmp_path):
    CALLS.clear()
    seen = []
    responses = [
        (200, chat_sse([chunk({"role": "assistant", "tool_calls": [
            {"index": 0, "id": "c1", "type": "function", "function": {"name": "met", "arguments": ""}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"name": "as", "arguments": "{}"}}]}),
            chunk({}, "tool_calls")]), {}),
        (200, chat_sse([chunk({"content": "Tudo certo."}), chunk({}, "stop")]), {}),
    ]
    conn = Connection(id="l", type="ollama", settings={"model": "llama-local", "context_tokens": "60"})
    provider = OllamaProvider(conn, http_client=mock_client(responses, seen))
    assert provider.is_configured()                                   # local: sem chave

    async def go():
        session = await provider.open(spec(tmp_path))
        session.messages = [{"role": "user", "content": "antiga " * 200}, {"role": "assistant", "content": "x"}]
        return await collect(session)
    out, _ = run(go())
    assert out.text == "Tudo certo." and CALLS == ["metas"]
    first = json.loads(seen[0].content)
    assert str(seen[0].url).startswith("http://127.0.0.1:11434/v1/")
    assert first["messages"][0]["role"] == "system"
    assert all("antiga" not in json.dumps(m) for m in first["messages"])  # cortado pela janela de contexto
    assert first["messages"][1]["role"] == "user"


def test_local_model_without_tools_capability(tmp_path):
    seen = []
    conn = Connection(id="l", type="ollama", settings={"model": "m", "tools": "não"})
    provider = OllamaProvider(conn, http_client=mock_client([(200, chat_sse([chunk({"content": "Oi"}),
                                                                              chunk({}, "stop")]), {})], seen))
    assert provider.effective_capabilities().tools is False

    async def go():
        return await collect(await provider.open(spec(tmp_path)))
    out, _ = run(go())
    assert out.text == "Oi" and "tools" not in json.loads(seen[0].content)


# ---------------------------------------------------------------- credenciais e runtime

def test_store_keeps_secret_private(tmp_path):
    store = ConnectionStore(tmp_path / "p" / "providers.json")
    runtime = Runtime(store)
    view = runtime.save(conn_type="anthropic", settings={"model": "claude-opus-5-5"},
                        api_key=FAKE_KEY)
    assert view["has_secret"] and view["secret_hint"] == "…1234" and view["configured"]
    assert "SEGREDO" not in json.dumps(runtime.public()) and "secret" not in view
    if os.name == "posix":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert runtime.default_id() == view["id"]


def test_changing_destination_drops_the_key(tmp_path):
    runtime = Runtime(ConnectionStore(tmp_path / "providers.json"))
    view = runtime.save(conn_type="openai_compatible", settings={"base_url": "https://a.example/v1", "model": "m"},
                        api_key=FAKE_KEY)
    moved = runtime.save(conn_type="openai_compatible", conn_id=view["id"],
                         settings={"base_url": "https://atacante.example/v1", "model": "m"})
    assert not moved["has_secret"]                                    # a chave não segue para o novo destino
    kept = runtime.save(conn_type="openai_compatible", conn_id=view["id"], label="renomeada",
                        settings={"base_url": "https://atacante.example/v1", "model": "m2"})
    assert not kept["has_secret"] and kept["label"] == "renomeada"


@pytest.mark.parametrize("kwargs", [
    {"conn_type": "inexistente"},
    {"conn_type": "anthropic", "settings": {"cli_path": "/bin/sh"}},
    {"conn_type": "openai_compatible", "settings": {"base_url": "file:///etc/passwd"}},
    {"conn_type": "anthropic", "api_key": "chave com espaço"},
    {"conn_type": "anthropic", "api_key": "x\ny"},
])
def test_invalid_connections_are_refused(tmp_path, kwargs):
    with pytest.raises(ProviderError):
        Runtime(ConnectionStore(tmp_path / "providers.json")).save(**kwargs)


def test_runtime_without_connections_reports_not_configured(tmp_path):
    runtime = Runtime(ConnectionStore(tmp_path / "providers.json"))
    assert runtime.public() == [] and runtime.default_id() is None
    with pytest.raises(ProviderError) as exc:
        runtime.provider(None)
    assert exc.value.kind == "not_configured"


def test_store_write_is_atomic(tmp_path, monkeypatch):
    store = ConnectionStore(tmp_path / "providers.json")
    store.save(Connection(id="a", type="anthropic", secret={"api_key": "k1"}))
    monkeypatch.setattr(json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disco cheio")))
    with pytest.raises(OSError):
        store.save(Connection(id="b", type="anthropic"))
    monkeypatch.undo()
    assert [c.id for c in store.list()] == ["a"]                      # arquivo anterior intacto
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.skipif(sys.platform == "win32", reason="permissões POSIX")
def test_store_file_is_owner_only(tmp_path):
    store = ConnectionStore(tmp_path / "providers.json")
    store.save(Connection(id="a", type="anthropic", secret={"api_key": "k"}))
    assert stat.S_IMODE(Path(store.path).stat().st_mode) == 0o600
