# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas `/api/providers/*` e `/api/agents/models`: conexões de IA e provedor/modelo por agente.

O web app não guarda segredo de IA: chaves seguem direto para o worker (operação `providers`) e só voltam
mascaradas. Toda resposta do worker ainda passa por `_clean`, que descarta qualquer campo de segredo.
"""

import re

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from team.agents import AGENTS

from . import store

CONN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MODEL = re.compile(r"^[A-Za-z0-9._:/@-]{0,120}$")
SECRET_KEYS = {"secret", "api_key", "access_token", "refresh_token", "id_token"}
ACTIONS = {"test": 45, "models": 45, "account": 30, "default": 15, "revoke": 45, "login_start": 60,
           "login_status": 15, "login_cancel": 15}
ROUTE_TARGETS = ("mentor", *[a for a in AGENTS if a != "mentor"])


class ConnectionIn(BaseModel):
    type: str = Field(max_length=40)
    label: str = Field("", max_length=80)
    settings: dict[str, str] = Field(default_factory=dict, max_length=12)
    api_key: str | None = Field(None, max_length=512)
    id: str | None = Field(None, max_length=64)
    make_default: bool = False


class LoginRef(BaseModel):
    login_id: str = Field("", max_length=200)


class CodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=512)


class KeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class AgentModel(BaseModel):
    connection: str = Field("", max_length=64)
    model: str = Field("", max_length=120)


class AgentModelsIn(BaseModel):
    models: dict[str, AgentModel] = Field(max_length=20)


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in SECRET_KEYS}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def register(app: FastAPI, conn, *, mentor, current_user, log_access) -> None:
    async def worker(action: str, timeout: float = 30, **fields) -> dict:
        result = await mentor.call({"op": "providers", "action": action, **fields}, timeout=timeout)
        if result.get("type") == "error":
            raise HTTPException(status_code=503, detail=result.get("message") or "Worker do mentor indisponível.")
        result.pop("type", None)  # tipo do evento do socket ("done"), não do provedor
        return _clean(result)

    def conn_id_ok(conn_id: str) -> str:
        if not CONN_ID.match(conn_id):
            raise HTTPException(status_code=404, detail="Conexão inexistente.")
        return conn_id

    @app.get("/api/providers")
    async def providers_list(user: str = Depends(current_user)):
        types, listed = await worker("types"), await worker("list")
        return {"types": types.get("types", []), "connections": listed.get("connections", []),
                "default": listed.get("default"), "agent_models": store.agent_models(conn),
                "agents": [{"id": a.id, "name": a.name, "title": a.title} for a in AGENTS.values()]}

    @app.post("/api/providers", status_code=201)
    async def providers_save(body: ConnectionIn, user: str = Depends(current_user)):
        if body.id:
            conn_id_ok(body.id)
        result = await worker("save", **body.model_dump(exclude_none=True))
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result.get("detail") or "Conexão recusada.")
        log_access(user, "provider_save", f"{body.type}:{result['connection']['id']}")
        return result["connection"]

    @app.delete("/api/providers/{conn_id}", status_code=204)
    async def providers_delete(conn_id: str, user: str = Depends(current_user)):
        result = await worker("delete", id=conn_id_ok(conn_id))
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail="Conexão inexistente.")
        conn.execute("DELETE FROM agent_models WHERE connection_id = ?", (conn_id,))
        log_access(user, "provider_delete", conn_id)

    @app.post("/api/providers/{conn_id}/login_submit")
    async def providers_login_submit(conn_id: str, body: CodeIn, user: str = Depends(current_user)):
        # O código é segredo: segue só para o CLI do worker; nunca vai para log nem volta na resposta.
        result = await worker("login_submit", timeout=120, id=conn_id_ok(conn_id), code=body.code)
        log_access(user, "provider_login", conn_id, "ok" if result.get("ok") else "falha")
        return result

    @app.post("/api/providers/{conn_id}/codex_api_key")
    async def providers_codex_key(conn_id: str, body: KeyIn, user: str = Depends(current_user)):
        result = await worker("codex_api_key", timeout=60, id=conn_id_ok(conn_id), api_key=body.api_key)
        log_access(user, "provider_login", conn_id, "ok" if result.get("ok") else "falha")
        return result

    @app.post("/api/providers/{conn_id}/{action}")
    async def providers_action(conn_id: str, action: str, body: LoginRef | None = None,
                               user: str = Depends(current_user)):
        if action not in ACTIONS:
            raise HTTPException(status_code=404, detail="Ação inexistente.")
        result = await worker(action, timeout=ACTIONS[action], id=conn_id_ok(conn_id),
                              **({"login_id": body.login_id} if body and body.login_id else {}))
        if action in ("default", "revoke", "login_start"):
            log_access(user, f"provider_{action}", conn_id, "ok" if result.get("ok", True) else "falha")
        return result

    @app.get("/api/agents/models")
    async def agent_models_get(user: str = Depends(current_user)):
        return store.agent_models(conn)

    @app.put("/api/agents/models")
    async def agent_models_put(body: AgentModelsIn, user: str = Depends(current_user)):
        known = {c["id"] for c in (await worker("list")).get("connections", [])}
        for agent_id, choice in body.models.items():
            if agent_id not in AGENTS:
                raise HTTPException(status_code=422, detail=f"Agente desconhecido: {agent_id[:40]}")
            if choice.connection and choice.connection not in known:
                raise HTTPException(status_code=422, detail="Conexão inexistente.")
            if not MODEL.match(choice.model):
                raise HTTPException(status_code=422, detail="Nome de modelo inválido.")
        for agent_id, choice in body.models.items():
            store.set_agent_model(conn, agent_id, choice.connection or None, choice.model)
        log_access(user, "agent_models", ",".join(sorted(body.models))[:200])
        return store.agent_models(conn)
