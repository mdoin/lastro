# SPDX-License-Identifier: AGPL-3.0-or-later
"""Computadores dos agentes na interface (docs/COMPUTADORES.md): estado, ligar/desligar, assumir/devolver e a tela
ao vivo (WebSocket ↔ VNC do container, pelo controlador do host)."""

import asyncio

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from mentor import computador
from team.agents import chat_agents

from . import store


class Controle(BaseModel):
    dono: bool


def register(app: FastAPI, *, current_user, session_ok, log_access) -> None:
    agents = {a.id: a for a in chat_agents()}

    def agent_or_404(agente: str):
        if agente not in agents:
            raise HTTPException(status_code=404, detail="Agente desconhecido.")
        return agente

    async def ask(op: str, **fields) -> dict:
        if not computador.enabled():
            raise HTTPException(status_code=503, detail="Computadores dos agentes não estão instalados neste servidor.")
        try:
            resp = await computador.call(op, **fields)
        except (ConnectionError, OSError) as exc:
            raise HTTPException(status_code=503, detail="O controlador dos computadores está fora do ar.") from exc
        if not resp.get("ok"):
            raise HTTPException(status_code=409, detail=resp.get("erro", "Falha no computador."))
        return resp

    @app.get("/api/computadores")
    async def computadores(user: str = Depends(current_user)):
        state = await ask("estado")
        on = state["computadores"]
        return {"ip_saida": state["ip_saida"], "limite": state["limite"],
                "agentes": [{"id": a.id, "nome": a.name, "titulo": a.title, "ligado": a.id in on,
                             "controle": on.get(a.id, {}).get("controle", "agente"),
                             "agente_ativo": on.get(a.id, {}).get("agente_ativo", False)} for a in agents.values()]}

    @app.post("/api/computadores/{agente}/ligar")
    async def ligar(agente: str, user: str = Depends(current_user)):
        await ask("ligar", agente=agent_or_404(agente))
        log_access(user, "computador_ligar", agente)
        return {"ok": True}

    @app.post("/api/computadores/{agente}/desligar")
    async def desligar(agente: str, user: str = Depends(current_user)):
        await ask("desligar", agente=agent_or_404(agente))
        log_access(user, "computador_desligar", agente)
        return {"ok": True}

    @app.post("/api/computadores/{agente}/controle")
    async def controle(agente: str, body: Controle, user: str = Depends(current_user)):
        await ask("controle", agente=agent_or_404(agente), dono=body.dono)
        log_access(user, "computador_assumir" if body.dono else "computador_devolver", agente)
        return {"ok": True}

    @app.websocket("/api/computadores/{agente}/tela")
    async def tela(ws: WebSocket, agente: str):
        # O middleware HTTP não vê WebSockets: login e origem conferidos aqui (o cookie é SameSite=Strict).
        origin = ws.headers.get("origin", "")
        if (agente not in agents or not computador.enabled() or not session_ok(ws.cookies)
                or origin.split("://", 1)[-1] != ws.headers.get("host")):
            await ws.close(code=4403)
            return
        try:
            reader, writer = await computador.open_pipe(agente, "tela")
        except (ConnectionError, OSError):
            await ws.close(code=4503)
            return
        await ws.accept(subprotocol="binary" if "binary" in ws.scope.get("subprotocols", []) else None)
        log_access(store.OWNER, "computador_tela", agente)

        async def up():
            try:
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    data = msg.get("bytes") or (msg.get("text") or "").encode()
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()

        async def down():
            while data := await reader.read(65536):
                await ws.send_bytes(data)

        tasks = [asyncio.ensure_future(up()), asyncio.ensure_future(down())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            writer.close()
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):  # já fechado pelo navegador
                pass

