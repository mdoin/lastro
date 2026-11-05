# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conversa com o dono pelo WhatsApp (fase 5): comandos e entrevista simulada com o agente `treinador`.

Lê da Evolution só as mensagens recebidas do número do dono (as do próprio bot e de qualquer outro contato são
ignoradas). Sem webhook: o serviço consulta a Evolution a cada POLL_SECONDS, sem abrir porta nenhuma.

Comandos: "vagas", "cv N", "treinar N", "parar" e "ajuda". Fora disso, durante um treino, a mensagem vai para o
Treinador; sem treino ativo, a resposta é a ajuda.
"""

import json
import logging
import re
import time
import unicodedata

import httpx

from app import db
from app.mentor_client import MentorClient

from . import alfaiate

log = logging.getLogger("lastro.carreira")
POLL_SECONDS = 20
HELP = ("*Lastro · Carreira*\n"
        "• *vagas*: candidaturas prontas, com aderência\n"
        "• *cv N*: currículo e carta da vaga N\n"
        "• *treinar N*: entrevista simulada para a vaga N\n"
        "• *parar*: encerra o treino com nota e feedback")


def owner_jids(number: str) -> set[str]:
    """O WhatsApp registra números brasileiros antigos sem o 9: aceita as duas formas."""
    forms = {number}
    if re.fullmatch(r"55\d{2}9\d{8}", number):
        forms.add(number[:4] + number[5:])
    return {f"{n}@s.whatsapp.net" for n in forms}


def message_text(record: dict) -> str:
    msg = record.get("message") or {}
    return str(msg.get("conversation") or (msg.get("extendedTextMessage") or {}).get("text") or "").strip()


async def fetch_owner_messages(client: httpx.AsyncClient, cfg: dict, since: int) -> list[tuple[int, str]]:
    url = f"{cfg['evolution_url'].rstrip('/')}/chat/findMessages/{cfg['evolution_instance']}"
    response = await client.post(url, headers={"apikey": cfg["evolution_key"]},
                                 json={"where": {"key": {"fromMe": False}}, "page": 1, "offset": 50})
    response.raise_for_status()
    data = response.json().get("messages") or {}
    jids = owner_jids(cfg["whatsapp_to"])
    found = []
    for record in data.get("records") or []:
        key = record.get("key") or {}
        stamp = int(record.get("messageTimestamp") or 0)
        if key.get("fromMe") or stamp <= since or not ({key.get("remoteJid"), key.get("remoteJidAlt")} & jids):
            continue
        if text := message_text(record):
            found.append((stamp, text[:4000]))
    return sorted(found)


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def cursor(conn) -> int:
    row = conn.execute("SELECT valor FROM carreira_estado WHERE chave = 'whatsapp_cursor'").fetchone()
    if row:
        return int(row["valor"])
    now = int(time.time())  # primeira vez: o histórico anterior não vira comando
    set_cursor(conn, now)
    return now


def set_cursor(conn, stamp: int) -> None:
    conn.execute("INSERT INTO carreira_estado (chave, valor) VALUES ('whatsapp_cursor', ?) "
                 "ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor", (str(stamp),))


def _vaga(conn, n: str):
    return conn.execute("SELECT v.rowid AS n, v.*, c.aderencia, c.resumo, c.lacunas_json, c.curriculo_md, c.carta "
                        "FROM carreira_vagas v LEFT JOIN carreira_candidaturas c ON c.vaga_id = v.id "
                        "WHERE v.rowid = ?", (int(n),)).fetchone()


def _context(vaga, perfil: str) -> str:
    lacunas = "; ".join(f"{g['requisito']}" for g in json.loads(vaga["lacunas_json"] or "[]")) or "nenhuma registrada"
    return f"{alfaiate.prompt(perfil, vaga)}\nLACUNAS: {lacunas}\n"


async def coach(mentor: MentorClient, vaga, perfil: str, transcript: list[dict], last: str) -> str:
    history = "\n".join(f"[{t['de']}] {t['texto']}" for t in transcript[-30:]) or "(início da entrevista)"
    text = f"{_context(vaga, perfil)}\nHISTÓRICO:\n{history}\n\nÚLTIMA MENSAGEM:\n{last}\n"
    output, failed = "", None
    async for event in mentor.stream({"op": "ephemeral", "role": "treinador", "text": text, "effort": "medium"}):
        if event.get("type") == "done":
            output = event.get("text") or ""
        elif event.get("type") == "error":
            failed = event.get("message") or "falha"
    if failed or not output.strip():
        raise RuntimeError(failed or "resposta vazia")
    return output.strip()[:4000]


async def handle(conn, mentor: MentorClient | None, text: str) -> str:
    """Resposta para uma mensagem do dono."""
    plain = _plain(text)
    active = conn.execute("SELECT * FROM carreira_treinos WHERE status = 'ativo' ORDER BY id DESC LIMIT 1").fetchone()
    if plain in ("ajuda", "menu", "oi", "ola"):
        return HELP
    if plain == "vagas":
        rows = conn.execute(
            "SELECT v.rowid AS n, v.title, v.company, c.aderencia FROM carreira_candidaturas c "
            "JOIN carreira_vagas v ON v.id = c.vaga_id ORDER BY c.aderencia DESC, c.created_at DESC LIMIT 10").fetchall()
        if not rows:
            return "Ainda não há currículos prontos. Eles saem a cada ciclo, para as vagas compatíveis."
        return "*Candidaturas prontas*\n" + "\n".join(
            f"#{r['n']} {r['title'][:80]} — {r['company'][:40]} · {r['aderencia']}%" for r in rows)
    if match := re.fullmatch(r"cv #?(\d+)", plain):
        vaga = _vaga(conn, match.group(1))
        if not vaga or vaga["curriculo_md"] is None:
            return "Não tenho currículo pronto para essa vaga. Mande *vagas* para ver a lista."
        gaps = "\n".join(f"• {g['requisito']}: {g['dica']}" for g in json.loads(vaga["lacunas_json"]))
        return (f"*{vaga['title']}* — {vaga['company']} · aderência {vaga['aderencia']}%\n{vaga['url']}\n\n"
                f"{vaga['curriculo_md']}\n\n*Carta*\n{vaga['carta']}" + (f"\n\n*O que estudar*\n{gaps}" if gaps else ""))
    perfil = alfaiate.profile()
    if mentor is None or perfil is None:
        return "O Treinador não está disponível agora (sem conexão com o mentor ou sem perfil)."
    if match := re.fullmatch(r"(treinar|entrevista) #?(\d+)", plain):
        vaga = _vaga(conn, match.group(2))
        if not vaga:
            return "Não achei essa vaga. Mande *vagas* para ver a lista."
        now = db.utcnow()
        conn.execute("UPDATE carreira_treinos SET status = 'encerrado', updated_at = ? WHERE status = 'ativo'", (now,))
        reply = await coach(mentor, vaga, perfil, [], "Comece a entrevista com a primeira pergunta.")
        conn.execute("INSERT INTO carreira_treinos (vaga_id, status, transcript_json, created_at, updated_at) "
                     "VALUES (?, 'ativo', ?, ?, ?)", (vaga["id"], json.dumps([{"de": "treinador", "texto": reply}],
                                                                             ensure_ascii=False), now, now))
        return f"*Treino: {vaga['title']}* (mande *parar* para encerrar)\n\n{reply}"
    if active is None:
        return HELP
    vaga = conn.execute("SELECT rowid AS n, * FROM carreira_vagas WHERE id = ?", (active["vaga_id"],)).fetchone()
    vaga = _vaga(conn, vaga["n"])
    transcript = json.loads(active["transcript_json"])
    ending = plain in ("parar", "encerrar", "fim")
    reply = await coach(mentor, vaga, perfil, transcript,
                        "ENCERRAR: a pessoa pediu para encerrar; dê o fechamento." if ending else text)
    transcript += [{"de": "pessoa", "texto": text}, {"de": "treinador", "texto": reply}]
    conn.execute("UPDATE carreira_treinos SET transcript_json = ?, status = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(transcript, ensure_ascii=False), "encerrado" if ending else "ativo", db.utcnow(),
                  active["id"]))
    return reply


async def poll_once(conn, client: httpx.AsyncClient, cfg: dict, mentor: MentorClient | None, send) -> int:
    handled = 0
    for stamp, text in await fetch_owner_messages(client, cfg, cursor(conn)):
        try:
            reply = await handle(conn, mentor, text)
        except Exception as exc:  # noqa: BLE001 — avisa o dono em vez de sumir com a mensagem
            log.warning("conversa falhou: %s", type(exc).__name__)
            reply = "Não consegui responder agora (o mentor falhou ou demorou). Tente de novo em instantes."
        set_cursor(conn, stamp)  # antes do envio: uma mensagem nunca é respondida duas vezes
        await send(reply)
        handled += 1
    return handled
