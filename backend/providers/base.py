"""Contrato do AI Provider Runtime.

Um *provedor* é um tipo de integração (Anthropic API, OpenAI, Ollama…); uma *conexão* é uma instância
configurada dele (credencial + ajustes) que pertence a esta instalação. Cada conexão abre *sessões*: o trabalho
de um agente num turno ou numa conversa. A sessão é descartável; o estado persistente do agente (histórico,
memória, decisões, relatórios) vive no banco do Lastro e é remontado quando a sessão nativa não serve mais.

Nenhum adaptador conhece o banco. Ferramentas chegam como `ToolSpec` já filtradas pelo papel do agente, e
toda chamada passa pela barreira de `toolspec.run_tool`, independentemente do que o modelo pedir.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar

from .toolspec import ToolSpec

Emit = Callable[[dict], Awaitable[None]]

# Tipos de erro normalizados (o worker e a interface só conhecem estes).
ERROR_KINDS = ("auth", "rate_limit", "network", "timeout", "internal", "max_turns", "unsupported", "not_configured")


class ProviderError(Exception):
    def __init__(self, kind: str, message: str = "", *, retry_at: float | None = None):
        super().__init__(message or kind)
        self.kind = kind if kind in ERROR_KINDS else "internal"
        self.message = message
        self.retry_at = retry_at  # epoch (s) em que o provedor volta a aceitar, se ele informou


@dataclass(frozen=True)
class ProviderCapabilities:
    """O que o adaptador realmente oferece. A interface mostra isto; o worker respeita."""
    streaming: bool = True
    tools: bool = True               # chamada de ferramentas (sem isto o agente responde sem dados do Lastro)
    cancel: bool = True
    native_resume: bool = False      # retoma sessão nativa por id (senão o contexto vem do histórico do Lastro)
    usage: bool = True               # devolve consumo (tokens) por turno
    model_listing: bool = True
    api_key: bool = False            # autentica por chave de API
    oauth: bool = False              # fluxo OAuth oficial
    revocation: bool = False         # revogação remota da credencial
    external_login: bool = False     # login feito pelo operador no executável oficial (o Lastro não vê o token)
    experimental: bool = False
    notes: str = ""

    def public(self) -> dict:
        return asdict(self)


@dataclass
class TurnOutcome:
    text: str = ""
    status: str = "ok"  # ok | error | interrupted
    session_id: str | None = None
    quiet: bool = False
    tools: list = field(default_factory=list)
    error_kind: str | None = None
    error_message: str = ""
    limit_resets_at: float | None = None  # epoch (s) quando o provedor volta a aceitar
    usage: dict = field(default_factory=dict)

    def add_usage(self, **counts) -> None:
        for key, value in counts.items():
            if value:
                self.usage[key] = self.usage.get(key, 0) + value


@dataclass
class SessionSpec:
    role: str
    system_prompt: str
    tools: list[ToolSpec]
    workdir: Path
    model: str | None = None
    max_turns: int = 8
    effort: str = "high"
    ephemeral: bool = False
    session_id: str | None = None   # id a usar numa sessão nova (quando o provedor aceita escolher)
    resume: str | None = None       # id nativo a retomar (só se capabilities.native_resume)


class AgentSession(ABC):
    """Uma sessão viva com o provedor. Um `send` por vez (o worker garante com lock)."""
    native_id: str | None = None

    @abstractmethod
    async def send(self, prompt: str, emit: Emit) -> TurnOutcome: ...

    @abstractmethod
    async def interrupt(self) -> None: ...

    async def close(self) -> None:
        return None


@dataclass
class Connection:
    """Configuração de uma conexão. `secret` nunca sai do worker (ver credentials.py)."""
    id: str
    type: str
    label: str = ""
    settings: dict = field(default_factory=dict)   # não secretos: base_url, modelo padrão, timeout, contexto…
    secret: dict = field(default_factory=dict)     # api_key ou tokens OAuth
    created_at: float = field(default_factory=time.time)


class Provider(ABC):
    type: ClassVar[str]
    label: ClassVar[str]
    capabilities: ClassVar[ProviderCapabilities]
    # Ajustes aceitos pela conexão (nome → descrição). Qualquer outro é recusado na configuração.
    settings_schema: ClassVar[dict[str, str]] = {"model": "modelo padrão"}

    def __init__(self, connection: Connection):
        self.connection = connection

    @property
    def default_model(self) -> str | None:
        return self.connection.settings.get("model") or None

    def effective_capabilities(self) -> ProviderCapabilities:
        """Capacidades desta conexão (um modelo local pode não ter ferramentas, por exemplo)."""
        return self.capabilities

    def is_configured(self) -> bool:
        return True

    @abstractmethod
    async def open(self, spec: SessionSpec) -> AgentSession: ...

    async def list_models(self) -> list[dict]:
        raise ProviderError("unsupported", "Este provedor não lista modelos.")

    async def test(self) -> dict:
        """Teste de conexão barato. Padrão: listar modelos."""
        models = await self.list_models()
        return {"ok": True, "detail": f"{len(models)} modelo(s) disponível(is)."}

    async def revoke(self) -> bool:
        raise ProviderError("unsupported", "Este provedor não oferece revogação remota.")

    async def account(self) -> dict:
        """Estado da conta/limites que o provedor informa (vazio quando não informa)."""
        return {}
