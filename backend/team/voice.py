# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quem fala numa conversa e quando uma fala não acrescenta nada (docs/CONVERSAS.md, "Identidade comportamental").

Regras de texto, sem modelo: escolher vozes por relevância (não por rodízio cego), deixar quem não foi chamado
ficar em silêncio e não publicar a fala opcional que só repete, concorda ou explica por que estava quieta. As
mesmas medidas de homogeneidade servem ao script de avaliação (scripts/eval_conversas.py).
"""

import re

from .auditor import fold
from .routing import CRYPTO

SILENT = "[silêncio]"
# Quem a pessoa não chamou não precisa falar; silêncio não é falha e não se justifica.
OPTIONAL = ("\n\n[Participação opcional: a pessoa não chamou você diretamente. Fale só se tiver algo seu: uma "
            "informação, uma pergunta, uma discordância, uma reação genuína. Se não tiver, responda exatamente "
            f"{SILENT} e nada mais (ninguém vê; silêncio não é falha). Não explique por que não tinha falado.]")
# Assuntos que puxam cada voz numa conversa (texto sem acento; início de palavra). Fora deles ninguém é chamado por
# obrigação: o personagem conversa sobre qualquer coisa quando é chamado, mas não é convocado para tudo.
CHAT_TOPICS = {
    "planejador": r"\b(reserva|orcament|meta|divida|gasto|despesa|salario|aposent|poupa|emergencia|financia|quitar|"
                  r"parcela|planej|boleto)",
    "analista": r"\b(invest|aplic|acoes|fii|etf|cdb|lci|lca|tesouro|renda fixa|carteira|fundo|rentab|bolsa|dividend)",
    "economista": r"\b(selic|juro|inflacao|ipca|cambio|dolar|cenario|economia|recessao|cdi|banco central|copom|pib|"
                  r"desemprego|fiscal|governo|eleica|noticia|endivid)",
    "riscos": r"\b(risco|perd|volatil|concentr|seguro|garantia|alavanc|golpe|fraude|confiavel|perigo|piramide)",
    "comportamental": r"\b(impuls|ansie|medo|fomo|urgente|emoc|vontade|arrepend|pressa|culpa|cansad|exaust|desanim|"
                      r"estress|triste|motiva|habito|procrastin|preguica)",
    "mila": r"\b(extrato|fatura|lancament|gastei|comprovante|concilia|categoria|nota fiscal|recibo|planilha|organiz)",
    "cripto": CRYPTO.pattern + r"|\b(web3|ia|inteligencia artificial|tecnologia|hype|modinha)\b",
}
_ABSENCE = re.compile(r"\b(fiquei (quiet|calad|so ouvindo|na minha|de fora|observando)\w*|nao (e|eh|sao) (bem |muito )?"
                      r"(a )?minha (area|praia|especialidade)|fora da minha (area|praia|especialidade)|"
                      r"so (pra|para) me apresentar|como (especialista|organizadora|analista|planejadora|economista|"
                      r"gestor|conselheira|auditora) (em|de|financeir))")
_HOLLOW_OPEN = re.compile(r"^(concordo|boa (observacao|colocacao|pergunta)|exatamente|isso mesmo|perfeito|"
                          r"assino embaixo|faco minhas as palavras)\b")
_WORD = re.compile(r"[a-z0-9]+")
SIMILAR = 0.25  # trigramas de radicais em comum (Jaccard); falas independentes ficam bem abaixo


def silent(text: str | None) -> bool:
    """O agente escolheu não falar (ou não disse nada)."""
    folded = fold(text or "").strip().strip("*_ .")
    return folded in ("", "[silencio]", "(silencio)", "silencio", "—", "-")


def _words(text: str) -> list[str]:
    return _WORD.findall(fold(text or ""))


def _stems(text: str) -> list[str]:
    # radical grosseiro: "quietinha" e "quieto" contam como a mesma palavra (mesmo esqueleto, outro vocabulário)
    return [w[:5] for w in _words(text)]


def opening(text: str, n: int = 4) -> str:
    return " ".join(_stems(text)[:n])


def _shingles(text: str, n: int = 3) -> set:
    w = _stems(text)
    return {tuple(w[i:i + n]) for i in range(max(len(w) - n + 1, 0))}


def similarity(a: str, b: str) -> float:
    """Sobreposição de trigramas de palavras (Jaccard): 1.0 = mesmo texto."""
    sa, sb = _shingles(a), _shingles(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def shape(text: str) -> tuple:
    """Esqueleto da fala: parágrafos, frases, perguntas e se termina perguntando."""
    body = (text or "").strip()
    paragraphs = len([p for p in re.split(r"\n\s*\n", body) if p.strip()])
    sentences = len(re.findall(r"[.!?…]+(\s|$)", body)) or 1
    return paragraphs, min(sentences, 6), min(body.count("?"), 3), body.endswith("?")


def redundant(text: str, previous: list[str]) -> str | None:
    """Por que uma fala opcional não deve ser publicada, ou None. Não se aplica a quem a pessoa chamou."""
    words = _words(text)
    if _ABSENCE.search(fold(text)):
        return "explica a própria ausência ou se apresenta em vez de conversar"
    if _HOLLOW_OPEN.match(" ".join(words)) and len(words) < 30:
        return "só concorda com quem já falou"
    for prev in previous:
        if similarity(text, prev) >= SIMILAR:
            return "repete o que um colega acabou de dizer"
        if len(words) >= 4 and opening(text) == opening(prev):
            return "começa exatamente como a fala anterior"
    return None


def relevance(agent_id: str, text: str) -> int:
    pattern = CHAT_TOPICS.get(agent_id)
    return sum(1 for _ in re.finditer(pattern, fold(text or ""))) if pattern else 0


def pick(text: str, pool: list[str], last_spoke: dict[str, str], plural: bool) -> list[str]:
    """Vozes para uma mensagem sem destinatário. Quem tem a ver com o assunto vem primeiro; empate vai para quem
    falou há mais tempo. Sem assunto (um "oi, pessoal"), poucas vozes, e não necessariamente o Bento."""
    if not plural:  # não falou com ninguém em especial: o Bento responde e, se o assunto for de alguém, essa voz pode
        topical = [a for a in pool if a != "mentor" and relevance(a, text)]
        return ["mentor", *sorted(topical, key=lambda a: -relevance(a, text))[:1]]
    ranked = sorted(pool, key=lambda a: (-relevance(a, text), last_spoke.get(a) or "", pool.index(a)))
    topical = [a for a in ranked if relevance(a, text)]
    return (topical[:3] if topical else ranked[:2]) or ["mentor"]


def homogeneity(replies: list[str]) -> dict:
    """Medidas de um conjunto de falas da mesma rodada (para a avaliação): pares parecidos, aberturas e esqueletos
    repetidos e falas que se apresentam ou justificam ausência."""
    pairs = [(i, j) for i in range(len(replies)) for j in range(i + 1, len(replies))]
    return {
        "falas": len(replies),
        "pares_parecidos": sum(similarity(replies[i], replies[j]) >= SIMILAR for i, j in pairs),
        "aberturas_repetidas": len(replies) - len({opening(r, 3) for r in replies}),
        "esqueletos_repetidos": len(replies) - len({shape(r) for r in replies}),
        "autoapresentacao_ou_ausencia": sum(bool(_ABSENCE.search(fold(r))) for r in replies),
        "so_concordancia": sum(bool(_HOLLOW_OPEN.match(" ".join(_words(r)))) for r in replies),
    }
