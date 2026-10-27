from decimal import Decimal

import pytest

from financial_engine.money import format_brl, parse_brl, round_brl, to_decimal
from financial_engine.rates import annual_to_monthly, deflator, monthly_to_annual, net_of_fee, real_rate

D = Decimal


def test_float_is_rejected():
    with pytest.raises(TypeError):
        to_decimal(0.1)


@pytest.mark.parametrize("text, expected", [
    ("R$ 1.234,56", "1234.56"),
    ("150", "150"),
    ("150,00", "150.00"),
    ("0,5", "0.5"),
    ("1.000", "1000"),
    ("1.234.567,89", "1234567.89"),
    ("-R$ 10,00", "-10.00"),
    ("(10,00)", "-10.00"),
])
def test_parse_brl_regional_format(text, expected):
    assert parse_brl(text) == D(expected)


@pytest.mark.parametrize("text", ["10.50", "0.5", "1,234,56", "12.34,5", "abc", "", "1.2345"])
def test_parse_brl_rejects_ambiguous_or_invalid(text):
    with pytest.raises(ValueError):
        parse_brl(text)


def test_format_brl():
    assert format_brl(D("1234567.891")) == "R$ 1.234.567,89"
    assert format_brl(D("-0.5")) == "-R$ 0,50"


def test_round_half_up_to_cents():
    assert round_brl(D("0.005")) == D("0.01")


def test_annual_to_monthly_by_compounding_not_division():
    monthly = annual_to_monthly(D("0.12"))
    assert monthly != D("0.01")
    assert abs(monthly - D("0.009488792934583")) < D("1e-15")
    assert abs(monthly_to_annual(monthly) - D("0.12")) < D("1e-25")


def test_negative_rate_allowed_but_not_below_minus_100():
    assert annual_to_monthly(D("-0.10")) < 0
    with pytest.raises(ValueError):
        annual_to_monthly(D("-1"))


def test_real_rate_fisher():
    assert abs(real_rate(D("0.10"), D("0.045")) - D("0.0526315789473684210526315789")) < D("1e-25")


def test_fee_reduces_return():
    assert net_of_fee(D("0.10"), D("0.01")) == D("0.089")


def test_deflator_one_year():
    assert deflator(D("0.05"), 12) == D("1.05")


def test_to_decimal_rejects_exponent_and_huge_values():
    from financial_engine.money import to_decimal

    for bad in ("1E+999999999", "1e3", "9" * 16, "0." + "1" * 19, "NaN", "", " "):
        with pytest.raises(ValueError):
            to_decimal(bad)
    with pytest.raises(ValueError):
        to_decimal(10 ** 15)
    assert to_decimal("-1234.56") == Decimal("-1234.56") and to_decimal("0.000000000000000001")
