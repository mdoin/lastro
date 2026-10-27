# SPDX-License-Identifier: AGPL-3.0-or-later
"""Testes matemáticos obrigatórios (seção 9.4)."""
from decimal import Decimal

import pytest

from financial_engine.projection import (
    Assumptions, Plan, compare_scenarios, future_value, required_contribution_for_real_goal,
    required_monthly_contribution, simulate,
)
from financial_engine.rates import annual_to_monthly

D = Decimal
CENT = D("0.01")


def a(ret="0.10", inf="0.045", fee="0"):
    return Assumptions("teste", D(ret), D(inf), D(fee))


def test_closed_form_reference_value():
    # 1000 inicial + 100/mês a 1% a.m. por 12 meses: valor conhecido.
    fv = future_value(D("1000"), D("100"), D("0.01"), 12)
    assert fv.quantize(CENT) == D("2395.08")


def test_iterative_matches_closed_form():
    asm = a("0.12", "0.04")
    plan = Plan(D("5000"), D("300"), 240)
    closed = future_value(plan.initial, plan.monthly_contribution, asm.net_monthly_return, plan.months)
    assert abs(simulate(plan, asm).final_nominal - closed) < D("1e-18")


def test_zero_contribution():
    p = simulate(Plan(D("1000"), D("0"), 12), a("0.12", "0"))
    assert p.final_nominal.quantize(CENT) == D("1120.00")
    assert p.total_contributed == 0


def test_zero_return():
    p = simulate(Plan(D("100"), D("50"), 10), a("0", "0"))
    assert p.final_nominal == D("600")
    assert p.market_result == 0
    assert future_value(D("100"), D("50"), D("0"), 10) == D("600")


def test_negative_return_loses_value():
    p = simulate(Plan(D("1000"), D("0"), 12), a("-0.20", "0"))
    assert p.final_nominal.quantize(CENT) == D("800.00")
    assert p.market_result < 0


def test_withdrawal_mid_period():
    plan = Plan(D("1000"), D("100"), 12, withdrawals=((6, D("300")),))
    p = simulate(plan, a("0", "0"))
    assert p.final_nominal == D("1000") + 12 * D("100") - D("300")
    assert p.total_withdrawn == D("300")


def test_withdrawal_larger_than_balance_fails():
    with pytest.raises(ValueError):
        simulate(Plan(D("0"), D("10"), 3, withdrawals=((1, D("100")),)), a("0", "0"))


def test_paused_contributions():
    p = simulate(Plan(D("0"), D("100"), 12, paused_months={4, 5, 6}), a("0", "0"))
    assert p.total_contributed == D("900")


def test_contribution_annual_increase():
    p = simulate(Plan(D("0"), D("100"), 24, contribution_annual_increase=D("0.10")), a("0", "0"))
    assert p.total_contributed == 12 * D("100") + 12 * D("110")


def test_fee_lowers_result():
    plan = Plan(D("10000"), D("500"), 120)
    assert simulate(plan, a(fee="0.01")).final_nominal < simulate(plan, a(fee="0")).final_nominal


def test_real_value_is_deflated_and_market_result_separates_deposits():
    p = simulate(Plan(D("1000"), D("0"), 12), a("0.10", "0.10"))
    assert p.final_real.quantize(CENT) == D("1000.00")
    assert p.final_nominal.quantize(CENT) == D("1100.00")
    assert p.market_result.quantize(CENT) == D("100.00")


def test_deposit_is_not_counted_as_gain():
    p = simulate(Plan(D("0"), D("1000"), 1), a("0", "0"))
    assert p.market_result == 0


def test_reproducible_fingerprint():
    plan = Plan(D("1000"), D("100"), 60)
    p1, p2 = simulate(plan, a()), simulate(plan, a())
    assert p1.inputs_fingerprint == p2.inputs_fingerprint
    assert p1.as_dict() == p2.as_dict()
    assert simulate(plan, a(ret="0.11")).inputs_fingerprint != p1.inputs_fingerprint


def test_three_scenarios_ordered():
    plan = Plan(D("1000"), D("200"), 120)
    results = compare_scenarios(plan, [a("0.06"), a("0.09"), a("0.12")])
    finals = [r.final_nominal for r in results]
    assert finals == sorted(finals)
    for r in results:
        d = r.as_dict()
        assert d["limitations"] and d["assumptions"] and d["engine_version"]


def test_reverse_goal_reaches_target():
    r = annual_to_monthly(D("0.08"))
    needed = required_monthly_contribution(D("100000"), D("5000"), r, 120)
    assert future_value(D("5000"), needed, r, 120) >= D("100000")
    assert future_value(D("5000"), needed - CENT, r, 120) < D("100000")


def test_reverse_goal_already_met_returns_zero():
    assert required_monthly_contribution(D("1000"), D("5000"), D("0.01"), 12) == 0


def test_reverse_goal_zero_rate():
    assert required_monthly_contribution(D("1200"), D("0"), D("0"), 12) == D("100")


def test_real_goal_uses_real_rate():
    asm = a("0.10", "0.045")
    nominal_rate = required_monthly_contribution(D("100000"), D("0"), asm.net_monthly_return, 120)
    real = required_contribution_for_real_goal(D("100000"), D("0"), 120, asm)
    assert real > nominal_rate  # meta em poder de compra exige mais esforço


def test_float_inputs_rejected():
    with pytest.raises(TypeError):
        Plan(1000.0, D("1"), 1)


def test_fingerprint_ignores_decimal_formatting():
    asm = a()
    assert simulate(Plan(D("0"), D("150"), 12), asm).inputs_fingerprint == \
        simulate(Plan(D("0.00"), D("150.00"), 12), asm).inputs_fingerprint
