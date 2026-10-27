# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vistas calculadas sobre os dados do usuário (diagnóstico, projeção, metas).

Compartilhadas pelo web app e pela API de leitura do mentor, para que o número
mostrado na tela e o número citado pelo mentor saiam do mesmo código.
"""

import sqlite3
from datetime import date
from decimal import Decimal

from financial_engine.budget import debt_commitment_ratio, free_cash_flow, monthly_guidance, reserve_status
from financial_engine.money import to_decimal
from financial_engine.projection import Assumptions, Plan, compare_scenarios, required_contribution_for_real_goal

from . import store

MAX_MONTHS = 12 * 80
STALE_AFTER_DAYS = 45


class NoData(Exception):
    """O usuário ainda não registrou a situação financeira."""


def _latest(conn: sqlite3.Connection) -> dict:
    snap = store.latest_snapshot(conn)
    if not snap:
        raise NoData("Nenhuma situação financeira registrada ainda.")
    return snap


def diagnosis_view(conn: sqlite3.Connection, *, reserve_months: int = 6, reference_annual_return: str = "0.10") -> dict:
    snap = _latest(conn)
    fin = store.to_financial(snap)
    reserve = reserve_status(fin.essential_expenses, fin.liquid_reserve, reserve_months)
    guidance = monthly_guidance(fin, reserve_target_months=reserve_months,
                                reference_annual_return=to_decimal(reference_annual_return))
    ratio = debt_commitment_ratio(fin)
    return {
        "as_of": snap["as_of"],
        "free_cash_flow": str(free_cash_flow(fin)),
        "debt_commitment_ratio": None if ratio is None else str(ratio.quantize(Decimal("0.0001"))),
        "total_debt": str(sum((d.balance for d in fin.debts), Decimal(0))),
        "reserve": {"target_months": reserve_months, "target_amount": str(reserve.target_amount),
                    "current": str(reserve.current), "gap": str(reserve.gap),
                    "coverage_months": None if reserve.coverage_months is None else str(reserve.coverage_months),
                    "complete": reserve.complete},
        "guidance": guidance.as_dict(),
    }


def scenarios(conn: sqlite3.Connection) -> list[Assumptions]:
    return [Assumptions(**s) for s in store.get_assumptions(conn)["scenarios"]]


def projection_view(conn: sqlite3.Connection, *, initial: str, contribution: str, months: int,
                    contribution_annual_increase: str = "0", paused_months: list[int] | None = None,
                    include_path: bool = False) -> dict:
    if not 0 <= months <= MAX_MONTHS:
        raise ValueError(f"months: de 0 a {MAX_MONTHS}.")
    plan = Plan(initial=to_decimal(initial), monthly_contribution=to_decimal(contribution), months=months,
                contribution_annual_increase=to_decimal(contribution_annual_increase),
                paused_months=frozenset(paused_months or ()))
    results = compare_scenarios(plan, scenarios(conn))
    assumptions = store.get_assumptions(conn)
    return {"assumptions_note": assumptions["note"], "assumptions_are_default": assumptions["is_default"],
            "projections": [r.as_dict(include_path=include_path) for r in results]}


def months_between(today: date, deadline: date) -> int:
    return max((deadline.year - today.year) * 12 + (deadline.month - today.month) - (deadline.day < today.day), 0)


def goals_view(conn: sqlite3.Connection, today: date) -> list[dict]:
    """Metas com aporte mensal necessário por cenário e um status de trajetória.

    Status (heurística transparente): `no_rumo` se a meta já foi atingida ou o aporte
    necessário no cenário base cabe numa fatia igual da sobra mensal entre as metas;
    `atencao` se cabe na sobra inteira; `revisar` caso contrário ou sem dados.
    """
    goals = store.list_goals(conn)
    snap = store.latest_snapshot(conn)
    fcf = max(free_cash_flow(store.to_financial(snap)), Decimal(0)) if snap else None
    scen = scenarios(conn)
    enriched = []
    for g in goals:
        months_left = months_between(today, date.fromisoformat(g["deadline"]))
        target, current = to_decimal(g["target_real_value"]), to_decimal(g["current_amount"])
        required = {}
        for a in scen:
            if current >= target:
                required[a.name] = "0.00"
            elif months_left == 0:
                required[a.name] = str((target - current).quantize(Decimal("0.01")))
            else:
                required[a.name] = str(required_contribution_for_real_goal(target, current, months_left, a))
        base = to_decimal(required.get("base", next(iter(required.values()), "0")))
        if current >= target:
            status = "no_rumo"
        elif fcf is None:
            status = "revisar"
        elif base <= fcf / max(len(goals), 1):
            status = "no_rumo"
        elif base <= fcf:
            status = "atencao"
        else:
            status = "revisar"
        enriched.append({**g, "required_monthly": required, "months_left": months_left, "status": status})
    return enriched


def data_freshness(conn: sqlite3.Connection, today: date) -> dict:
    snap = store.latest_snapshot(conn)
    if not snap:
        return {"latest_snapshot_as_of": None, "stale": True}
    age = (today - date.fromisoformat(snap["as_of"])).days
    return {"latest_snapshot_as_of": snap["as_of"], "stale": age > STALE_AFTER_DAYS}
