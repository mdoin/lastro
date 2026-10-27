# SPDX-License-Identifier: AGPL-3.0-or-later
"""Projeções de acumulação em cenários determinísticos.

Convenções (documentadas em docs/FINANCIAL_METHODS.md):
- período mensal; rendimento aplicado sobre o saldo do início do mês;
- aporte no FIM do mês; resgate no fim do mês, depois do aporte;
- taxa de administração descontada do retorno anual antes da conversão mensal;
- valor real = nominal deflacionado por inflação constante do cenário;
- tributos NÃO são modelados nesta versão (ver `LIMITATIONS`).
"""

import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal, localcontext

from . import ENGINE_VERSION
from .money import CALC_CONTEXT, CENT, round_brl, to_decimal
from .rates import annual_to_monthly, deflator, net_of_fee, real_rate

ZERO = Decimal(0)
ONE = Decimal(1)

LIMITATIONS = (
    "Cenários determinísticos: não são previsões nem têm probabilidade associada.",
    "Taxas de retorno e inflação são premissas informadas, não dados de mercado verificados.",
    "Tributos não estão modelados nesta versão; valores são brutos de imposto.",
    "Inflação constante ao longo do horizonte; séries reais variam.",
)


@dataclass(frozen=True)
class Assumptions:
    name: str
    annual_return: Decimal
    annual_inflation: Decimal
    annual_fee: Decimal = ZERO
    note: str = ""

    def __post_init__(self):
        for attr in ("annual_return", "annual_inflation", "annual_fee"):
            object.__setattr__(self, attr, to_decimal(getattr(self, attr)))

    @property
    def net_annual_return(self) -> Decimal:
        return net_of_fee(self.annual_return, self.annual_fee)

    @property
    def net_monthly_return(self) -> Decimal:
        return annual_to_monthly(self.net_annual_return)

    @property
    def real_annual_return(self) -> Decimal:
        return real_rate(self.net_annual_return, self.annual_inflation)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "annual_return": str(self.annual_return),
            "annual_inflation": str(self.annual_inflation),
            "annual_fee": str(self.annual_fee),
            "note": self.note,
        }


@dataclass(frozen=True)
class Plan:
    initial: Decimal
    monthly_contribution: Decimal
    months: int
    contribution_annual_increase: Decimal = ZERO
    paused_months: frozenset = field(default_factory=frozenset)
    withdrawals: tuple = ()  # ((mês, valor), ...) com mês em 1..months

    def __post_init__(self):
        object.__setattr__(self, "initial", to_decimal(self.initial))
        object.__setattr__(self, "monthly_contribution", to_decimal(self.monthly_contribution))
        object.__setattr__(self, "contribution_annual_increase", to_decimal(self.contribution_annual_increase))
        object.__setattr__(self, "paused_months", frozenset(self.paused_months))
        object.__setattr__(self, "withdrawals", tuple((int(m), to_decimal(v)) for m, v in self.withdrawals))
        if self.months < 0:
            raise ValueError("Horizonte negativo.")
        if self.initial < 0 or self.monthly_contribution < 0:
            raise ValueError("Patrimônio inicial e aporte não podem ser negativos.")
        if self.contribution_annual_increase <= -1:
            raise ValueError("Reajuste anual do aporte precisa ser maior que -100%.")
        for month, value in self.withdrawals:
            if not 1 <= month <= self.months or value < 0:
                raise ValueError(f"Resgate inválido no mês {month}.")

    def as_dict(self) -> dict:
        return {
            "initial": str(self.initial),
            "monthly_contribution": str(self.monthly_contribution),
            "months": self.months,
            "contribution_annual_increase": str(self.contribution_annual_increase),
            "paused_months": sorted(self.paused_months),
            "withdrawals": [[m, str(v)] for m, v in self.withdrawals],
        }


@dataclass(frozen=True)
class Projection:
    scenario: str
    final_nominal: Decimal
    final_real: Decimal
    total_contributed: Decimal
    total_withdrawn: Decimal
    market_result: Decimal
    path: tuple  # ((mês, nominal, real), ...)
    inputs_fingerprint: str
    plan: Plan
    assumptions: Assumptions

    def as_dict(self, include_path: bool = False) -> dict:
        data = {
            "scenario": self.scenario,
            "engine_version": ENGINE_VERSION,
            "inputs_fingerprint": self.inputs_fingerprint,
            "final_nominal": str(round_brl(self.final_nominal)),
            "final_real_todays_money": str(round_brl(self.final_real)),
            "total_contributed": str(round_brl(self.total_contributed)),
            "total_withdrawn": str(round_brl(self.total_withdrawn)),
            "market_result": str(round_brl(self.market_result)),
            "plan": self.plan.as_dict(),
            "assumptions": self.assumptions.as_dict(),
            "limitations": list(LIMITATIONS),
        }
        if include_path:
            data["path"] = [[m, str(round_brl(n)), str(round_brl(r))] for m, n, r in self.path]
        return data


def _canonical(value):
    """Representação estável: '0', '0.00' e '0E+2' viram o mesmo texto."""
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except ArithmeticError:
            return value
        return format(number.normalize(), "f") if number.is_finite() else value
    return value


def fingerprint(plan: Plan, assumptions: Assumptions) -> str:
    payload = _canonical({"engine_version": ENGINE_VERSION, "plan": plan.as_dict(), "assumptions": assumptions.as_dict()})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def future_value(initial, contribution, monthly_rate, months: int) -> Decimal:
    """Fórmula fechada: FV = P(1+r)^n + A[((1+r)^n - 1)/r]; para r = 0, FV = P + A·n."""
    p, a, r = to_decimal(initial), to_decimal(contribution), to_decimal(monthly_rate)
    if months < 0:
        raise ValueError("Horizonte negativo.")
    with localcontext(CALC_CONTEXT):
        if r == 0:
            return p + a * months
        growth = (ONE + r) ** months
        return p * growth + a * (growth - ONE) / r


def simulate(plan: Plan, assumptions: Assumptions) -> Projection:
    r = assumptions.net_monthly_return
    growth = to_decimal(plan.contribution_annual_increase)
    withdrawals = {}
    for month, value in plan.withdrawals:
        withdrawals[month] = withdrawals.get(month, ZERO) + value

    balance = plan.initial
    contributed = withdrawn = ZERO
    path = [(0, balance, balance)]
    with localcontext(CALC_CONTEXT):
        for month in range(1, plan.months + 1):
            balance += balance * r
            if month not in plan.paused_months:
                year_index = (month - 1) // 12
                contribution = plan.monthly_contribution * (ONE + growth) ** year_index
                balance += contribution
                contributed += contribution
            if month in withdrawals:
                amount = withdrawals[month]
                if amount > balance:
                    raise ValueError(f"Resgate de {amount} no mês {month} excede o saldo projetado de {round_brl(balance)}.")
                balance -= amount
                withdrawn += amount
            path.append((month, balance, balance / deflator(assumptions.annual_inflation, month)))

    final_real = path[-1][2]
    return Projection(
        scenario=assumptions.name,
        final_nominal=balance,
        final_real=final_real,
        total_contributed=contributed,
        total_withdrawn=withdrawn,
        market_result=balance - plan.initial - contributed + withdrawn,
        path=tuple(path),
        inputs_fingerprint=fingerprint(plan, assumptions),
        plan=plan,
        assumptions=assumptions,
    )


def compare_scenarios(plan: Plan, scenarios) -> list:
    return [simulate(plan, a) for a in scenarios]


def required_monthly_contribution(target, initial, monthly_rate, months: int) -> Decimal:
    """Meta reversa: aporte constante de fim de mês para atingir `target`. Arredonda para cima (centavo)."""
    fv, p, r = to_decimal(target), to_decimal(initial), to_decimal(monthly_rate)
    if months <= 0:
        raise ValueError("Horizonte precisa ser de pelo menos 1 mês.")
    with localcontext(CALC_CONTEXT):
        if r == 0:
            needed = (fv - p) / months
        else:
            growth = (ONE + r) ** months
            needed = (fv - p * growth) * r / (growth - ONE)
    if needed <= 0:
        return ZERO
    return needed.quantize(CENT, rounding=ROUND_CEILING)


def required_contribution_for_real_goal(target_real, initial, months: int, assumptions: Assumptions) -> Decimal:
    """Aporte mensal, em dinheiro de hoje, para uma meta em poder de compra atual.

    Premissa: o aporte é reajustado pela inflação do cenário todo mês, então o
    cálculo usa a taxa real líquida de taxas.
    """
    real_monthly = annual_to_monthly(assumptions.real_annual_return)
    return required_monthly_contribution(target_real, initial, real_monthly, months)
