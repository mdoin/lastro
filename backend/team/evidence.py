# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regras determinísticas em volta da pesquisa na internet (sem modelo, testadas).

- `outbound`: o que sai para buscadores e sites. A sessão de pesquisa não vê os dados da pessoa, mas o pedido é
  escrito por um agente que vê; aqui saem valores, números longos, documentos, e-mails, telefones e o nome dela.
- `needs_research`: a pergunta depende de fato recente (eleição, Copom, "hoje", notícia…): o agente é orientado a
  pesquisar antes de responder.
- `wants_report`: a pessoa pediu formato de relatório (tabela, comparativo, estudo detalhado).
- `unverified_urls`: endereços citados na resposta que nenhuma ferramenta consultou (fonte inventada).
"""

import re
from urllib.parse import urlsplit

from .auditor import fold

_MONEY = re.compile(r"(?:R\$|US\$|\$|€)\s*[\d.,]+(?:\s*(?:mil|milh[õo]es|bilh[õo]es|k|mi|bi))?", re.IGNORECASE)
_DOCS = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b")
_BIGNUM = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+(?:,\d+)?\b|\b\d{4,}\b")
_YEAR = re.compile(r"^(19|20|21)\d{2}$")


def outbound(text: str, names: tuple[str, ...] = ()) -> tuple[str, bool]:
    """Pedido de pesquisa sem dados da pessoa. Devolve (texto limpo, se algo foi removido). Anos ficam."""
    original = text or ""
    out = _MONEY.sub("[valor]", original)
    out = _DOCS.sub("[documento]", out)
    out = _EMAIL.sub("[e-mail]", out)
    out = _PHONE.sub("[telefone]", out)
    out = _BIGNUM.sub(lambda m: m.group(0) if _YEAR.match(m.group(0)) else "[número]", out)
    for name in names:
        if name and len(name) >= 2:
            out = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "a pessoa", out, flags=re.IGNORECASE)
    out = " ".join(out.split())
    return out, out != " ".join(original.split())


_RECENT = re.compile(
    r"\b(hoje|ontem|agora|nesta semana|esta semana|essa semana|este mes|esse mes|ultim[oa]s?|recente\w*|atual\w*|"
    r"acabou de|ja saiu|saiu o|divulga\w*|anunci\w*|noticia\w*|eleic\w*|eleit\w*|venceu|vencedor|segundo turno|"
    r"primeiro turno|apuracao|copom|reuniao do fed|decisao do (copom|fed|banco central)|balanco|resultado trimestral|"
    r"aprovad[oa]|sancionad[oa]|nova lei|medida provisoria|reforma|cotacao de hoje|como esta o (mercado|cenario)|"
    r"cenario (atual|nacional)|o que aconteceu|aconteceu com)\b")
_REPORT = re.compile(
    r"\b(relatorio|estudo (completo|detalhado)|analise (aprofundada|detalhada|completa)|comparativo|compare em tabela|"
    r"em (uma )?tabela|tabela comparativa|passo a passo detalhado|documento completo|resumo executivo)\b")


def needs_research(text: str) -> bool:
    return bool(_RECENT.search(fold(text or "")))


def wants_report(text: str) -> bool:
    return bool(_REPORT.search(fold(text or "")))


_URL = re.compile(r"https?://[^\s)\]>\"'<]+")


def consulted_hosts(tools: list) -> set[str]:
    hosts = set()
    for t in tools:
        data = t.get("input") or {}
        if t.get("name") in ("fonte_web", "ler_pagina_oficial") and data.get("url"):
            hosts.add((urlsplit(str(data["url"])).hostname or "").lower().removeprefix("www."))
    return hosts


def unverified_urls(text: str, tools: list) -> list[str]:
    """Endereços citados cujo domínio não passou por nenhuma ferramenta nesta resposta."""
    seen = consulted_hosts(tools)
    out = []
    for url in _URL.findall(text or ""):
        host = (urlsplit(url.rstrip(".,;")).hostname or "").lower().removeprefix("www.")
        if host and host not in seen and host not in out:
            out.append(host)
    return out


def web_sources(tools: list) -> list[dict]:
    """Fontes da web para a mensagem: páginas lidas primeiro; resultados de busca só se nenhuma página foi lida."""
    items = [t.get("input") or {} for t in tools if t.get("name") == "fonte_web"]
    read = [i for i in items if i.get("tipo") == "pagina_lida"]
    chosen = read or [i for i in items if i.get("tipo") == "resultado_busca"][:5]
    out, seen = [], set()
    for i in chosen:
        url = str(i.get("url", ""))[:300]
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"kind": "web", "label": (str(i.get("titulo") or "") or urlsplit(url).hostname or url)[:200],
                    "url": url, "source": str(i.get("fonte", ""))[:120],
                    "published_at": str(i.get("publicado_em", ""))[:40], "fetched_at": str(i.get("consultado_em", ""))[:40],
                    "official": bool(i.get("oficial")),
                    "validity": "lida" if i.get("tipo") == "pagina_lida" else "resultado de busca"})
    return out
