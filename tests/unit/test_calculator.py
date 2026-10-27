"""Calculadora determinística: resultados conhecidos (conferidos à mão ou em tabela financeira)."""
from decimal import Decimal

import pytest

from financial_engine.calculator import CalculationError, OPERATIONS, calculate, numbers_in


def r(op, **params):
    return calculate(op, params)["resultado"]


def test_simple_and_compound_interest():
    assert r("juros_simples", principal="1000", rate="0.01", periods=12) == {"juros": "120.00", "montante": "1120.00"}
    comp = r("juros_compostos", principal="1000", rate="0.01", periods=12)
    assert comp["montante"] == "1126.83" and comp["juros"] == "126.83"


def test_future_value_end_and_beginning_of_period():
    assert r("valor_futuro", contribution="100", rate="0.01", periods=12)["valor_futuro"] == "1268.25"
    assert r("valor_futuro", contribution="100", rate="0.01", periods=12, timing="inicio")["valor_futuro"] == "1280.93"
    assert r("valor_futuro", initial="500", contribution="100", rate="0", periods=10)["valor_futuro"] == "1500.00"


def test_present_value():
    assert r("valor_presente", future_value="1000", rate="0.10", periods=1)["valor_presente"] == "909.09"
    assert r("valor_presente", payment="100", rate="0.01", periods=12)["valor_presente"] == "1125.51"


def test_inflation_and_real_rate():
    acc = r("inflacao_acumulada", rates=["0.01", "0.02"], amount="100")
    assert acc["inflacao_acumulada"] == "0.03020000" and acc["valor_corrigido"] == "103.02"
    assert r("taxa_real", nominal="0.10", inflation="0.045")["taxa_real"] == "0.05263158"
    assert r("converter_taxa", rate="0.1268250301", **{"from": "anual"})["mensal"] == "0.01000000"


def test_amortization_price_and_sac():
    price = r("amortizacao", principal="10000", monthly_rate="0.01", months=12, system="price")
    assert price["primeira_parcela"] == "888.49" and price["total_juros"] == "661.85"
    assert price["tabela"][-1]["saldo"] == "0.00"
    sac = r("amortizacao", principal="10000", monthly_rate="0.01", months=12, system="sac")
    assert sac["primeira_parcela"] == "933.33" and sac["ultima_parcela"] == "841.67" and sac["total_juros"] == "650.00"


def test_goals():
    assert r("aporte_para_meta", target="1268.25", monthly_rate="0.01", months=12)["aporte_mensal"] == "100.00"
    assert r("meses_para_meta", target="1200", contribution="100", monthly_rate="0")["meses"] == 12
    assert r("meses_para_meta", target="10", initial="20", monthly_rate="0")["meses"] == 0


def test_net_yield_comparison_uses_explicit_tax_premise():
    out = r("comparar_rendimentos", amount="1000", months=12,
            alternatives=[{"name": "A", "annual_rate": "0.10", "tax_rate": "0.15"},
                          {"name": "B", "annual_rate": "0.09"}])
    a, b = out["alternativas"]
    assert a["bruto"] == "1100.00" and a["impostos_premissa"] == "15.00" and a["liquido"] == "1085.00"
    assert b["liquido"] == "1090.00" and out["ordem_por_liquido"] == ["B", "A"]


def test_risk_metrics_correlation_concentration_stress():
    m = r("metricas_risco", returns=["0.1", "-0.2", "0.1"])
    assert m["drawdown_maximo"] == "-0.20000000" and m["retorno_acumulado"] == "-0.03200000"
    assert m["volatilidade_periodo"] == "0.17320508"
    assert r("correlacao", series_a=["1", "2", "3"], series_b=["2", "4", "6"])["correlacao"] == "1.0000"
    assert r("correlacao", series_a=["1", "2", "3"], series_b=["3", "2", "1"])["correlacao"] == "-1.0000"
    c = r("concentracao", positions=[{"name": "x", "value": "50"}, {"name": "y", "value": "50"}])
    assert c["hhi"] == "0.50000000" and c["numero_efetivo_de_posicoes"] == "2.00"
    s = r("cenario_estresse", positions=[{"name": "ações", "value": "1000", "shock": "-0.3"}])
    assert s["perda"] == "300.00"


def test_projection_matches_engine_and_is_labelled_hypothetical():
    out = calculate("projecao_hipotetica", {"contribution": "1000", "months": 120, "annual_return": "0.10",
                                            "annual_inflation": "0.045"})
    assert out["natureza"] == "projecao_hipotetica" and out["resultado"]["inputs_fingerprint"]
    assert out["observacoes"]


def test_rejects_float_unknown_operation_and_bad_input():
    with pytest.raises(CalculationError):
        calculate("juros_simples", {"principal": 1000.0, "rate": "0.01", "periods": 1})
    with pytest.raises(CalculationError, match="desconhecida"):
        calculate("transferir_dinheiro", {})
    with pytest.raises(CalculationError):
        calculate("juros_compostos", {"principal": "1", "rate": "-1", "periods": 1})
    with pytest.raises(CalculationError):
        calculate("juros_compostos", {"principal": "1", "rate": "0.01", "periods": 5000})


def test_same_inputs_same_fingerprint_and_numbers_extraction():
    a = calculate("juros_compostos", {"principal": "1000", "rate": "0.01", "periods": 12})
    b = calculate("juros_compostos", {"periods": 12, "rate": "0.01", "principal": "1000"})
    assert a["fingerprint"] == b["fingerprint"]
    assert Decimal("1126.83") in numbers_in(a["resultado"])


def test_every_operation_is_documented_in_tool_schema():
    from mentor.tools import CALC_OPERATIONS_HELP

    assert set(OPERATIONS) == set(CALC_OPERATIONS_HELP)
