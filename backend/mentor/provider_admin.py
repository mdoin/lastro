# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operação `providers` do worker: conexões de IA, teste, modelos e login oficial dos executáveis.

Quem chama é só o web app (socket Unix, conferido por SO_PEERCRED), e o web app só repassa pedidos do dono
autenticado. Nenhuma resposta carrega segredo: chaves voltam mascaradas e o código colado no login do Claude
segue só em direção ao CLI.
"""

from __future__ import annotations

import logging
import os

from providers import claude_code
from providers.base import ProviderError
from providers.cli_login import CodeLogin
from providers.registry import Runtime, types_public

log = logging.getLogger("lastro.mentor.providers")
ENV_DROP = ("MPA_", "LASTRO_", "ANTHROPIC_", "OPENAI_")
ACTIONS = {"types", "list", "save", "delete", "default", "test", "models", "account", "revoke", "login_start",
           "login_submit", "login_status", "login_cancel", "codex_api_key"}


def _cli_env() -> dict:
    """Ambiente do CLI de login: sem tokens do Lastro nem chaves de outros provedores."""
    return {**{k: v for k, v in os.environ.items() if not k.startswith(ENV_DROP)}, **claude_code.cli_env()}


class ProviderAdmin:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self.claude_login: CodeLogin | None = None

    async def handle(self, req: dict) -> dict:
        action = str(req.get("action") or "")
        if action not in ACTIONS:
            raise ValueError("ação de provedor desconhecida")
        try:
            return await getattr(self, f"_{action}")(req)
        except ProviderError as exc:
            return {"ok": False, "kind": exc.kind, "detail": exc.message or exc.kind}

    # ---- conexões ----
    async def _types(self, _req) -> dict:
        return {"types": types_public()}

    async def _list(self, _req) -> dict:
        return {"connections": self.runtime.public(), "default": self.runtime.default_id()}

    async def _save(self, req) -> dict:
        view = self.runtime.save(conn_type=str(req.get("type") or ""), label=str(req.get("label") or ""),
                                 settings=req.get("settings") or {}, api_key=req.get("api_key"),
                                 conn_id=req.get("id"), make_default=bool(req.get("make_default")))
        return {"ok": True, "connection": view}

    async def _delete(self, req) -> dict:
        return {"ok": self.runtime.delete(str(req.get("id") or ""))}

    async def _default(self, req) -> dict:
        self.runtime.set_default(str(req.get("id") or ""))
        return {"ok": True}

    async def _test(self, req) -> dict:
        provider = self.runtime.provider(req.get("id"))
        try:
            return await provider.test()
        except ProviderError as exc:
            return {"ok": False, "kind": exc.kind, "detail": exc.message or exc.kind}

    async def _models(self, req) -> dict:
        return {"ok": True, "models": await self.runtime.provider(req.get("id")).list_models()}

    async def _account(self, req) -> dict:
        return {"ok": True, "account": await self.runtime.provider(req.get("id")).account()}

    async def _revoke(self, req) -> dict:
        provider = self.runtime.provider(req.get("id"))
        if provider.type == "claude_code":
            return {"ok": await claude_code.logout(), "detail": "Login do Claude Code encerrado no servidor."}
        if provider.type == "codex":
            await provider.revoke()
            return {"ok": True, "detail": "Login do Codex encerrado no servidor."}
        conn = provider.connection
        self.runtime.save(conn_type=conn.type, label=conn.label, settings=conn.settings, api_key="", conn_id=conn.id)
        return {"ok": True, "detail": "Chave apagada desta instalação. Revogue-a também no painel do provedor."}

    # ---- login oficial dos executáveis ----
    async def _login_start(self, req) -> dict:
        provider = self.runtime.provider(req.get("id"))
        if provider.type == "codex":
            return {"ok": True, "kind": "device_code", **await provider.login_device_code()}
        if provider.type != "claude_code":
            raise ProviderError("unsupported", "Este provedor usa chave de API, não login.")
        cli = claude_code.cli_path()
        if cli is None:
            raise ProviderError("not_configured", "Claude Code não instalado neste worker.")
        if self.claude_login:
            await self.claude_login.cancel()
        self.claude_login = CodeLogin([str(cli), "auth", "login", "--claudeai"], _cli_env())
        started = await self.claude_login.start()
        return {"ok": started["state"] == "waiting_code", "kind": "paste", **started}

    async def _login_submit(self, req) -> dict:
        if self.claude_login is None:
            raise ProviderError("not_configured", "Nenhum login em andamento.")
        result = await self.claude_login.submit(str(req.get("code") or ""))
        if result["state"] == "done":
            claude_code.forget_auth_status()
        return {"ok": result["state"] == "done", **result}

    async def _login_status(self, req) -> dict:
        provider = self.runtime.provider(req.get("id"))
        if provider.type == "codex":
            return await provider.login_wait(str(req.get("login_id") or ""), timeout=1)
        return {"ok": True, **(self.claude_login.public() if self.claude_login else {"state": "idle"})}

    async def _login_cancel(self, req) -> dict:
        provider = self.runtime.provider(req.get("id"))
        if provider.type == "codex":
            await provider.server.request("account/login/cancel", {"loginId": str(req.get("login_id") or "")})
            return {"ok": True}
        if self.claude_login:
            await self.claude_login.cancel()
        return {"ok": True}

    async def _codex_api_key(self, req) -> dict:
        provider = self.runtime.provider(req.get("id"))
        if provider.type != "codex":
            raise ProviderError("unsupported", "Só para conexões do Codex.")
        return await provider.login_api_key(str(req.get("api_key") or "").strip())
