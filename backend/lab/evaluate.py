# SPDX-License-Identifier: AGPL-3.0-or-later
"""Avaliação do Laboratório em dimensões independentes, sem índice composto.

Determinístico primeiro: auditoria de números (A), Brier (B), categorias de risco por vocabulário explícito (C),
problemas de consistência (D), consumo (F) e contribuição do debate a partir do registro da reunião (G). Utilidade (E)
vem de avaliações registradas (IA às cegas com trechos conferidos, ou a pessoa) e fica separada por avaliador.
Agregados sempre com o tamanho da amostra; percentuais só com amostra mínima; "vencedor" só com teste do sinal.
"""

import math
import re
import unicodedata
from decimal import Decimal

from app import convictions

MIN_SAMPLE_PCT = 5        # abaixo disso, mostra contagens, não porcentagem
MIN_PAIRS_VERDICT = 10    # pares decisivos mínimos para o teste do sinal falar em superioridade
TIE_BRIER = Decimal("0.02")
REPEAT_JACCARD = 0.6

RISK_TERMS = {
    "juros": r"juros|selic|copom|taxa basica",
    "inflacao": r"inflac|ipca|poder de compra",
    "liquidez": r"liquidez|resgate|carencia|reserva de emergencia|emergencia",
    "credito": r"credito|calote|inadimpl|emissor|\bfgc\b|garantia",
    "mercado": r"volatil|oscila|marcacao a mercado|queda de preco|preco cai|desvaloriz",
    "cambio": r"cambio|cambial|dolar",
    "concentracao": r"concentrac|diversific",
    "tributacao": r"imposto|\bir\b|\biof\b|tribut",
    "prazo": r"prazo|vencimento|horizonte",
    "divida": r"divida|endivid|parcela|cartao",
    "comportamental": r"emocion|impulso|ansiedade|panico|vies|comportament",
    "dados": r"dados? (insuficiente|desatualizad|incomplet)|falta de dados|incerteza",
}
_RISK = {k: re.compile(v) for k, v in RISK_TERMS.items()}
RISK_LABELS = {"juros": "Juros", "inflacao": "Inflação", "liquidez": "Liquidez", "credito": "Crédito",
               "mercado": "Preço/volatilidade", "cambio": "Câmbio", "concentracao": "Concentração",
               "tributacao": "Tributação", "prazo": "Prazo", "divida": "Dívida", "comportamental": "Comportamento",
               "dados": "Qualidade dos dados"}
_RISK_SECTION = re.compile(r"^#{1,3}\s*riscos?\b.*?$(.*?)(?=^#{1,3}\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL)


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))


def risk_categories(record: dict | None, text: str) -> list[str]:
    """Categorias citadas na lista de riscos do registro e na seção "Riscos" do texto (não no texto inteiro)."""
    parts = list((record or {}).get("riscos_identificados") or [])
    parts += [m.group(1) for m in _RISK_SECTION.finditer(text or "")]
    folded = fold(" ".join(parts))
    return [k for k, rx in _RISK.items() if rx.search(folded)]


def consistency(record: dict | None, record_problems: list[str], audit: dict | None) -> list[str]:
    out = list(record_problems)
    for reason in (audit or {}).get("reasons", []):
        if re.search(r"contradi|incompat|c[aá]lculo|n[uú]mero", reason, re.IGNORECASE):
            out.append(f"Auditor: {reason}")
    if record:
        if record["dados_insuficientes"] and record["nivel_confianca"] == "alta":
            out.append("Diz que os dados são insuficientes, mas declara confiança alta.")
        horizon = record.get("horizonte_dias")
        if horizon and record["hipoteses"]:
            # a data da hipótese vem validada; compara com o horizonte declarado (tolerância de 30 dias)
            out += [f"Hipótese \"{h['afirmacao'][:60]}\" vence depois do horizonte declarado ({horizon} dias)."
                    for h in record["hipoteses"] if h.get("_dias") and h["_dias"] > horizon + 30]
    return out


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", fold(text))}


def jaccard(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def debate(meeting: dict | None, turn_texts: list[str], corrections: int) -> dict | None:
    """Contribuição do debate (G), só com o que o registro da reunião mostra."""
    if not meeting:
        return None
    turns = meeting.get("falas") or []
    repeats = sum(1 for i, a in enumerate(turn_texts) for b in turn_texts[i + 1:] if jaccard(a, b) >= REPEAT_JACCARD)
    return {"falas": len(turns), "mudancas_de_posicao": list(meeting.get("mudancas") or []),
            "contestacoes": sum(1 for t in turns if (t.get("kind") or "") in ("contestacao", "pergunta", "evidencia")),
            "revisoes_declaradas": sum(1 for t in turns if t.get("revised")),
            "divergencias_finais": list(meeting.get("divergencias") or []),
            "devolucoes_da_auditoria": sum(1 for t in turns if str(t.get("round", "")).startswith("auditoria")),
            "correcoes_apos_auditor": corrections, "falas_repetitivas": repeats,
            "limites_atingidos": list(meeting.get("limites_atingidos") or [])}


# ---------------------------------------------------------------- estatística

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def proportion(k: int, n: int) -> dict:
    """Proporção com amostra e intervalo de Wilson (95%); sem porcentagem abaixo da amostra mínima."""
    out = {"k": k, "n": n, "pct": None, "ic95": None, "amostra_pequena": n < MIN_SAMPLE_PCT}
    if n >= MIN_SAMPLE_PCT:
        lo, hi = wilson(k, n)
        out |= {"pct": round(100 * k / n, 1), "ic95": [round(100 * lo, 1), round(100 * hi, 1)]}
    return out


def sign_test(wins: int, losses: int) -> float | None:
    """p bilateral exato do teste do sinal (empates fora)."""
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def brier_summary(rows: list[dict]) -> dict:
    """Brier das hipóteses conferidas com probabilidade (as sem probabilidade ficam fora da conta)."""
    scored = [Decimal(convictions.brier(Decimal(r["probability"]), r["status"]))
              for r in rows if r["probability"] is not None and r["status"] in convictions.RESOLVED]
    n = len(scored)
    out = {"n": n, "brier": None, "ic95": None, "amostra_pequena": n < convictions.SMALL_SAMPLE,
           "referencia_50pct": str(convictions.BASELINE)}
    if n:
        mean = sum(scored) / n
        out["brier"] = f"{round(mean, 4).normalize():f}"
        if n >= 2:
            var = sum((x - mean) ** 2 for x in scored) / (n - 1)
            se = Decimal(math.sqrt(float(var) / n))
            out["ic95"] = [f"{max(Decimal(0), round(mean - Decimal('1.96') * se, 4)):f}",
                           f"{round(mean + Decimal('1.96') * se, 4):f}"]
    return out


def pair_outcome(solo: list[dict], council: list[dict]) -> str:
    """Comparação de um par (mesma repetição) pelas hipóteses conferidas com probabilidade."""
    a, b = brier_summary(solo), brier_summary(council)
    if not a["n"] or not b["n"]:
        return "sem_avaliacao"
    diff = Decimal(a["brier"]) - Decimal(b["brier"])
    if abs(diff) < TIE_BRIER:
        return "empate"
    return "conselho" if diff > 0 else "individual"


def verdict(wins_council: int, wins_solo: int, ties: int) -> dict:
    decisive = wins_council + wins_solo
    p = sign_test(wins_council, wins_solo)
    if decisive < MIN_PAIRS_VERDICT:
        text = (f"Evidência insuficiente: {decisive} comparação(ões) decisiva(s); são necessárias pelo menos "
                f"{MIN_PAIRS_VERDICT} para um teste com algum poder. Nenhum vencedor declarado.")
        winner = None
    elif p is not None and p < 0.05:
        winner = "conselho" if wins_council > wins_solo else "individual"
        text = (f"{'O Conselho' if winner == 'conselho' else 'O Bento sozinho'} foi melhor em {max(wins_council, wins_solo)} "
                f"de {decisive} comparações decisivas (teste do sinal, p = {p:.3f}). Vale para os cenários testados, "
                "não para qualquer pergunta.")
    else:
        winner = None
        text = (f"Sem diferença detectável: {wins_council} × {wins_solo} em {decisive} comparações decisivas "
                f"(teste do sinal, p = {p:.3f}); {ties} empate(s).")
    return {"conselho": wins_council, "individual": wins_solo, "empates": ties, "decisivos": decisive,
            "p_valor": None if p is None else round(p, 4), "vencedor": winner, "texto": text}


UTILITY_CRITERIA = ("alternativas", "restricoes", "consequencias", "clareza")


def utility_scores(review_scores: dict, texts: dict[str, str]) -> dict:
    """Notas verificáveis: cada nota precisa de um trecho literal encontrado no texto avaliado; senão é descartada."""
    out = {}
    for label, text in texts.items():
        body = " ".join(fold(text).split())
        crit, discarded = {}, []
        for c in UTILITY_CRITERIA:
            item = (review_scores.get(label) or {}).get(c) or {}
            try:
                score = int(item.get("nota"))
            except (TypeError, ValueError):
                discarded.append(c)
                continue
            quote = " ".join(fold(str(item.get("trecho") or "")).split()).strip(" .…\"'")
            if score not in (0, 1, 2) or (score > 0 and (len(quote) < 8 or quote[:160] not in body)):
                discarded.append(c)
                continue
            crit[c] = {"nota": score, "trecho": str(item.get("trecho") or "")[:200]}
        out[label] = {"criterios": crit, "descartados": discarded,
                      "total": sum(v["nota"] for v in crit.values()), "max": 2 * len(crit)}
    return out
