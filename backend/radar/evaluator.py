"""Avaliação determinística de um sinal: qualidade dos dados, adequação ao perfil, custos, score e hipótese.

O score é uma soma ponderada de três critérios documentados (docs/RADAR.md §Classificação). Ele ordena sinais
para investigação; NÃO é probabilidade de lucro e nunca aparece como tal.
"""

from datetime import date
from decimal import Decimal

from financial_engine.money import to_decimal

from .observations import Point, validity

FRAGILE_STAGES = ("priorizar_divida", "organizar_orcamento", "sem_recurso_disponivel")
INVESTMENT_CATEGORIES = ("renda_fixa", "acoes", "etf", "fii")
WEIGHTS = {"magnitude": Decimal("0.4"), "qualidade": Decimal("0.3"), "adequacao": Decimal("0.3")}
# Custódia da B3 no Tesouro Direto (premissa documentada; a isenção do Tesouro Selic até R$ 10 mil não é aplicada).
TD_CUSTODY_ANNUAL = Decimal("0.0020")
ANALYSIS_MIN_CLASS = 3
MAX_SPECIALISTS = 3
AGENTS_BY_CATEGORY = {
    "renda_fixa": ("analista", "economista", "riscos"),
    "acoes": ("analista", "riscos", "comportamental"),
    "etf": ("analista", "riscos", "comportamental"),
    "fii": ("analista", "riscos", "comportamental"),
    "macro": ("economista", "riscos"),
    "patrimonio": ("planejador", "riscos"),
}
LIMITATIONS_ALWAYS = ("Dados de fontes públicas com atraso: não são cotações em tempo real.",
                      "O Radar não executa operações: o sinal é uma hipótese para investigar, não uma ordem.")


def data_quality(meta: dict | None, point: Point | None, today: date) -> dict:
    if meta is None or point is None:
        return {"score": Decimal(0), "status": "indisponivel", "issues": ["Sem observação para a série."]}
    status, issues, score = validity(meta, point.reference_date, today), [], Decimal(1)
    if status == "desatualizado":
        score, issues = Decimal("0.5"), [f"Último dado de {point.reference_date}: mais antigo que o limite de "
                                        f"{meta['max_age_days']} dias para esta série."]
    if point.quality == "suspeito":
        score = min(score, Decimal("0.5"))
        issues.append("Valor diverge da outra fonte que mede a mesma coisa: confira antes de usar.")
    if point.quality == "revisado":
        issues.append(f"A fonte revisou este valor (revisão {point.revision}).")
    return {"score": score, "status": status, "issues": issues, "reference_date": point.reference_date,
            "fetched_at": point.fetched_at, "revision": point.revision, "quality": point.quality}


def _years_to(maturity: str, today: date) -> Decimal:
    return (Decimal((date.fromisoformat(maturity) - today).days) / Decimal("365.25")).quantize(Decimal("0.1"))


def suitability(profile: dict, category: str, meta: dict | None, today: date) -> dict:
    """Adequação ao momento financeiro da pessoa. `profile` vem de `profile_for` (retrato, diagnóstico, metas)."""
    if category not in INVESTMENT_CATEGORIES:
        return {"status": "nao_se_aplica", "score": Decimal(1), "reasons": []}
    if not profile.get("has_snapshot"):
        return {"status": "desconhecido", "score": Decimal("0.5"),
                "reasons": ["Sem retrato financeiro cadastrado: não dá para avaliar a adequação ao seu momento."]}
    stage, reasons = profile.get("stage"), []
    if stage in FRAGILE_STAGES:
        return {"status": "inadequado_agora", "score": Decimal(0),
                "reasons": [f"Seu diagnóstico indica outra prioridade agora ({profile.get('next_step') or stage}). "
                            "Investir antes disso aumenta o risco do seu orçamento."]}
    status = "adequado"
    maturity = (meta or {}).get("meta", {}).get("vencimento")
    if stage == "construir_reserva" and (meta or {}).get("meta", {}).get("tipo") != "selic":
        status = "condicional"
        reasons.append("A reserva de emergência ainda está incompleta: este ativo oscila (marcação a mercado) e não "
                       "serve como reserva.")
    if maturity:
        years = _years_to(maturity, today)
        goal_years = [g for g in profile.get("goal_years", []) if g < years]
        if goal_years:
            status = "condicional"
            reasons.append(f"O título vence em {years} anos e você tem meta(s) com prazo menor "
                           f"({', '.join(str(g) for g in sorted(goal_years))} anos): resgatar antes do vencimento "
                           "segue o preço de mercado do dia.")
    risk_profile = profile.get("risk_profile")
    if risk_profile and "conserv" in risk_profile.lower() and category in ("acoes", "etf", "fii"):
        status = "condicional"
        reasons.append("Seu perfil de risco confirmado é conservador e este ativo é de renda variável.")
    return {"status": status, "score": Decimal(1) if status == "adequado" else Decimal("0.5"), "reasons": reasons}


def costs(category: str, meta: dict | None) -> dict:
    if (meta or {}).get("source") == "tesouro_direto":
        return {"custodia_anual": str(TD_CUSTODY_ANNUAL),
                "premissas": ["Custódia B3 de 0,20% a.a. pro rata (isenção do Tesouro Selic até R$ 10 mil não aplicada).",
                              "IR regressivo sobre o ganho (Lei 11.033/2004): 22,5% até 180 dias, 20% até 360, 17,5% "
                              "até 720 e 15% acima.",
                              "IOF regressivo sobre o rendimento nos primeiros 30 dias (Decreto 6.306/2007).",
                              "Estimativas para comparação; não substituem o cálculo fiscal oficial."]}
    if category in ("acoes", "etf", "fii"):
        return {"premissas": ["Custos de corretagem, emolumentos e impostos não informados: não descontados.",
                              "IR em renda variável depende do seu volume mensal de vendas: não estimado."]}
    return {"premissas": []}


def classify(rule: dict, magnitude: Decimal, quality: dict, suit: dict) -> dict:
    """Classificação (1..5) e score explicável, com cada ajuste justificado."""
    parts = {"magnitude": magnitude, "qualidade": quality["score"], "adequacao": suit["score"]}
    score = sum((WEIGHTS[k] * v for k, v in parts.items()), Decimal(0)).quantize(Decimal("0.01"))
    level, reasons = rule["priority"], [f"Prioridade da regra: {rule['priority']}."]
    if level < 5:
        if quality["score"] < 1:
            level = max(level - 1, 1)
            reasons.append("Rebaixado um nível: qualidade dos dados abaixo do ideal.")
        if suit["status"] == "inadequado_agora" and level > 2:
            level = 2
            reasons.append("Limitado a 'em observação': não é adequado ao seu momento financeiro.")
        if rule["kind"] == "queda" and level > 3:
            level = 3
            reasons.append("Queda de preço sozinha não indica oportunidade: limitado a 'potencialmente interessante'.")
        if level == 3 and rule["kind"] != "queda" and magnitude >= 1 and quality["score"] == 1 and                 suit["status"] == "adequado":
            level = 4
            reasons.append("Elevado a 'alta prioridade para avaliação': bem além do limite, dados bons e adequado.")
    return {"classification": level, "score": str(score),
            "score_breakdown": {k: {"valor": str(v), "peso": str(WEIGHTS[k])} for k, v in parts.items()},
            "reasons": reasons}


def hypothesis(rule: dict, meta: dict | None, values: dict) -> dict:
    """Hipótese verificável registrada ANTES de qualquer resultado, com critério e mecanismo explícitos."""
    category, kind = rule["category"], rule["kind"]
    label = (meta or {}).get("label", "série")
    excess = {"metrica": "excesso_vs_cdi_pp", "operador": ">=", "valor": "0", "banda_inconclusiva_pp": "0.10"}
    if (meta or {}).get("source") == "tesouro_direto" and meta["meta"].get("metrica") == "taxa_compra":
        return {"metodo": "td_marcacao", "benchmark": "cdi", "criterio": excess,
                "mecanismo": {"metrica": "variacao_taxa_pp", "operador": "<", "valor": "0",
                              "descricao": "queda posterior da taxa (valorização do título)"},
                "texto": (f"Com {label} a {values.get('valor')}% a.a. nesta data, aplicar e resgatar no horizonte (preço "
                          "de recompra do Tesouro) teria retorno líquido estimado igual ou superior ao CDI líquido no "
                          "mesmo período. Mecanismo esperado: queda posterior da taxa; o carregamento da taxa também "
                          "contribui. Invalida: revisão do dado que disparou o sinal."),
                "invalidacao": ["revisão do dado que disparou o sinal"]}
    if category in ("acoes", "etf", "fii"):
        return {"metodo": "preco_total", "benchmark": "cdi", "criterio": excess,
                "mecanismo": {"metrica": "retorno_preco_pct", "operador": ">=", "valor": "0",
                              "descricao": "recuperação do preço (ajustado por eventos corporativos)"},
                "texto": (f"{label}: o retorno total (preço ajustado + proventos) no horizonte supera o CDI acumulado, "
                          "desde que margens, endividamento e geração de caixa se mantenham. Essa premissa de "
                          "fundamentos não é verificável com os dados do Radar e fica registrada como tal."),
                "premissas_nao_verificaveis": ["fundamentos do negócio (margens, dívida, caixa) mantidos"],
                "invalidacao": ["revisão do dado que disparou o sinal", "evento corporativo não informado"]}
    if kind == "reserva":
        return {"metodo": "reserva", "benchmark": None,
                "criterio": {"metrica": "reserva_meses", "operador": "<", "valor": rule["params"]["meses_minimos"]},
                "texto": ("Sem mudança, a reserva continuaria abaixo do mínimo no horizonte (o risco persiste). "
                          "Confirmada = o risco persistiu; não confirmada = a reserva voltou ao mínimo."),
                "invalidacao": []}
    return {"metodo": "serie_macro", "benchmark": None, "criterio": None,
            "texto": f"Sinal informativo: acompanhar a evolução de {label}. Não há hipótese de retorno a verificar.",
            "invalidacao": ["revisão do dado que disparou o sinal"]}


def select_agents(category: str, kind: str, magnitude: Decimal, suit: dict) -> list[str]:
    agents = list(AGENTS_BY_CATEGORY[category])
    if suit["status"] in ("inadequado_agora", "condicional") and "planejador" not in agents:
        agents.insert(1, "planejador")
    if kind in ("variacao", "queda") and magnitude >= 1 and "comportamental" not in agents:
        agents.append("comportamental")
    return agents[:MAX_SPECIALISTS]


def needs_analysis(rule: dict, classification: int, quality: dict) -> tuple[bool, str]:
    if rule["kind"] in ("reserva", "dado_desatualizado"):
        return False, "sinal determinístico: a análise do Conselho não acrescenta informação"
    if classification < ANALYSIS_MIN_CLASS:
        return False, f"classificação {classification} abaixo do mínimo ({ANALYSIS_MIN_CLASS}) para acionar o Conselho"
    if quality["score"] == 0:
        return False, "sem dados suficientes para analisar"
    return True, ""


def td_context(values: dict, meta: dict, today: date, ipca_12m: str | None) -> dict:
    """Leitura da taxa: real (IPCA+) ou nominal deflacionada pelo IPCA passado (rótulo explícito de retrovisor)."""
    out = {"vencimento": meta["meta"]["vencimento"], "anos_ate_vencimento": str(_years_to(meta["meta"]["vencimento"], today)),
           "tipo": meta["meta"]["tipo"]}
    rate = to_decimal(values["valor"]) / 100
    if meta["meta"]["tipo"] in ("ipca", "ipca_js", "educa", "renda"):
        out["taxa_real_contratada"] = str(rate)
        out["retorno_contratado"] = f"IPCA + {values['valor']}% a.a. se levado ao vencimento"
    elif meta["meta"]["tipo"] in ("pre", "pre_js") and ipca_12m:
        from financial_engine.rates import real_rate

        out["taxa_real_aproximada"] = str(real_rate(rate, to_decimal(ipca_12m) / 100).quantize(Decimal("0.0001")))
        out["nota_taxa_real"] = "Aproximação com o IPCA dos últimos 12 meses (passado), não com a inflação futura."
        out["retorno_contratado"] = f"{values['valor']}% a.a. nominal se levado ao vencimento"
    return out
