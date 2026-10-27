"""Laço de ferramentas para provedores sem estado (APIs HTTP).

O provedor não guarda a conversa: a sessão mantém o histórico em memória e o reenvia a cada passo. Se o worker
reiniciar, o worker reabre a sessão com o resumo do histórico persistido no Lastro (ver mentor/worker.py).
"""

from __future__ import annotations

import asyncio
import email.utils
import time
from abc import abstractmethod
from dataclasses import dataclass, field

from .base import AgentSession, Emit, ProviderError, SessionSpec, TurnOutcome
from .toolspec import by_name, run_tool

QUIET_TOOL = "sem_novidade"


@dataclass
class Call:
    id: str
    name: str
    args: dict | str


@dataclass
class Step:
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def finalize_quiet(out: TurnOutcome) -> None:
    """"Sem novidade" esconde a execução da caixa de entrada: só vale se o texto final for mesmo só isso."""
    out.quiet = out.quiet and out.text.strip().rstrip(".!").strip().lower() in ("", "sem novidade")


class LoopSession(AgentSession):
    def __init__(self, spec: SessionSpec):
        self.spec = spec
        self.granted = by_name(spec.tools)
        self.messages: list = []
        self.native_id = None
        self._task: asyncio.Task | None = None
        self._interrupted = False

    # ---- o que cada adaptador implementa ----
    @abstractmethod
    def add_user(self, text: str) -> None: ...

    @abstractmethod
    def add_assistant_text(self, text: str) -> None: ...

    @abstractmethod
    async def step(self, emit: Emit) -> Step:
        """Uma ida ao modelo: transmite deltas de texto, registra a resposta no histórico e devolve as chamadas."""

    @abstractmethod
    def add_tool_results(self, results: list[tuple[Call, str, bool]]) -> None: ...

    # ---- laço comum ----
    async def send(self, prompt: str, emit: Emit) -> TurnOutcome:
        out = TurnOutcome()
        mark = len(self.messages)
        self._task, self._interrupted = asyncio.current_task(), False
        narration: list[str] = []
        final = ""
        self.add_user(prompt)
        try:
            for _ in range(max(1, self.spec.max_turns)):
                step = await self.step(emit)
                out.add_usage(**step.usage)
                if not step.calls:
                    final = step.text
                    break
                if step.text.strip():
                    narration.append(step.text)
                results = []
                for call in step.calls:
                    shown = call.args if isinstance(call.args, dict) else {}
                    out.tools.append({"name": call.name, "input": shown})
                    out.quiet = out.quiet or call.name == QUIET_TOOL
                    await emit({"type": "tool", "name": call.name, "input": shown})
                    text, is_error = await run_tool(self.granted, call.name, call.args)
                    results.append((call, text, is_error))
                self.add_tool_results(results)
            else:
                out.status, out.error_kind = "error", "max_turns"
        except asyncio.CancelledError:
            if not self._interrupted:
                raise
            asyncio.current_task().uncancel()
            out.status = "interrupted"
        except ProviderError as exc:
            out.status, out.error_kind, out.error_message = "error", exc.kind, exc.message
            out.limit_resets_at = exc.retry_at
        finally:
            self._task = None
        out.text = (final if final.strip() else "\n\n".join(narration)).strip()
        if out.status != "ok":
            # Histórico consistente para o próximo turno: sem chamadas de ferramenta penduradas.
            del self.messages[mark:]
            self.add_user(prompt)
            self.add_assistant_text(out.text or "(resposta interrompida)")
        finalize_quiet(out)
        return out

    async def interrupt(self) -> None:
        if self._task is not None:
            self._interrupted = True
            self._task.cancel()


def retry_at_from_headers(headers) -> float | None:
    """`retry-after` em segundos ou data HTTP → epoch."""
    value = (headers or {}).get("retry-after") if headers is not None else None
    if not value:
        return None
    try:
        return time.time() + float(value)
    except ValueError:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.timestamp() if parsed else None


def map_sdk_error(exc: Exception) -> ProviderError:
    """Erros dos SDKs oficiais (anthropic, openai) → erro normalizado. Mensagem nunca carrega a credencial."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name == "APITimeoutError":
        return ProviderError("timeout", "O provedor demorou demais para responder.")
    if name == "APIConnectionError":
        return ProviderError("network", "Falha de rede ao falar com o provedor.")
    if status in (401, 403):
        return ProviderError("auth", "Credencial recusada pelo provedor.")
    if status == 429:
        response = getattr(exc, "response", None)
        return ProviderError("rate_limit", "Limite de uso do provedor atingido.",
                             retry_at=retry_at_from_headers(getattr(response, "headers", None)))
    if status == 404:
        return ProviderError("internal", "Modelo ou rota inexistente neste provedor.")
    if status and status >= 500:
        return ProviderError("network", f"O provedor falhou ({status}).")
    if status in (400, 422):
        return ProviderError("unsupported", "O provedor recusou a requisição (parâmetro ou modelo não suportado).")
    return ProviderError("internal", f"Falha no provedor ({name}).")
