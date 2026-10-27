# SPDX-License-Identifier: AGPL-3.0-or-later
"""Auditoria determinística das respostas dos agentes.

Roda em toda mensagem de agente, antes de ela ser publicada. O parecer de outro modelo (Auditor semântico) só
pode ENDURECER este veredito, nunca aliviá-lo: texto de modelo não é prova de correção.

Evidência aceita para números: resultados do motor refeitos a partir das entradas que o agente usou, dados do
próprio usuário (retrato, diagnóstico, metas, premissas, fatos confirmados), valores das séries externas
consultadas e números que a pessoa escreveu na conversa.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from financial_engine.audit import forbidden_claims

PASSA, RESSALVAS, REPROVA = "PASSA", "PASSA COM RESSALVAS", "REPROVA"
ORDER = {PASSA: 0, RESSALVAS: 1, REPROVA: 2}
LEGACY = {"REVISAR": RESSALVAS, "BLOQUEAR": REPROVA}

_MONEY = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)(\s?(?:mil\b|milh(?:ão|ões|ao|oes)\b))?",
                    re.IGNORECASE)
_PCT = re.compile(r"(?<![\d,.])(-?\d{1,3}(?:,\d+)?)\s?%")
_PROMISES = (r"garant\w*\s+(de\s+)?(retorno|rendimento|lucro|ganho)", r"(retorno|rendimento|lucro)\s+garantid",
             r"(vai|ira)\s+(render|subir|valorizar)\s+com\s+certeza", r"sem\s+(nenhuma\s+)?chance\s+de\s+perd",
             r"lucro\s+cert", r"nao\s+tem\s+como\s+perder", r"dinheiro\s+facil")
_EXECUTION = (r"(me|nos)\s+(envie|passe|informe|mande|diga)\s+(a\s+|sua\s+|seu\s+)?(senha|token|codigo|cookie)",
              r"\bvou\s+(executar|realizar|fazer|enviar)\s+(a\s+|uma\s+)?(compra|venda|transferencia|aplicacao|ordem|pix)",
              r"\b(executei|transferi|comprei|vendi|apliquei|resgatei)\s+(para|por)\s+voce")
_MARKET_TERMS = re.compile(r"\b(selic|cdi|ipca|inflacao|dolar|cambio|ibovespa|fed\s*funds|juros\s+basicos?)\b")
_DATED = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|\bref(erencia|\.)|\bfonte\b|\bem\s+(jan|fev|mar|abr|mai|"
                    r"jun|jul|ago|set|out|nov|dez)\w*\s+de\s+\d{4}")
_PRODUCTS = re.compile(r"\b(acoes|acao|etfs?|fiis?|fundos?\s+imobiliarios?|cripto\w*|bitcoin|cdbs?|lcis?|lcas?|"
                       r"tesouro|debentures?|fundos?\s+de\s+investimento)\b")
_VOLATILE = re.compile(r"\b(acoes|acao|etfs?|fiis?|cripto\w*|bitcoin)\b")
_RISK_WORDS = re.compile(r"\b(risco|volatil|oscila|perda|perder|liquidez|marcacao\s+a\s+mercado|fgc|garantidor|"
                         r"queda|desvaloriz)")
_RECOMMEND = re.compile(r"\b(recomendo|sugiro|invista|aplique|compre|coloque\s+(o|seu)\s+dinheiro)\b")
_DEBT_WORDS = re.compile(r"\b(divida|cartao|reserva|orcamento|emergencia)")
FRAGILE_STAGES = ("priorizar_divida", "organizar_orcamento", "sem_recurso_disponivel")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _br_number(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def money_values(text: str) -> list[tuple[Decimal, Decimal]]:
    """(valor, tolerância de exibição) de cada "R$ …" do texto."""
    found = []
    for m in _MONEY.finditer(text or ""):
        value = _br_number(m.group(1))
        if value is None:
            continue
        scale = Decimal(1)
        if m.group(2):
            scale = Decimal(1000) if "mil" in m.group(2).lower() and "milh" not in m.group(2).lower() else Decimal(10**6)
        decimals = len(m.group(1).split(",")[1]) if "," in m.group(1) else 0
        found.append((value * scale, (Decimal(5) / Decimal(10) ** (decimals + 1)) * scale))
    return found


def percent_values(text: str) -> list[tuple[Decimal, Decimal]]:
    """(fração, tolerância) de cada "x%" do texto: "5,26%" → 0.0526 ± 0.00005."""
    found = []
    for m in _PCT.finditer(text or ""):
        value = _br_number(m.group(1))
        if value is None:
            continue
        decimals = len(m.group(1).split(",")[1]) if "," in m.group(1) else 0
        found.append((value / 100, Decimal(5) / Decimal(10) ** (decimals + 3)))
    return found


def text_numbers(text: str) -> list[Decimal]:
    """Números citados num texto (para evidência vinda de mensagens da pessoa e de textos do motor)."""
    plain = [Decimal(x) for x in re.findall(r"(?<![\d,])\d+\.\d+(?![\d,])", text or "")]
    return [v for v, _ in money_values(text)] + [v for v, _ in percent_values(text)] + plain + [
        v for v in (_br_number(x) for x in re.findall(r"\d[\d.]*,\d+|\d+", text or "")) if v is not None]


@dataclass
class Evidence:
    numbers: list = field(default_factory=list)        # dados do usuário, fatos, mensagens da pessoa
    computed: list = field(default_factory=list)       # resultados do motor refeitos a partir das entradas
    market: list = field(default_factory=list)         # [{"series", "value", "stale", "reference_date"}]
    sourced: bool = False                              # o agente consultou série externa ou fonte oficial
    stage: str | None = None                           # etapa do diagnóstico (escada do motor)


@dataclass
class AuditResult:
    verdict: str
    reasons: list
    checked_numbers: int = 0

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "reasons": self.reasons, "checked_numbers": self.checked_numbers}


def _matches(value: Decimal, tol: Decimal, pool: list) -> bool:
    return any(abs(value - e) <= max(tol, abs(e) * Decimal("0.001")) for e in pool)


def _near(value: Decimal, pool: list) -> Decimal | None:
    """Evidência "parecida" (até 25% de diferença): número que provavelmente deveria ser aquele."""
    close = [e for e in pool if e and abs(value - e) / abs(e) <= Decimal("0.25")]
    return min(close, key=lambda e: abs(value - e)) if close else None


def audit_text(text: str, evidence: Evidence, *, council: bool = False) -> AuditResult:
    reasons_fail, reasons_warn = [], []
    folded = fold(text)

    for claim in forbidden_claims(text):
        reasons_fail.append(f"Promessa ou linguagem proibida: {claim}")
    if any(re.search(p, folded) for p in _PROMISES):
        reasons_fail.append("Promessa de rentabilidade ou de ausência de perda.")
    if any(re.search(p, folded) for p in _EXECUTION):
        reasons_fail.append("Sugere executar operação ou pede credenciais; o Lastro não faz nenhuma das duas coisas.")

    market_values = [Decimal(str(m["value"])) for m in evidence.market if m.get("value") is not None]
    market_values += [v / 100 for v in market_values]
    pool = [*evidence.numbers, *evidence.computed, *market_values]
    checked = 0
    unsourced = []
    for value, tol in money_values(text) + percent_values(text):
        checked += 1
        if _matches(value, tol, pool):
            continue
        near = _near(value, evidence.computed)
        if near is not None:
            reasons_fail.append(f"Número {value.normalize():f} diverge do motor financeiro ({near.normalize():f}).")
        else:
            unsourced.append(f"{value.normalize():f}")
    if unsourced:
        reasons_warn.append(f"Números sem origem verificável (motor, seus dados ou fonte): {', '.join(unsourced[:5])}.")

    for sentence in re.split(r"(?<=[.!?\n])\s+", folded):
        if _MARKET_TERMS.search(sentence) and (_PCT.search(sentence) or re.search(r"\d", sentence)):
            if not evidence.sourced and not _DATED.search(folded):
                reasons_warn.append("Afirmação sobre indicador de mercado sem fonte nem data de referência.")
                break
    if any(m.get("stale") for m in evidence.market) and "desatualiz" not in folded:
        reasons_warn.append("Usou série externa desatualizada sem avisar que está desatualizada.")
    if _PRODUCTS.search(folded) and not _RISK_WORDS.search(folded):
        reasons_warn.append("Cita categorias de investimento sem apresentar riscos (liquidez, perdas, crédito).")
    if (evidence.stage in FRAGILE_STAGES and _VOLATILE.search(folded) and _RECOMMEND.search(folded)
            and not _DEBT_WORDS.search(folded)):
        reasons_fail.append("Recomenda ativo volátil sem considerar a etapa atual (dívida cara, orçamento ou reserva).")
    if council and "diverg" not in folded:
        reasons_warn.append("A síntese do Conselho não declara divergências (nem que não houve).")

    verdict = REPROVA if reasons_fail else RESSALVAS if reasons_warn else PASSA
    return AuditResult(verdict, reasons_fail + reasons_warn, checked)


_VERDICT_LINE = re.compile(r"^VEREDITO:\s*(PASSA COM RESSALVAS|PASSA|REPROVA|REVISAR|BLOQUEAR)\b", re.IGNORECASE)


def parse_semantic(auditor_text: str) -> AuditResult:
    """Lê o parecer do Auditor (modelo). Fora do formato vira ressalva, nunca aprovação."""
    first = next((line.strip() for line in (auditor_text or "").splitlines() if line.strip()), "")
    match = _VERDICT_LINE.match(first)
    reasons = [line.lstrip("-• ").strip() for line in (auditor_text or "").splitlines()
               if line.strip().startswith(("-", "•"))][:5]
    if not match:
        return AuditResult(RESSALVAS, ["O Auditor não devolveu um veredito no formato esperado."] + reasons)
    verdict = match.group(1).upper()
    return AuditResult(LEGACY.get(verdict, verdict), reasons)


def combine(deterministic: AuditResult, semantic: AuditResult | None) -> AuditResult:
    if semantic is None:
        return deterministic
    verdict = max(deterministic.verdict, semantic.verdict, key=ORDER.get)
    reasons = [f"[verificação automática] {r}" for r in deterministic.reasons] + \
              [f"[Auditor] {r}" for r in semantic.reasons]
    return AuditResult(verdict, reasons, deterministic.checked_numbers)
