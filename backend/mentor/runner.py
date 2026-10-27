"""Executa um turno no Claude e traduz as mensagens do SDK em eventos do Lastro.

Eventos emitidos: {"type": "delta", "text"} e {"type": "tool", "name", "input"}.
O resultado do turno volta como `TurnOutcome` (o worker decide o que fazer com
limites de uso, erros e interrupções).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, TextBlock, ToolUseBlock
from claude_agent_sdk.types import StreamEvent

from .tools import QUIET_TOOL, SERVER_NAME

Emit = Callable[[dict], Awaitable[None]]

_ASSISTANT_ERRORS = {
    "authentication_failed": "auth",
    "billing_error": "rate_limit",
    "rate_limit": "rate_limit",
    "server_error": "network",
    "invalid_request": "internal",
    "unknown": "internal",
}


@dataclass
class TurnOutcome:
    text: str = ""
    status: str = "ok"  # ok | error | interrupted
    session_id: str | None = None
    quiet: bool = False
    tools: list = field(default_factory=list)
    error_kind: str | None = None
    limit_resets_at: int | None = None  # epoch (s) quando a assinatura volta a aceitar


def short_tool_name(name: str) -> str:
    prefix = f"mcp__{SERVER_NAME}__"
    return name[len(prefix):] if name.startswith(prefix) else name


def _kind_from_status(code: int | None) -> str:
    if code == 429:
        return "rate_limit"
    if code in (401, 403):
        return "auth"
    if code and code >= 500:
        return "network"
    return "internal"


async def run_turn(client, prompt: str, emit: Emit) -> TurnOutcome:
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
            if message.terminal_reason in ("aborted_streaming", "aborted_tools"):
                out.status = "interrupted"
            elif message.terminal_reason == "max_turns":
                out.status, out.error_kind = "error", "max_turns"
            elif message.is_error:
                out.status = "error"
                out.error_kind = out.error_kind or _kind_from_status(message.api_error_status)
    final = texts if any(t.strip() for t in texts) else narration
    out.text = "\n\n".join(t.strip() for t in final if t.strip())
    # "Sem novidade" esconde a execução da caixa de entrada: só vale se o texto final for mesmo só isso.
    out.quiet = out.quiet and out.text.strip().rstrip(".!").strip().lower() in ("", "sem novidade")
    if out.error_kind and out.status == "ok":
        out.status = "error"
    return out
