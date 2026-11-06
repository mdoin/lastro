# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas `/api/contas/*`: Central de Contas e Acessos (docs/CONTAS.md), compartilhada por Finanças e Carreira.

- Metadados e pendências vêm do banco (app/contas.py); credenciais só existem no cofre cifrado do worker
  (operação `contas`), e o web app só repassa: nenhuma resposta ou log traz senha, token ou cookie.
- Gravar, revogar e desconectar exigem a senha do dono de novo, no mesmo limitador do login.
- CSRF: o middleware do web app exige `X-Lastro: 1` e mesma origem em toda escrita; o cookie é SameSite=Strict.
"""

import json
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, contas


class Reauth(BaseModel):
    senha_dono: str = Field(min_length=1, max_length=256)


class Credencial(Reauth):
    usuario: str = Field(default="", max_length=254)
    senha: str = Field(min_length=1, max_length=512)
    dominios: list[str] | None = Field(default=None, min_length=1, max_length=10)


class Resolver(BaseModel):
    acao: Literal["verificar", "concluir", "descartar"]


def register(app: FastAPI, conn, *, mentor, current_user, log_access) -> None:
    async def worker(body: dict, timeout: float = 15) -> dict:
        result = await mentor.call({"op": "contas", **body}, timeout=timeout)
        if result.get("type") == "error":
            raise HTTPException(status_code=503, detail=result.get("message") or "Worker do mentor indisponível.")
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result.get("detalhe") or "Pedido recusado pelo cofre.")
        return result

    def platform(pid: str):
        row = conn.execute("SELECT * FROM contas_plataformas WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Plataforma não encontrada.")
        return row

    def reauth(request: Request, user: str, password: str, action: str) -> None:
        client = auth.client_key(request.client.host if request.client else None)
        if auth.too_many_failures(conn, client):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde alguns minutos.")
        if not auth.owner_password_ok(conn, password):
            auth.record_failure(conn, client)
            log_access(user, action, "", "negado")
            raise HTTPException(status_code=403, detail="Senha do Lastro incorreta.")

    async def verify(row) -> dict:
        if not row["url_verificacao"]:
            raise HTTPException(status_code=409, detail="Esta plataforma não tem página de verificação.")
        result = await worker({"acao": "verificar", "plataforma": row["id"], "url": row["url_verificacao"],
                               "dominios": json.loads(row["dominios_json"])}, timeout=120)
        if result["estado"] == "ocupado":
            raise HTTPException(status_code=409, detail=result.get("detalhe") or "Navegador ocupado.")
        contas.marcar(conn, row["id"], result["estado"], result.get("detalhe") or result.get("pagina") or "",
                      verificada=True)
        resumed = (contas.resolver_acesso(conn, row["id"], "sessão confirmada pela verificação")
                   if result["estado"] == "conectada" else [])
        return {"estado": result["estado"], "pagina": result.get("pagina", ""), "retomadas": len(resumed)}

    @app.get("/api/contas")
    async def contas_lista(user: str = Depends(current_user)):
        data = contas.listar(conn)
        result = await mentor.call({"op": "contas", "acao": "listar"})
        creds = {c["plataforma"]: c for c in result.get("credenciais", [])} if result.get("ok") else None
        for p in data["plataformas"]:
            if creds is not None:
                p["credencial"] = creds.get(p["id"])
                if p["tem_credencial"] != (p["id"] in creds):  # espelho do cofre (sem valor) para os agentes
                    conn.execute("UPDATE contas_plataformas SET tem_credencial = ? WHERE id = ?",
                                 (int(p["id"] in creds), p["id"]))
                    p["tem_credencial"] = p["id"] in creds
        data["cofre"] = {"disponivel": result.get("disponivel") if result.get("ok") else None}
        return data

    @app.post("/api/contas/{pid}/verificar")
    async def contas_verificar(pid: str, user: str = Depends(current_user)):
        log_access(user, "contas.verificar", pid)
        return await verify(platform(pid))

    @app.put("/api/contas/{pid}/credencial")
    async def contas_credencial(pid: str, body: Credencial, request: Request, user: str = Depends(current_user)):
        row = platform(pid)
        reauth(request, user, body.senha_dono, "contas.credencial.salvar")
        dominios = body.dominios or json.loads(row["dominios_json"])
        if not dominios:
            raise HTTPException(status_code=422, detail="Informe os domínios em que a senha pode ser digitada.")
        result = await worker({"acao": "salvar", "plataforma": pid, "usuario": body.usuario, "senha": body.senha,
                               "dominios": dominios})
        conn.execute("UPDATE contas_plataformas SET tem_credencial = 1, dominios_json = CASE WHEN dominios_json = '[]' "
                     "THEN ? ELSE dominios_json END WHERE id = ?", (json.dumps(result["credencial"]["dominios"]), pid))
        log_access(user, "contas.credencial.salvar", pid)
        return {"credencial": result["credencial"]}

    @app.post("/api/contas/{pid}/revogar")
    async def contas_revogar(pid: str, body: Reauth, request: Request, user: str = Depends(current_user)):
        platform(pid)
        reauth(request, user, body.senha_dono, "contas.credencial.revogar")
        result = await worker({"acao": "revogar", "plataforma": pid})
        conn.execute("UPDATE contas_plataformas SET tem_credencial = 0 WHERE id = ?", (pid,))
        log_access(user, "contas.credencial.revogar", pid)
        return {"revogada": result["revogada"]}

    @app.post("/api/contas/{pid}/desconectar")
    async def contas_desconectar(pid: str, body: Reauth, request: Request, user: str = Depends(current_user)):
        row = platform(pid)
        if row["autenticacao"] == "env":
            raise HTTPException(status_code=409, detail="Configurada no servidor: veja docs/CONTAS.md.")
        reauth(request, user, body.senha_dono, "contas.desconectar")
        result = await worker({"acao": "desconectar", "plataforma": pid, "dominios": json.loads(row["dominios_json"])},
                              timeout=120)
        if result.get("estado") == "ocupado":
            raise HTTPException(status_code=409, detail=result.get("detalhe") or "Navegador ocupado.")
        conn.execute("UPDATE contas_plataformas SET tem_credencial = 0 WHERE id = ?", (pid,))
        contas.marcar(conn, pid, "nao_configurada", "desconectada pelo dono")
        log_access(user, "contas.desconectar", pid)
        return {"estado": "nao_configurada"}

    @app.post("/api/contas/pendencias/{pend_id}/resolver")
    async def pendencia_resolver(pend_id: int, body: Resolver, user: str = Depends(current_user)):
        pend = conn.execute("SELECT * FROM contas_pendencias WHERE id = ? AND estado = 'aberta'", (pend_id,)).fetchone()
        if pend is None:
            raise HTTPException(status_code=404, detail="Pendência não encontrada ou já resolvida.")
        log_access(user, f"contas.pendencia.{body.acao}", str(pend_id))
        if body.acao == "verificar":
            if pend["tipo"] not in contas.ACESSO:
                raise HTTPException(status_code=409, detail="Esta pendência não é de acesso: marque como resolvida.")
            result = await verify(platform(pend["plataforma"]))  # sessão ativa fecha as pendências de acesso dela
            if result["estado"] != "conectada":
                raise HTTPException(status_code=409, detail="A sessão ainda não está ativa. Entre pelo navegador do "
                                                            "agente e verifique de novo.")
            return result
        resumed = contas.resolver(conn, pend_id, resolucao="concluída pelo dono" if body.acao == "concluir"
                                  else "descartada pelo dono", estado="resolvida" if body.acao == "concluir" else "descartada")
        return {"retomadas": len(resumed)}
