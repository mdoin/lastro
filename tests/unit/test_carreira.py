# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caçador de vagas sem rede: regras do dono, parsers das fontes e aviso por WhatsApp (httpx.MockTransport)."""
import asyncio
import json
from datetime import datetime

import httpx
import pytest

from app import db
from carreira import hunter, match, sources


def job(title, workplace="remoto", location="", source="gupy", salary=None, currency=None, description=""):
    return sources.Job(id=f"{source}:{title}", source=source, url="https://x.example/vaga", title=title, company="ACME",
                       location=location, workplace=workplace, salary_min=salary, currency=currency,
                       description=description, published_at=None)


@pytest.mark.parametrize("vaga, verdict", [
    (job("Desenvolvedor Python Júnior", description="LLM, RAG e SQL"), "compativel"),
    (job("AI Engineer Jr", location="LATAM", source="remoteok", description="python agents"), "compativel"),
    (job("Engenheiro de Software Pleno", description="python"), "talvez"),
    (job("Software Engineer", location="Remote", source="remoteok"), "talvez"),
    (job("Desenvolvedor Júnior", "hibrido", "Cambé, Paraná", description="python"), "talvez"),
    (job("Desenvolvedor Júnior", "presencial", "Londrina, Paraná"), "talvez"),
    (job("Desenvolvedor Júnior", "presencial", "Cambé, Paraná"), "fora"),  # presencial só em Londrina
    (job("Desenvolvedor Júnior", "hibrido", "Curitiba, Paraná"), "fora"),
    (job("AI Engineer Junior", location="USA only", source="remotive"), "fora"),
    (job("Senior Python Developer"), "fora"),
    (job("Tech Lead de Dados"), "fora"),
    (job("Executivo de Vendas"), "fora"),
    (job("Analista de TI Júnior"), "talvez"),
    (job("Analista de Suporte", salary=6000, currency="BRL"), "compativel"),
    (job("Analista de Infraestrutura", salary=4000, currency="BRL"), "fora"),
    (job("Desenvolvedor Júnior", salary=3000, currency="BRL"), "fora"),
    (job("Desenvolvedor Júnior", salary=3000, currency="USD", description="python"), "compativel"),
])
def test_regras_do_dono(vaga, verdict):
    assert match.evaluate(vaga)[0] == verdict


GUPY_PAGE = """<html><script id="__NEXT_DATA__" type="application/json">%s</script></html>""" % json.dumps(
    {"props": {"pageProps": {"initialJobList": {"data": [
        {"id": 7, "name": "Dev &amp; IA <b>Jr</b>", "careerPageName": "Empresa", "workplaceType": "hybrid",
         "city": "Londrina", "state": "Paraná", "jobUrl": "https://empresa.gupy.io/job/7", "description": "<p>Python</p>",
         "publishedDate": "2026-11-01T00:00:00Z"}]}}}})


def test_parse_gupy():
    [vaga] = sources.parse_gupy(GUPY_PAGE)
    assert vaga["id"] == "gupy:7" and vaga["title"] == "Dev & IA Jr" and vaga["workplace"] == "hibrido"
    assert vaga["location"] == "Londrina, Paraná" and vaga["description"] == "Python"
    with pytest.raises(ValueError):
        sources.parse_gupy("<html>mudou</html>")


def test_link_fora_de_https_e_recusado():
    with pytest.raises(ValueError):
        sources.parse_remoteok([{"legal": "aviso"}, {"id": 1, "url": "javascript:alert(1)", "position": "Dev"}])


def handler(sent):
    def respond(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "portal.gupy.io":
            return httpx.Response(200, text=GUPY_PAGE)
        if host == "remoteok.com":
            return httpx.Response(200, json=[{"legal": "x"}, {"id": 9, "url": "https://remoteok.com/9",
                                                               "position": "AI Engineer Junior", "company": "Co",
                                                               "location": "Worldwide", "description": "python llm"}])
        if host == "remotive.com":
            return httpx.Response(503)
        if host == "evo.example":
            sent.append((request.url.path, request.headers["apikey"], json.loads(request.content)))
            return httpx.Response(201, json={"ok": True})
        raise AssertionError(f"rede inesperada: {request.url}")
    return respond


def test_ciclo_guarda_avisa_uma_vez_e_respeita_horario(monkeypatch, tmp_path):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(hunter.asyncio, "sleep", lambda _s: real_sleep(0))
    for k, v in {"EVOLUTION_URL": "https://evo.example", "EVOLUTION_KEY": "k", "EVOLUTION_INSTANCE": "inst",
                 "WHATSAPP_TO": "5543988273960"}.items():
        monkeypatch.setenv(f"CARREIRA_{k}", v)
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    sent = []
    noon, night = datetime(2026, 11, 5, 12, tzinfo=hunter.TZ), datetime(2026, 11, 5, 23, tzinfo=hunter.TZ)

    async def cycle(now):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler(sent))) as client:
            return await hunter.run_once(conn, client, now)

    first = asyncio.run(cycle(night))
    assert first["novas"] == 2 and first["aviso"] == "fora do horário" and not sent
    assert any(e.startswith("remotive") for e in first["erros"])  # fonte fora do ar não derruba o ciclo
    assert asyncio.run(cycle(noon))["aviso"] == "2 enviada(s)"
    [(path, key, body)] = sent
    assert path == "/message/sendText/inst" and key == "k" and body["number"] == "5543988273960"
    assert "AI Engineer Junior" in body["text"] and "https://empresa.gupy.io/job/7" in body["text"]
    assert asyncio.run(cycle(noon))["aviso"] == "sem novidade" and len(sent) == 1


def test_evolution_exige_https(monkeypatch):
    for k, v in {"EVOLUTION_URL": "http://1.2.3.4:8080", "EVOLUTION_KEY": "k", "EVOLUTION_INSTANCE": "i",
                 "WHATSAPP_TO": "5543988273960"}.items():
        monkeypatch.setenv(f"CARREIRA_{k}", v)
    with pytest.raises(ValueError):
        hunter.evolution_config()
