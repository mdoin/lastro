# SPDX-License-Identifier: AGPL-3.0-or-later
"""Candidatura automática (fase 3): manda as melhores vagas ao agente `aplicador` do worker e registra o resultado.

Só vagas com currículo sob medida e aderência ≥ MIN_ADERENCIA, até DAILY_LIMIT tentativas por dia e
MAX_ATTEMPTS por vaga. O Aplicador para e devolve `precisa_de_voce` diante de CAPTCHA, código de verificação,
teste ou campo obrigatório sem resposta conhecida; o dono recebe o aviso no WhatsApp.
"""

import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path

from app import db
from app.mentor_client import MentorClient

from . import alfaiate, curriculo, documento, registro, sources

log = logging.getLogger("lastro.carreira")
MIN_ADERENCIA = 60
DAILY_LIMIT = int(os.environ.get("CARREIRA_LIMITE_DIA", 10))  # tentativas por dia (limite de volume)
PER_CYCLE = int(os.environ.get("CARREIRA_POR_CICLO", 3))  # tentativas por volta da fila (a cada 30 min)
MAX_ATTEMPTS = 2
# Pedido de intervenção (login, CAPTCHA, teste) não é tentativa de envio: o dono resolve e a vaga volta à fila.
ATTEMPT = "status != 'precisa_de_voce'"
TIMEOUT_SECONDS = 1000
STATUS = {"enviada": "candidatada", "incerta": "incerta", "precisa_de_voce": "precisa_de_voce", "nao_aplicavel": "encerrada"}
EVENT = {"enviada": "candidatura_enviada", "incerta": "resultado_desconhecido", "precisa_de_voce": "intervencao_solicitada",
         "nao_aplicavel": "candidatura_nao_aplicavel", "falhou": "candidatura_falhou"}


def answers() -> str | None:
    path = Path(os.environ.get("CARREIRA_RESPOSTAS", "/var/lib/patrimonio/carreira/respostas.md"))
    return path.read_text(encoding="utf-8") if path.is_file() else None


def parse(output: str, require_evidence: bool = True) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", output.strip())
    data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    status = data.get("status") if data.get("status") in ("enviada", "precisa_de_voce", "nao_aplicavel") else "falhou"
    url = str(data.get("url_final") or "")
    evidencia = sources.text(data.get("evidencia"))[:300]
    if status == "enviada" and not evidencia and require_evidence:  # clicar em "enviar" não basta: sem confirmação da plataforma, é incerto
        status = "incerta"
    return {"status": status, "motivo": sources.text(data.get("motivo"))[:400] or "sem motivo informado",
            "evidencia": evidencia,
            "url_final": url[:500] if url.startswith("https://") else "",
            "documento": sources.text(data.get("documento"))[:200],
            "respostas": [{"pergunta": sources.text(r.get("pergunta"))[:200], "resposta": sources.text(r.get("resposta"))[:500]}
                          for r in (data.get("respostas") or [])[:40] if isinstance(r, dict)]}


def pending(conn, limit: int):
    return conn.execute(
        "SELECT v.rowid AS n, v.*, c.curriculo_md, c.carta, c.aderencia, c.curriculo_id, k.pdf, k.docx "
        "FROM carreira_candidaturas c JOIN carreira_vagas v ON v.id = c.vaga_id "
        "LEFT JOIN carreira_curriculos k ON k.id = c.curriculo_id WHERE c.status = 'curriculo' AND c.aderencia >= ? "
        # com currículo-base estruturado, só versão com o documento validado (PDF) vai para envio
        "AND (k.pdf IS NOT NULL OR NOT EXISTS (SELECT 1 FROM carreira_base)) "
        f"AND (SELECT COUNT(*) FROM carreira_envios e WHERE e.vaga_id = v.id AND e.{ATTEMPT}) < ? "
        # só a versão do currículo aprovada pelo Talent (talent.py) vai para envio
        "AND EXISTS (SELECT 1 FROM talent_revisoes r WHERE r.curriculo_id = c.curriculo_id AND r.resultado = 'aprovado') "
        "ORDER BY c.aderencia DESC, c.created_at LIMIT ?", (MIN_ADERENCIA, MAX_ATTEMPTS, limit)).fetchall()


PLATFORMS = {"gupy": "https://www.gupy.io/", "linkedin": "https://www.linkedin.com/in/me/",
             "catho": "https://www.catho.com.br/", "indeed": "https://br.indeed.com/",
             "programathor": "https://programathor.com.br/", "infojobs": "https://www.infojobs.com.br/",
             "vagas": "https://www.vagas.com.br/"}


base_cv = registro.curriculo_base_md


def liberado(conn) -> bool:
    """O dono conferiu os currículos do gerador novo e liberou o envio (tela Currículos). Sem base estruturada, o
    modo antigo segue como antes."""
    return curriculo.base_atual(conn) is None or conn.execute(
        "SELECT 1 FROM carreira_estado WHERE chave = 'curriculo_liberado'").fetchone() is not None


async def ask(mentor: MentorClient, vaga, perfil: str, respostas: str) -> dict:
    text = (f"{alfaiate.prompt(perfil, vaga)}\nLINK DA VAGA: {vaga['url']}\n\nRESPOSTAS:\n{respostas}\n\n"
            f"CARTA:\n{vaga['carta']}\n")
    return await run(mentor, text, vaga["curriculo_md"], arquivos={"pdf": vaga["pdf"], "docx": vaga["docx"]})


async def update_profile(mentor: MentorClient, platform: str, conn=None) -> dict:
    """Atualiza o perfil do dono numa plataforma (modo carreira_perfil do aplicador). Com `conn`, registra a execução
    (data e resultado) em carreira_execucoes."""
    perfil, respostas, cv = alfaiate.profile(conn), answers(), base_cv()
    arquivos = {}
    if conn is not None and (atual := curriculo.base_atual(conn)):  # currículo geral = versão Backend validada
        await documento.versoes_dos_perfis(conn, mentor)
        geral = documento.versao_do_perfil(conn, atual["id"], "backend")
        arquivos, cv = {"pdf": geral["pdf"], "docx": geral["docx"]}, cv or ""
    if None in (perfil, respostas, cv):
        raise RuntimeError("faltam perfil, respostas ou currículo base")
    text = (f"PLATAFORMA: {platform} ({PLATFORMS[platform]})\n\nPERFIL:\n{perfil}\n\nRESPOSTAS:\n{respostas}\n")
    if conn is None:
        return await asyncio.wait_for(run(mentor, text, cv, mode="carreira_perfil"), TIMEOUT_SECONDS)
    with registro.execucao(conn, "perfil") as rec:
        result = await asyncio.wait_for(run(mentor, text, cv, mode="carreira_perfil", arquivos=arquivos),
                                        TIMEOUT_SECONDS)
        rec["resultado"] = f"{platform}: {result['status']} — {result['motivo']}"
        if result["status"] == "falhou":
            rec["erro"] = result["motivo"]
    return result


async def run(mentor: MentorClient, text: str, curriculo_md: str, mode: str | None = None,
              arquivos: dict | None = None) -> dict:
    aplicacao = {"curriculo_md": curriculo_md, "nome_arquivo": "Maite-Doin-Curriculo",
                 **{f"{fmt}_b64": base64.b64encode(data).decode() for fmt, data in (arquivos or {}).items() if data}}
    request = {"op": "ephemeral", "role": "aplicador", "text": text, "effort": "medium", "aplicacao": aplicacao,
               **({"mode": mode} if mode else {})}
    output, failed, seen, anexos = "", None, False, []
    async for event in mentor.stream(request):
        if event.get("type") == "done":
            output = event.get("text") or ""
            anexos = [t["anexo"] for t in event.get("tools") or [] if isinstance(t, dict) and t.get("anexo")]
        elif event.get("type") == "error":
            if not seen and event.get("kind") == "network":  # worker fora do ar (o cliente não lança): nada foi feito
                raise ConnectionRefusedError(event.get("message") or "worker indisponível")
            failed = event.get("message") or "falha"
        seen = True
    if failed or not output:
        raise RuntimeError(failed or "resposta vazia")
    result = parse(output, require_evidence=mode is None)  # atualizar perfil não é candidatura
    # O que foi anexado vem do worker (não do agente); sem anexo, o documento que a plataforma usou, se ele disse.
    result["anexo"] = ",".join(dict.fromkeys(anexos)) or (f"plataforma: {result['documento']}" if result["documento"]
                                                          else "nenhum anexo")
    return result


def notice(vaga, result: dict) -> str:
    head = f"#{vaga['n']} {vaga['title'][:100]} — {vaga['company'][:50]}"
    if result["status"] == "enviada":
        return f"*Candidatura enviada* ✅\n{head}\n{result['motivo']}"
    if result["status"] == "incerta":
        return (f"*Candidatura sem confirmação* ⚠️\n{head}\n{result['motivo']}\nConfira no Lastro (Candidaturas) "
                f"antes de tentar de novo: {result['url_final'] or vaga['url']}")
    if result["status"] == "precisa_de_voce":
        return f"*Preciso de você* na candidatura\n{head}\n{result['motivo']}\n{result['url_final'] or vaga['url']}"
    return f"*Candidatura não feita*\n{head}\n{result['motivo']}"


async def apply_pending(conn, mentor: MentorClient) -> list[str]:
    """Tenta as próximas candidaturas. Devolve os avisos para o WhatsApp."""
    perfil, respostas = alfaiate.profile(conn), answers()
    if perfil is None or respostas is None or not liberado(conn):
        return []
    today = db.utcnow()[:10]
    used = conn.execute("SELECT COUNT(*) FROM carreira_envios WHERE substr(created_at, 1, 10) = ?", (today,)).fetchone()[0]
    notices = []
    for vaga in pending(conn, min(PER_CYCLE, DAILY_LIMIT - used)):
        if prior := registro.candidatura_anterior(conn, vaga["id"]):  # mesma vaga por outra fonte: não repete
            conn.execute("UPDATE carreira_candidaturas SET status = 'encerrada', updated_at = ? WHERE vaga_id = ?",
                         (db.utcnow(), vaga["id"]))
            registro.evento(conn, vaga["id"], "duplicata_bloqueada", "sistema", vaga_n=prior["n"], status=prior["status"])
            continue
        with registro.execucao(conn, "candidatura", vaga["id"]) as run:
            registro.evento(conn, vaga["id"], "candidatura_iniciada", "aplicador", execucao_id=run["id"])
            try:
                result = await asyncio.wait_for(ask(mentor, vaga, perfil, respostas), TIMEOUT_SECONDS)
            except (ConnectionRefusedError, FileNotFoundError) as exc:  # o worker nem atendeu: nada foi enviado
                log.warning("aplicador indisponível em %s: %s", vaga["id"], type(exc).__name__)
                run["erro"] = f"worker indisponível ({type(exc).__name__}); a vaga continua na fila sem gastar tentativa"
                break  # as próximas também cairiam: espera a próxima volta
            except Exception as exc:  # noqa: BLE001 — o agente pode ter enviado antes de cair: resultado desconhecido
                log.warning("aplicador falhou em %s: %s", vaga["id"], type(exc).__name__)
                result = {"status": "incerta", "motivo": f"o agente não concluiu ({type(exc).__name__}); pode ter "
                          "enviado antes de parar"}
            result = {"url_final": "", "respostas": [], "evidencia": "", "anexo": "", **result}
            now = db.utcnow()
            envio_id = conn.execute(
                "INSERT INTO carreira_envios (vaga_id, status, motivo, url_final, respostas_json, evidencia, curriculo_id,"
                " execucao_id, anexo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (vaga["id"], result["status"], result["motivo"], result["url_final"],
                 json.dumps(result["respostas"], ensure_ascii=False), result["evidencia"], vaga["curriculo_id"],
                 run["id"], result["anexo"], now)).fetchone()[0]
            status = STATUS.get(result["status"])
            attempts = conn.execute(f"SELECT COUNT(*) FROM carreira_envios WHERE vaga_id = ? AND {ATTEMPT}",
                                    (vaga["id"],)).fetchone()[0]
            if status is None and attempts >= MAX_ATTEMPTS:
                status = "falhou"  # esgotou as tentativas: sai da fila e aparece como falha
            if status:
                conn.execute("UPDATE carreira_candidaturas SET status = ?, updated_at = ? WHERE vaga_id = ?",
                             (status, now, vaga["id"]))
            registro.evento(conn, vaga["id"], EVENT[result["status"]], "aplicador", envio_id=envio_id,
                            motivo=result["motivo"], tentativa=attempts)
            run["resultado"] = result["status"]
            if result["status"] == "falhou":
                run["erro"] = result["motivo"]
            else:
                notices.append(notice(vaga, result))
    return notices
