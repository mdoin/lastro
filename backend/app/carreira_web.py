# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas `/api/carreira/navegador`: o dono vê e controla o navegador do aplicador (Carreira) pelo Lastro.

Serve para entrar nas contas das plataformas (inclusive com Google), resolver CAPTCHA e destravar uma candidatura.
O web app só repassa ao worker (operação `navegador`); o texto digitado pode ser senha: nunca vai para log nem
volta na resposta.
"""

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

KEYS = Literal["Enter", "Backspace", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"]


class Acao(BaseModel):
    acao: Literal["iniciar", "tela", "clicar", "digitar", "tecla", "abrir", "voltar", "rolar", "encerrar"]
    x: int = Field(0, ge=0, le=4000)
    y: int = Field(0, ge=0, le=4000)
    dy: int = Field(600, ge=-3000, le=3000)
    texto: str = Field("", max_length=2000)
    tecla: KEYS | None = None
    url: str = Field("", max_length=2000)


def register(app: FastAPI, *, mentor, current_user, log_access) -> None:
    async def worker(body: dict) -> dict:
        result = await mentor.call({"op": "navegador", **body}, timeout=60)
        if result.get("type") == "error":
            raise HTTPException(status_code=503, detail=result.get("message") or "Worker do mentor indisponível.")
        result.pop("type", None)
        return result

    @app.get("/api/carreira/navegador")
    async def navegador_tela(user: str = Depends(current_user)):
        return await worker({"acao": "tela"})

    @app.post("/api/carreira/navegador")
    async def navegador_acao(body: Acao, user: str = Depends(current_user)):
        if body.acao in ("iniciar", "encerrar", "abrir"):  # o que se digita (talvez senha) nunca entra no log
            log_access(user, f"carreira.navegador.{body.acao}", body.url[:200] if body.acao == "abrir" else "")
        return await worker(body.model_dump(exclude_none=True))
