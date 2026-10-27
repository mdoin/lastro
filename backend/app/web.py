"""Lastro — web app (API do contrato docs/WEB_API.md + frontend estático).

Roda como o usuário `patrimonio`. Todas as rotas são `async` e compartilham uma
única conexão SQLite no laço de eventos (app de uma pessoa só).
"""

import asyncio
import decimal
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
import datetime as dt
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from financial_engine import ENGINE_VERSION
from financial_engine.budget import Guidance

from . import auth, db, routines, store, views
from .mentor_client import MentorClient
from .turns import ConversationBusy, TurnManager

APP_VERSION = "0.2.0"
USER_TZ = ZoneInfo("America/Sao_Paulo")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'")


@dataclass
class Settings:
    db_path: Path
    mentor_socket: Path
    static_dir: Path | None = None
    cookie_secure: bool = True
    run_scheduler: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        static = os.environ.get("LASTRO_STATIC_DIR")
        return cls(db_path=Path(os.environ.get("LASTRO_DB", "/var/lib/patrimonio/lastro.db")),
                   mentor_socket=Path(os.environ.get("LASTRO_MENTOR_SOCKET", "/run/lastro-mentor/mentor.sock")),
                   static_dir=Path(static) if static else None,
                   cookie_secure=os.environ.get("LASTRO_COOKIE_SECURE", "1") != "0")


def today() -> date:
    return datetime.now(USER_TZ).date()


# ---------- modelos de entrada ----------

class LoginIn(BaseModel):
    password: str = Field(max_length=512)


class DebtIn(BaseModel):
    name: str = Field(max_length=120)
    balance: str
    monthly_rate: str
    monthly_payment: str


class SnapshotIn(BaseModel):
    as_of: date
    net_monthly_income: str
    essential_expenses: str
    variable_expenses: str
    liquid_reserve: str
    available_this_month: str
    debts: list[DebtIn] = Field(default_factory=list, max_length=50)


class ScenarioIn(BaseModel):
    name: str = Field(max_length=40)
    annual_return: str
    annual_inflation: str
    annual_fee: str = "0"
    note: str = Field("", max_length=200)


class AssumptionsIn(BaseModel):
    scenarios: list[ScenarioIn] = Field(min_length=1, max_length=5)


class ProjectionIn(BaseModel):
    initial: str = "0"
    contribution: str = "0"
    months: int = Field(120, ge=0, le=views.MAX_MONTHS)
    contribution_annual_increase: str = "0"
    paused_months: list[int] = Field(default_factory=list, max_length=960)
    include_path: bool = False


class GoalIn(BaseModel):
    name: str = Field(max_length=120)
    target_real_value: str
    deadline: date
    priority: int = Field(3, ge=1, le=5)
    liquidity: str = "longo_prazo"
    current_amount: str = "0"


class ConversationIn(BaseModel):
    title: str | None = Field(None, max_length=120)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class PanelIn(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class RoutineIn(BaseModel):
    name: str = Field(max_length=120)
    instruction: str = Field(max_length=4000)
    schedule: dict
    timezone: str = "America/Sao_Paulo"
    active: bool = True
    missed_policy: str = "skip"
    use_panel: bool = False


class DecisionIn(BaseModel):
    date: dt.date | None = None
    question: str = Field(max_length=500)
    alternatives: list[str] = Field(default_factory=list, max_length=10)
    information: str = Field("", max_length=2000)
    risk_accepted: str = Field("", max_length=1000)
    user_choice: str = Field(max_length=500)
    planned_amount: str | None = None
    confirmed: bool = False
    review_of_id: str | None = None


# ---------- app ----------

def create_app(settings: Settings) -> FastAPI:
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    mentor = MentorClient(settings.mentor_socket)
    turns = TurnManager(conn, mentor)
    scheduler = routines.Scheduler(conn, turns.routine_executor)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(scheduler.run_forever()) if settings.run_scheduler else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Lastro", version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.conn, app.state.turns, app.state.scheduler = conn, turns, scheduler

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS:
            if request.headers.get("x-lastro") != "1":
                return JSONResponse({"detail": "Requisição recusada (cabeçalho de segurança ausente)."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
                return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    async def require_session(request: Request) -> None:  # async: a conexão SQLite é do laço, nunca de threads
        if not auth.session_is_valid(conn, request.cookies.get(auth.SESSION_COOKIE)):
            raise HTTPException(status_code=401, detail="Faça login.")

    def bad_request(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except views.NoData as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, TypeError, decimal.DecimalException) as exc:
            raise HTTPException(status_code=422, detail=str(exc) or "Valor fora do intervalo calculável.") from exc

    private = [Depends(require_session)]

    # --- autenticação ---
    @app.get("/api/auth/state")
    async def auth_state(request: Request):
        return {"authenticated": auth.session_is_valid(conn, request.cookies.get(auth.SESSION_COOKIE)),
                "setup_required": not auth.password_is_set(conn)}

    @app.post("/api/auth/login", status_code=204)
    async def login(body: LoginIn, request: Request, response: Response):
        client = auth.client_key(request.client.host if request.client else None)
        if auth.too_many_failures(conn, client):
            raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 15 minutos.")
        delay = auth.global_delay(conn)
        if delay:
            await asyncio.sleep(delay)
            # Durante a espera outras requisições do mesmo cliente passaram pela checagem acima: checa de novo.
            if auth.too_many_failures(conn, client):
                raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 15 minutos.")
        token = auth.attempt_login(conn, body.password, client)
        if not token:
            raise HTTPException(status_code=401, detail="Senha incorreta.")
        response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                            secure=settings.cookie_secure, samesite="strict", path="/")

    @app.post("/api/auth/logout", status_code=204)
    async def logout(request: Request, response: Response):
        auth.logout(conn, request.cookies.get(auth.SESSION_COOKIE))
        response.delete_cookie(auth.SESSION_COOKIE, path="/")

    # --- situação financeira ---
    @app.get("/api/snapshot/latest", dependencies=private)
    async def snapshot_latest():
        return store.latest_snapshot(conn)

    @app.post("/api/snapshot", status_code=201, dependencies=private)
    async def snapshot_create(body: SnapshotIn):
        return bad_request(store.create_snapshot, conn, body.model_dump(mode="json"))

    @app.get("/api/snapshot/history", dependencies=private)
    async def snapshot_history():
        return store.snapshot_history(conn)

    @app.get("/api/diagnosis", dependencies=private)
    async def diagnosis(reserve_months: int = Query(6, ge=1, le=24),
                        reference_annual_return: str = Query("0.10", pattern=r"^-?\d{1,3}(\.\d{1,8})?$")):
        return bad_request(views.diagnosis_view, conn, reserve_months=reserve_months,
                           reference_annual_return=reference_annual_return)

    # --- premissas, projeção, metas ---
    @app.get("/api/assumptions", dependencies=private)
    async def assumptions_get():
        return store.get_assumptions(conn)

    @app.put("/api/assumptions", dependencies=private)
    async def assumptions_put(body: AssumptionsIn):
        return bad_request(store.save_assumptions, conn, [s.model_dump() for s in body.scenarios])

    @app.post("/api/projection", dependencies=private)
    async def projection(body: ProjectionIn):
        return bad_request(views.projection_view, conn, **body.model_dump())

    @app.get("/api/goals", dependencies=private)
    async def goals_list():
        return views.goals_view(conn, today())

    def _goal_out(goal_id: str) -> dict:
        return next(g for g in views.goals_view(conn, today()) if g["id"] == goal_id)

    @app.post("/api/goals", status_code=201, dependencies=private)
    async def goals_create(body: GoalIn):
        goal = bad_request(store.create_goal, conn, body.model_dump(mode="json"), today=today().isoformat())
        return _goal_out(goal["id"])

    @app.put("/api/goals/{goal_id}", dependencies=private)
    async def goals_update(goal_id: str, body: GoalIn):
        if not bad_request(store.update_goal, conn, goal_id, body.model_dump(mode="json")):
            raise HTTPException(status_code=404, detail="Meta inexistente.")
        return _goal_out(goal_id)

    @app.delete("/api/goals/{goal_id}", status_code=204, dependencies=private)
    async def goals_delete(goal_id: str):
        if not store.delete_goal(conn, goal_id):
            raise HTTPException(status_code=404, detail="Meta inexistente.")

    # --- mentor ---
    def _conversation(conv_id: str) -> dict:
        conv = store.get_conversation(conn, conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversa inexistente.")
        return conv

    @app.get("/api/conversations", dependencies=private)
    async def conversations_list():
        return store.list_conversations(conn)

    @app.post("/api/conversations", status_code=201, dependencies=private)
    async def conversations_create(body: ConversationIn):
        conv = store.create_conversation(conn, body.title or "Nova conversa")
        return {k: conv[k] for k in ("id", "kind", "title", "created_at", "updated_at")}

    @app.delete("/api/conversations/{conv_id}", status_code=204, dependencies=private)
    async def conversations_delete(conv_id: str):
        if conv_id in turns.active:
            raise HTTPException(status_code=409, detail="Há uma resposta em andamento nesta conversa.")
        if not store.delete_conversation(conn, conv_id):
            raise HTTPException(status_code=404, detail="Conversa inexistente.")

    @app.get("/api/conversations/{conv_id}/messages", dependencies=private)
    async def messages_list(conv_id: str):
        _conversation(conv_id)
        return store.list_messages(conn, conv_id)

    @app.post("/api/conversations/{conv_id}/messages", dependencies=private)
    async def messages_send(conv_id: str, body: MessageIn):
        conv = _conversation(conv_id)
        if conv["kind"] != "chat":
            raise HTTPException(status_code=409, detail="Esta conversa não aceita mensagens.")
        try:
            turn = turns.start_chat(conv_id, body.text)
        except ConversationBusy as exc:
            raise HTTPException(status_code=409, detail="Aguarde a resposta anterior terminar.") from exc
        return sse(turn.subscribe())

    @app.post("/api/conversations/{conv_id}/interrupt", status_code=204, dependencies=private)
    async def messages_interrupt(conv_id: str):
        _conversation(conv_id)
        await turns.interrupt(conv_id)

    @app.post("/api/panels", dependencies=private)
    async def panels(body: PanelIn):
        if body.conversation_id and _conversation(body.conversation_id)["kind"] != "panel":
            raise HTTPException(status_code=409, detail="O painel só continua conversas do tipo painel.")
        try:
            turn = turns.start_panel(body.question, body.conversation_id)
        except ConversationBusy as exc:
            raise HTTPException(status_code=409, detail="Aguarde a resposta anterior terminar.") from exc
        return sse(turn.subscribe())

    # --- rotinas ---
    @app.get("/api/routines", dependencies=private)
    async def routines_list():
        return routines.list_routines(conn)

    @app.post("/api/routines", status_code=201, dependencies=private)
    async def routines_create(body: RoutineIn):
        routine = bad_request(routines.create_routine, conn, body.model_dump())
        scheduler.wake()
        return routine

    @app.put("/api/routines/{rid}", dependencies=private)
    async def routines_update(rid: str, body: RoutineIn):
        routine = bad_request(routines.update_routine, conn, rid, body.model_dump())
        if not routine:
            raise HTTPException(status_code=404, detail="Rotina inexistente.")
        scheduler.wake()
        return routine

    @app.delete("/api/routines/{rid}", status_code=204, dependencies=private)
    async def routines_delete(rid: str):
        if not routines.delete_routine(conn, rid):
            raise HTTPException(status_code=404, detail="Rotina inexistente.")

    @app.post("/api/routines/{rid}/run", status_code=202, dependencies=private)
    async def routines_run(rid: str):
        run = routines.queue_manual_run(conn, rid)
        if not run:
            raise HTTPException(status_code=404, detail="Rotina inexistente.")
        scheduler.submit(run)
        return run

    @app.get("/api/routines/{rid}/runs", dependencies=private)
    async def routines_runs(rid: str):
        return routines.list_runs(conn, rid)

    @app.get("/api/inbox", dependencies=private)
    async def inbox():
        return routines.inbox(conn)

    @app.post("/api/inbox/{run_id}/read", status_code=204, dependencies=private)
    async def inbox_read(run_id: str):
        if not routines.mark_read(conn, run_id):
            raise HTTPException(status_code=404, detail="Item inexistente.")

    # --- decisões, estado, exportação ---
    @app.get("/api/decisions", dependencies=private)
    async def decisions_list():
        return store.list_decisions(conn)

    @app.post("/api/decisions", status_code=201, dependencies=private)
    async def decisions_create(body: DecisionIn):
        return bad_request(store.create_decision, conn, body.model_dump(mode="json"), today=today().isoformat())

    @app.get("/api/status", dependencies=private)
    async def status():
        worker = await mentor.call({"op": "status"}, timeout=12)
        available = worker.get("type") == "done"
        return {"app_version": APP_VERSION, "engine_version": ENGINE_VERSION,
                "disclaimer": Guidance.__dataclass_fields__["disclaimer"].default,
                "mentor": {"available": available, "logged_in": worker.get("logged_in") if available else None,
                           "subscription": worker.get("subscription"), "busy": worker.get("busy", 0),
                           "queued": worker.get("queued", 0), "limit_until": worker.get("limit_until")},
                "data": views.data_freshness(conn, today())}

    @app.get("/api/export", dependencies=private)
    async def export():
        payload = json.dumps(store.export_all(conn), ensure_ascii=False, indent=2)
        return Response(payload, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="lastro-{today().isoformat()}.json"'})

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def api_not_found(rest: str):
        raise HTTPException(status_code=404, detail="Rota inexistente.")

    # --- frontend estático (SPA) ---
    if settings.static_dir and (settings.static_dir / "index.html").exists():
        root = settings.static_dir.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            try:
                candidate = (root / path).resolve()
                found = bool(path) and candidate.is_file() and root in candidate.parents
            except (ValueError, OSError):  # ex.: byte NUL no caminho
                found = False
            if found:
                immutable = path.startswith("assets/")  # nomes com hash de conteúdo
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"
                                                        if immutable else "no-cache"})
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def sse(events) -> StreamingResponse:
    async def body():
        async for event in events:
            name = event.get("type", "message")
            data = {k: v for k, v in event.items() if k != "type"}
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def main() -> None:
    import uvicorn

    host = os.environ.get("LASTRO_HOST", "127.0.0.1")
    port = int(os.environ.get("LASTRO_PORT", "8080"))
    uvicorn.run(create_app(Settings.from_env()), host=host, port=port, access_log=False, server_header=False,
                proxy_headers=True, forwarded_allow_ips=os.environ.get("LASTRO_TRUSTED_PROXIES", "127.0.0.1"))


if __name__ == "__main__":
    main()
