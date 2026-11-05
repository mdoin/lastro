# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fontes públicas de vagas, sem login: Gupy (página de busca), RemoteOK e Remotive (APIs públicas).

Cada fonte devolve dicionários no mesmo formato (`Job`). Tudo que vem daqui é texto de terceiros: vai para o banco
e para o aviso como dado, nunca como instrução. Poucas requisições: uma busca por termo a cada ciclo.
"""

import html
import json
import re
from typing import TypedDict
from urllib.parse import quote

import httpx

MAX_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTION = 6000
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Lastro/0.4 (uso pessoal)"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAG = re.compile(r"<[^>]+>")


class Job(TypedDict):
    id: str
    source: str
    url: str
    title: str
    company: str
    location: str
    workplace: str  # remoto | hibrido | presencial | desconhecido
    salary_min: float | None
    currency: str | None
    description: str
    published_at: str | None


def text(value) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", str(value or "")))).strip()


def _https(url) -> str:
    url = str(url or "")
    if not url.startswith("https://"):
        raise ValueError(f"link fora de https: {url[:80]}")
    return url


async def _get(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if len(response.content) > MAX_BYTES:
        raise ValueError(f"resposta grande demais de {url}")
    return response.text


GUPY_WORKPLACE = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial"}


def parse_gupy(page: str) -> list[Job]:
    match = _NEXT_DATA.search(page)
    if not match:
        raise ValueError("página da Gupy sem __NEXT_DATA__ (o site mudou?)")
    data = json.loads(match.group(1))["props"]["pageProps"].get("initialJobList") or {}
    jobs = []
    for item in data.get("data") or []:
        jobs.append(Job(
            id=f"gupy:{int(item['id'])}", source="gupy", url=_https(item.get("jobUrl")), title=text(item.get("name")),
            company=text(item.get("careerPageName")),
            location=", ".join(p for p in (text(item.get("city")), text(item.get("state"))) if p),
            workplace=GUPY_WORKPLACE.get(item.get("workplaceType"), "desconhecido"), salary_min=None, currency=None,
            description=text(item.get("description"))[:MAX_DESCRIPTION], published_at=item.get("publishedDate")))
    return jobs


async def gupy(client: httpx.AsyncClient, term: str) -> list[Job]:
    return parse_gupy(await _get(client, f"https://portal.gupy.io/job-search/term={quote(term)}"))


def parse_remoteok(payload: list) -> list[Job]:
    jobs = []
    for item in payload:
        if not isinstance(item, dict) or "id" not in item:
            continue  # o primeiro item é o aviso legal da API
        salary = item.get("salary_min") or None
        jobs.append(Job(
            id=f"remoteok:{item['id']}", source="remoteok", url=_https(item.get("url")),
            title=text(item.get("position")), company=text(item.get("company")),
            location=text(item.get("location")), workplace="remoto",
            salary_min=float(salary) if salary else None, currency="USD" if salary else None,
            description=text(item.get("description"))[:MAX_DESCRIPTION], published_at=item.get("date")))
    return jobs


async def remoteok(client: httpx.AsyncClient) -> list[Job]:
    return parse_remoteok(json.loads(await _get(client, "https://remoteok.com/api")))


def parse_remotive(payload: dict) -> list[Job]:
    return [Job(
        id=f"remotive:{item['id']}", source="remotive", url=_https(item.get("url")), title=text(item.get("title")),
        company=text(item.get("company_name")), location=text(item.get("candidate_required_location")),
        workplace="remoto", salary_min=None, currency=None,  # salário vem como texto livre: não confiável
        description=text(item.get("description"))[:MAX_DESCRIPTION], published_at=item.get("publication_date"))
        for item in payload.get("jobs") or []]


async def remotive(client: httpx.AsyncClient, term: str) -> list[Job]:
    return parse_remotive(json.loads(await _get(client, f"https://remotive.com/api/remote-jobs?search={quote(term)}")))


def _first(pattern: str, chunk: str) -> str:
    found = re.search(pattern, chunk, re.S)
    return text(found.group(1)) if found else ""


def parse_linkedin(page: str, workplace: str) -> list[Job]:
    """Busca pública do LinkedIn (jobs-guest), sem login. `workplace` vem do filtro usado na busca."""
    jobs = []
    for chunk in page.split("<li")[1:]:
        job_id = _first(r'urn:li:jobPosting:(\d+)', chunk)
        if not job_id:
            continue
        jobs.append(Job(
            id=f"linkedin:{job_id}", source="linkedin", url=f"https://www.linkedin.com/jobs/view/{job_id}/",
            title=_first(r'base-search-card__title[^>]*>(.*?)</h3>', chunk),
            company=_first(r'base-search-card__subtitle[^>]*>(.*?)</h4>', chunk),
            location=_first(r'job-search-card__location[^>]*>(.*?)</span>', chunk), workplace=workplace,
            salary_min=None, currency=None, description="", published_at=_first(r'datetime="([^"]+)"', chunk) or None))
    return jobs


async def linkedin(client: httpx.AsyncClient, term: str, location: str, remote: bool) -> list[Job]:
    query = f"keywords={quote(term)}&location={quote(location)}&f_E=1%2C2" + ("&f_WT=2" if remote else "")
    page = await _get(client, f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{query}")
    return parse_linkedin(page, "remoto" if remote else "desconhecido")


REMOTE_TITLE = re.compile(r"work from home|trabalhe de casa|home office|remot[oa]", re.I)


def parse_brl(value: str) -> float | None:
    found = re.search(r"R\$\s*([\d.]+)(?:,\d{2})?", value)
    return float(found.group(1).replace(".", "")) if found else None


def parse_catho(page: str) -> list[Job]:
    jobs = []
    for chunk in re.findall(r'<li data-offer-item="\d+".*?</article>', page, re.S):
        title = _first(r'class="title_offer">\s*<a[^>]*>(.*?)</a>', chunk)
        salary = parse_brl(_first(r'i_salary"></span>\s*<strong>(.*?)</strong>', chunk))
        jobs.append(Job(
            id=f"catho:{_first(r'data-offer-item=\"(\d+)\"', chunk)}", source="catho",
            url="https://www.catho.com.br" + _first(r'class="title_offer">\s*<a href="(/vagas/[^"]+)"', chunk),
            title=title, company=_first(r'<span class="text-12">(.*?)</span>', chunk),
            location=_first(r'</strong>\s*-\s*([^<]+)', chunk),
            workplace="remoto" if REMOTE_TITLE.search(title) else "desconhecido",
            salary_min=salary, currency="BRL" if salary else None, description="", published_at=None))
    return [j for j in jobs if j["title"] and j["id"] != "catho:"]


async def catho(client: httpx.AsyncClient, term: str) -> list[Job]:
    return parse_catho(await _get(client, f"https://www.catho.com.br/vagas/{quote(term.replace(' ', '-'))}/"))


def parse_programathor(page: str) -> list[Job]:
    jobs = []
    for chunk in page.split('<a href="/jobs/')[1:]:
        slug = chunk.split('"', 1)[0]
        if not re.match(r"\d+-", slug):
            continue
        spans = [text(s) for s in re.findall(r"</i>(.*?)</span>", chunk.split("</a>", 1)[0], re.S)]
        company, place, size, level = (spans + ["", "", "", ""])[:4]
        title = _first(r"<h3[^>]*>(.*?)</h3>", chunk)
        if title.startswith("Vencida"):
            continue
        if level and level.lower() not in title.lower():
            title = f"{title} ({level})"  # o nível vem à parte; as regras de senioridade leem o título
        remote = place.lower() == "remoto"
        jobs.append(Job(
            id=f"programathor:{slug.split('-', 1)[0]}", source="programathor",
            url=f"https://programathor.com.br/jobs/{slug}", title=title, company=company,
            location="" if remote else place, workplace="remoto" if remote else "desconhecido", salary_min=None,
            currency=None, description=size, published_at=None))
    return jobs


async def programathor(client: httpx.AsyncClient, term: str) -> list[Job]:
    return parse_programathor(await _get(client, f"https://programathor.com.br/jobs-{quote(term)}"))
