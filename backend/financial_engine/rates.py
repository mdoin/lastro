# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conversão de taxas por composição (nunca dividir taxa efetiva anual por 12)."""

from decimal import Decimal, localcontext

from .money import CALC_CONTEXT, to_decimal

ONE = Decimal(1)
TWELVE = Decimal(12)


def _check_rate(rate: Decimal) -> Decimal:
    if rate <= -1:
        raise ValueError("Taxa precisa ser maior que -100%.")
    return rate


def annual_to_monthly(annual_rate) -> Decimal:
    r = _check_rate(to_decimal(annual_rate))
    with localcontext(CALC_CONTEXT):
        return (ONE + r) ** (ONE / TWELVE) - ONE


def monthly_to_annual(monthly_rate) -> Decimal:
    r = _check_rate(to_decimal(monthly_rate))
    with localcontext(CALC_CONTEXT):
        return (ONE + r) ** 12 - ONE


def real_rate(nominal_rate, inflation_rate) -> Decimal:
    """Taxa real pela equação de Fisher: (1+n)/(1+i) - 1."""
    n = _check_rate(to_decimal(nominal_rate))
    i = _check_rate(to_decimal(inflation_rate))
    with localcontext(CALC_CONTEXT):
        return (ONE + n) / (ONE + i) - ONE


def net_of_fee(annual_rate, annual_fee) -> Decimal:
    """Retorno anual após taxa cobrada como percentual do patrimônio: (1+r)(1-f) - 1."""
    r = _check_rate(to_decimal(annual_rate))
    f = to_decimal(annual_fee)
    if not Decimal(0) <= f < ONE:
        raise ValueError("Taxa de administração precisa estar entre 0% e 100%.")
    with localcontext(CALC_CONTEXT):
        return (ONE + r) * (ONE - f) - ONE


def deflator(annual_inflation, months: int) -> Decimal:
    """Fator que converte valor nominal no mês `months` para poder de compra de hoje (inflação constante)."""
    i = _check_rate(to_decimal(annual_inflation))
    if months < 0:
        raise ValueError("Número de meses negativo.")
    with localcontext(CALC_CONTEXT):
        return (ONE + i) ** (Decimal(months) / TWELVE)
