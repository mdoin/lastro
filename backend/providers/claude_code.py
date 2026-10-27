# SPDX-License-Identifier: AGPL-3.0-or-later
"""Claude Code: o executável oficial da Anthropic, rodado pelo Claude Agent SDK, sem modificação.

Desenho estudado no OpenBot (só ideias; nenhum código copiado):
- o Lastro não faz login próprio do Claude.ai: quem autentica é o CLI (`claude auth login --claudeai`, ou uma
  API key em `ANTHROPIC_API_KEY`, que tem precedência). O CLI guarda a credencial no HOME do worker; o Lastro
  nunca lê, copia nem guarda esse token, e consulta só `claude auth status`;
- o autoatualizador do CLI fica desligado; o binário é o que veio no wheel (hash conferido pelo uv.lock) ou o
  apontado por `LASTRO_CLAUDE_PATH`.

Barreiras técnicas, independentes do prompt:
- `tools=[]`: nenhuma ferramenta nativa (sem terminal, arquivos, web, agendamento);
- `strict_mcp_config` + `setting_sources=[]`: ignora configurações e MCPs do disco;
- sem `allowed_tools`: toda chamada passa por `can_use_tool`, que só libera as ferramentas concedidas ao papel;
- diretório de trabalho vazio e dedicado.

Termos: ver docs/PROVIDER_TERMS.md antes de usar uma assinatura Claude neste modo.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .base import (AgentSession, Emit, Provider, ProviderCapabilities, ProviderError, SessionSpec,
                   TurnOutcome)
from .loop import finalize_quiet
from .toolspec import DENIED, ToolSpec

SERVER_NAME = "patrimonio"
MCP_PREFIX = f"mcp__{SERVER_NAME}__"
QUIET_TOOL = f"{MCP_PREFIX}sem_novidade"
MODEL_ALIASES = [{"id": "", "label": "Padrão do Claude Code"}, {"id": "opus", "label": "Opus"},
                 {"id": "sonnet", "label": "Sonnet"}, {"id": "haiku", "label": "Haiku"}]

_ASSISTANT_ERRORS = {
    "authentication_failed": "auth",
    "billing_error": "rate_limit",
    "rate_limit": "rate_limit",
    "server_error": "network",
    "invalid_request": "internal",
    "unknown": "internal",
}


def available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def cli_path() -> Path | None:
    explicit = os.environ.get("LASTRO_CLAUDE_PATH")
    if explicit:
        return Path(explicit)
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
    for name in ("claude", "claude.exe"):
        if (bundled / name).exists():
            return bundled / name
    return None


def cli_env(api_key: str | None = None) -> dict:
    env = {"DISABLE_AUTOUPDATER": "1"}
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    return env


def mcp_name(tool_name: str) -> str:
    return MCP_PREFIX + tool_name


def short_tool_name(name: str) -> str:
    return name[len(MCP_PREFIX):] if name.startswith(MCP_PREFIX) else name


def tool_gate(allowed: set[str]):
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    async def gate(tool_name: str, _input: dict, _context) -> PermissionResultAllow | PermissionResultDeny:
        if tool_name in allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message=DENIED)
    return gate


def sdk_tool(spec: ToolSpec):
    from claude_agent_sdk import SdkMcpTool
    from mcp.types import ToolAnnotations

    annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                  open_world_hint=spec.open_world)
    return SdkMcpTool(name=spec.name, description=spec.description, input_schema=spec.input_schema,
                      handler=spec.handler, annotations=annotations)


def claude_options(spec: SessionSpec, *, api_key: str | None = None):
    from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server

    server = create_sdk_mcp_server(name=SERVER_NAME, version="0.1.0", tools=[sdk_tool(t) for t in spec.tools])
    path = os.environ.get("LASTRO_CLAUDE_PATH")
    return ClaudeAgentOptions(
        tools=[],
        mcp_servers={SERVER_NAME: server},
        strict_mcp_config=True,
        setting_sources=[],
        can_use_tool=tool_gate({mcp_name(t.name) for t in spec.tools}),
        permission_mode="default",
        system_prompt=spec.system_prompt,
        cwd=str(spec.workdir),
        session_id=spec.session_id,
        resume=spec.resume,
        model=spec.model or None,
        effort=spec.effort,
        max_turns=spec.max_turns,
        include_partial_messages=True,
        extra_args={"no-session-persistence": None} if spec.ephemeral else {},
        env=cli_env(api_key),
        **({"cli_path": path} if path else {}),
    )


def _kind_from_status(code: int | None) -> str:
    if code == 429:
        return "rate_limit"
    if code in (401, 403):
        return "auth"
    if code and code >= 500:
        return "network"
    return "internal"


async def run_turn(client, prompt: str, emit: Emit) -> TurnOutcome:
    """Executa um turno e traduz as mensagens do SDK em eventos do Lastro (delta, tool)."""
    from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, TextBlock, ToolUseBlock
    from claude_agent_sdk.types import StreamEvent

    out = TurnOutcome()
    texts: list[str] = []  # texto desde a última ferramenta; o anterior é narração ("vou consultar…")
    narration: list[str] = []
    await client.query(prompt)
    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            event = message.event
            if message.parent_tool_use_id is None and event.get("type") == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    await emit({"type": "delta", "text": delta["text"]})
        elif isinstance(message, AssistantMessage):
            if message.parent_tool_use_id is not None:
                continue
            if message.error:
                out.error_kind = _ASSISTANT_ERRORS.get(message.error, "internal")
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    narration.extend(texts)
                    texts = []
                    tool = {"name": short_tool_name(block.name), "input": block.input}
                    out.tools.append(tool)
                    out.quiet = out.quiet or block.name == QUIET_TOOL
                    await emit({"type": "tool", **tool})
        elif isinstance(message, RateLimitEvent):
            if message.rate_limit_info.status == "rejected":
                out.limit_resets_at = message.rate_limit_info.resets_at
                out.error_kind = "rate_limit"
        elif isinstance(message, ResultMessage):
            out.session_id = message.session_id
            usage = message.usage or {}
            out.add_usage(input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0))
            if message.terminal_reason in ("aborted_streaming", "aborted_tools"):
                out.status = "interrupted"
            elif message.terminal_reason == "max_turns":
                out.status, out.error_kind = "error", "max_turns"
            elif message.is_error:
                out.status = "error"
                out.error_kind = out.error_kind or _kind_from_status(message.api_error_status)
    final = texts if any(t.strip() for t in texts) else narration
    out.text = "\n\n".join(t.strip() for t in final if t.strip())
    finalize_quiet(out)
    if out.error_kind and out.status == "ok":
        out.status = "error"
    return out


class ClaudeCodeSession(AgentSession):
    def __init__(self, client):
        self.client = client
        self.native_id = None

    async def send(self, prompt: str, emit: Emit) -> TurnOutcome:
        outcome = await run_turn(self.client, prompt, emit)
        self.native_id = outcome.session_id or self.native_id
        return outcome

    async def interrupt(self) -> None:
        await self.client.interrupt()

    async def close(self) -> None:
        await self.client.disconnect()


class ClaudeCodeProvider(Provider):
    type = "claude_code"
    label = "Claude Code (executável oficial)"
    capabilities = ProviderCapabilities(
        native_resume=True, model_listing=False, api_key=True, external_login=True,
        notes="Roda o CLI oficial da Anthropic. Login pelo próprio CLI (o Lastro não vê o token) ou API key. "
              "Leia docs/PROVIDER_TERMS.md antes de usar uma assinatura.")
    settings_schema = {"model": "opus, sonnet, haiku ou id completo (vazio = padrão do CLI)"}

    def __init__(self, connection, *, client_factory=None):
        super().__init__(connection)
        self.client_factory = client_factory

    def is_configured(self) -> bool:
        return self.client_factory is not None or available()

    async def open(self, spec: SessionSpec) -> ClaudeCodeSession:
        if not self.is_configured():
            raise ProviderError("not_configured", "O Claude Code não está instalado neste worker (extra claude-code).")
        factory = self.client_factory
        if factory is None:
            from claude_agent_sdk import ClaudeSDKClient as factory
        spec.model = spec.model or self.default_model
        client = factory(options=claude_options(spec, api_key=self.connection.secret.get("api_key")))
        await client.connect()
        return ClaudeCodeSession(client)

    async def list_models(self) -> list[dict]:
        return MODEL_ALIASES

    async def test(self) -> dict:
        if self.connection.secret.get("api_key"):
            return {"ok": True, "detail": "API key configurada (tem precedência sobre o login do CLI)."}
        status = await auth_status()
        if status["logged_in"]:
            return {"ok": True, "detail": f"CLI conectado ({status.get('subscription') or 'conta Claude'})."}
        if status["logged_in"] is None:
            return {"ok": False, "detail": "Não foi possível consultar o CLI do Claude Code."}
        return {"ok": False, "detail": "CLI do Claude Code sem login."}

    async def account(self) -> dict:
        return await auth_status()


_auth_cache: tuple[float, dict] | None = None


async def auth_status(*, fresh: bool = False) -> dict:
    """`claude auth status --json` com cache; timeout vira "desconhecido", nunca "deslogado"."""
    global _auth_cache
    if not fresh and _auth_cache and time.monotonic() - _auth_cache[0] < 300:
        return _auth_cache[1]
    result = {"logged_in": None, "subscription": None}
    cli = cli_path()
    if cli is None:
        return result
    try:
        proc = await asyncio.create_subprocess_exec(str(cli), "auth", "status", "--json",
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                    env={**os.environ, **cli_env()})
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        data = json.loads(stdout or b"{}")
        result = {"logged_in": bool(data.get("loggedIn")), "subscription": data.get("subscriptionType")}
    except (asyncio.TimeoutError, OSError, json.JSONDecodeError):
        pass
    _auth_cache = (time.monotonic(), result)
    return result


def forget_auth_status() -> None:
    global _auth_cache
    _auth_cache = None


async def logout() -> bool:
    cli = cli_path()
    if cli is None:
        return False
    proc = await asyncio.create_subprocess_exec(str(cli), "auth", "logout", stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.DEVNULL, env={**os.environ, **cli_env()})
    await asyncio.wait_for(proc.wait(), timeout=30)
    forget_auth_status()
    return proc.returncode == 0


def main(argv=None) -> int:
    """Login no terminal do operador: `python -m providers.claude_code login|status|logout`."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    cli = cli_path()
    if cli is None:
        print("Claude Code não instalado (instale o extra claude-code ou defina LASTRO_CLAUDE_PATH).", file=sys.stderr)
        return 2
    command = args[0] if args else "status"
    if command == "login":
        os.execvpe(str(cli), [str(cli), "auth", "login", "--claudeai"], {**os.environ, **cli_env()})
    if command == "logout":
        return 0 if asyncio.run(logout()) else 1
    print(json.dumps(asyncio.run(auth_status(fresh=True)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
