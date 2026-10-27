# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diagnóstico de orçamento, reserva e dívidas, e o módulo "o que fazer com meu dinheiro este mês?".

As regras de prioridade são determinísticas e explícitas. Elas montam um CENÁRIO
para o usuário avaliar; não são ordem de compra nem recomendação profissional.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, localcontext

from .money import CALC_CONTEXT, format_brl, format_pct, round_brl, to_decimal
from .rates import annual_to_monthly

ZERO = Decimal(0)

UNDERSTANDING_CHECKLIST = (
    "Você sabe quando poderá resgatar esse dinheiro?",
    "Esse valor pode perder valor? Em que situação?",
    "Quais taxas ou impostos incidem?",
    "Esse dinheiro vai fazer falta nos próximos meses?",
)


@dataclass(frozen=True)
class Debt:
    name: str
    balance: Decimal
    monthly_rate: Decimal  # CET mensal informado pelo usuário
    monthly_payment: Decimal

    def __post_init__(self):
        for attr in ("balance", "monthly_rate", "monthly_payment"):
            object.__setattr__(self, attr, to_decimal(getattr(self, attr)))


@dataclass(frozen=True)
class FinancialSnapshot:
    net_monthly_income: Decimal
    essential_expenses: Decimal
    variable_expenses: Decimal
    liquid_reserve: Decimal
    available_this_month: Decimal
    debts: tuple = ()
    as_of: str = ""

    def __post_init__(self):
        for attr in ("net_monthly_income", "essential_expenses", "variable_expenses", "liquid_reserve", "available_this_month"):
            object.__setattr__(self, attr, to_decimal(getattr(self, attr)))
        object.__setattr__(self, "debts", tuple(self.debts))


@dataclass(frozen=True)
class ReserveStatus:
    target_months: int
    target_amount: Decimal
    current: Decimal
    coverage_months: Decimal | None
    gap: Decimal

    @property
    def complete(self) -> bool:
        return self.gap == 0


@dataclass(frozen=True)
class AllocationLine:
    purpose: str
    amount: Decimal
    percent: Decimal
    rationale: str


@dataclass(frozen=True)
class Guidance:
    stage: str
    next_step: str
    situation: tuple
    allocation: tuple
    comparisons: tuple
    premises: tuple
    missing_information: tuple
    checklist: tuple = UNDERSTANDING_CHECKLIST
    follow_up: str = ""
    disclaimer: str = (
        "Cenário educativo calculado a partir dos dados informados. Não é ordem, "
        "não garante resultado e não substitui consultoria autorizada. A decisão é sua."
    )
    notes: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "next_step": self.next_step,
            "situation": list(self.situation),
            "allocation": [
                {"purpose": a.purpose, "amount": str(round_brl(a.amount)), "percent": str(a.percent), "rationale": a.rationale}
                for a in self.allocation
            ],
            "comparisons": list(self.comparisons),
            "premises": list(self.premises),
            "missing_information": list(self.missing_information),
            "checklist": list(self.checklist),
            "follow_up": self.follow_up,
            "disclaimer": self.disclaimer,
            "notes": list(self.notes),
        }


def free_cash_flow(s: FinancialSnapshot) -> Decimal:
    payments = sum((d.monthly_payment for d in s.debts), ZERO)
    return s.net_monthly_income - s.essential_expenses - s.variable_expenses - payments


def debt_commitment_ratio(s: FinancialSnapshot) -> Decimal | None:
    if s.net_monthly_income <= 0:
        return None
    payments = sum((d.monthly_payment for d in s.debts), ZERO)
    with localcontext(CALC_CONTEXT):
        return payments / s.net_monthly_income


def reserve_status(essential_expenses, liquid_reserve, target_months: int) -> ReserveStatus:
    essential, current = to_decimal(essential_expenses), to_decimal(liquid_reserve)
    if target_months <= 0:
        raise ValueError("Meta de reserva precisa ser de pelo menos 1 mês.")
    target = essential * target_months
    with localcontext(CALC_CONTEXT):
        coverage = (current / essential).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if essential > 0 else None
    return ReserveStatus(target_months, target, current, coverage, max(target - current, ZERO))


def expensive_debts(debts, reference_monthly_rate) -> list:
    """Dívidas cujo custo mensal supera o retorno de referência, da mais cara para a mais barata."""
    ref = to_decimal(reference_monthly_rate)
    return sorted((d for d in debts if d.balance > 0 and d.monthly_rate > ref), key=lambda d: d.monthly_rate, reverse=True)


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        return ZERO
    return (part * 100 / whole).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def monthly_guidance(s: FinancialSnapshot, *, reserve_target_months: int, reference_annual_return) -> Guidance:
    """Próximo passo do mês, seguindo a escada: orçamento → dívida cara → reserva → metas.

    `reference_annual_return` é uma PREMISSA do usuário (retorno que uma aplicação de
    liquidez diária poderia render), usada só para comparar com o custo das dívidas.
    """
    ref_annual = to_decimal(reference_annual_return)
    ref_monthly = annual_to_monthly(ref_annual)
    available = s.available_this_month
    fcf = free_cash_flow(s)
    reserve = reserve_status(s.essential_expenses, s.liquid_reserve, reserve_target_months)
    costly = expensive_debts(s.debts, ref_monthly)

    premises = (
        f"Retorno de referência informado para comparação: {format_pct(ref_annual)} ao ano "
        f"({format_pct(ref_monthly, 3)} ao mês). É hipótese, não oferta verificada.",
        f"Meta de reserva: {reserve_target_months} meses de despesas essenciais.",
        "Prioridade adotada: cobrir o orçamento, depois dívidas mais caras que o retorno de referência, "
        "depois reserva, depois metas de investimento.",
    )
    missing = []
    if not s.as_of:
        missing.append("Data de referência dos dados informados.")
    if s.net_monthly_income <= 0:
        missing.append("Renda líquida mensal.")
    if s.essential_expenses <= 0:
        missing.append("Despesas essenciais mensais (necessárias para dimensionar a reserva).")

    coverage = "não calculável" if reserve.coverage_months is None else f"{reserve.coverage_months} meses".replace(".", ",")
    situation = [
        f"Sobra mensal estimada após despesas e parcelas: {format_brl(fcf)}.",
        f"Reserva líquida de {format_brl(reserve.current)}, cobrindo {coverage} de despesas essenciais "
        f"(meta: {format_brl(reserve.target_amount)}).",
    ]
    if costly:
        situation.append(
            f"{len(costly)} dívida(s) custam mais que o retorno de referência; a mais cara é "
            f"{costly[0].name} a {format_pct(costly[0].monthly_rate)} ao mês."
        )
    elif s.debts:
        situation.append("Nenhuma dívida informada custa mais que o retorno de referência.")
    else:
        situation.append("Nenhuma dívida informada.")

    allocation, comparisons = [], []

    if available <= 0:
        return Guidance(
            stage="sem_recurso_disponivel",
            next_step="Não investir este mês. O próximo passo é revisar o orçamento para identificar uma sobra possível, sem culpa: meses apertados acontecem.",
            situation=tuple(situation),
            allocation=(),
            comparisons=(),
            premises=premises,
            missing_information=tuple(missing),
            follow_up="Voltar à análise quando receber o próximo salário.",
        )

    if fcf < 0:
        return Guidance(
            stage="organizar_orcamento",
            next_step=(
                f"Não investir ainda: o orçamento mensal está negativo em {format_brl(-fcf)}. "
                "O valor disponível deve primeiro cobrir as contas essenciais do mês."
            ),
            situation=tuple(situation),
            allocation=(AllocationLine("Cobrir despesas essenciais / déficit do mês", available, Decimal(100),
                                       "Evita atraso de contas e novas dívidas."),),
            comparisons=(),
            premises=premises,
            missing_information=tuple(missing),
            follow_up="Revisar despesas variáveis juntos antes do próximo mês.",
        )

    remaining = available
    with localcontext(CALC_CONTEXT):
        for debt in costly:
            if remaining <= 0:
                break
            amount = min(remaining, debt.balance)
            remaining -= amount
            allocation.append(AllocationLine(
                f"Amortizar {debt.name}", amount, _pct(amount, available),
                f"Custo de {format_pct(debt.monthly_rate)} ao mês, acima do retorno de referência.",
            ))
            comparisons.append(
                f"Amortizar {format_brl(amount)} de {debt.name} evita cerca de {format_brl(amount * debt.monthly_rate)} "
                f"de juros no próximo mês; aplicar o mesmo valor ao retorno de referência renderia cerca de "
                f"{format_brl(amount * ref_monthly)}, antes de impostos."
            )
        if remaining > 0 and not reserve.complete:
            amount = min(remaining, reserve.gap)
            remaining -= amount
            allocation.append(AllocationLine(
                "Reserva de emergência (liquidez diária)", amount, _pct(amount, available),
                f"Faltam {format_brl(reserve.gap)} para a meta de reserva.",
            ))
        if remaining > 0:
            allocation.append(AllocationLine(
                "Investimento para metas", remaining, _pct(remaining, available),
                "Orçamento positivo, sem dívida cara e reserva completa.",
            ))

    if costly:
        stage_name = "priorizar_divida"
    elif not reserve.complete:
        stage_name = "construir_reserva"
    else:
        stage_name = "investir_para_metas"
    next_steps = {
        "priorizar_divida": f"Priorizar a dívida mais cara ({costly[0].name}) antes de buscar rendimento." if costly else "",
        "construir_reserva": "Começar ou completar a reserva de emergência em aplicação de liquidez diária, sem perseguir o maior rendimento.",
        "investir_para_metas": "Estudar alternativas de investimento compatíveis com o prazo de cada meta.",
    }
    notes = ()
    if stage_name in ("construir_reserva", "investir_para_metas"):
        notes = ("Produtos específicos só serão comparados com taxas, garantias e fontes verificadas na data da análise (Fase 3).",)
    return Guidance(
        stage=stage_name,
        next_step=next_steps[stage_name],
        situation=tuple(situation),
        allocation=tuple(allocation),
        comparisons=tuple(comparisons),
        premises=premises,
        missing_information=tuple(missing),
        follow_up="Registrar o que foi efetivamente feito (plano ≠ aporte confirmado) e revisar no próximo salário.",
        notes=notes,
    )
