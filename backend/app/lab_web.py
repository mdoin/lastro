# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas do Laboratório do Conselho (docs/LAB.md). Tudo filtra pelo dono: experimento de outra pessoa responde 404."""

import datetime as dt
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from lab.service import CATEGORIES, LabError

ClientId = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ExperimentIn(BaseModel):
    question: str = Field(min_length=10, max_length=2000)
    category: Literal[tuple(CATEGORIES)] = "outros"  # type: ignore[valid-type]
    repetitions: int = Field(1, ge=1, le=5)
    research: bool = False
    as_of: dt.date | None = None
    followups: list[int] = Field(default_factory=lambda: [30, 90, 180], max_length=4)
    client_id: str | None = ClientId


class SettingsIn(BaseModel):
    automation: Literal["desligada", "propor", "executar"] | None = None
    max_per_week: int | None = Field(None, ge=0, le=14)
    monthly_token_budget: int | None = Field(None, ge=0, le=100_000_000)
    repetitions: int | None = Field(None, ge=1, le=5)


class HypothesisIn(BaseModel):
    outcome: Literal["aconteceu", "nao_aconteceu", "indeterminada"]
    note: str = Field("", max_length=500)


class ReviewIn(BaseModel):
    repetition: int = Field(ge=1, le=5)
    scores: dict[Literal["individual", "conselho"], dict[Literal["alternativas", "restricoes", "consequencias",
                                                                  "clareza"], int]]
    note: str = Field("", max_length=500)


class JudgeIn(BaseModel):
    repetition: int = Field(ge=1, le=5)


class LinkIn(BaseModel):
    decision_id: str = Field(max_length=64)


def register(app: FastAPI, conn, *, lab, current_user, log_access) -> None:
    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc) or "Experimento inexistente.") from exc
        except (LabError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/lab")
    async def lab_list(category: str | None = Query(None, max_length=40), since: dt.date | None = None,
                       status: str | None = Query(None, max_length=20), user: str = Depends(current_user)):
        return {"experiments": lab.listing(user, category=category, since=since.isoformat() if since else None,
                                           status=status),
                "dashboard": lab.dashboard(user, category=category, since=since.isoformat() if since else None),
                "categories": CATEGORIES, "settings": lab.settings(user)}

    @app.post("/api/lab", status_code=201)
    async def lab_create(body: ExperimentIn, user: str = Depends(current_user)):
        exp = call(lab.create, user, question=body.question, category=body.category, repetitions=body.repetitions,
                   research=body.research, as_of=body.as_of.isoformat() if body.as_of else None,
                   followups=body.followups, client_id=body.client_id)
        log_access(user, "lab.create", exp["id"])
        return exp

    @app.get("/api/lab/journal")
    async def lab_journal(user: str = Depends(current_user)):
        return lab.journal(user)

    @app.put("/api/lab/settings")
    async def lab_settings(body: SettingsIn, user: str = Depends(current_user)):
        log_access(user, "lab.settings", "settings")
        return call(lab.set_settings, user, body.model_dump())

    @app.get("/api/lab/{exp_id}")
    async def lab_get(exp_id: str, user: str = Depends(current_user)):
        lab.advance()
        return call(lab.experiment, user, exp_id)

    @app.post("/api/lab/{exp_id}/start")
    async def lab_start(exp_id: str, user: str = Depends(current_user)):
        log_access(user, "lab.start", exp_id)
        return call(lab.start, user, exp_id)

    @app.post("/api/lab/{exp_id}/refuse")
    async def lab_refuse(exp_id: str, user: str = Depends(current_user)):
        return call(lab.refuse, user, exp_id)

    @app.post("/api/lab/{exp_id}/cancel")
    async def lab_cancel(exp_id: str, user: str = Depends(current_user)):
        call(lab._row, user, exp_id)
        log_access(user, "lab.cancel", exp_id)
        return await lab.cancel(user, exp_id)

    @app.post("/api/lab/{exp_id}/judge")
    async def lab_judge(exp_id: str, body: JudgeIn, user: str = Depends(current_user)):
        call(lab._row, user, exp_id)
        log_access(user, "lab.judge", exp_id)
        try:
            return await lab.judge(user, exp_id, body.repetition)
        except LabError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/lab/{exp_id}/review")
    async def lab_review(exp_id: str, body: ReviewIn, user: str = Depends(current_user)):
        log_access(user, "lab.review", exp_id)
        return call(lab.human_review, user, exp_id, body.repetition, body.scores, body.note)

    @app.post("/api/lab/hypotheses/{hyp_id}/resolve")
    async def lab_resolve(hyp_id: str, body: HypothesisIn, user: str = Depends(current_user)):
        log_access(user, "lab.resolve", hyp_id)
        return call(lab.resolve_manual, user, hyp_id, body.outcome, body.note)

    @app.post("/api/lab/{exp_id}/decision")
    async def lab_link(exp_id: str, body: LinkIn, user: str = Depends(current_user)):
        log_access(user, "lab.decision", exp_id)
        return call(lab.link_decision, user, exp_id, body.decision_id)
