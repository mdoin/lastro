"""Ferramentas neutras (independentes de provedor) e a barreira que decide o que pode rodar.

Uma ferramenta é nome + descrição + JSON Schema + handler assíncrono que devolve o formato
`{"content": [{"type": "text", "text": ...}], "is_error": bool}`. Cada adaptador só traduz o anúncio
(MCP, function calling, tool_use); a execução é sempre `run_tool`, que recusa o que não foi concedido.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

log = logging.getLogger("lastro.providers")

DENIED = "Ferramenta indisponível: o agente só tem as ferramentas de leitura do papel dele."
MAX_RESULT_CHARS = 60_000


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Awaitable[dict]]
    open_world: bool = False   # lê conteúdo da internet (dado não confiável)


def tool(name: str, description: str, schema: dict, *, open_world: bool = False):
    """Decorador: transforma um handler assíncrono em ToolSpec. Schema vazio = sem parâmetros."""
    if not schema or "type" not in schema:
        schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def wrap(handler: Callable[[dict], Awaitable[dict]]) -> ToolSpec:
        return ToolSpec(name=name, description=description, input_schema=schema, handler=handler,
                        open_world=open_world)
    return wrap


def result_text(result: dict) -> str:
    parts = [c.get("text", "") for c in (result or {}).get("content", []) if c.get("type") == "text"]
    return "\n".join(parts)[:MAX_RESULT_CHARS]


async def run_tool(granted: dict[str, ToolSpec], name: str, args) -> tuple[str, bool]:
    """Executa uma chamada pedida pelo modelo. Nome fora da concessão → recusa, sem chamar nada."""
    spec = granted.get(name)
    if spec is None:
        log.warning("ferramenta recusada: %s", str(name)[:80])
        return DENIED, True
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return "Entrada inválida: os argumentos precisam ser um objeto JSON.", True
    if not isinstance(args, dict):
        return "Entrada inválida: os argumentos precisam ser um objeto JSON.", True
    missing = [k for k in spec.input_schema.get("required", []) if k not in args]
    if missing:
        return f"Entrada inválida: faltam {', '.join(missing)}.", True
    try:
        result = await spec.handler(args)
    except Exception as exc:  # noqa: BLE001 — falha da ferramenta vira resposta, não derruba o turno
        log.warning("ferramenta %s falhou: %s", name, type(exc).__name__)
        return f"A ferramenta falhou ({type(exc).__name__}).", True
    return result_text(result), bool(result.get("is_error"))


def by_name(tools: Iterable[ToolSpec]) -> dict[str, ToolSpec]:
    return {t.name: t for t in tools}
