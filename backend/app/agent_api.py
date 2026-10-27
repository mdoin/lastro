"""API local SOMENTE LEITURA exposta aos agentes do OpenBot.

Barreiras técnicas (não dependem de prompt):
- só existem rotas GET; qualquer outro método é recusado com 405 antes do roteamento;
- não há rota, função ou cliente capaz de escrever em instituição financeira;
- escuta apenas em loopback; `serve()` recusa outra interface;
- exige token Bearer lido do ambiente; recusa iniciar sem token forte;
- na Fase 0/1 só carrega arquivos marcados com "synthetic": true.

Uso (a partir da raiz do projeto): MPA_AGENT_API_TOKEN=... uv run python -m app.agent_api
"""

import hmac
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from financial_engine import ENGINE_VERSION
from financial_engine.budget import Debt, FinancialSnapshot, monthly_guidance, reserve_status
from financial_engine.projection import Assumptions, Plan, compare_scenarios

from . import db, store, views

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures_synthetic"
ALLOWED_METHODS = {"GET"}
MIN_TOKEN_LENGTH = 32
MAX_MONTHS = 12 * 80
DECIMAL_PATTERN = r"^\d{1,12}(\.\d{1,8})?$"
USER_TZ = ZoneInfo("America/Sao_Paulo")


class DataNotAllowed(Exception):
    pass


def load_synthetic(data_dir: Path, name: str) -> dict:
    data = json.loads((data_dir / name).read_text(encoding="utf-8"))
    if data.get("synthetic") is not True:
        raise DataNotAllowed(f"{name} não está marcado como sintético; dados reais não são servidos nesta fase.")
    return data


def _snapshot(p: dict, as_of: str) -> FinancialSnapshot:
    return FinancialSnapshot(
        net_monthly_income=p["net_monthly_income"],
        essential_expenses=p["essential_expenses"],
        variable_expenses=p["variable_expenses"],
        liquid_reserve=p["liquid_reserve"],
        available_this_month=p["available_this_month"],
        debts=tuple(Debt(**d) for d in p["debts"]),
        as_of=as_of,
    )


def create_app(token: str, data_dir: Path, db_path: Path | None = None) -> FastAPI:
    if len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(f"Token da API precisa ter pelo menos {MIN_TOKEN_LENGTH} caracteres aleatórios.")

    app = FastAPI(
        title="Meu Patrimônio AI — API de leitura para agentes",
        version=ENGINE_VERSION,
        docs_url=None, redoc_url=None, openapi_url=None,
    )

    @app.middleware("http")
    async def read_only_guard(request: Request, call_next):
        if request.method not in ALLOWED_METHODS:
            return JSONResponse({"detail": "API somente leitura: apenas GET é aceito."},
                                status_code=405, headers={"Allow": "GET"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def require_token(request: Request):
        header = request.headers.get("authorization", "")
        if not (header.startswith("Bearer ") and hmac.compare_digest(header[7:].encode(), token.encode())):
            raise HTTPException(status_code=401, detail="não autorizado")

    @app.exception_handler(DataNotAllowed)
    async def data_not_allowed(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    def personas_data() -> dict:
        return load_synthetic(data_dir, "personas.json")

    auth = [Depends(require_token)]

    @app.get("/v1/health", dependencies=auth)
    def health():
        return {"status": "ok", "engine_version": ENGINE_VERSION, "mode": "read-only", "data_kind": "synthetic"}

    @app.get("/v1/personas", dependencies=auth)
    def personas():
        data = personas_data()
        return {"as_of": data["as_of"], "data_kind": "synthetic",
                "personas": [{"id": p["id"], "label": p["label"]} for p in data["personas"]]}

    @app.get("/v1/personas/{persona_id}/diagnosis", dependencies=auth)
    def diagnosis(
        persona_id: str,
        reserve_months: int = Query(6, ge=1, le=24),
        reference_annual_return: str = Query("0.10", pattern=DECIMAL_PATTERN),
    ):
        data = personas_data()
        persona = next((p for p in data["personas"] if p["id"] == persona_id), None)
        if persona is None:
            raise HTTPException(status_code=404, detail="persona inexistente")
        snapshot = _snapshot(persona, data["as_of"])
        reserve = reserve_status(snapshot.essential_expenses, snapshot.liquid_reserve, reserve_months)
        guidance = monthly_guidance(snapshot, reserve_target_months=reserve_months,
                                    reference_annual_return=Decimal(reference_annual_return))
        return {
            "as_of": data["as_of"], "data_kind": "synthetic", "persona": persona_id,
            "reserve": {
                "target_months": reserve_months,
                "target_amount": str(reserve.target_amount),
                "current": str(reserve.current),
                "gap": str(reserve.gap),
                "coverage_months": None if reserve.coverage_months is None else str(reserve.coverage_months),
            },
            "guidance": guidance.as_dict(),
        }

    @app.get("/v1/projection", dependencies=auth)
    def projection(
        initial: str = Query("0", pattern=DECIMAL_PATTERN),
        contribution: str = Query("0", pattern=DECIMAL_PATTERN),
        months: int = Query(120, ge=0, le=MAX_MONTHS),
    ):
        scenarios = load_synthetic(data_dir, "scenarios.json")
        plan = Plan(initial=Decimal(initial), monthly_contribution=Decimal(contribution), months=months)
        results = compare_scenarios(plan, [Assumptions(**s) for s in scenarios["scenarios"]])
        return {"data_kind": "synthetic", "assumptions_note": scenarios["note"],
                "projections": [r.as_dict() for r in results]}

    if db_path is not None:
        _add_owner_routes(app, auth, db_path)
    return app


def _add_owner_routes(app: FastAPI, auth: list, db_path: Path) -> None:
    """Dados reais do dono, sempre por conexão somente leitura."""

    def read(fn):
        conn = db.connect_readonly(db_path)
        try:
            return fn(conn)
        except views.NoData as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            conn.close()

    def today():
        return datetime.now(USER_TZ).date()

    @app.get("/v1/me/situation", dependencies=auth)
    def situation():
        def build(conn):
            snap = store.latest_snapshot(conn)
            if not snap:
                raise views.NoData("Nenhuma situação financeira registrada ainda.")
            return {"data_kind": "owner", "today": today().isoformat(), "latest": snap,
                    "history": store.snapshot_history(conn)[-12:], "freshness": views.data_freshness(conn, today())}
        return read(build)

    @app.get("/v1/me/diagnosis", dependencies=auth)
    def my_diagnosis(reserve_months: int = Query(6, ge=1, le=24),
                     reference_annual_return: str = Query("0.10", pattern=DECIMAL_PATTERN)):
        return read(lambda conn: {"data_kind": "owner", **views.diagnosis_view(
            conn, reserve_months=reserve_months, reference_annual_return=reference_annual_return)})

    @app.get("/v1/me/projection", dependencies=auth)
    def my_projection(initial: str = Query("0", pattern=DECIMAL_PATTERN),
                      contribution: str = Query("0", pattern=DECIMAL_PATTERN),
                      months: int = Query(120, ge=0, le=MAX_MONTHS),
                      contribution_annual_increase: str = Query("0", pattern=DECIMAL_PATTERN)):
        return read(lambda conn: {"data_kind": "owner", **views.projection_view(
            conn, initial=initial, contribution=contribution, months=months,
            contribution_annual_increase=contribution_annual_increase)})

    @app.get("/v1/me/goals", dependencies=auth)
    def my_goals():
        return read(lambda conn: {"data_kind": "owner", "today": today().isoformat(),
                                  "goals": views.goals_view(conn, today())})

    @app.get("/v1/me/assumptions", dependencies=auth)
    def my_assumptions():
        return read(lambda conn: {"data_kind": "owner", **store.get_assumptions(conn)})

    @app.get("/v1/me/decisions", dependencies=auth)
    def my_decisions():
        return read(lambda conn: {"data_kind": "owner", "decisions": store.list_decisions(conn)[:20]})


def serve(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn

    if host not in LOOPBACK_HOSTS:
        raise RuntimeError("A API dos agentes só pode escutar em loopback (127.0.0.1/::1).")
    db_path = os.environ.get("LASTRO_DB")
    app = create_app(
        token=os.environ.get("MPA_AGENT_API_TOKEN", ""),
        data_dir=Path(os.environ.get("MPA_DATA_DIR", DEFAULT_DATA_DIR)),
        db_path=Path(db_path) if db_path else None,
    )
    uvicorn.run(app, host=host, port=port, access_log=False, server_header=False)


if __name__ == "__main__":
    serve()
