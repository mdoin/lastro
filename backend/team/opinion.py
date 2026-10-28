# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parecer estruturado do Conselho: leitura determinística da posição e das seções, mapa de posições e checagem
de que a síntese não apaga dissenso.

A posição é declarada pelo próprio agente ("**Posição:** contrária"); o Lastro não a infere do texto. Assim a
divergência fica registrada de forma verificável e independe do provedor de IA que escreveu o parecer.
"""

import re

from .agents import get
from .auditor import fold

STANCES = {"favoravel": "favorável", "contraria": "contrária", "condicional": "condicional",
           "insuficiente": "sem base suficiente"}
SECTIONS = {"tese": "Tese", "evidencia": "Evidências", "fonte": "Fontes", "hipotese": "Hipóteses",
            "risco": "Riscos", "lacuna": "Lacunas", "nao agir": "Não agir"}
OPPOSED = ("favoravel", "contraria")

_STANCE = re.compile(r"^\W*posicao\W*:?\W*(favoravel|contraria|condicional|sem base suficiente)\b", re.MULTILINE)
_HEADING = re.compile(r"^#{2,3}\s*(.+?)\s*#*\s*$", re.MULTILINE)


def stance(text: str) -> str | None:
    match = _STANCE.search(fold(text))
    if not match:
        return None
    return "insuficiente" if match.group(1).startswith("sem") else match.group(1)


def sections(text: str) -> dict[str, str]:
    """Seções conhecidas com corpo não vazio (texto original), por chave de SECTIONS."""
    heads = list(_HEADING.finditer(text or ""))
    found = {}
    for i, head in enumerate(heads):
        body = text[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        key = next((k for k in SECTIONS if fold(head.group(1)).startswith(k)), None)
        if key and body:
            found[key] = body
    return found


def problems(text: str, required: tuple = tuple(SECTIONS)) -> list[str]:
    """Motivos de reprovação de um parecer fora da estrutura (vazio = estruturado)."""
    reasons = []
    if stance(text) is None:
        reasons.append("Parecer sem posição declarada (\"**Posição:** favorável, contrária, condicional ou sem base "
                       "suficiente\").")
    missing = [SECTIONS[k] for k in required if k not in sections(text)]
    if missing:
        reasons.append(f"Parecer sem as seções obrigatórias: {', '.join(missing)}.")
    return reasons


EXCERPT_CHARS = 420


def summary(text: str) -> dict:
    """O que fica gravado junto da mensagem: a posição, as seções que vieram e trechos curtos para o painel do
    agente (tese, riscos, evidências, fontes, lacunas). O parecer completo continua na mensagem."""
    found = sections(text)
    excerpts = {k: _excerpt(found[k]) for k in ("tese", "risco", "evidencia", "fonte", "lacuna", "nao agir")
                if k in found}
    return {"stance": stance(text), "sections": sorted(found), "excerpts": excerpts}


def _excerpt(body: str) -> str:
    plain = re.sub(r"(\*\*|__|`)", "", " ".join(body.split()))
    return plain if len(plain) <= EXCERPT_CHARS else plain[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"


def conflict(stances: dict[str, str | None]) -> bool:
    """Divergência material: ao menos um especialista favorável e outro contrário à proposta."""
    return all(s in stances.values() for s in OPPOSED)


def opposite(value: str | None) -> str | None:
    return {"favoravel": "contraria", "contraria": "favoravel"}.get(value)


def contested(initial: dict[str, str | None]) -> list[str]:
    """Quem entra na rodada de contestação: os lados opostos, e só quando há divergência material."""
    return [a for a, s in initial.items() if s in OPPOSED] if conflict(initial) else []


def position_map(initial: dict[str, str | None], final: dict[str, str | None]) -> str:
    """Registro determinístico das posições, publicado antes da síntese e independente dela."""
    debated = contested(initial)
    rows = [f"| {get(a).name} | {_label(initial[a])} | {_label(final[a]) if a in debated else '—'} |" for a in initial]
    lines = ["**Mapa de posições do Conselho** (registro automático do Lastro, sem interpretação)", "",
             "| Especialista | Posição no parecer | Após contestação |", "|---|---|---|", *rows, ""]
    if conflict(final):
        sides = [", ".join(get(a).name for a, s in final.items() if s == side) for side in OPPOSED]
        lines.append(f"**Divergência material mantida:** {sides[0]} (favorável) × {sides[1]} (contrária).")
    elif debated:
        lines.append("Houve divergência material nos pareceres; depois da contestação ela não se manteve.")
    else:
        lines.append("Sem divergência material entre as posições declaradas.")
    return "\n".join(lines)


def _label(value: str | None) -> str:
    return STANCES.get(value, "não declarada")


def dissent_problems(text: str, dissenters: list[str]) -> list[str]:
    """A síntese precisa nomear, na seção de divergências, cada especialista que segue discordando."""
    if not dissenters:
        return []
    folded = fold(text)
    match = re.search(r"^#{2,3}\s*diverg[^\n]*\n?(.*?)(?=^#{1,3}\s|\Z)", folded, re.MULTILINE | re.DOTALL)
    if not match:
        return ["A síntese não tem a seção \"## Divergências\", mas há divergência material entre especialistas."]
    block = match.group(0)
    omitted = [get(a).name for a in dissenters if not _named(block, a)]
    return [f"A síntese apaga a divergência de {', '.join(omitted)}."] if omitted else []


def _named(folded_block: str, agent_id: str) -> bool:
    """Nome ou @menção como palavra inteira: "@rui" conta, "ruim" não. Apelidos ficam de fora ("risco" é palavra
    comum demais para provar que o Rui foi citado)."""
    spec = get(agent_id)
    names = {fold(spec.name), fold(spec.handle)}
    return any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", folded_block) for n in names)
