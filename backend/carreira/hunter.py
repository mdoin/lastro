# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caçador de vagas (serviço lastro-carreira): busca nas fontes públicas, avalia pelas regras e avisa no WhatsApp.

Não usa modelo de IA nem conta do dono. O aviso sai pela Evolution API do próprio dono (outro servidor), configurada
em /etc/meu-patrimonio/carreira.env; sem ela, as vagas ficam guardadas como "nova" e saem no próximo aviso possível.

Uso: python -m carreira.hunter [--loop]
"""

import argparse
import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app import db

from app.mentor_client import MentorClient

from . import alfaiate, carteiro, conversa, match, sources

log = logging.getLogger("lastro.carreira")
INTERVAL_SECONDS = 6 * 3600
TZ = ZoneInfo("America/Sao_Paulo")
NOTIFY_HOURS = range(8, 21)  # não acorda o dono de madrugada
MAX_PER_DIGEST = (8, 4)  # compatíveis, talvez


async def fetch_all(client: httpx.AsyncClient) -> tuple[list[sources.Job], list[str]]:
    calls = [(f"gupy:{t}", sources.gupy(client, t)) for t in match.GUPY_TERMS]
    calls += [(f"remotive:{t}", sources.remotive(client, t)) for t in match.REMOTIVE_TERMS]
    calls.append(("remoteok", sources.remoteok(client)))
    calls += [(f"linkedin:{t}@{where}", sources.linkedin(client, t, where, remote))
              for t, where, remote in match.LINKEDIN_SEARCHES]
    calls += [(f"catho:{t}", sources.catho(client, t)) for t in match.CATHO_TERMS]
    calls += [(f"programathor:{t}", sources.programathor(client, t)) for t in match.PROGRAMATHOR_TERMS]
    jobs, errors = {}, []
    for name, call in calls:
        try:
            for job in await call:
                jobs[job["id"]] = job
        except Exception as exc:  # noqa: BLE001 — uma fonte fora do ar não derruba as outras
            errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:120]}")
        await asyncio.sleep(1)
    return list(jobs.values()), errors


def store(conn, jobs: list[sources.Job]) -> int:
    now, new = db.utcnow(), 0
    for job in jobs:
        verdict, score, reasons = match.evaluate(job)
        new += conn.execute("SELECT 1 FROM carreira_vagas WHERE id = ?", (job["id"],)).fetchone() is None
        conn.execute(
            """INSERT INTO carreira_vagas (id, source, url, title, company, location, workplace, salary_min, currency,
                   description, published_at, verdict, score, reasons_json, first_seen, last_seen)
               VALUES (:id, :source, :url, :title, :company, :location, :workplace, :salary_min, :currency,
                   :description, :published_at, :verdict, :score, :reasons, :now, :now)
               ON CONFLICT (id) DO UPDATE SET url = excluded.url, title = excluded.title, company = excluded.company,
                   location = excluded.location, workplace = excluded.workplace, salary_min = excluded.salary_min,
                   currency = excluded.currency, description = excluded.description, verdict = excluded.verdict,
                   score = excluded.score, reasons_json = excluded.reasons_json, last_seen = excluded.last_seen""",
            {**job, "verdict": verdict, "score": score, "reasons": json.dumps(reasons, ensure_ascii=False), "now": now})
    return new


def pending_digest(conn) -> tuple[str, list[str]] | None:
    picked = []
    for verdict, limit in zip(("compativel", "talvez"), MAX_PER_DIGEST):
        picked += conn.execute(
            "SELECT v.rowid AS n, v.*, c.aderencia, c.resumo FROM carreira_vagas v LEFT JOIN carreira_candidaturas c "
            "ON c.vaga_id = v.id WHERE v.status = 'nova' AND v.verdict = ? ORDER BY v.score DESC, v.first_seen "
            "LIMIT ?", (verdict, limit)).fetchall()
    if not picked:
        return None
    lines = [f"*Lastro · Carreira* — {len(picked)} vaga(s) nova(s)"]
    for verdict, header in (("compativel", "Compatíveis"), ("talvez", "Vale conferir")):
        rows = [r for r in picked if r["verdict"] == verdict]
        if rows:
            lines.append(f"\n*{header}*")
        for row in rows:
            fit = (f"\n   Aderência {row['aderencia']}%: {row['resumo'][:200]} (*cv {row['n']}*, *treinar {row['n']}*)"
                   if row["aderencia"] is not None else "")
            lines.append(f"#{row['n']} {row['title'][:120]} — {row['company'][:60] or 'empresa não informada'}\n"
                         f"   {'; '.join(json.loads(row['reasons_json']))}{fit}\n   {row['url']}")
    return "\n".join(lines), [r["id"] for r in picked]


def evolution_config() -> dict | None:
    cfg = {k: os.environ.get(f"CARREIRA_{k.upper()}", "").strip() for k in ("evolution_url", "evolution_key",
                                                                            "evolution_instance", "whatsapp_to")}
    if not all(cfg.values()):
        return None
    url = cfg["evolution_url"]
    local = re.match(r"http://(127\.0\.0\.1|localhost)(:\d+)?(/|$)", url)  # Evolution no mesmo servidor
    if not (url.startswith("https://") or local):
        raise ValueError("CARREIRA_EVOLUTION_URL precisa ser https:// (a chave da API não pode trafegar aberta), "
                         "ou http://127.0.0.1 com a Evolution neste servidor")
    if not re.fullmatch(r"\d{12,13}", cfg["whatsapp_to"]):
        raise ValueError("CARREIRA_WHATSAPP_TO: só dígitos com DDI e DDD, ex.: 5543999999999")
    return cfg


async def send_whatsapp(client: httpx.AsyncClient, cfg: dict, message: str) -> None:
    url = f"{cfg['evolution_url'].rstrip('/')}/message/sendText/{cfg['evolution_instance']}"
    # "text" é o formato da Evolution v2; "textMessage" o da v1. Mandar os dois serve às duas versões.
    response = await client.post(url, headers={"apikey": cfg["evolution_key"]},
                                 json={"number": cfg["whatsapp_to"], "text": message, "textMessage": {"text": message}})
    response.raise_for_status()


async def run_once(conn, client: httpx.AsyncClient, now: datetime | None = None, mentor: MentorClient | None = None) -> dict:
    jobs, errors = await fetch_all(client)
    summary = {"vistas": len(jobs), "novas": store(conn, jobs), "erros": errors, "aviso": "sem novidade"}
    if mentor is not None:
        summary["curriculos"] = len(await alfaiate.tailor_pending(conn, mentor))
    digest = pending_digest(conn)
    if digest is None:
        return summary
    if (now or datetime.now(TZ)).hour not in NOTIFY_HOURS:
        summary["aviso"] = "fora do horário"
        return summary
    cfg = evolution_config()
    if cfg is None:
        summary["aviso"] = "WhatsApp não configurado"
        return summary
    message, ids = digest
    await send_whatsapp(client, cfg, message)
    conn.executemany("UPDATE carreira_vagas SET status = 'avisada' WHERE id = ?", [(i,) for i in ids])
    summary["aviso"] = f"{len(ids)} enviada(s)"
    return summary


async def chat_forever(conn, mentor: MentorClient | None) -> None:
    """Responde às mensagens do dono no WhatsApp (comandos e Treinador)."""
    while True:
        try:
            cfg = evolution_config()
            if cfg:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
                    await conversa.poll_once(conn, client, cfg, mentor, lambda text: send_whatsapp(client, cfg, text))
        except Exception:  # noqa: BLE001 — Evolution fora do ar: tenta de novo na próxima volta
            log.exception("conversa falhou")
        await asyncio.sleep(conversa.POLL_SECONDS)


async def mail_forever(conn, mentor: MentorClient) -> None:
    """Lê os e-mails de vagas (Carteiro) e avisa no WhatsApp o que pede ação."""
    while True:
        try:
            cfg = evolution_config()
            if cfg and datetime.now(TZ).hour in NOTIFY_HOURS:
                notices = await carteiro.run_once(conn, mentor, lambda jobs: store(conn, jobs))
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
                    for text in notices:
                        await send_whatsapp(client, cfg, text)
        except Exception:  # noqa: BLE001 — Gmail ou Evolution fora do ar: tenta de novo na próxima volta
            log.exception("carteiro falhou")
        await asyncio.sleep(carteiro.POLL_SECONDS)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):  # a URL da Evolution leva o nome da instância: fora do log
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="lastro-carreira")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    conn = db.connect(Path(os.environ.get("LASTRO_DB", "/var/lib/patrimonio/lastro.db")))
    db.migrate(conn)
    socket = os.environ.get("LASTRO_MENTOR_SOCKET")
    mentor = MentorClient(Path(socket)) if socket else None  # sem o worker, só caça e avisa
    tasks = [asyncio.create_task(chat_forever(conn, mentor))] if args.loop else []  # noqa: F841 — mantém a referência
    if args.loop and mentor is not None:
        tasks.append(asyncio.create_task(mail_forever(conn, mentor)))
    while True:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
            try:
                log.info("ciclo: %s", await run_once(conn, client, mentor=mentor))
            except Exception:  # noqa: BLE001 — o serviço segue; o próximo ciclo tenta de novo
                log.exception("ciclo falhou")
        if not args.loop:
            return
        await asyncio.sleep(int(os.environ.get("CARREIRA_INTERVAL", INTERVAL_SECONDS)))


if __name__ == "__main__":
    asyncio.run(main())
