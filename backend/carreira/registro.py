# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registro da Carreira (migração 018): histórico imutável, execuções dos agentes, versões de currículo e duplicatas.

Os agentes gravam aqui no backend, com ou sem a interface aberta; o web app só lê (e registra as ações do dono).
Nada de cookie, senha ou corpo de e-mail entra no detalhe dos eventos.
"""

import json
import os
import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from app import db

# Prazo além do qual uma execução ainda "executando" é tratada como travada (o timeout de cada agente + folga).
STALE_SECONDS = {"busca": 1800, "curriculo": 600, "candidatura": 1500, "perfil": 1500}
# Envios que impedem nova tentativa na mesma vaga ou numa duplicata dela.
BLOCKING = ("candidatada", "incerta", "precisa_de_voce")
ETAPA_ORDEM = {"em_analise": 1, "teste": 2, "entrevista": 3, "proposta": 4}


def evento(conn, vaga_id: str, tipo: str, origem: str, /, envio_id: int | None = None, **detalhe) -> None:
    conn.execute("INSERT INTO carreira_eventos (vaga_id, tipo, origem, detalhe_json, envio_id, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (vaga_id, tipo, origem, json.dumps(detalhe, ensure_ascii=False), envio_id, db.utcnow()))


@contextmanager
def execucao(conn, tipo: str, vaga_id: str | None = None):
    """Registra uma execução de agente. Quem chama preenche `run["resultado"]` e, se falhar sem exceção, `run["erro"]`."""
    now = db.utcnow()
    run = {"id": conn.execute("INSERT INTO carreira_execucoes (tipo, vaga_id, estado, started_at, updated_at) "
                              "VALUES (?, ?, 'executando', ?, ?) RETURNING id", (tipo, vaga_id, now, now)).fetchone()[0],
           "resultado": "", "erro": ""}
    try:
        yield run
    except BaseException as exc:
        state = "falhou" if isinstance(exc, Exception) else "interrompida"  # CancelledError: serviço parado
        _finish(conn, run, state, run["erro"] or type(exc).__name__)
        raise
    _finish(conn, run, "falhou" if run["erro"] else "concluida", run["erro"])


def _finish(conn, run: dict, state: str, erro: str) -> None:
    now = db.utcnow()
    conn.execute("UPDATE carreira_execucoes SET estado = ?, resultado = ?, erro = ?, updated_at = ?, finished_at = ? "
                 "WHERE id = ?", (state, run["resultado"][:400], erro[:400], now, now, run["id"]))


def interromper_pendentes(conn) -> int:
    """No início do serviço: o que ficou "executando" morreu com o processo anterior."""
    now = db.utcnow()
    return conn.execute("UPDATE carreira_execucoes SET estado = 'interrompida', erro = 'serviço reiniciado durante a "
                        "execução', updated_at = ?, finished_at = ? WHERE estado = 'executando'", (now, now)).rowcount


# --- Duplicatas ---------------------------------------------------------------------------------------------

_LEGAL = re.compile(r"\b(ltda|s ?a|sa|inc|llc|ltd|me|eireli|epp|corp|co|gmbh|plc)\b")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def url_canonica(url: str) -> str | None:
    """URL sem parâmetros de rastreio; LinkedIn por id da vaga (o link do e-mail e o da busca são o mesmo emprego)."""
    if m := re.search(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d{6,})", url or ""):
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = parts.query if re.search(r"(^|&)(jk|id|job|vaga|jobid)=", parts.query, re.I) else ""  # o id às vezes vem na query
    return f"https://{parts.netloc.lower().removeprefix('www.')}{parts.path.rstrip('/')}" + (f"?{query}" if query else "")


def chave(company: str, title: str, location: str, workplace: str) -> str | None:
    """empresa|cargo|local normalizados. Sem empresa não há chave: melhor deixar passar que juntar vagas diferentes."""
    empresa = _LEGAL.sub(" ", _norm(company)).strip()
    if len(empresa) < 2:
        return None
    local = "remoto" if workplace == "remoto" else _norm((location or "").split(",")[0]) or "?"
    return f"{re.sub(' +', ' ', empresa)}|{_norm(title)}|{local}"


def preencher_chaves(conn) -> int:
    rows = conn.execute("SELECT id, url, company, title, location, workplace FROM carreira_vagas "
                        "WHERE url_canonica IS NULL AND chave IS NULL").fetchall()
    conn.executemany("UPDATE carreira_vagas SET url_canonica = ?, chave = ? WHERE id = ?",
                     [(url_canonica(r["url"]), chave(r["company"], r["title"], r["location"], r["workplace"]), r["id"])
                      for r in rows])
    return len(rows)


# `o` é duplicata provável de `v`: mesma URL canônica (inclui o id da vaga na plataforma) ou mesma empresa|cargo|local.
SAME_JOB = ("o.id != v.id AND ((v.url_canonica IS NOT NULL AND o.url_canonica = v.url_canonica) OR "
            "(v.chave IS NOT NULL AND o.chave = v.chave))")
DUPLICATES_SQL = f"SELECT o.id, o.rowid AS n FROM carreira_vagas v JOIN carreira_vagas o ON {SAME_JOB} WHERE v.id = ?"


def candidatura_anterior(conn, vaga_id: str):
    """Envio já feito, incerto ou pendente do dono nesta vaga ou numa duplicata dela (impede candidatura repetida)."""
    marks = ",".join("?" * len(BLOCKING))
    return conn.execute(
        f"SELECT c.vaga_id, c.status, v.rowid AS n FROM carreira_candidaturas c JOIN carreira_vagas v ON v.id = c.vaga_id "
        f"WHERE c.status IN ({marks}) AND (c.vaga_id = ? OR c.vaga_id IN (SELECT id FROM ({DUPLICATES_SQL}))) "
        f"UNION SELECT e.vaga_id, e.status, v.rowid FROM carreira_envios e JOIN carreira_vagas v ON v.id = e.vaga_id "
        f"WHERE e.status IN ('enviada', 'incerta') AND (e.vaga_id = ? OR e.vaga_id IN (SELECT id FROM ({DUPLICATES_SQL}))) "
        f"LIMIT 1", (*BLOCKING, vaga_id, vaga_id, vaga_id, vaga_id)).fetchone()


# --- Currículos ---------------------------------------------------------------------------------------------

def curriculo_base_md() -> str | None:
    path = Path(os.environ.get("CARREIRA_CURRICULO", "/var/lib/patrimonio/carreira/curriculo.md"))
    return path.read_text(encoding="utf-8") if path.is_file() else None


def sincronizar_base(conn) -> int | None:
    """Grava uma nova versão base quando o arquivo do dono mudou. Devolve o id da base vigente."""
    text = curriculo_base_md()
    last = conn.execute("SELECT id, conteudo_md FROM carreira_curriculos WHERE tipo = 'base' ORDER BY id DESC LIMIT 1"
                        ).fetchone()
    if text is None or (last and last["conteudo_md"] == text):
        return last["id"] if last else None
    return conn.execute("INSERT INTO carreira_curriculos (tipo, conteudo_md, created_at) VALUES ('base', ?, ?) "
                        "RETURNING id", (text, db.utcnow())).fetchone()[0]


# --- Etapas informadas pela empresa ---------------------------------------------------------------------------

def avancar_etapa(conn, vaga_id: str, etapa: str, origem: str, **detalhe) -> bool:
    """Etapa só avança (andamento depois de entrevista não regride); recusa encerra. Etapa implica que houve envio."""
    row = conn.execute("SELECT status, etapa FROM carreira_candidaturas WHERE vaga_id = ?", (vaga_id,)).fetchone()
    if row is None or row["etapa"] == "recusada" or (
            etapa != "recusada" and ETAPA_ORDEM.get(row["etapa"] or "", 0) >= ETAPA_ORDEM[etapa]):
        return False
    conn.execute("UPDATE carreira_candidaturas SET etapa = ?, status = 'candidatada', updated_at = ? WHERE vaga_id = ?",
                 (etapa, db.utcnow(), vaga_id))
    evento(conn, vaga_id, "etapa_atualizada", origem, etapa=etapa, anterior=row["etapa"], **detalhe)
    return True
