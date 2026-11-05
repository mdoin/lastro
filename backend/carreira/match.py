# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regras do dono para vagas, determinísticas (sem modelo): cargo, senioridade, local e salário.

- Remoto: Brasil todo ou internacional, desde que a vaga aceite quem mora no Brasil.
- Híbrido só em Londrina/Cambé; presencial só em Londrina; nos dois casos salário ≥ piso ou empresa grande.
- Cargos: AI Engineer, Software Engineer/Developer, Python, dados, automação; júnior ou estágio de preferência.
"""

import re

from .sources import Job

MIN_SALARY_BRL = 5000
GUPY_TERMS = ("python", "inteligência artificial", "desenvolvedor júnior", "engenheiro de software júnior",
              "dados júnior", "estágio desenvolvimento", "llm", "analista de ti", "analista de sistemas")
REMOTIVE_TERMS = ("python", "ai engineer", "llm")
LINKEDIN_SEARCHES = (("python", "Brasil", True), ("inteligência artificial", "Brasil", True),
                     ("desenvolvedor", "Londrina, Paraná", False), ("analista de ti", "Londrina, Paraná", False))
CATHO_TERMS = ("python", "desenvolvedor junior", "inteligencia artificial", "analista de ti")
PROGRAMATHOR_TERMS = ("python",)


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


ROLE = _rx(r"python|\bia\b|\bai\b|\bllm|machine learning|\bml\b|intelig[eê]ncia artificial|software|desenvolvedor|"
           r"desenvolviment|developer|programador|engenheir|engineer|\bdados\b|\bdata\b|automa[çc]|\brpa\b|back[- ]?end|"
           r"full[- ]?stack")
# TI geral (suporte, infraestrutura, sistemas, QA): só interessa se pagar bem, então nunca passa de "talvez" sem salário.
IT_ROLE = _rx(r"\bti\b|t\.i\.?|analista de sistemas|suporte|infraestrutura|redes|help ?desk|service desk|devops|"
              r"sysadmin|cloud|\bqa\b|qualidade de software|\btestes?\b|tecnologia da informa[çc][ãa]o")
NOT_ROLE = _rx(r"sales|vendas|comercial|civil|mec[aâ]nic|el[eé]tric|qu[ií]mic|seguran[çc]a do trabalho|marketing|"
               r"designer|data entry|digita[çc]|neg[óo]cios")
SENIOR = _rx(r"s[eê]nior|\bsr\b|staff|principal|\blead\b|l[ií]der|\bhead\b|director|diretor|manager|gerente|"
             r"coordenador|especialista|\biii\b|\biv\b")
PLENO = _rx(r"pleno|\bpl\b|mid[- ]level|\bii\b")
JUNIOR = _rx(r"j[uú]nior|\bjr\b|est[aá]gi|\bintern(ship)?\b|trainee|entry[- ]level|graduate|aprendiz")
REMOTE_OK = _rx(r"^\s*remot[eo]\s*$|worldwide|anywhere|global|latam|latin america|south america|americas|brazil|brasil")
# Sites brasileiros: o local de uma vaga remota é a cidade da empresa, não onde a pessoa precisa morar.
BR_SOURCES = ("gupy", "catho", "programathor")
HYBRID_CITIES = _rx(r"londrina|camb[eé]")
ONSITE_CITIES = _rx(r"londrina")
SKILLS = {name: _rx(p) for name, p in {
    "Python": r"python", "SQL": r"\bsql\b|postgres", "LLM": r"\bllms?\b|\bgpt|openai|claude|anthropic",
    "RAG": r"\brag\b", "MCP": r"\bmcp\b|model context protocol", "agentes": r"\bagent(e|es|s)?\b|\bagentic",
    "prompt": r"prompt", "IA": r"\bia\b|\bai\b|intelig[eê]ncia artificial|machine learning",
    "FastAPI": r"fastapi", "visão computacional": r"vis[ãa]o computacional|computer vision|yolo",
    "automação": r"automa[çc]|playwright|\brpa\b"}.items()}


def evaluate(job: Job) -> tuple[str, int, list[str]]:
    """(veredito, pontuação, motivos). Veredito: compativel | talvez | fora."""
    title, reasons = job["title"], []
    it_only = not ROLE.search(title) and bool(IT_ROLE.search(title))
    if not (ROLE.search(title) or it_only) or NOT_ROLE.search(title):
        return "fora", 0, ["cargo fora da área"]
    if SENIOR.search(title):
        return "fora", 0, ["senioridade acima de júnior"]

    place, workplace = job["location"], job["workplace"]
    firm = False  # local confirmado sem depender de salário/porte
    if workplace == "remoto":
        if place and job["source"] not in BR_SOURCES and not REMOTE_OK.search(place):
            return "fora", 0, [f"remoto restrito a {place}"]
        firm = True
        reasons.append("remoto" + (f" ({place})" if place else ""))
    elif workplace == "hibrido" and HYBRID_CITIES.search(place):
        reasons.append(f"híbrido em {place}: confirmar salário ≥ {MIN_SALARY_BRL} ou empresa grande")
    elif workplace in ("presencial", "desconhecido") and ONSITE_CITIES.search(place):
        reasons.append(f"{workplace} em {place}: confirmar salário ≥ {MIN_SALARY_BRL} ou empresa grande")
    else:
        return "fora", 0, [f"{workplace} em {place or 'local não informado'}"]

    if job["salary_min"] is not None and (job["currency"] or "BRL") == "BRL" and job["salary_min"] < MIN_SALARY_BRL:
        return "fora", 0, [f"salário abaixo de {MIN_SALARY_BRL}"]

    corpus = f"{title} {job['description']}"
    skills = [name for name, rx in SKILLS.items() if rx.search(corpus)]
    junior, pleno = bool(JUNIOR.search(title)), bool(PLENO.search(title))
    score = 10 * min(len(skills), 6) + (25 if junior else 0) - (20 if pleno else 0)
    if skills:
        reasons.append("pede " + ", ".join(skills))
    if junior:
        reasons.append("júnior/estágio")
    if pleno:
        reasons.append("pleno: um degrau acima")
    verdict = "compativel" if firm and junior and skills else "talvez"
    if it_only:
        pays = job["salary_min"] is not None  # abaixo do piso em BRL já saiu acima
        reasons.append("TI geral: " + ("salário publicado acima do piso" if pays else "só vale se pagar bem"))
        verdict = "compativel" if firm and pays else "talvez"
    return verdict, score, reasons
