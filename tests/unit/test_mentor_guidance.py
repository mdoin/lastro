# SPDX-License-Identifier: AGPL-3.0-or-later
"""Critérios de aceitação do mentor (seção 24.9), com personas sintéticas."""
from decimal import Decimal

import pytest

from financial_engine.budget import (
    Debt, FinancialSnapshot, debt_commitment_ratio, free_cash_flow, monthly_guidance, reserve_status,
)

D = Decimal
REF = D("0.10")


def snap(p, as_of="2026-10-26", **overrides):
    data = {**p, **overrides}
    return FinancialSnapshot(
        net_monthly_income=data["net_monthly_income"], essential_expenses=data["essential_expenses"],
        variable_expenses=data["variable_expenses"], liquid_reserve=data["liquid_reserve"],
        available_this_month=data["available_this_month"], debts=tuple(Debt(**d) for d in data["debts"]), as_of=as_of,
    )


def guide(s):
    return monthly_guidance(s, reserve_target_months=6, reference_annual_return=REF)


def test_expensive_debt_is_prioritized_over_investing(personas):
    g = guide(snap(personas["cartao-rotativo"]))
    assert g.stage == "priorizar_divida"
    assert g.allocation[0].purpose.startswith("Amortizar Cartão")
    assert not any("Investimento" in line.purpose for line in g.allocation)
    assert g.comparisons and "evita cerca de" in g.comparisons[0]


def test_cheap_debt_is_not_prioritized():
    s = FinancialSnapshot(D("5000"), D("2000"), D("1000"), D("0"), D("500"),
                          (Debt("Consignado", D("3000"), D("0.005"), D("200")),))
    assert guide(s).stage == "construir_reserva"


def test_first_time_investor_starts_with_reserve(personas):
    g = guide(snap(personas["iniciante-150"]))
    assert g.stage == "construir_reserva"
    assert g.allocation[0].amount == D("150.00")
    assert g.allocation[0].percent == D("100.0")


@pytest.mark.parametrize("amount", ["50", "150", "1000"])
def test_adapts_to_amount_without_inventing_minimums(personas, amount):
    g = guide(snap(personas["iniciante-150"], available_this_month=amount))
    assert sum(line.amount for line in g.allocation) == D(amount)
    text = str(g.as_dict()).lower()
    assert "mínimo" not in text and "minimo" not in text


def test_no_money_available_means_dont_invest_without_blame(personas):
    g = guide(snap(personas["sem-sobra"]))
    assert g.stage == "sem_recurso_disponivel"
    assert g.allocation == ()
    assert "Não investir" in g.next_step and "sem culpa" in g.next_step


def test_negative_budget_blocks_investing(personas):
    g = guide(snap(personas["deficit"]))
    assert g.stage == "organizar_orcamento"
    assert "Não investir ainda" in g.next_step


def test_complete_reserve_moves_to_goals(personas):
    g = guide(snap(personas["reserva-completa-1000"]))
    assert g.stage == "investir_para_metas"
    assert g.allocation[0].amount == D("1000")
    assert any("verificadas" in n for n in g.notes)


def test_reserve_overflow_goes_to_goals():
    s = FinancialSnapshot(D("5000"), D("1000"), D("1000"), D("5900"), D("500"))
    g = guide(s)
    assert [line.amount for line in g.allocation] == [D("100"), D("400")]


def test_allocation_has_value_percent_and_rationale(personas):
    for pid in ("cartao-rotativo", "iniciante-150", "reserva-completa-1000"):
        g = guide(snap(personas[pid]))
        assert sum(line.percent for line in g.allocation) == D("100.0")
        for line in g.allocation:
            assert line.amount > 0 and line.rationale


def test_output_has_premises_checklist_single_follow_up_and_disclaimer(personas):
    g = guide(snap(personas["iniciante-150"])).as_dict()
    assert len(g["situation"]) == 3
    assert any("hipótese" in p for p in g["premises"])
    assert len(g["checklist"]) == 4
    assert isinstance(g["follow_up"], str) and g["follow_up"]
    assert "plano ≠ aporte confirmado" in g["follow_up"]
    assert "Não é ordem" in g["disclaimer"]


def test_missing_data_is_flagged(personas):
    g = guide(snap(personas["iniciante-150"], as_of=""))
    assert any("Data de referência" in m for m in g.missing_information)


def test_cash_flow_reserve_and_commitment(personas):
    s = snap(personas["cartao-rotativo"])
    assert free_cash_flow(s) == D("4200") - D("2600") - D("700") - D("750")
    assert debt_commitment_ratio(s).quantize(D("0.0001")) == D("0.1786")
    r = reserve_status(D("2600"), D("200"), 6)
    assert r.target_amount == D("15600") and r.gap == D("15400") and not r.complete
    assert reserve_status(D("0"), D("100"), 6).coverage_months is None
