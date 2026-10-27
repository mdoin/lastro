"""Calculadora determinística compartilhada por todos os agentes.

Uma única porta de entrada (`calculate(operation, params)`) para as contas que os agentes precisam fazer:
juros, aportes, inflação, valor presente/futuro, taxa real, amortização, metas, comparação de rendimentos
líquidos e métricas de risco. O modelo de IA nunca faz conta de cabeça: chama esta função (pela ferramenta
`calcular`) e cita o resultado. O mesmo código roda no Auditor, que refaz cada cálculo a partir das entradas.

Regras:
- tudo em Decimal; float é recusado (`to_decimal`);
- taxas em fração decimal ("0.01" = 1% no período);
- cada resultado diz se é CÁLCULO (consequência aritmética das entradas) ou PROJEÇÃO HIPOTÉTICA
  (depende de premissas sobre o futuro), e traz a impressão digital das entradas;
- tributos só entram como premissa explícita (`tax_rate`), nunca por tabela embutida (ver DECISIONS.md).
"""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, localcontext

from . import ENGINE_VERSION
from .money import CALC_CONTEXT, CENT, round_brl, to_decimal
from .projection import Assumptions, Plan, future_value, required_monthly_contribution, simulate
from .rates import annual_to_monthly, monthly_to_annual, real_rate

ZERO, ONE = Decimal(0), Decimal(1)
MAX_PERIODS = 1200
MAX_SERIES = 600
MAX_ITEMS = 20
RATE_PLACES = Decimal("0.00000001")

CALCULO = "calculo"
PROJECAO = "projecao_hipotetica"


class CalculationError(ValueError):
    """Entrada inválida para a calculadora (mensagem em português, segura para o modelo)."""


def _rate(value, field: str) -> Decimal:
    rate = _num(value, field)
    if rate <= -1:
        raise CalculationError(f"{field}: taxa precisa ser maior que -100%.")
    return rate


def _num(value, field: str) -> Decimal:
    try:
        return to_decimal(value)
    except (TypeError, ValueError) as exc:
        raise CalculationError(f"{field}: número inválido (use texto com ponto decimal, ex.: \"150.00\").") from exc


def _money_in(value, field: str, *, allow_negative: bool = False) -> Decimal:
    number = _num(value, field)
    if number < 0 and not allow_negative:
        raise CalculationError(f"{field}: não pode ser negativo.")
    return number


def _periods(value, field: str = "periods", minimum: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise CalculationError(f"{field}: inteiro obrigatório.") from exc
    if isinstance(value, bool) or not minimum <= n <= MAX_PERIODS:
        raise CalculationError(f"{field}: de {minimum} a {MAX_PERIODS}.")
    return n


def _series(values, field: str, minimum: int = 1) -> list[Decimal]:
    if not isinstance(values, list) or not minimum <= len(values) <= MAX_SERIES:
        raise CalculationError(f"{field}: lista com {minimum} a {MAX_SERIES} números.")
    return [_num(v, f"{field}[{i}]") for i, v in enumerate(values)]


def _brl(value: Decimal) -> str:
    return str(round_brl(value))


def _pct(value: Decimal) -> str:
    return str(value.quantize(RATE_PLACES, rounding=ROUND_HALF_UP))


# ---------- operações ----------

def juros_simples(p: dict) -> tuple[dict, str, list]:
    principal, rate, n = _money_in(p.get("principal"), "principal"), _rate(p.get("rate"), "rate"), _periods(p.get("periods"))
    with localcontext(CALC_CONTEXT):
        interest = principal * rate * n
    return {"juros": _brl(interest), "montante": _brl(principal + interest)}, CALCULO, []


def juros_compostos(p: dict) -> tuple[dict, str, list]:
    principal, rate, n = _money_in(p.get("principal"), "principal"), _rate(p.get("rate"), "rate"), _periods(p.get("periods"))
    with localcontext(CALC_CONTEXT):
        amount = principal * (ONE + rate) ** n
    return {"montante": _brl(amount), "juros": _brl(amount - principal),
            "fator": _pct((ONE + rate) ** n)}, CALCULO, []


def valor_futuro(p: dict) -> tuple[dict, str, list]:
    initial = _money_in(p.get("initial", "0"), "initial")
    contribution = _money_in(p.get("contribution", "0"), "contribution")
    rate, n = _rate(p.get("rate"), "rate"), _periods(p.get("periods"))
    timing = p.get("timing", "fim")
    if timing not in ("fim", "inicio"):
        raise CalculationError("timing: use \"fim\" (aporte no fim do período) ou \"inicio\".")
    with localcontext(CALC_CONTEXT):
        fv = future_value(initial, contribution, rate, n)
        if timing == "inicio" and rate != 0:
            fv = initial * (ONE + rate) ** n + (fv - initial * (ONE + rate) ** n) * (ONE + rate)
    contributed = contribution * n
    return {"valor_futuro": _brl(fv), "total_aportado": _brl(initial + contributed),
            "rendimento": _brl(fv - initial - contributed)}, PROJECAO, [
        "Taxa constante em todos os períodos: é premissa, não previsão."]


def valor_presente(p: dict) -> tuple[dict, str, list]:
    rate, n = _rate(p.get("rate"), "rate"), _periods(p.get("periods"))
    future = _money_in(p.get("future_value", "0"), "future_value")
    payment = _money_in(p.get("payment", "0"), "payment")
    with localcontext(CALC_CONTEXT):
        growth = (ONE + rate) ** n
        pv_lump = future / growth
        pv_annuity = payment * n if rate == 0 else payment * (ONE - ONE / growth) / rate
    return {"valor_presente": _brl(pv_lump + pv_annuity), "vp_do_valor_futuro": _brl(pv_lump),
            "vp_dos_pagamentos": _brl(pv_annuity)}, CALCULO, []


def inflacao_acumulada(p: dict) -> tuple[dict, str, list]:
    rates = [_rate(r, "rates") for r in _series(p.get("rates"), "rates")]
    with localcontext(CALC_CONTEXT):
        factor = ONE
        for r in rates:
            factor *= ONE + r
    notes = []
    amount = p.get("amount")
    result = {"inflacao_acumulada": _pct(factor - ONE), "fator": _pct(factor), "periodos": len(rates)}
    if amount not in (None, ""):
        value = _money_in(amount, "amount")
        result["valor_corrigido"] = _brl(value * factor)
        result["poder_de_compra_de_hoje"] = _brl(value / factor)
    return result, CALCULO, notes


def taxa_real(p: dict) -> tuple[dict, str, list]:
    nominal, inflation = _rate(p.get("nominal"), "nominal"), _rate(p.get("inflation"), "inflation")
    return {"taxa_real": _pct(real_rate(nominal, inflation))}, CALCULO, [
        "Equação de Fisher: (1 + nominal) / (1 + inflação) - 1. Não é a subtração simples."]


def converter_taxa(p: dict) -> tuple[dict, str, list]:
    rate = _rate(p.get("rate"), "rate")
    direction = p.get("from")
    if direction == "anual":
        return {"mensal": _pct(annual_to_monthly(rate)), "anual": _pct(rate)}, CALCULO, []
    if direction == "mensal":
        return {"mensal": _pct(rate), "anual": _pct(monthly_to_annual(rate))}, CALCULO, []
    raise CalculationError("from: use \"anual\" ou \"mensal\".")


def amortizacao(p: dict) -> tuple[dict, str, list]:
    principal = _money_in(p.get("principal"), "principal")
    rate, n = _rate(p.get("monthly_rate"), "monthly_rate"), _periods(p.get("months"), "months", minimum=1)
    system = p.get("system", "price")
    rows = []
    balance = principal
    with localcontext(CALC_CONTEXT):
        if system == "price":
            payment = principal / n if rate == 0 else principal * rate / (ONE - (ONE + rate) ** -n)
            for month in range(1, n + 1):
                interest = balance * rate
                amort = payment - interest
                balance -= amort
                rows.append((month, payment, interest, amort, max(balance, ZERO)))
        elif system == "sac":
            amort = principal / n
            for month in range(1, n + 1):
                interest = balance * rate
                balance -= amort
                rows.append((month, amort + interest, interest, amort, max(balance, ZERO)))
        else:
            raise CalculationError("system: use \"price\" ou \"sac\".")
    total_paid = sum((r[1] for r in rows), ZERO)
    total_interest = sum((r[2] for r in rows), ZERO)
    shown = rows if n <= 24 else rows[:12] + rows[-12:]
    return {"sistema": system, "primeira_parcela": _brl(rows[0][1]), "ultima_parcela": _brl(rows[-1][1]),
            "total_pago": _brl(total_paid), "total_juros": _brl(total_interest),
            "tabela": [{"mes": m, "parcela": _brl(pay), "juros": _brl(i), "amortizacao": _brl(a), "saldo": _brl(b)}
                       for m, pay, i, a, b in shown],
            "tabela_resumida": n > 24}, CALCULO, ["Taxa mensal constante; não inclui seguros, tarifas ou IOF."]


def aporte_para_meta(p: dict) -> tuple[dict, str, list]:
    target = _money_in(p.get("target"), "target")
    initial = _money_in(p.get("initial", "0"), "initial")
    rate, n = _rate(p.get("monthly_rate"), "monthly_rate"), _periods(p.get("months"), "months", minimum=1)
    needed = required_monthly_contribution(target, initial, rate, n)
    return {"aporte_mensal": _brl(needed), "total_aportado": _brl(initial + needed * n)}, PROJECAO, [
        "Aporte constante no fim de cada mês e taxa constante: premissas, não garantias."]


def meses_para_meta(p: dict) -> tuple[dict, str, list]:
    target = _money_in(p.get("target"), "target")
    initial = _money_in(p.get("initial", "0"), "initial")
    contribution = _money_in(p.get("contribution", "0"), "contribution")
    rate = _rate(p.get("monthly_rate"), "monthly_rate")
    if initial >= target:
        return {"meses": 0, "atingivel": True}, PROJECAO, []
    balance = initial
    with localcontext(CALC_CONTEXT):
        for month in range(1, MAX_PERIODS + 1):
            balance = balance * (ONE + rate) + contribution
            if balance >= target:
                return {"meses": month, "anos": str((Decimal(month) / 12).quantize(Decimal("0.1"))),
                        "saldo_no_mes": _brl(balance), "atingivel": True}, PROJECAO, [
                    "Simulação mês a mês com taxa e aporte constantes."]
    return {"meses": None, "atingivel": False}, PROJECAO, [f"Não atinge a meta em {MAX_PERIODS} meses com essas premissas."]


def projecao_hipotetica(p: dict) -> tuple[dict, str, list]:
    try:
        plan = Plan(initial=_money_in(p.get("initial", "0"), "initial"),
                    monthly_contribution=_money_in(p.get("contribution", "0"), "contribution"),
                    months=_periods(p.get("months"), "months"),
                    contribution_annual_increase=_num(p.get("contribution_annual_increase", "0"),
                                                      "contribution_annual_increase"))
        assumptions = Assumptions(name=str(p.get("scenario", "hipotético"))[:40],
                                  annual_return=_rate(p.get("annual_return"), "annual_return"),
                                  annual_inflation=_rate(p.get("annual_inflation", "0"), "annual_inflation"),
                                  annual_fee=_num(p.get("annual_fee", "0"), "annual_fee"))
        projection = simulate(plan, assumptions)
    except CalculationError:
        raise
    except ValueError as exc:
        raise CalculationError(str(exc)) from exc
    data = projection.as_dict()
    return {k: data[k] for k in ("final_nominal", "final_real_todays_money", "total_contributed", "market_result",
                                 "inputs_fingerprint")}, PROJECAO, list(data["limitations"])


def comparar_rendimentos(p: dict) -> tuple[dict, str, list]:
    amount = _money_in(p.get("amount"), "amount")
    months = _periods(p.get("months"), "months", minimum=1)
    inflation = p.get("annual_inflation")
    alternatives = p.get("alternatives")
    if not isinstance(alternatives, list) or not 1 <= len(alternatives) <= MAX_ITEMS:
        raise CalculationError(f"alternatives: lista com 1 a {MAX_ITEMS} itens.")
    out = []
    with localcontext(CALC_CONTEXT):
        years = Decimal(months) / 12
        deflate = ONE if inflation in (None, "") else (ONE + _rate(inflation, "annual_inflation")) ** years
        for i, alt in enumerate(alternatives):
            name = str(alt.get("name") or f"alternativa {i + 1}")[:60]
            gross_rate = _rate(alt.get("annual_rate"), f"alternatives[{i}].annual_rate")
            fee = _num(alt.get("annual_fee", "0"), f"alternatives[{i}].annual_fee")
            tax = _num(alt.get("tax_rate", "0"), f"alternatives[{i}].tax_rate")
            if not ZERO <= fee < ONE or not ZERO <= tax < ONE:
                raise CalculationError(f"alternatives[{i}]: annual_fee e tax_rate entre 0 e 1.")
            gross = amount * (ONE + gross_rate) ** years
            after_fee = amount * ((ONE + gross_rate) * (ONE - fee)) ** years
            gain = after_fee - amount
            taxes = gain * tax if gain > 0 else ZERO
            net = after_fee - taxes
            out.append({"nome": name, "bruto": _brl(gross), "custos_taxa": _brl(gross - after_fee),
                        "impostos_premissa": _brl(taxes), "liquido": _brl(net),
                        "liquido_em_dinheiro_de_hoje": _brl(net / deflate),
                        "rentabilidade_liquida_no_periodo": _pct(net / amount - ONE if amount else ZERO)})
    ranking = sorted(out, key=lambda a: Decimal(a["liquido"]), reverse=True)
    return {"alternativas": out, "ordem_por_liquido": [a["nome"] for a in ranking]}, PROJECAO, [
        "Taxas constantes informadas como premissa; imposto aplicado sobre o ganho no resgate, à alíquota informada.",
        "Não considera risco de crédito, liquidez, marcação a mercado nem garantias (FGC): compare também esses pontos."]


def metricas_risco(p: dict) -> tuple[dict, str, list]:
    returns = _series(p.get("returns"), "returns", minimum=2)
    per_year = _periods(p.get("periods_per_year", 12), "periods_per_year", minimum=1)
    with localcontext(CALC_CONTEXT):
        n = Decimal(len(returns))
        mean = sum(returns, ZERO) / n
        variance = sum(((r - mean) ** 2 for r in returns), ZERO) / (n - 1)
        vol = variance.sqrt()
        level, peak, max_dd = ONE, ONE, ZERO
        for r in returns:
            level *= ONE + r
            peak = max(peak, level)
            max_dd = min(max_dd, level / peak - ONE)
        cumulative = level - ONE
    return {"retorno_medio_periodo": _pct(mean), "volatilidade_periodo": _pct(vol),
            "volatilidade_anualizada": _pct(vol * Decimal(per_year).sqrt()),
            "drawdown_maximo": _pct(max_dd), "pior_periodo": _pct(min(returns)),
            "retorno_acumulado": _pct(cumulative), "observacoes": len(returns)}, CALCULO, [
        "Métricas do histórico informado; o passado não garante o futuro.",
        "Volatilidade anualizada pela raiz do número de períodos por ano (supõe retornos independentes)."]


def correlacao(p: dict) -> tuple[dict, str, list]:
    a, b = _series(p.get("series_a"), "series_a", minimum=3), _series(p.get("series_b"), "series_b", minimum=3)
    if len(a) != len(b):
        raise CalculationError("series_a e series_b precisam ter o mesmo tamanho.")
    with localcontext(CALC_CONTEXT):
        n = Decimal(len(a))
        ma, mb = sum(a, ZERO) / n, sum(b, ZERO) / n
        cov = sum(((x - ma) * (y - mb) for x, y in zip(a, b)), ZERO)
        sa = sum(((x - ma) ** 2 for x in a), ZERO).sqrt()
        sb = sum(((y - mb) ** 2 for y in b), ZERO).sqrt()
        if sa == 0 or sb == 0:
            raise CalculationError("Série constante: correlação indefinida.")
        rho = cov / (sa * sb)
    return {"correlacao": str(rho.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))}, CALCULO, [
        "Correlação de Pearson do histórico informado; muda com o tempo e costuma subir em crises."]


def concentracao(p: dict) -> tuple[dict, str, list]:
    positions = p.get("positions")
    if not isinstance(positions, list) or not 1 <= len(positions) <= MAX_SERIES:
        raise CalculationError(f"positions: lista com 1 a {MAX_SERIES} itens {{name, value}}.")
    values = [(str(x.get("name") or f"item {i + 1}")[:60], _money_in(x.get("value"), f"positions[{i}].value"))
              for i, x in enumerate(positions)]
    total = sum((v for _, v in values), ZERO)
    if total <= 0:
        raise CalculationError("positions: total precisa ser positivo.")
    with localcontext(CALC_CONTEXT):
        shares = [(name, v / total) for name, v in values]
        hhi = sum((s ** 2 for _, s in shares), ZERO)
    largest = max(shares, key=lambda s: s[1])
    return {"total": _brl(total), "participacoes": [{"nome": n, "participacao": _pct(s)} for n, s in shares],
            "maior_posicao": {"nome": largest[0], "participacao": _pct(largest[1])},
            "hhi": _pct(hhi), "numero_efetivo_de_posicoes": str((ONE / hhi).quantize(Decimal("0.01")))}, CALCULO, [
        "HHI (soma dos quadrados das participações): perto de 1 = concentrado; 1/HHI = nº efetivo de posições."]


def cenario_estresse(p: dict) -> tuple[dict, str, list]:
    positions = p.get("positions")
    if not isinstance(positions, list) or not 1 <= len(positions) <= MAX_ITEMS:
        raise CalculationError(f"positions: lista com 1 a {MAX_ITEMS} itens {{name, value, shock}}.")
    rows, before, after = [], ZERO, ZERO
    with localcontext(CALC_CONTEXT):
        for i, x in enumerate(positions):
            value = _money_in(x.get("value"), f"positions[{i}].value")
            shock = _num(x.get("shock", "0"), f"positions[{i}].shock")
            if shock < -1:
                raise CalculationError(f"positions[{i}].shock: no mínimo -1 (perda total).")
            new = value * (ONE + shock)
            before, after = before + value, after + new
            rows.append({"nome": str(x.get("name") or f"item {i + 1}")[:60], "antes": _brl(value), "depois": _brl(new),
                         "variacao": _brl(new - value)})
    return {"posicoes": rows, "total_antes": _brl(before), "total_depois": _brl(after), "perda": _brl(before - after),
            "variacao_percentual": _pct(after / before - ONE if before else ZERO)}, PROJECAO, [
        "Choques informados como hipótese de estresse, não previsão."]


OPERATIONS = {
    "juros_simples": juros_simples, "juros_compostos": juros_compostos, "valor_futuro": valor_futuro,
    "valor_presente": valor_presente, "inflacao_acumulada": inflacao_acumulada, "taxa_real": taxa_real,
    "converter_taxa": converter_taxa, "amortizacao": amortizacao, "aporte_para_meta": aporte_para_meta,
    "meses_para_meta": meses_para_meta, "projecao_hipotetica": projecao_hipotetica,
    "comparar_rendimentos": comparar_rendimentos, "metricas_risco": metricas_risco, "correlacao": correlacao,
    "concentracao": concentracao, "cenario_estresse": cenario_estresse,
}


def _canonical(value):
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return str(value)


def calculate(operation: str, params: dict) -> dict:
    """Executa uma operação. Erros de entrada viram `CalculationError` com mensagem clara."""
    fn = OPERATIONS.get(operation)
    if fn is None:
        raise CalculationError(f"Operação desconhecida: {str(operation)[:40]}. Use uma de: {', '.join(OPERATIONS)}.")
    if not isinstance(params, dict):
        raise CalculationError("params precisa ser um objeto.")
    result, nature, notes = fn(params)
    inputs = _canonical(params)
    digest = hashlib.sha256(json.dumps({"op": operation, "in": inputs, "v": ENGINE_VERSION}, sort_keys=True,
                                       ensure_ascii=False).encode()).hexdigest()
    return {"operacao": operation, "natureza": nature, "engine_version": ENGINE_VERSION, "entradas": inputs,
            "resultado": result, "observacoes": notes, "fingerprint": digest[:16]}


def numbers_in(value) -> list[Decimal]:
    """Todos os números de um resultado (usado pelo Auditor como evidência)."""
    found: list[Decimal] = []
    if isinstance(value, dict):
        for v in value.values():
            found.extend(numbers_in(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(numbers_in(v))
    elif isinstance(value, (str, int)) and not isinstance(value, bool):
        try:
            found.append(to_decimal(value))
        except (TypeError, ValueError):
            pass
    return found


__all__ = ["CENT", "CalculationError", "OPERATIONS", "calculate", "numbers_in"]
