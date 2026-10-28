# SPDX-License-Identifier: AGPL-3.0-or-later
"""Aba livre da sessão de pesquisa com o Chrome real e a rede simulada (httpx.MockTransport): nada sai da máquina.

O Chrome nunca conecta sozinho: tudo o que a página pede passa por research.pinned_request, que é onde a rede
simulada responde. Um nome que aponta para IP interno, http:// e WebSocket nunca chegam à rede.
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from mentor import browser as rb

CHROME = Path("/opt/lastro-browsers/chrome-headless-shell-linux64/chrome-headless-shell")
pytestmark = pytest.mark.skipif(not CHROME.exists(), reason="Chrome da implantação não instalado")

ADDRESSES = {"site.test": "93.184.216.34", "outro.test": "93.184.216.35", "interno.test": "10.0.0.5"}

PAGES = {
    ("site.test", "/"): """<!doctype html><title>Início</title><p>Bem-vindo ao site de teste.</p>
<a href="/vai">Ir para a notícia</a>
<form action="/busca"><input type="search" name="q" placeholder="Buscar"></form>
<form action="/envio" method="post"><input name="campo" placeholder="Campo"><button>Enviar</button></form>
<img src="https://interno.test/segredo.png"><img src="http://site.test/inseguro.png">
<script>try { new WebSocket('wss://site.test/ws'); } catch (e) {}</script>""",
    ("outro.test", "/noticia"): "<!doctype html><title>Notícia</title><p>Copom decidiu manter a Selic.</p>",
}


def network():
    seen: list[tuple[str, str, str]] = []
    schemes: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        seen.append((request.method, host, request.url.path))
        schemes.add(request.url.scheme)
        if (host, request.url.path) == ("site.test", "/vai"):
            return httpx.Response(302, headers={"location": "https://outro.test/noticia"})
        if (host, request.url.path) == ("site.test", "/busca"):
            q = request.url.params.get("q", "")
            return httpx.Response(200, html=f"<!doctype html><title>Busca: {q}</title><p>Resultados para {q}</p>")
        if (host, request.url.path) == ("site.test", "/envio"):
            return httpx.Response(200, html=f"<!doctype html><title>Recebido</title><p>{request.content.decode()}</p>")
        body = PAGES.get((host, request.url.path))
        return httpx.Response(200, html=body) if body else httpx.Response(404, text="não achei")

    return httpx.MockTransport(handler), seen, schemes


async def resolve(host: str) -> list[str]:
    if host not in ADDRESSES:
        raise OSError("sem DNS")
    return [ADDRESSES[host]]


def test_free_tab_browses_clicks_types_and_never_reaches_internal_hosts():
    transport, seen, schemes = network()
    frames, pages = [], []

    async def sink(image, url):
        frames.append(url)

    async def scenario():
        browser = rb.ResearchBrowser(str(CHROME), sandbox=False)
        tab = browser.open_tab(sink, lambda url, title, at: pages.append(url), resolve=resolve, transport=transport)
        try:
            home = await tab.goto("https://site.test/")
            link = next(e["n"] for e in home["elementos"] if e["texto"] == "Ir para a notícia")
            news = await tab.click(link)
            back = await tab.back()
            box = next(e["n"] for e in back["elementos"] if e["texto"] == "Buscar")
            search = await tab.type(box, "selic hoje", submit=True)
            await tab.back()
            again = await tab.read()
            field = next(e["n"] for e in again["elementos"] if e["texto"] == "Campo")
            posted = await tab.type(field, "abc", submit=True)
            blocked = await tab.goto("https://interno.test/")
            plain = await tab.goto("http://site.test/")
            return home, news, search, posted, blocked, plain
        finally:
            await tab.close()
            await browser.close()

    home, news, search, posted, blocked, plain = asyncio.run(scenario())
    assert home["status"] == "ok" and home["titulo"] == "Início" and "Bem-vindo" in home["texto"]
    assert any("interno.test" in b for b in home["bloqueados"])
    assert news["status"] == "ok" and news["url"] == "https://outro.test/noticia" and "Selic" in news["texto"]
    assert search["titulo"] == "Busca: selic hoje"
    assert posted["titulo"] == "Recebido" and "campo=abc" in posted["texto"]
    assert blocked["status"] == "bloqueado" and plain["status"] == "bloqueado"
    hosts = {h for _, h, _ in seen}
    assert "interno.test" not in hosts  # o nome interno nunca virou requisição
    assert schemes == {"https"} and ("GET", "site.test", "/ws") not in seen  # http:// da página sobe para https
    assert ("POST", "site.test", "/envio") in seen
    assert "https://outro.test/noticia" in pages and frames  # fonte registrada e tela ao vivo enviada
    assert rb.TAB_SLOTS._value == 2  # a vaga da aba foi devolvida


def test_free_tab_respects_the_action_limit(monkeypatch):
    transport, _, _ = network()
    monkeypatch.setattr(rb, "TAB_MAX_ACTIONS", 1)

    async def scenario():
        browser = rb.ResearchBrowser(str(CHROME), sandbox=False)
        tab = browser.open_tab(resolve=resolve, transport=transport)
        try:
            return await tab.goto("https://site.test/"), await tab.goto("https://outro.test/noticia")
        finally:
            await tab.close()
            await browser.close()

    first, second = asyncio.run(scenario())
    assert first["status"] == "ok" and second["status"] == "limite"
