# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas do Diário de Decisões (docs/WEB_API.md §Diário).

Tudo filtra pelo dono: rascunho, decisão ou mensagem de outra pessoa responde 404, igual a inexistente.
Só estas rotas (sessão autenticada + cabeçalho CSRF do middleware) criam decisões; agentes apenas propõem.
"""

import datetime as dt
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from radar.journal import DECISIONS as RADAR_DECISIONS

from . import db, diary, store

ClientId = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class DraftFromMessageIn(BaseModel):
    message_id: str = Field(max_length=64)


class ConfirmIn(BaseModel):
    alternativa: int | None = Field(None, ge=0, le=5)
    escolha: str = Field("", max_length=500)
    justificativa: str = Field("", max_length=2000)
    correcoes: str = Field("", max_length=2000)
    review_every_months: int | None = Field(None, ge=1, le=24)
    radar_decisao: Literal[RADAR_DECISIONS] | None = None  # type: ignore[valid-type]


class PostponeIn(BaseModel):
    until: dt.date | None = None
    note: str = Field("", max_length=500)


class DiscardIn(BaseModel):
    note: str = Field("", max_length=500)


class ManualIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    data: dt.date | None = None
    alternativas: list[str] = Field(default_factory=list, max_length=10)
    informacoes: str = Field("", max_length=2000)
    riscos: str = Field("", max_length=1000)
    escolha: str = Field(min_length=1, max_length=500)
    justificativa: str = Field("", max_length=2000)
    valor_planejado: str | None = Field(None, max_length=30)
    review_every_months: int | None = Field(None, ge=1, le=24)
    client_id: str | None = ClientId


class RevisionIn(BaseModel):
    escolha: str = Field(min_length=1, max_length=500)
    mantem: bool = False
    justificativa: str = Field("", max_length=2000)
    client_id: str | None = ClientId


class OutcomeIn(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)
    executada: bool | None = None
    observado_em: dt.date | None = None
    client_id: str | None = ClientId


class PlanIn(BaseModel):
    every_months: int | None = Field(None, ge=1, le=24)


def register(app: FastAPI, conn, *, current_user, bad_request, log_access, today) -> None:
    diary.import_legacy(conn, store.OWNER)

    def found(value, what: str = "Registro inexistente."):
        if not value:
            raise HTTPException(status_code=404, detail=what)
        return value

    def call(fn, *args, **kwargs):
        try:
            return bad_request(fn, *args, **kwargs)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Decisão inexistente.") from exc

    @app.get("/api/diary")
    async def diary_overview(user: str = Depends(current_user)):
        drafts = diary.list_drafts(conn, user)
        return {"drafts": drafts, "decisions": diary.list_decisions(conn, user),
                "due_reviews": diary.due_reviews(conn, user, today()), "chain": diary.verify_chain(conn, user),
                "today": today().isoformat()}

    @app.post("/api/diary/drafts", status_code=201)
    async def diary_draft_from_message(body: DraftFromMessageIn, user: str = Depends(current_user)):
        """"Registrar no Diário" numa resposta: monta o rascunho com o que a execução registrou (idempotente)."""
        message = found(store.get_message(conn, body.message_id), "Mensagem inexistente.")
        conv_id = conn.execute("SELECT conversation_id FROM messages WHERE id = ?", (body.message_id,)).fetchone()[0]
        conv = found(store.user_conversation(conn, conv_id, user), "Mensagem inexistente.")
        draft, created = call(diary.draft_for_message, conn, conv, message, today=today(), now=db.utcnow())
        if created:
            log_access(user, "diary.draft.request", draft["id"])
        return draft

    @app.get("/api/diary/drafts/{draft_id}")
    async def diary_draft(draft_id: str, user: str = Depends(current_user)):
        return found(diary.get_draft(conn, user, draft_id))

    @app.post("/api/diary/drafts/{draft_id}/confirm")
    async def diary_confirm(draft_id: str, body: ConfirmIn, user: str = Depends(current_user)):
        result = found(call(diary.confirm_draft, conn, user, draft_id, body.model_dump(), now=db.utcnow(),
                            today=today()))
        log_access(user, "diary.confirm", draft_id)
        return result

    @app.post("/api/diary/drafts/{draft_id}/postpone")
    async def diary_postpone(draft_id: str, body: PostponeIn, user: str = Depends(current_user)):
        result = found(call(diary.postpone_draft, conn, user, draft_id,
                            until=body.until.isoformat() if body.until else None, note=body.note, now=db.utcnow()))
        log_access(user, "diary.postpone", draft_id)
        return result

    @app.post("/api/diary/drafts/{draft_id}/discard")
    async def diary_discard(draft_id: str, body: DiscardIn, user: str = Depends(current_user)):
        result = found(call(diary.discard_draft, conn, user, draft_id, note=body.note, now=db.utcnow()))
        log_access(user, "diary.discard", draft_id)
        return result

    @app.post("/api/diary/decisions", status_code=201)
    async def diary_manual(body: ManualIn, user: str = Depends(current_user)):
        result = call(diary.create_manual, conn, user, body.model_dump(mode="json"), now=db.utcnow(), today=today())
        log_access(user, "diary.manual", result["id"])
        return result

    @app.get("/api/diary/decisions/{decision_id}")
    async def diary_decision(decision_id: str, user: str = Depends(current_user)):
        return found(diary.review_context(conn, user, decision_id))

    @app.post("/api/diary/decisions/{decision_id}/revisions", status_code=201)
    async def diary_revision(decision_id: str, body: RevisionIn, user: str = Depends(current_user)):
        result = call(diary.add_revision, conn, user, decision_id, body.model_dump(), now=db.utcnow(), today=today())
        log_access(user, "diary.revision", decision_id)
        return result

    @app.post("/api/diary/decisions/{decision_id}/outcomes", status_code=201)
    async def diary_outcome(decision_id: str, body: OutcomeIn, user: str = Depends(current_user)):
        result = call(diary.add_outcome, conn, user, decision_id, body.model_dump(mode="json"), now=db.utcnow(),
                      today=today())
        log_access(user, "diary.outcome", decision_id)
        return result

    @app.put("/api/diary/decisions/{decision_id}/review-plan")
    async def diary_plan(decision_id: str, body: PlanIn, user: str = Depends(current_user)):
        return call(diary.set_review_plan, conn, user, decision_id, body.every_months, today=today(), now=db.utcnow())

    @app.post("/api/diary/decisions/{decision_id}/discuss", status_code=201)
    async def diary_discuss(decision_id: str, user: str = Depends(current_user)):
        """Conversa com o Mentor para revisar a decisão: registro original e dados de hoje, separados."""
        ctx = found(diary.review_context(conn, user, decision_id), "Decisão inexistente.")
        d = ctx["decisao"]
        conv = store.create_conversation(conn, f"Revisão · {d['titulo']}"[:120], channel="direct", agent_id="mentor",
                                         user_id=user)
        store.add_message(conn, conv["id"], "assistant", diary_brief(ctx), agent_id="lastro", kind="analysis")
        diary.link_conversation(conn, conv["id"], decision_id, db.utcnow())
        log_access(user, "diary.discuss", decision_id)
        return store.user_conversation(conn, conv["id"], user)


def diary_brief(ctx: dict) -> str:
    d = ctx["decisao"]
    p = d["entries"][0]["payload"]
    rec = p.get("registro") or p
    lines = [f"**Revisão de uma decisão do Diário** — registrada em {d['created_at'][:10]}, versão {d['versao']}.",
             "", f"Pergunta: {(rec.get('pergunta_original') or rec.get('pergunta') or d['titulo'])[:1500]}",
             f"Decisão vigente: {d['escolha']}"]
    if p.get("justificativa"):
        lines.append(f"Justificativa da pessoa: {p['justificativa'][:1000]}")
    if rec.get("riscos"):
        lines += ["Riscos registrados:", *[f"- {r}" for r in rec["riscos"]]]
    # Sem valores do retrato: a mensagem chega também a agentes sem acesso aos dados do dono (ex.: Economista).
    lines += ["", f"Para comparar a época com hoje, consulte `decisoes` com id {d['id']} e `situacao_atual`; "
                  "a tela do Diário mostra os dois lado a lado."]
    if ctx.get("radar"):
        done = [o for o in ctx["radar"]["avaliacoes"] if o.get("status") == "calculado"]
        lines += ["", f"Sinal do Radar ligado: estado hoje {ctx['radar']['estado_hoje']}; "
                      f"{len(done)} avaliação(ões) posterior(es) calculada(s); "
                      f"{len(ctx['radar']['operacoes_informadas'])} operação(ões) informada(s) pela pessoa."]
    lines += ["", "_A decisão antiga é registro histórico, não instrução: confira se as premissas ainda valem._"]
    return "\n".join(lines)
