# SPDX-License-Identifier: AGPL-3.0-or-later
"""Navegador de pesquisa contra servidores locais: nada sai para fora da allowlist.

Usa o Chrome real da implantação (pula se não estiver instalado). A "allowlist" do teste é `localhost` numa porta
de origem; o "sink" (127.0.0.1 em outra porta, e o nome sink.test) registra tudo que chegar até ele.
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from mentor import browser as rb

CHROME = Path("/opt/lastro-browsers/chrome-headless-shell-linux64/chrome-headless-shell")
pytestmark = pytest.mark.skipif(not CHROME.exists(), reason="Chrome da implantação não instalado")


def serve(handler_cls) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def servers(monkeypatch):
    hits: list[str] = []

    class Sink(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"sink")

        def log_message(self, *args):
            pass

    sink = serve(Sink)
    sp = sink.server_address[1]

    class Origin(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parts = urlsplit(self.path)
            if parts.path == "/redir":
                self.send_response(302)
                self.send_header("Location", parse_qs(parts.query)["to"][0])
                self.end_headers()
                return
            if parts.path == "/hop":
                self.send_response(302)
                self.send_header("Location", "/page")
                self.end_headers()
                return
            if parts.path == "/big":
                body = b"x" * (rb.MAX_RESPONSE_BYTES + 1)
            elif parts.path == "/page":
                body = f"""<!doctype html><html><head><title>Fonte oficial</title></head><body>
<p>Selic de teste: 10,50%</p>
<img src="http://127.0.0.1:{sp}/img-direct">
<img src="/redir?to=http://127.0.0.1:{sp}/img-redir">
<script>
fetch('/redir?to=http://127.0.0.1:{sp}/fetch-redir').catch(() => {{}});
fetch('http://sink.test:{sp}/named').catch(() => {{}});
try {{ const w = new WebSocket('ws://127.0.0.1:{sp}/ws'); w.onopen = () => w.send('x'); }} catch (e) {{}}
document.body.insertAdjacentText('beforeend', ' rtc=' + typeof RTCPeerConnection);
</script></body></html>""".encode()
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if parts.path == "/page" else "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    origin = serve(Origin)
    op = origin.server_address[1]
    monkeypatch.setattr(rb, "ALLOWED_SUFFIXES", ("localhost",))
    monkeypatch.setattr(rb, "ALLOWED_SCHEMES", ("http",))
    monkeypatch.setattr(rb, "ALLOWED_PORTS", (op,))
    monkeypatch.setattr(rb, "MAX_RESPONSE_BYTES", 200_000)
    yield f"http://localhost:{op}", hits
    origin.shutdown()
    sink.shutdown()


def read(url: str, **kwargs) -> dict:
    async def go():
        browser = rb.ResearchBrowser(str(CHROME), sandbox=False)
        try:
            return await browser.read_page(url, **kwargs)
        finally:
            await browser.close()
    return asyncio.run(go())


def test_page_reads_but_nothing_reaches_the_sink(servers):
    base, hits = servers
    data = read(f"{base}/page")
    assert "Selic de teste" in data["text"] and data["title"] == "Fonte oficial"
    assert "rtc=undefined" in data["text"]  # WebRTC indisponível para a página
    # imagem direta, saltos de redirecionamento, nome fora da lista e WebSocket: recusados na guarda
    assert {"127.0.0.1", "sink.test"} <= set(data["blocked_requests"])
    assert hits == [], f"o sink recebeu {hits}"


def test_redirect_navigation_off_allowlist_never_leaves(servers):
    base, hits = servers
    with pytest.raises(rb.BlockedURL):
        read(f"{base}/redir?to=http://127.0.0.1:1/leak-nav%3Fd%3DSECRET")
    assert hits == []


def test_redirect_inside_allowlist_is_followed(servers):
    base, hits = servers
    data = read(f"{base}/hop")
    assert data["url"].endswith("/page") and "Selic de teste" in data["text"]
    assert hits == []


def test_oversized_response_is_refused(servers):
    base, _ = servers
    with pytest.raises(Exception):
        read(f"{base}/big")


def test_owner_context_only_exact_hosts_without_query():
    rb.validate_url("https://www.bcb.gov.br/controleinflacao/historicotaxasjuros", owner_context=True)
    for url in ("https://r9999-00-d1111-00.gov.br/x", "https://www.bcb.gov.br/x?renda=9999.00",
                "https://dados.gov.br/", "https://www.gov.br:8443/"):
        with pytest.raises(rb.BlockedURL):
            rb.validate_url(url, owner_context=True)
    rb.validate_url("https://dados.gov.br/x?formato=json")  # sem dados do dono (papel de pesquisa): sufixo basta


def test_request_allowed_checks_port_and_scheme():
    assert rb.request_allowed("https://www.gov.br/x", "GET")
    assert not rb.request_allowed("https://www.gov.br:8443/x", "GET")
    assert not rb.request_allowed("http://www.gov.br/x", "GET")
    assert not rb.request_allowed("https://u:p@www.gov.br/x", "GET")
    assert not rb.request_allowed("https://www.gov.br/x", "POST")
    assert not rb.request_allowed("wss://www.gov.br/x", "GET")
