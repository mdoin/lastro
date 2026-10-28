# SPDX-License-Identifier: AGPL-3.0-or-later
"""Veredito do Conselho em estrutura: seções, itens e menções resolvidas no servidor.

A interface não procura @nomes no texto final: recebe segmentos `{"t": texto}` e `{"agent": id}`, e só vira
menção o identificador que resolve para um agente que participou da reunião. O texto é sempre exibido como texto
puro (sem HTML), então nada do que o modelo escreveu é interpretado como marcação.
"""

import re

from .auditor import fold
from .routing import MENTION, resolve_handle

SECTIONS = (("conclusao", "Conclusão"), ("fundamentos", "Argumentos determinantes"), ("participacao", "Participação"),
            ("concordancia", "Concordâncias"), ("reconsideradas", "Posições reconsideradas"),
            ("diverg", "Divergências"), ("risco", "Riscos"), ("informac", "Incertezas"),
            ("condicoes", "Condições que mudariam o resultado"), ("proxim", "Próximos passos"))
# Títulos aceitos (sem acento, começo do título) → seção. Títulos antigos continuam valendo.
PREFIXES = (("conclus", "conclusao"), ("decis", "conclusao"), ("argument", "fundamentos"), ("fundament", "fundamentos"),
            ("participa", "participacao"), ("especialistas", "participacao"), ("concord", "concordancia"),
            ("posicoes reconsider", "reconsideradas"), ("reconsider", "reconsideradas"), ("mudancas", "reconsideradas"),
            ("diverg", "diverg"), ("discord", "diverg"), ("risco", "risco"), ("informac", "informac"),
            ("incertez", "informac"), ("condic", "condicoes"), ("proxim", "proxim"))
_HEADING = re.compile(r"^#{2,3}\s*(.+?)\s*#*\s*$", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_EMPHASIS = re.compile(r"(\*\*|__|`)")
MAX_ITEMS, MAX_CHARS = 12, 600


def segments(text: str, participants: set[str]) -> list[dict]:
    out, pos = [], 0
    for match in MENTION.finditer(text):
        agent = resolve_handle(match.group(1))
        if agent not in participants:
            continue
        if match.start() > pos:
            out.append({"t": text[pos:match.start()]})
        out.append({"agent": agent})
        pos = match.end()
    if pos < len(text):
        out.append({"t": text[pos:]})
    return out


def _items(body: str) -> list[str]:
    lines = [line for line in body.strip().splitlines()]
    if any(_BULLET.match(line) for line in lines):
        items, current = [], []
        for line in lines:
            if _BULLET.match(line):
                if current:
                    items.append(" ".join(current))
                current = [_BULLET.sub("", line, count=1).strip()]
            elif line.strip() and current:
                current.append(line.strip())
        if current:
            items.append(" ".join(current))
    else:
        items = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]
    return [_EMPHASIS.sub("", i).strip()[:MAX_CHARS] for i in items if i.strip()][:MAX_ITEMS]


def parse(text: str, participants: set[str]) -> dict | None:
    """None quando a síntese não segue a estrutura (a interface mostra o texto como antes)."""
    heads = list(_HEADING.finditer(text or ""))
    sections, mentioned = [], []
    for i, head in enumerate(heads):
        name = fold(head.group(1))
        key = next((k for prefix, k in PREFIXES if name.startswith(prefix)), None)
        if key is None or any(s["key"] == key for s in sections):
            continue
        title = dict(SECTIONS)[key]
        inline = head.group(1).split(":", 1)[1].strip() if ":" in head.group(1) else ""  # "## Divergências: nenhuma"
        body = inline + "\n" + text[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        items = [segments(item, participants) for item in _items(body)]
        for item in items:
            mentioned += [s["agent"] for s in item if "agent" in s and s["agent"] not in mentioned]
        sections.append({"key": key, "title": title, "items": items})
    if len(sections) < 2 or not any(s["key"] == "conclusao" for s in sections):
        return None
    order = [k for k, _ in SECTIONS]
    sections.sort(key=lambda s: order.index(s["key"]))
    return {"sections": sections, "mentioned": mentioned}
