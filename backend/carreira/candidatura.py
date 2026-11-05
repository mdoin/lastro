# SPDX-License-Identifier: AGPL-3.0-or-later
"""Candidatura automática (fase 3): manda as melhores vagas ao agente `aplicador` do worker e registra o resultado.

Só vagas com currículo sob medida e aderência ≥ MIN_ADERENCIA, até DAILY_LIMIT tentativas por dia e
MAX_ATTEMPTS por vaga. O Aplicador para e devolve `precisa_de_voce` diante de CAPTCHA, código de verificação,
teste ou campo obrigatório sem resposta conhecida; o dono recebe o aviso no WhatsApp.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path

from app import db
from app.mentor_client import MentorClient

from . import alfaiate, sources

log = logging.getLogger("lastro.carreira")
MIN_ADERENCIA = 60
DAILY_LIMIT = 10
PER_CYCLE = 3
MAX_ATTEMPTS = 2
TIMEOUT_SECONDS = 1000
STATUS = {"enviada": "candidatada", "precisa_de_voce": "precisa_de_voce", "nao_aplicavel": "encerrada"}


def answers() -> str | None:
    path = Path(os.environ.get("CARREIRA_RESPOSTAS", "/var/lib/patrimonio/carreira/respostas.md"))
    return path.read_text(encoding="utf-8") if path.is_file() else None


def parse(output: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", output.strip())
    data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    status = data.get("status") if data.get("status") in ("enviada", "precisa_de_voce", "nao_aplicavel") else "falhou"
    url = str(data.get("url_final") or "")
    return {"status": status, "motivo": sources.text(data.get("motivo"))[:400] or "sem motivo informado",
            "url_final": url[:500] if url.startswith("https://") else "",
            "respostas": [{"pergunta": sources.text(r.get("pergunta"))[:200], "resposta": sources.text(r.get("resposta"))[:500]}
                          for r in (data.get("respostas") or [])[:40] if isinstance(r, dict)]}


def pending(conn, limit: int):
    return conn.execute(
        "SELECT v.rowid AS n, v.*, c.curriculo_md, c.carta, c.aderencia FROM carreira_candidaturas c "
        "JOIN carreira_vagas v ON v.id = c.vaga_id WHERE c.status = 'curriculo' AND c.aderencia >= ? "
        "AND (SELECT COUNT(*) FROM carreira_envios e WHERE e.vaga_id = v.id) < ? "
        "ORDER BY c.aderencia DESC, c.created_at LIMIT ?", (MIN_ADERENCIA, MAX_ATTEMPTS, limit)).fetchall()


PLATFORMS = {"gupy": "https://www.gupy.io/", "linkedin": "https://www.linkedin.com/in/me/",
             "catho": "https://www.catho.com.br/", "indeed": "https://br.indeed.com/",
             "programathor": "https://programathor.com.br/", "infojobs": "https://www.infojobs.com.br/",
             "vagas": "https://www.vagas.com.br/"}


def base_cv() -> str | None:
    path = Path(os.environ.get("CARREIRA_CURRICULO", "/var/lib/patrimonio/carreira/curriculo.md"))
    return path.read_text(encoding="utf-8") if path.is_file() else None


async def ask(mentor: MentorClient, vaga, perfil: str, respostas: str) -> dict:
    text = (f"{alfaiate.prompt(perfil, vaga)}\nLINK DA VAGA: {vaga['url']}\n\nRESPOSTAS:\n{respostas}\n\n"
            f"CARTA:\n{vaga['carta']}\n")
    return await run(mentor, text, vaga["curriculo_md"])


async def update_profile(mentor: MentorClient, platform: str) -> dict:
    """Atualiza o perfil do dono numa plataforma (modo carreira_perfil do aplicador)."""
    perfil, respostas, cv = alfaiate.profile(), answers(), base_cv()
    if None in (perfil, respostas, cv):
        raise RuntimeError("faltam perfil, respostas ou currículo base")
    text = (f"PLATAFORMA: {platform} ({PLATFORMS[platform]})\n\nPERFIL:\n{perfil}\n\nRESPOSTAS:\n{respostas}\n")
    return await asyncio.wait_for(run(mentor, text, cv, mode="carreira_perfil"), TIMEOUT_SECONDS)


async def run(mentor: MentorClient, text: str, curriculo_md: str, mode: str | None = None) -> dict:
    request = {"op": "ephemeral", "role": "aplicador", "text": text, "effort": "medium",
               "aplicacao": {"curriculo_md": curriculo_md, "nome_arquivo": "Maite-Doin-Curriculo"},
               **({"mode": mode} if mode else {})}
    output, failed = "", None
    async for event in mentor.stream(request):
        if event.get("type") == "done":
            output = event.get("text") or ""
        elif event.get("type") == "error":
            failed = event.get("message") or "falha"
    if failed or not output:
        raise RuntimeError(failed or "resposta vazia")
    return parse(output)


def notice(vaga, result: dict) -> str:
    head = f"#{vaga['n']} {vaga['title'][:100]} — {vaga['company'][:50]}"
    if result["status"] == "enviada":
        return f"*Candidatura enviada* ✅\n{head}\n{result['motivo']}"
    if result["status"] == "precisa_de_voce":
        return f"*Preciso de você* na candidatura\n{head}\n{result['motivo']}\n{result['url_final'] or vaga['url']}"
    return f"*Candidatura não feita*\n{head}\n{result['motivo']}"


async def apply_pending(conn, mentor: MentorClient) -> list[str]:
    """Tenta as próximas candidaturas. Devolve os avisos para o WhatsApp."""
    perfil, respostas = alfaiate.profile(), answers()
    if perfil is None or respostas is None:
        return []
    today = db.utcnow()[:10]
    used = conn.execute("SELECT COUNT(*) FROM carreira_envios WHERE substr(created_at, 1, 10) = ?", (today,)).fetchone()[0]
    notices = []
    for vaga in pending(conn, min(PER_CYCLE, DAILY_LIMIT - used)):
        try:
            result = await asyncio.wait_for(ask(mentor, vaga, perfil, respostas), TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 — conta como tentativa: não insiste para sempre na mesma vaga
            log.warning("aplicador falhou em %s: %s", vaga["id"], type(exc).__name__)
            result = {"status": "falhou", "motivo": f"o agente não concluiu ({type(exc).__name__})", "url_final": "",
                      "respostas": []}
        now = db.utcnow()
        conn.execute("INSERT INTO carreira_envios (vaga_id, status, motivo, url_final, respostas_json, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (vaga["id"], result["status"], result["motivo"], result["url_final"],
                                                   json.dumps(result["respostas"], ensure_ascii=False), now))
        if result["status"] in STATUS:
            conn.execute("UPDATE carreira_candidaturas SET status = ?, updated_at = ? WHERE vaga_id = ?",
                         (STATUS[result["status"]], now, vaga["id"]))
        if result["status"] != "falhou":
            notices.append(notice(vaga, result))
    return notices
