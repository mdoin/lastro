"""Interface real (frontend/dist) contra o backend real, num Chrome headless.

Nenhuma porta é aberta: cada requisição do navegador é entregue ao app ASGI dentro
do próprio processo (Playwright `route` + httpx ASGITransport). O mentor é falso.
Roda só com LASTRO_E2E=1 (precisa do Chrome em /opt/lastro-browsers e do frontend compilado).
"""
import asyncio
import re
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from test_web_app import PASSWORD, SNAP, FakeMentor  # noqa: E402

from app import auth  # noqa: E402
from app.web import Settings, create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHROME = Path("/opt/lastro-browsers/chrome-headless-shell-linux64/chrome-headless-shell")
ORIGIN = "http://lastro.test"
SHOTS = Path(os.environ.get("LASTRO_E2E_SHOTS", ROOT / ".e2e-shots"))

pytestmark = pytest.mark.skipif(os.environ.get("LASTRO_E2E") != "1" or not CHROME.exists()
                                or not (ROOT / "frontend" / "dist" / "index.html").exists(),
                                reason="defina LASTRO_E2E=1, com Chrome e frontend compilado")


async def scenario(tmp_path):
    from playwright.async_api import async_playwright, expect

    SHOTS.mkdir(parents=True, exist_ok=True)
    with FakeMentor(tmp_path / "mentor.sock"):
        app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "mentor.sock",
                                  static_dir=ROOT / "frontend" / "dist", cookie_secure=False, run_scheduler=False))
        auth.set_password(app.state.conn, PASSWORD)
        asgi = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
        external = []
        current = {}

        async def to_app(route):
            req = route.request
            if not req.url.startswith(ORIGIN):
                external.append(req.url)
                return await route.abort()
            headers = {k: v for k, v in req.headers.items() if k.lower() not in ("host", "content-length")}
            asgi.cookies.clear()  # só vale o cookie que o próprio navegador mandou
            resp = await asgi.request(req.method, req.url, headers=headers, content=req.post_data_buffer)
            # O Chromium ignora Set-Cookie de respostas interceptadas; repassamos como um navegador real faria.
            for cookie in resp.cookies.jar:
                await current["ctx"].add_cookies([{"name": cookie.name, "value": cookie.value, "url": ORIGIN,
                                                   "httpOnly": True, "sameSite": "Strict"}])
            await route.fulfill(status=resp.status_code, headers=dict(resp.headers), body=resp.content)

        async with async_playwright() as pw:
            # Página só de conteúdo local e confiável (o próprio app), sem rede externa.
            browser = await pw.chromium.launch(executable_path=str(CHROME), chromium_sandbox=False)
            results = {}
            for name, viewport in (("desktop", {"width": 1280, "height": 860}), ("celular", {"width": 390, "height": 844})):
                ctx = await browser.new_context(viewport=viewport, locale="pt-BR")
                current["ctx"] = ctx
                await ctx.route("**/*", to_app)
                page = await ctx.new_page()
                errors = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

                await page.goto(f"{ORIGIN}/")
                await expect(page).to_have_url(re.compile(r".*/login.*"), timeout=10000)
                await page.locator("input[type=password]").fill(PASSWORD)
                await page.get_by_role("button", name="Entrar").click()
                await expect(page).to_have_url(f"{ORIGIN}/", timeout=10000)
                await page.screenshot(path=str(SHOTS / f"{name}-1-visao-geral-vazia.png"), full_page=True)

                if name == "desktop":  # dados criados uma vez, pela própria interface (fetch com cookie)
                    status = await page.evaluate("""async (snap) => (await fetch('/api/snapshot', {method: 'POST',
                        credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-Lastro': '1'},
                        body: JSON.stringify(snap)})).status""", SNAP)
                    assert status == 201
                await page.reload()
                await expect(page.get_by_text("Priorizar a dívida mais cara").first).to_be_visible(timeout=10000)
                await page.screenshot(path=str(SHOTS / f"{name}-2-visao-geral.png"), full_page=True)

                await page.goto(f"{ORIGIN}/futuro")
                await expect(page.get_by_text("conservador").first).to_be_visible(timeout=10000)
                await page.screenshot(path=str(SHOTS / f"{name}-3-futuro.png"), full_page=True)

                await page.goto(f"{ORIGIN}/mentor")
                await page.locator("#composer-text").fill("O que faço com meu dinheiro este mês?")
                await page.locator("#composer-text").press("Enter")
                await expect(page.get_by_text("Pague o cartão.").first).to_be_visible(timeout=15000)
                await page.screenshot(path=str(SHOTS / f"{name}-4-mentor.png"), full_page=True)

                if name == "desktop":
                    await page.goto(f"{ORIGIN}/mentor")
                    await page.get_by_text("Painel de especialistas", exact=True).first.click()
                    await page.locator("#composer-text").fill("Invisto ou quito o cartão?")
                    await page.locator("#composer-text").press("Enter")
                    await expect(page.get_by_text("PASSA").first).to_be_visible(timeout=15000)
                    await page.screenshot(path=str(SHOTS / f"{name}-5-painel.png"), full_page=True)

                overflow = await page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
                results[name] = {"errors": [e for e in errors if "404" not in e and "401" not in e],
                                 "overflow": overflow}
                await ctx.close()
            await browser.close()
        await asgi.aclose()
        return results, external


def test_frontend_against_real_backend(tmp_path):
    results, external = asyncio.run(scenario(tmp_path))
    assert external == [], f"a interface tentou acessar origens externas: {external}"
    for name, r in results.items():
        assert r["errors"] == [], f"{name}: erros no console {r['errors']}"
        assert r["overflow"] is False, f"{name}: rolagem horizontal na página"
