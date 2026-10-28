# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas do livro de movimentações, do registro a partir da conversa e da Caixa de entrada (docs/LEDGER.md).

Tudo filtra pela pessoa autenticada: movimentação, captura ou documento de outra conta responde 404, igual a
inexistente. Escrita só por estas rotas (sessão + cabeçalho CSRF do middleware); agentes apenas leem.
O envio de documento chega como corpo binário (sem multipart): o tamanho é limitado enquanto o corpo é lido.
"""

import asyncio
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ledger import book, capture, parsers
from ledger.inbox import Inbox, ai_prompt, summary_text

from . import store

log = logging.getLogger("lastro.caixa")


class Changes(BaseModel):
    kind: Literal[book.KINDS] | None = None  # type: ignore[valid-type]
    category: str | None = Field(None, max_length=40)
    amount: str | None = Field(None, max_length=20, pattern=r"^-?\d{1,9}([.,]\d{1,2})?$")
    occurred_on: date | None = None
    description: str | None = Field(None, max_length=200)
    counterparty: str | None = Field(None, max_length=120)
    settled: bool | None = None


class ActionIn(BaseModel):
    changes: Changes = Field(default_factory=Changes)


class ConsentIn(BaseModel):
    granted: bool


class InterpretIn(BaseModel):
    confirm: bool  # a pessoa leu o aviso de que o texto vai ao provedor de IA configurado


def _uuid(value: str, what: str) -> str:
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} inexistente.") from None
    return value


def _changes(body: ActionIn) -> dict:
    data = body.changes.model_dump(exclude_none=True)
    if "amount" in data:
        data["amount"] = data["amount"].replace(",", ".")
    return data


def register(app: FastAPI, conn, *, current_user, log_access, today, docs_dir: Path, orchestrator,
             inbox: Inbox | None = None) -> Inbox:
    inbox = inbox or Inbox(conn, docs_dir)

    def guarded(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except book.LedgerError as exc:
            raise HTTPException(status_code=409 if "inexistente" not in str(exc) else 404, detail=str(exc)) from exc

    # --- consentimento ---

    @app.get("/api/consents")
    async def consents_get(user: str = Depends(current_user)):
        return book.consents(conn, user)

    @app.put("/api/consents/{scope}")
    async def consent_set(scope: Literal["auto_register", "ai_documents"], body: ConsentIn,
                          user: str = Depends(current_user)):
        log_access(user, f"consent.{scope}", "on" if body.granted else "off")
        return book.set_consent(conn, user, scope, body.granted)

    # --- livro ---

    @app.get("/api/ledger")
    async def ledger_list(status: Literal["registrado", "pendente", "duplicada", "desfeito", "descartado"] | None = None,
                          document_id: str | None = Query(None, max_length=64), user: str = Depends(current_user)):
        return book.list_entries(conn, user, status=status, source_ref=document_id)

    @app.get("/api/ledger/summary")
    async def ledger_summary(month: str = Query("", pattern=r"^(\d{4}-\d{2})?$"), user: str = Depends(current_user)):
        start, end = book.month_bounds(date.fromisoformat(f"{month}-01") if month else today())
        return book.summary(conn, user, start, end)

    @app.get("/api/ledger/categories")
    async def ledger_categories():
        return [{"key": k, "label": v} for k, v in book.LABELS.items()]

    @app.get("/api/ledger/{entry_id}/events")
    async def ledger_events(entry_id: str, user: str = Depends(current_user)):
        if not book.get_entry(conn, user, _uuid(entry_id, "Movimentação")):
            raise HTTPException(status_code=404, detail="Movimentação inexistente.")
        return book.events(conn, user, entry_id)

    @app.post("/api/ledger/{entry_id}/{action}")
    async def ledger_action(entry_id: str, action: Literal["confirmar", "descartar", "desfazer", "restaurar", "corrigir",
                                                           "e_duplicada", "nao_e_duplicada"],
                            body: ActionIn | None = None, user: str = Depends(current_user)):
        entry = guarded(book.update_entry, conn, user, _uuid(entry_id, "Movimentação"), action, actor="pessoa",
                        changes=_changes(body or ActionIn()))
        log_access(user, f"ledger.{action}", entry_id)
        if entry["source_kind"] in ("documento", "ia"):
            inbox.refresh(user, entry["source_ref"])
        return entry

    # --- registros reconhecidos na conversa ---

    @app.get("/api/captures")
    async def captures_list(status: Literal["registrado", "pendente", "informativo", "desfeito", "descartado"] | None = None,
                            user: str = Depends(current_user)):
        return capture.list_captures(conn, user, status)

    @app.post("/api/captures/{capture_id}/{action}")
    async def capture_action(capture_id: str, action: Literal["desfazer", "confirmar", "descartar"],
                             body: ActionIn | None = None, user: str = Depends(current_user)):
        out = guarded(capture.act, conn, user, _uuid(capture_id, "Registro"), action, today(),
                      _changes(body or ActionIn()))
        log_access(user, f"capture.{action}", capture_id)
        return out

    # --- Caixa de entrada ---

    @app.get("/api/documents")
    async def documents_list(user: str = Depends(current_user)):
        inbox.purge()
        return {"documents": inbox.list(user), "ocr": inbox.ocr is not None, "pdf": parsers_pdf_available(),
                "limits": {"max_bytes": parsers.MAX_BYTES, "formats": ["pdf", "png", "jpg", "csv", "ofx"]},
                "retention_days": inbox.retention_days}

    @app.post("/api/documents", status_code=201)
    async def document_upload(request: Request, conversation_id: str | None = Query(None, max_length=64),
                              user: str = Depends(current_user)):
        conv = None
        if conversation_id:
            conv = store.user_conversation(conn, _uuid(conversation_id, "Conversa"), user)
            if not conv:
                raise HTTPException(status_code=404, detail="Conversa inexistente.")
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > parsers.MAX_BYTES:
            raise HTTPException(status_code=413, detail="Arquivo grande demais (limite de 10 MB).")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > parsers.MAX_BYTES:
                raise HTTPException(status_code=413, detail="Arquivo grande demais (limite de 10 MB).")
            chunks.append(chunk)
        name = unquote(request.headers.get("x-filename", "documento"))[:200]
        try:
            doc = inbox.receive(user, b"".join(chunks), name, today=today(), conversation_id=conv["id"] if conv else None)
        except parsers.UnsupportedDocument as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        except book.LedgerError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        log_access(user, "document.upload", doc["id"])
        if conv and not doc.get("repeated"):
            message = store.add_message(conn, conv["id"], "assistant", summary_text(doc), agent_id="mila",
                                        kind="message", meta={"document": {"id": doc["id"], "summary": doc["summary"],
                                                                           "status": doc["status"]}})
            orchestrator.bus.publish(conv["id"], {"type": "message", "message": message})
        return doc

    @app.get("/api/documents/{doc_id}")
    async def document_get(doc_id: str, user: str = Depends(current_user)):
        doc = inbox.get(user, _uuid(doc_id, "Documento"))
        if not doc:
            raise HTTPException(status_code=404, detail="Documento inexistente.")
        return {**doc, "entries": book.list_entries(conn, user, source_ref=doc_id, limit=1000),
                "summary_text": summary_text(doc)}

    @app.post("/api/documents/{doc_id}/approve")
    async def document_approve(doc_id: str, user: str = Depends(current_user)):
        if not inbox.get(user, _uuid(doc_id, "Documento")):
            raise HTTPException(status_code=404, detail="Documento inexistente.")
        approved = guarded(inbox.approve_all, user, doc_id)
        log_access(user, "document.approve_all", doc_id)
        return {"approved": approved, "document": inbox.get(user, doc_id)}

    @app.delete("/api/documents/{doc_id}")
    async def document_delete(doc_id: str, entries: bool = False, user: str = Depends(current_user)):
        out = guarded(inbox.delete, user, _uuid(doc_id, "Documento"), undo_entries=entries)
        log_access(user, "document.delete", doc_id)
        return out

    @app.post("/api/documents/{doc_id}/interpret", status_code=202)
    async def document_interpret(doc_id: str, body: InterpretIn, user: str = Depends(current_user)):
        """Leitura por IA, só a pedido e com consentimento: o TEXTO extraído (nunca a imagem) vai ao provedor
        configurado para a Mila; a resposta é validada e tudo fica pendente."""
        if not body.confirm or not book.consent(conn, user, "ai_documents"):
            raise HTTPException(status_code=403, detail="Autorize o envio do texto do documento ao provedor de IA "
                                                        "nas preferências da Caixa de entrada.")
        doc = inbox.get(user, _uuid(doc_id, "Documento"))
        if not doc:
            raise HTTPException(status_code=404, detail="Documento inexistente.")
        if doc["status"] == "interpretando":
            return doc
        text = guarded(inbox.text_for_ai, user, doc_id)
        previous = doc["status"]
        conn.execute("UPDATE documents SET status = 'interpretando' WHERE id = ?", (doc_id,))
        log_access(user, "document.interpret", doc_id)

        async def run() -> None:
            request = {"op": "ephemeral", "role": "extrator", "mode": "extracao_documento", "text": ai_prompt(text),
                       "effort": "low", **store.ai_route(conn, "mila")}
            output, failed = "", None
            try:
                async with asyncio.timeout(300):
                    async for event in orchestrator.stream(request):
                        if event.get("type") == "done":
                            output = event.get("text") or ""
                        elif event.get("type") == "error":
                            failed = event.get("message") or "falha"
            except TimeoutError:
                failed = "tempo esgotado"
            if failed or not output:
                conn.execute("UPDATE documents SET status = ? WHERE id = ?", (previous, doc_id))
                log.info("leitura por IA do documento %s falhou", doc_id)
                return
            inbox.apply_ai(user, doc_id, output)

        task = asyncio.create_task(run())
        app.state.background = getattr(app.state, "background", set())
        app.state.background.add(task)
        task.add_done_callback(app.state.background.discard)
        return inbox.get(user, doc_id)

    return inbox


def parsers_pdf_available() -> bool:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True

