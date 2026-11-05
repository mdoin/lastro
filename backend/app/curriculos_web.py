# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas `/api/carreira/curriculos` e `/api/carreira/base`: currículo-base estruturado, versões e documentos.

- Base: o dono vê os fatos com status e fonte, confirma ou corrige um item e responde as perguntas de enriquecimento.
  Cada mudança é uma versão nova e imutável de `carreira_base` (nada é sobrescrito).
- Versões: as gerais de cada perfil e as personalizadas por vaga, com o PDF/DOCX exatos, o relatório de validação,
  a análise da vaga e as candidaturas em que cada uma foi enviada.
- Liberação: o envio automático com o gerador novo só começa quando o dono libera, depois de conferir os PDFs.
"""

import asyncio
import json
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from carreira import curriculo, documento

from . import db


class ItemEdicao(BaseModel):
    status: Literal["confirmado", "pendente", "inferido", "descartado"] | None = None
    pt: str | None = Field(None, min_length=2, max_length=400)
    en: str | None = Field(None, max_length=400)


class Resposta(BaseModel):
    resposta: str = Field("", max_length=2000)
    descartar: bool = False


class Liberacao(BaseModel):
    liberar: bool


def register(app: FastAPI, conn, *, mentor, current_user, log_access) -> None:
    previews: dict[tuple[int, int], bytes] = {}  # versões são imutáveis: a prévia de uma página não muda

    def atual():
        found = curriculo.carregar(conn)
        if found is None:
            raise HTTPException(status_code=404, detail="Nenhum currículo-base estruturado ainda.")
        return found

    def liberado() -> str | None:
        row = conn.execute("SELECT valor FROM carreira_estado WHERE chave = 'curriculo_liberado'").fetchone()
        return row[0] if row else None

    def resumo_validacao(raw: str | None) -> dict | None:
        if not raw:
            return None
        v = json.loads(raw)
        return {"ok": v.get("ok"), "paginas": v.get("paginas"), "erros": len(v.get("erros") or []),
                "avisos": len(v.get("avisos") or [])}

    @app.get("/api/carreira/base")
    async def base(user: str = Depends(current_user)):
        base_id, conteudo = atual()
        row = curriculo.base_atual(conn)
        perfis = []
        for pid, p in curriculo.PERFIS.items():
            v = conn.execute("SELECT id, validacao_json, created_at FROM carreira_curriculos WHERE tipo = 'base' AND "
                             "base_id = ? AND perfil = ? ORDER BY id DESC LIMIT 1", (base_id, pid)).fetchone()
            perfis.append({"perfil": pid, "nome": p.nome, "descricao": p.descricao,
                           "curriculo_id": v["id"] if v else None, "created_at": v["created_at"] if v else None,
                           "validacao": resumo_validacao(v["validacao_json"]) if v else None})
        historico = [dict(r) for r in conn.execute(
            "SELECT id, origem, nota, created_at FROM carreira_base ORDER BY id DESC LIMIT 30")]
        return {"versao": {"id": base_id, "origem": row["origem"], "nota": row["nota"], "created_at": row["created_at"]},
                "base": conteudo, "pendencias": curriculo.pendencias(conteudo), "perfis": perfis,
                "historico": historico, "liberado_em": liberado()}

    @app.post("/api/carreira/base/itens/{item_id}")
    async def editar_item(item_id: str, body: ItemEdicao, user: str = Depends(current_user)):
        _, conteudo = atual()
        try:
            nova = curriculo.editar(conteudo, item_id, status=body.status, pt=body.pt, en=body.en)
        except KeyError:
            raise HTTPException(status_code=404, detail="Item não encontrado no currículo-base.") from None
        except curriculo.BaseInvalida as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        nota = f"{item_id}: " + ", ".join(x for x in (f"status {body.status}" if body.status else "",
                                                      "texto editado" if body.pt or body.en else "") if x)
        novo_id = curriculo.salvar(conn, nova, "dono", nota)
        log_access(user, "carreira.base.item", item_id)
        return {"id": novo_id}

    @app.post("/api/carreira/base/perguntas/{pergunta_id}")
    async def responder(pergunta_id: str, body: Resposta, user: str = Depends(current_user)):
        _, conteudo = atual()
        if not body.descartar and len(body.resposta.strip()) < 2:
            raise HTTPException(status_code=422, detail="Escreva a resposta ou descarte a pergunta.")
        try:
            nova = curriculo.responder(conteudo, pergunta_id, body.resposta, body.descartar)
        except KeyError:
            raise HTTPException(status_code=404, detail="Pergunta não encontrada.") from None
        novo_id = curriculo.salvar(conn, nova, "dono", f"pergunta {pergunta_id} " +
                                   ("descartada" if body.descartar else "respondida"))
        log_access(user, "carreira.base.pergunta", pergunta_id)
        return {"id": novo_id}

    @app.post("/api/carreira/base/gerar")
    async def gerar(user: str = Depends(current_user)):
        """Gera agora as versões gerais dos três perfis para a base vigente (o serviço também gera na fila)."""
        atual()
        try:
            feitos = await documento.versoes_dos_perfis(conn, mentor)
        except documento.DocumentoInvalido as exc:
            raise HTTPException(status_code=422, detail=f"O documento não passou na validação: {exc}") from None
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=f"Não foi possível gerar o PDF agora ({exc}).") from None
        log_access(user, "carreira.base.gerar", str(len(feitos)))
        return {"criados": feitos}

    @app.post("/api/carreira/base/liberar")
    async def liberar(body: Liberacao, user: str = Depends(current_user)):
        if body.liberar:
            conn.execute("INSERT INTO carreira_estado (chave, valor) VALUES ('curriculo_liberado', ?) "
                         "ON CONFLICT (chave) DO NOTHING", (db.utcnow(),))
        else:
            conn.execute("DELETE FROM carreira_estado WHERE chave = 'curriculo_liberado'")
        log_access(user, "carreira.base.liberar", str(body.liberar))
        return {"liberado_em": liberado()}

    @app.get("/api/carreira/curriculos")
    async def curriculos(user: str = Depends(current_user)):
        rows = conn.execute(
            "SELECT k.id, k.tipo, k.origem_id, k.alteracoes_json, k.created_at, length(k.conteudo_md) AS tamanho,"
            " k.perfil, k.idioma, k.base_id, k.validacao_json, k.pdf IS NOT NULL AS tem_pdf,"
            " v.rowid AS n, v.title, v.company FROM carreira_curriculos k LEFT JOIN carreira_vagas v ON v.id = k.vaga_id"
            " ORDER BY k.id DESC").fetchall()
        uses: dict[int, list] = {}
        for e in conn.execute("SELECT e.curriculo_id, e.status, e.anexo, e.created_at, v.rowid AS n FROM carreira_envios e "
                              "JOIN carreira_vagas v ON v.id = e.vaga_id WHERE e.curriculo_id IS NOT NULL ORDER BY e.id"):
            uses.setdefault(e["curriculo_id"], []).append({"n": e["n"], "status": e["status"], "anexo": e["anexo"],
                                                           "created_at": e["created_at"]})
        estruturada = curriculo.base_atual(conn)
        legado = next((r["id"] for r in rows if r["tipo"] == "base" and r["perfil"] is None), None)

        def vigente(r) -> bool:
            if r["tipo"] != "base":
                return False
            if estruturada is None:
                return r["id"] == legado
            return r["base_id"] == estruturada["id"]

        return [{"id": r["id"], "tipo": r["tipo"], "vigente": vigente(r), "origem_id": r["origem_id"],
                 "alteracoes": json.loads(r["alteracoes_json"]), "created_at": r["created_at"], "tamanho": r["tamanho"],
                 "perfil": r["perfil"], "idioma": r["idioma"], "base_id": r["base_id"], "tem_pdf": bool(r["tem_pdf"]),
                 "validacao": resumo_validacao(r["validacao_json"]),
                 "n": r["n"], "title": r["title"], "company": r["company"], "envios": uses.get(r["id"], [])}
                for r in rows]

    def curriculo_row(cid: int):
        row = conn.execute("SELECT k.*, v.rowid AS n, v.title, v.company FROM carreira_curriculos k "
                           "LEFT JOIN carreira_vagas v ON v.id = k.vaga_id WHERE k.id = ?", (cid,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Currículo não encontrado.")
        return row

    @app.get("/api/carreira/curriculos/{cid}")
    async def curriculo_detalhe(cid: int, user: str = Depends(current_user)):
        row = curriculo_row(cid)
        origem = (conn.execute("SELECT conteudo_md FROM carreira_curriculos WHERE id = ?", (row["origem_id"],)).fetchone()
                  if row["origem_id"] else None)
        doc = json.loads(row["documento_json"]) if row["documento_json"] else None
        envios = [dict(e) for e in conn.execute(
            "SELECT e.id, e.status, e.anexo, e.created_at, v.rowid AS n, v.title, v.company FROM carreira_envios e "
            "JOIN carreira_vagas v ON v.id = e.vaga_id WHERE e.curriculo_id = ? ORDER BY e.id", (cid,))]
        return {"id": row["id"], "tipo": row["tipo"], "origem_id": row["origem_id"], "conteudo_md": row["conteudo_md"],
                "origem_md": origem["conteudo_md"] if origem else None, "alteracoes": json.loads(row["alteracoes_json"]),
                "created_at": row["created_at"], "n": row["n"], "title": row["title"], "company": row["company"],
                "perfil": row["perfil"], "idioma": row["idioma"], "base_id": row["base_id"], "sha256": row["sha256"],
                "tem_pdf": row["pdf"] is not None, "tem_docx": row["docx"] is not None,
                "paginas": (json.loads(row["validacao_json"]).get("paginas") if row["validacao_json"] else None),
                "validacao": json.loads(row["validacao_json"]) if row["validacao_json"] else None,
                "analise": (doc or {}).get("analise"), "envios": envios}

    @app.get("/api/carreira/curriculos/{cid}/documento")
    async def curriculo_documento(cid: int, formato: Literal["html", "md", "pdf", "docx"] = "html",
                                  download: bool = False, user: str = Depends(current_user)):
        """O arquivo exato da versão (PDF/DOCX guardados), o HTML que o gerou ou o Markdown."""
        row = curriculo_row(cid)
        doc = json.loads(row["documento_json"]) if row["documento_json"] else None
        name = f"{documento.nome_arquivo(doc) if doc else 'curriculo'}-v{cid}"
        if formato in ("pdf", "docx"):
            if row[formato] is None:
                raise HTTPException(status_code=404, detail="Esta versão não tem esse formato (versão antiga, só texto).")
            mime = "application/pdf" if formato == "pdf" else \
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            disposition = "inline" if formato == "pdf" and not download else "attachment"
            return Response(row[formato], media_type=mime,
                            headers={"Content-Disposition": f'{disposition}; filename="{name}.{formato}"'})
        if formato == "md":
            return Response(row["conteudo_md"], media_type="text/markdown; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
        if doc:
            return Response(documento.html(doc), media_type="text/html; charset=utf-8")
        from mentor.aplicador import markdown_html  # versão antiga: só HTML puro; o módulo não abre navegador

        page = markdown_html(row["conteudo_md"]).replace(
            "<style>", f"<title>{name}</title><style>@page{{size:A4;margin:14mm 15mm}}", 1)
        return Response(page, media_type="text/html; charset=utf-8")

    @app.get("/api/carreira/curriculos/{cid}/pagina/{pagina}.png")
    async def curriculo_pagina(cid: int, pagina: int, user: str = Depends(current_user)):
        """Prévia de uma página do PDF exato (a tela não pode embutir o PDF: o app proíbe frames)."""
        if (cid, pagina) not in previews:
            row = curriculo_row(cid)
            if row["pdf"] is None or not 1 <= pagina <= 4:
                raise HTTPException(status_code=404, detail="Página não encontrada.")
            png = await asyncio.to_thread(documento.previa_png, row["pdf"], pagina)
            if png is None:
                raise HTTPException(status_code=404, detail="Página não encontrada.")
            if len(previews) > 60:
                previews.clear()
            previews[(cid, pagina)] = png
        return Response(previews[(cid, pagina)], media_type="image/png")
