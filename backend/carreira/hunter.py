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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app import db

from app.mentor_client import MentorClient

from . import alfaiate, candidatura, carteiro, conversa, match, registro, sources

log = logging.getLogger("lastro.carreira")
INTERVAL_SECONDS = 6 * 3600
TZ = ZoneInfo("America/Sao_Paulo")
NOTIFY_HOURS = range(8, 21)  # não acorda o dono de madrugada
MAX_PER_DIGEST = (8, 4)  # compatíveis, talvez
FILA_SECONDS = 1800  # a fila (currículo + candidatura) roda bem mais vezes que a busca
RESUMO_HOUR = 20  # resumo diário no WhatsApp, na primeira volta da fila a partir desta hora


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
        is_new = conn.execute("SELECT 1 FROM carreira_vagas WHERE id = ?", (job["id"],)).fetchone() is None
        conn.execute(
            """INSERT INTO carreira_vagas (id, source, url, title, company, location, workplace, salary_min, currency,
                   description, published_at, verdict, score, reasons_json, first_seen, last_seen, url_canonica, chave)
               VALUES (:id, :source, :url, :title, :company, :location, :workplace, :salary_min, :currency,
                   :description, :published_at, :verdict, :score, :reasons, :now, :now, :url_canonica, :chave)
               ON CONFLICT (id) DO UPDATE SET url = excluded.url, title = excluded.title, company = excluded.company,
                   location = excluded.location, workplace = excluded.workplace, salary_min = excluded.salary_min,
                   currency = excluded.currency, description = excluded.description, verdict = excluded.verdict,
                   score = excluded.score, reasons_json = excluded.reasons_json, last_seen = excluded.last_seen,
                   url_canonica = excluded.url_canonica, chave = excluded.chave""",
            {**job, "verdict": verdict, "score": score, "reasons": json.dumps(reasons, ensure_ascii=False), "now": now,
             "url_canonica": registro.url_canonica(job["url"]),
             "chave": registro.chave(job["company"], job["title"], job["location"], job["workplace"])})
        if is_new:
            new += 1
            registro.evento(conn, job["id"], "descoberta", "cacador", fonte=job["source"], veredito=verdict,
                            pontuacao=score, motivos=reasons)
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


async def run_once(conn, client: httpx.AsyncClient, now: datetime | None = None) -> dict:
    """Busca e aviso de vagas novas. Currículo e candidatura ficam na fila (fila_forever), que roda mais vezes."""
    with registro.execucao(conn, "busca") as run:
        jobs, errors = await fetch_all(client)
        summary = {"vistas": len(jobs), "novas": store(conn, jobs), "erros": errors, "aviso": "sem novidade"}
        run["resultado"] = f"{summary['vistas']} vistas, {summary['novas']} novas"
        if errors:  # fonte fora do ar não é falha da busca: fica como aviso no resultado
            run["resultado"] += f"; {len(errors)} fonte(s) com erro: " + "; ".join(e.split(":")[0] for e in errors[:6])
    registro.sincronizar_base(conn)
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


def reavaliar(conn) -> int:
    """Aplica as regras atuais às vagas guardadas (as que vieram por e-mail não voltam pela busca). Devolve as mudadas."""
    changed = []
    for row in conn.execute("SELECT * FROM carreira_vagas").fetchall():
        verdict, score, reasons = match.evaluate(dict(row))
        if (verdict, score) != (row["verdict"], row["score"]):
            changed.append((verdict, score, json.dumps(reasons, ensure_ascii=False), row["id"]))
    conn.executemany("UPDATE carreira_vagas SET verdict = ?, score = ?, reasons_json = ? WHERE id = ?", changed)
    return len(changed)


def _estado(conn, chave: str, valor: str) -> None:
    conn.execute("INSERT INTO carreira_estado (chave, valor) VALUES (?, ?) "
                 "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor", (chave, valor))


def texto_resumo(r: dict) -> str:
    lines = ["*Lastro · Carreira* — resumo do dia",
             f"Vagas encontradas: {r['encontradas']} ({r['elegiveis']} elegíveis) · currículos feitos: {r['curriculos']}",
             f"Candidaturas tentadas: {r['tentativas']} · *enviadas e confirmadas: {r['confirmadas']}*",
             f"Sem confirmação: {r['incertas']} · precisaram de você: {r['intervencoes']} · falhas: {r['falhas']} · "
             f"não aplicáveis: {r['nao_aplicaveis']}"]
    if r["aguardando_voce"] or r["a_conferir"]:
        lines.append(f"Esperando você: {r['aguardando_voce']} pendência(s) e {r['a_conferir']} envio(s) a conferir "
                     "(Lastro → Carreira → Visão geral)")
    return "\n".join(lines)


async def fila_once(conn, mentor: MentorClient) -> list[str]:
    """Uma volta da fila: currículo das elegíveis e candidaturas, as de maior aderência primeiro. Devolve os avisos."""
    await alfaiate.tailor_pending(conn, mentor)
    return await candidatura.apply_pending(conn, mentor)


async def fila_forever(conn, mentor: MentorClient) -> None:
    """Processa a fila o dia todo (de dia: o aviso de "preciso de você" chega a tempo) e manda o resumo diário."""
    await asyncio.sleep(60)  # no deploy o worker reinicia junto: espera ele abrir o socket
    while True:
        try:
            notices = await fila_once(conn, mentor) if datetime.now(TZ).hour in NOTIFY_HOURS else []
            now = datetime.now(TZ)  # a volta pode levar uma hora: a hora do resumo é conferida depois dela
            last = conn.execute("SELECT valor FROM carreira_estado WHERE chave = 'resumo_dia'").fetchone()
            if RESUMO_HOUR <= now.hour < 23 and (last is None or last[0] != now.date().isoformat()):
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
                notices.append(texto_resumo(registro.resumo(conn, midnight.isoformat(timespec="seconds"))))
                _estado(conn, "resumo_dia", now.date().isoformat())
            if notices and (cfg := evolution_config()):
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
                    for text in notices:
                        await send_whatsapp(client, cfg, text)
        except Exception:  # noqa: BLE001 — worker ou Evolution fora do ar: a fila continua na próxima volta
            log.exception("fila falhou")
        interval = int(os.environ.get("CARREIRA_FILA_INTERVAL", FILA_SECONDS))
        _estado(conn, "proxima_fila", (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat(timespec="seconds"))
        await asyncio.sleep(interval)


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
    parser.add_argument("--fila", action="store_true", help="uma volta da fila agora (fora do horário também) e sai")
    parser.add_argument("--perfil", choices=sorted(candidatura.PLATFORMS), help="atualiza o perfil nessa plataforma e sai")
    args = parser.parse_args()
    conn = db.connect(Path(os.environ.get("LASTRO_DB", "/var/lib/patrimonio/lastro.db")))
    db.migrate(conn)
    registro.interromper_pendentes(conn)
    registro.preencher_chaves(conn)
    log.info("regras: %d vaga(s) reavaliada(s)", reavaliar(conn))
    socket = os.environ.get("LASTRO_MENTOR_SOCKET")
    mentor = MentorClient(Path(socket)) if socket else None  # sem o worker, só caça e avisa
    if args.fila or args.perfil:  # operação manual (primeira execução, conferência): mesmo código do serviço
        if mentor is None:
            raise SystemExit("LASTRO_MENTOR_SOCKET não definido")
        result = (await candidatura.update_profile(mentor, args.perfil, conn) if args.perfil
                  else await fila_once(conn, mentor))
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    tasks = [asyncio.create_task(chat_forever(conn, mentor))] if args.loop else []  # noqa: F841 — mantém a referência
    if args.loop and mentor is not None:
        tasks.append(asyncio.create_task(mail_forever(conn, mentor)))
        tasks.append(asyncio.create_task(fila_forever(conn, mentor)))
    while True:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
            try:
                log.info("ciclo: %s", await run_once(conn, client))
            except Exception:  # noqa: BLE001 — o serviço segue; o próximo ciclo tenta de novo
                log.exception("ciclo falhou")
        if not args.loop:
            return
        interval = int(os.environ.get("CARREIRA_INTERVAL", INTERVAL_SECONDS))
        next_at = datetime.fromisoformat(db.utcnow()) + timedelta(seconds=interval)
        _estado(conn, "proximo_ciclo", next_at.isoformat())
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
