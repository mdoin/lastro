# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verificações determinísticas usadas pelo agente Auditor (AG-06).

IMPORTANTE: isto NÃO é controle de segurança. A barreira real contra operações
financeiras é a inexistência dessas operações na API e no ambiente dos agentes
(ver docs/SECURITY_MODEL.md). Estas checagens apenas apoiam o parecer.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .money import to_decimal
from .projection import Assumptions, Plan, simulate

PASSA, REVISAR, BLOQUEAR = "PASSA", "REVISAR", "BLOQUEAR"

# Pedidos que nenhum agente atende, em qualquer formulação.
_BLOCKED_REQUEST_PATTERNS = (
    r"\btransfer(ir|e|encia|ência)?\b",
    r"\b(fazer|faca|faça|mande|enviar?)\s+(um\s+)?pix\b",
    r"\bchave\s+pix\b",
    r"\b(compr(e|ar)|vend(a|er)|resgat(e|ar))\b.*\b(para mim|por mim|automatic)",
    r"\b(executar?|envi(e|ar))\s+(a\s+)?ordem\b",
    r"\bsenha\b",
    r"\b(token|codigo|código)\s+(de\s+)?(autenticacao|autenticação|acesso|sms)\b",
    r"\bcookies?\b",
    r"\bseed\s*phrase\b|\bchave\s+privada\b",
    r"\b(entr(e|ar)|log(ar|ue))\s+(na|no)\s+(minha\s+)?(conta|banco|corretora)\b",
    r"\bbeneficiari[oa]s?\b",
)

# Expressões proibidas sem evidência (seção 11).
_FORBIDDEN_CLAIMS = (
    "retorno garantido",
    "sem risco",
    "e certo que vai subir",
    "melhor investimento",
    "vale a pena para voce",
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


@dataclass(frozen=True)
class Verdict:
    outcome: str
    reasons: tuple

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "reasons": list(self.reasons)}


def screen_request(text: str) -> Verdict:
    normalized = _normalize(text)
    hits = [p for p in _BLOCKED_REQUEST_PATTERNS if re.search(_normalize(p), normalized)]
    if hits:
        return Verdict(BLOQUEAR, (
            "Pedido envolve execução financeira ou credenciais. Nenhum agente executa operações nem "
            "recebe senhas, tokens ou cookies; operações são feitas por você diretamente na instituição.",
        ))
    return Verdict(PASSA, ())


def forbidden_claims(text: str) -> list[str]:
    """Expressões proibidas sem evidência (seção 11) encontradas no texto."""
    normalized = _normalize(text)
    return [f"Expressão proibida sem evidência: \"{claim}\"." for claim in _FORBIDDEN_CLAIMS if claim in normalized]


def audit_report(report: dict, *, today: date, max_age_days: int) -> Verdict:
    """Confere data de referência, fontes, idade dos dados e linguagem proibida."""
    reasons = []
    as_of = report.get("as_of")
    if not as_of:
        reasons.append("Relatório sem data de referência (as_of).")
    else:
        age = (today - date.fromisoformat(as_of[:10])).days
        if age > max_age_days:
            reasons.append(f"Dados com {age} dias, acima do limite de {max_age_days}: marcar como desatualizado.")
        if age < 0:
            reasons.append("Data de referência no futuro.")

    facts = report.get("facts") or []
    sources = report.get("sources") or []
    if facts and not sources:
        reasons.append("Fatos apresentados sem fonte.")
    for i, src in enumerate(sources):
        if not src.get("accessed_at"):
            reasons.append(f"Fonte {i} sem data de acesso.")

    reasons.extend(forbidden_claims(" ".join(str(v) for v in report.get("conclusions") or [])))

    return Verdict(REVISAR if reasons else PASSA, tuple(reasons))


def audit_projection_claim(plan: Plan, assumptions: Assumptions, claimed_final_nominal, tolerance="0.01") -> Verdict:
    """Recalcula a projeção com o motor e compara com o número afirmado por um agente."""
    claimed = to_decimal(claimed_final_nominal)
    projection = simulate(plan, assumptions)
    actual = projection.final_nominal
    diff = abs(actual - claimed)
    if diff <= to_decimal(tolerance):
        return Verdict(PASSA, ())
    return Verdict(REVISAR, (
        f"Valor afirmado {claimed} diverge do motor ({actual.quantize(Decimal('0.01'))}) em "
        f"{diff.quantize(Decimal('0.01'))}. Usar o resultado do motor (fingerprint "
        f"{projection.inputs_fingerprint[:12]}).",
    ))
