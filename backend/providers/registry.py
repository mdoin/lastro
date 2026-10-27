# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tipos de provedor disponíveis e o runtime que resolve conexão → provedor.

`Runtime` é o único ponto em que o worker escolhe um provedor. Sem nenhuma conexão salva, e com
`LASTRO_IMPLICIT_CLAUDE_CODE=1`, existe a conexão implícita `claude-code` (o comportamento da instalação
pessoal anterior), para que uma atualização não deixe o mentor sem IA.
"""

from __future__ import annotations

import re
import uuid

from . import claude_code, codex
from .anthropic_api import AnthropicProvider
from .base import Connection, Provider, ProviderError
from .credentials import ConnectionStore, public_view
from .openai_api import (GeminiProvider, OllamaProvider, OpenAICompatibleProvider, OpenAIProvider,
                         OpenRouterProvider)

TYPES: dict[str, type[Provider]] = {cls.type: cls for cls in (
    AnthropicProvider, OpenAIProvider, claude_code.ClaudeCodeProvider, codex.CodexProvider, OllamaProvider,
    OpenRouterProvider, GeminiProvider, OpenAICompatibleProvider)}
IMPLICIT_ID = "claude-code"
MAX_SETTING = 500
SECRET_BOUND = ("base_url",)  # mudar o destino apaga a chave: um web app comprometido não redireciona o segredo


def types_public() -> list[dict]:
    out = []
    for cls in TYPES.values():
        probe = cls(Connection(id="-", type=cls.type))
        installed = cls.type not in ("claude_code", "codex") or probe.is_configured()
        out.append({"type": cls.type, "label": cls.label, "capabilities": cls.capabilities.public(),
                    "settings": cls.settings_schema, "installed": installed,
                    "default_base_url": getattr(cls, "default_base_url", None)})
    return out


class Runtime:
    def __init__(self, store: ConnectionStore | None, *, implicit_claude_code: bool = False,
                 claude_client_factory=None):
        self.store = store
        self.implicit_claude_code = implicit_claude_code
        self.claude_client_factory = claude_client_factory
        self._cache: dict[str, Provider] = {}

    # ---- leitura ----
    def connections(self) -> list[Connection]:
        stored = self.store.list() if self.store else []
        if self.implicit_claude_code and not any(c.id == IMPLICIT_ID for c in stored):
            stored.append(Connection(id=IMPLICIT_ID, type="claude_code", label="Claude Code (instalação atual)"))
        return stored

    def default_id(self) -> str | None:
        chosen = self.store.default_id() if self.store else None
        if chosen:
            return chosen
        connections = self.connections()
        return connections[0].id if connections else None

    def get(self, conn_id: str | None) -> Connection | None:
        conn_id = conn_id or self.default_id()
        return next((c for c in self.connections() if c.id == conn_id), None)

    def provider(self, conn_id: str | None) -> Provider:
        conn = self.get(conn_id)
        if conn is None:
            raise ProviderError("not_configured", "Nenhum provedor de IA configurado. Conecte um em Configurações.")
        cached = self._cache.get(conn.id)
        if cached is not None and cached.connection.type == conn.type:
            cached.connection = conn
            return cached
        cls = TYPES.get(conn.type)
        if cls is None:
            raise ProviderError("not_configured", f"Tipo de provedor desconhecido: {conn.type[:40]}")
        provider = (cls(conn, client_factory=self.claude_client_factory) if cls is claude_code.ClaudeCodeProvider
                    else cls(conn))
        self._cache[conn.id] = provider
        return provider

    def public(self) -> list[dict]:
        default = self.default_id()
        return [public_view(c, self.provider(c.id), default_id=default) for c in self.connections()]

    # ---- escrita (só pelo web app autenticado, via socket) ----
    def save(self, *, conn_type: str, label: str = "", settings: dict | None = None, api_key: str | None = None,
             conn_id: str | None = None, make_default: bool = False) -> dict:
        if self.store is None:
            raise ProviderError("not_configured", "Armazenamento de conexões indisponível.")
        cls = TYPES.get(conn_type)
        if cls is None:
            raise ProviderError("unsupported", "Tipo de provedor desconhecido.")
        clean = {}
        for key, value in (settings or {}).items():
            if key not in cls.settings_schema:
                raise ProviderError("unsupported", f"Ajuste não aceito por este provedor: {str(key)[:40]}")
            value = str(value if value is not None else "").strip()
            if len(value) > MAX_SETTING:
                raise ProviderError("unsupported", f"Valor longo demais em {key}.")
            if key == "base_url" and value and not re.match(r"^https?://[^\s]+$", value):
                raise ProviderError("unsupported", "base_url precisa começar com http:// ou https://.")
            if value:
                clean[key] = value
        existing = self.store.get(conn_id) if conn_id else None
        if existing and existing.type != conn_type:
            raise ProviderError("unsupported", "Não é possível mudar o tipo de uma conexão; crie outra.")
        secret = dict(existing.secret) if existing else {}
        if existing and any(existing.settings.get(k) != clean.get(k) for k in SECRET_BOUND):
            secret = {}
        if api_key is not None:
            api_key = api_key.strip()
            if api_key and (len(api_key) > 512 or not re.match(r"^[\x21-\x7e]+$", api_key)):
                raise ProviderError("unsupported", "Chave em formato inválido.")
            secret = {"api_key": api_key} if api_key else {}
        conn = Connection(id=existing.id if existing else (conn_id or f"{conn_type}-{uuid.uuid4().hex[:8]}"),
                          type=conn_type, label=label.strip()[:80], settings=clean, secret=secret,
                          **({"created_at": existing.created_at} if existing else {}))
        self.store.save(conn, make_default=make_default)
        self._cache.pop(conn.id, None)
        return public_view(conn, self.provider(conn.id), default_id=self.default_id())

    def delete(self, conn_id: str) -> bool:
        self._cache.pop(conn_id, None)
        return bool(self.store and self.store.delete(conn_id))

    def set_default(self, conn_id: str) -> None:
        if self.store is None or self.store.get(conn_id) is None:
            raise ProviderError("not_configured", "Conexão inexistente.")
        self.store.set_default(conn_id)
