# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas `/api/carreira/*`: o módulo Carreira do Lastro (docs/CARREIRA.md).

- Leitura do que os agentes gravaram (serviço lastro-carreira): resumo, vagas, candidaturas, currículos, agente.
- Ações do dono numa candidatura (confirmar envio, etapa, retirar), sempre com evento no histórico.
- `/api/carreira/navegador`: o dono vê e controla o navegador do aplicador. O web app só repassa ao worker
  (operação `navegador`); o texto digitado pode ser senha: nunca vai para log nem volta na resposta.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from carreira import alfaiate, candidatura, match, registro, talent

from . import db

TZ = ZoneInfo("America/Sao_Paulo")  # "hoje" do painel é o dia do dono
KEYS = Literal["Enter", "Backspace", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"]
ETAPAS = ("em_analise", "teste", "entrevista", "proposta", "recusada")
AGENT_STATE = {"busca": "buscando", "curriculo": "preparando_curriculo", "candidatura": "preenchendo",
               "perfil": "atualizando_perfil", "avaliacao": "avaliando_vaga", "revisao": "revisando_curriculo",
               "analise": "analisando_resultados"}
ESTAGIO = match._rx(r"est[aá]gi|\bintern(ship)?\b|aprendiz")
CONTRATO = {"CLT": match._rx(r"\bclt\b|efetivo"), "PJ": match._rx(r"\bpj\b|pessoa jur[ií]dica|contractor")}


class Acao(BaseModel):
    acao: Literal["iniciar", "tela", "clicar", "duplo", "arrastar", "inserir", "teclar", "digitar", "tecla",
                  "abrir", "voltar", "rolar", "encerrar"]
    x: int = Field(0, ge=0, le=4000)
    y: int = Field(0, ge=0, le=4000)
    x2: int = Field(0, ge=0, le=4000)
    y2: int = Field(0, ge=0, le=4000)
    dy: int = Field(600, ge=-3000, le=3000)
    texto: str = Field("", max_length=2000)
    tecla: KEYS | None = None
    key: str = Field("", max_length=16)  # tecla da interação direta: 1 caractere ou nome (Enter, ArrowLeft...)
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False
    url: str = Field("", max_length=2000)


class PropostaDecisao(BaseModel):
    decisao: Literal["aprovada", "recusada"]


class CandidaturaAcao(BaseModel):
    acao: Literal["confirmar_envio", "nao_enviada", "etapa", "retirar"]
    etapa: Literal["em_analise", "teste", "entrevista", "proposta", "recusada"] | None = None


def coluna(status: str, etapa: str | None) -> str:
    """Coluna do Kanban: etapa da empresa quando há; senão, o estado do envio."""
    if etapa == "recusada" or status in ("encerrada", "retirada"):
        return "encerrada"
    if etapa in ("proposta", "entrevista"):
        return etapa
    if etapa in ("em_analise", "teste"):
        return "em_analise"
    return "enviada" if status == "candidatada" else "preparando"


def senioridade(title: str) -> str:
    if ESTAGIO.search(title):
        return "estagio"
    for name, rx in (("senior", match.SENIOR), ("pleno", match.PLENO), ("junior", match.JUNIOR)):
        if rx.search(title):
            return name
    return "indefinida"


def contrato(title: str, description: str) -> str | None:
    """Só o que o texto da vaga diz; sem menção, fica vazio (não se inventa). Estágio só pelo título: descrições de
    vaga júnior costumam citar "estágio" como experiência anterior."""
    if ESTAGIO.search(title):
        return "Estágio"
    return next((name for name, rx in CONTRATO.items() if rx.search(f"{title} {description}")), None)


def _event(row) -> dict:
    return {"id": row["id"], "tipo": row["tipo"], "origem": row["origem"], "detalhe": json.loads(row["detalhe_json"]),
            "envio_id": row["envio_id"], "created_at": row["created_at"]}


def _vaga(row) -> dict:
    keys = row.keys()
    return {"n": row["n"], "id": row["id"], "title": row["title"], "company": row["company"], "location": row["location"],
            "workplace": row["workplace"], "salary_min": row["salary_min"], "currency": row["currency"],
            "source": row["source"], "url": row["url"], "first_seen": row["first_seen"], "published_at": row["published_at"],
            "verdict": row["verdict"], "score": row["score"], "reasons": json.loads(row["reasons_json"]),
            "senioridade": senioridade(row["title"]),
            "contrato": contrato(row["title"], row["description"] if "description" in keys else ""),
            "aderencia": row["aderencia"] if "aderencia" in keys else None,
            "candidatura_status": row["c_status"] if "c_status" in keys else None,
            "etapa": row["etapa"] if "etapa" in keys else None}


def _stale(run, now: datetime) -> bool:
    started = datetime.fromisoformat(run["started_at"])
    return (now - started).total_seconds() > registro.STALE_SECONDS.get(run["tipo"], 1800)


def metricas(conn) -> dict:
    c = conn.execute(
        "SELECT COUNT(*) FILTER (WHERE status = 'candidatada') AS enviadas,"
        " COUNT(*) FILTER (WHERE status = 'candidatada' AND etapa IS NULL) AS aguardando,"
        " COUNT(*) FILTER (WHERE etapa IN ('em_analise', 'teste', 'entrevista', 'proposta')) AS em_andamento,"
        " COUNT(*) FILTER (WHERE etapa = 'entrevista') AS entrevistas,"
        " COUNT(*) FILTER (WHERE etapa = 'proposta') AS propostas,"
        " COUNT(*) FILTER (WHERE etapa = 'recusada') AS rejeicoes,"
        " COUNT(*) FILTER (WHERE status = 'falhou') AS falhas,"
        " COUNT(*) FILTER (WHERE status = 'incerta') AS incertas,"
        " COUNT(*) FILTER (WHERE status = 'precisa_de_voce') AS intervencao,"
        " COUNT(*) FILTER (WHERE status = 'curriculo') AS preparando,"
        " COUNT(*) FILTER (WHERE status = 'candidatada' AND etapa IS NOT NULL) AS respondidas"
        " FROM carreira_candidaturas").fetchone()
    v = conn.execute(
        "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE verdict = 'compativel') AS compativeis,"
        " COUNT(*) FILTER (WHERE verdict = 'talvez') AS talvez,"
        " COUNT(*) FILTER (WHERE first_seen >= ?) AS novas_7d FROM carreira_vagas",
        ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds"),)).fetchone()
    out = {**dict(v), **dict(c)}
    out["taxa_resposta"] = round(c["respondidas"] / c["enviadas"], 3) if c["enviadas"] else None
    midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    out["hoje"] = registro.resumo(conn, midnight.isoformat(timespec="seconds"))
    out["na_fila"] = len(candidatura.pending(conn, 1000))
    out["executando"] = conn.execute("SELECT COUNT(*) FROM carreira_execucoes WHERE estado = 'executando'").fetchone()[0]
    return out


def agente(conn) -> dict:
    now = datetime.now(timezone.utc)
    title = "LEFT JOIN carreira_vagas v ON v.id = x.vaga_id"
    cols = "x.*, v.rowid AS n, v.title, v.company"
    running = conn.execute(f"SELECT {cols} FROM carreira_execucoes x {title} WHERE x.estado = 'executando' "
                           "ORDER BY x.started_at DESC").fetchall()
    recent = conn.execute(f"SELECT {cols} FROM carreira_execucoes x {title} ORDER BY x.id DESC LIMIT 30").fetchall()
    last = next((r for r in recent if r["estado"] != "executando"), None)
    waiting = conn.execute("SELECT COUNT(*) FROM carreira_candidaturas WHERE status = 'precisa_de_voce'").fetchone()[0]
    live = [r for r in running if not _stale(r, now)]
    if live:
        estado = AGENT_STATE[live[0]["tipo"]]
    elif running:
        estado = "travado"
    elif waiting:
        estado = "aguardando_intervencao"
    elif last and last["estado"] == "falhou":
        estado = "erro"
    elif last and last["finished_at"] and (now - datetime.fromisoformat(last["finished_at"])).total_seconds() < 600:
        estado = "concluido"
    else:
        estado = "ocioso"
    state = dict(conn.execute("SELECT chave, valor FROM carreira_estado WHERE chave IN ('proximo_ciclo', 'proxima_fila')"
                              ).fetchall())
    today = db.utcnow()[:10]
    used = conn.execute("SELECT COUNT(*) FROM carreira_envios WHERE substr(created_at, 1, 10) = ?", (today,)).fetchone()[0]

    def run(r) -> dict:
        return {k: r[k] for k in ("id", "tipo", "estado", "resultado", "erro", "started_at", "updated_at", "finished_at",
                                  "n", "title", "company")} | {"travada": r["estado"] == "executando" and _stale(r, now)}

    week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")
    return {
        "estado": estado,
        "atual": run(running[0]) if running else None,
        "ultima": run(last) if last else None,
        "proximo_ciclo": state.get("proximo_ciclo"),
        "proxima_fila": state.get("proxima_fila"),
        "recentes": [run(r) for r in recent],
        "erros": [run(r) for r in recent if r["estado"] in ("falhou", "interrompida") and r["started_at"] >= week_ago][:5],
        "fila": {
            "curriculos": [{"n": r["n"], "title": r["title"], "company": r["company"], "score": r["score"]}
                           for r in alfaiate.pending(conn, 10)],
            "envios": [{"n": r["n"], "title": r["title"], "company": r["company"], "aderencia": r["aderencia"]}
                       for r in candidatura.pending(conn, 10)],
            "envios_hoje": used, "limite_diario": candidatura.DAILY_LIMIT, "por_ciclo": candidatura.PER_CYCLE,
        },
    }


def proximas(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT v.rowid AS n, v.title, v.company, c.status, c.etapa, c.updated_at,"
        " COALESCE((SELECT motivo FROM carreira_envios e WHERE e.vaga_id = v.id ORDER BY e.id DESC LIMIT 1),"
        "  (SELECT 'Talent: ' || json_extract(detalhe_json, '$.motivo') FROM carreira_eventos x WHERE x.vaga_id = v.id"
        "   AND x.tipo = 'revisao_bloqueada' ORDER BY x.id DESC LIMIT 1)) AS motivo,"
        " (SELECT url_final FROM carreira_envios e WHERE e.vaga_id = v.id ORDER BY e.id DESC LIMIT 1) AS url_final,"
        " (SELECT json_extract(detalhe_json, '$.prazo') FROM carreira_eventos x WHERE x.vaga_id = v.id"
        "  AND x.tipo = 'resposta' ORDER BY x.id DESC LIMIT 1) AS prazo"
        " FROM carreira_candidaturas c JOIN carreira_vagas v ON v.id = c.vaga_id"
        " WHERE c.status IN ('precisa_de_voce', 'incerta', 'falhou') OR c.etapa IN ('entrevista', 'teste', 'proposta')"
        " ORDER BY c.updated_at DESC").fetchall()
    kind = {"precisa_de_voce": "intervencao", "incerta": "verificar_envio", "falhou": "falha"}
    out = [{"tipo": r["etapa"] if r["etapa"] in ("entrevista", "teste", "proposta") else kind[r["status"]],
            "n": r["n"], "title": r["title"], "company": r["company"], "motivo": r["motivo"] or "",
            "url": r["url_final"] or "", "prazo": r["prazo"] or "", "desde": r["updated_at"]} for r in rows]
    order = ["entrevista", "teste", "proposta", "intervencao", "verificar_envio", "falha"]
    return sorted(out, key=lambda a: order.index(a["tipo"]))


def atividade(conn, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT e.*, v.rowid AS n, v.title, v.company, c.vaga_id IS NOT NULL AS tem_candidatura"
        " FROM carreira_eventos e JOIN carreira_vagas v ON v.id = e.vaga_id"
        " LEFT JOIN carreira_candidaturas c ON c.vaga_id = v.id"
        " WHERE NOT (e.tipo = 'descoberta' AND v.verdict = 'fora')"
        " ORDER BY e.created_at DESC, e.id DESC LIMIT ?", (limit,)).fetchall()
    return [_event(r) | {"n": r["n"], "title": r["title"], "company": r["company"],
                         "candidatura": bool(r["tem_candidatura"])} for r in rows]


VAGA_COLS = ("v.rowid AS n, v.id, v.title, v.company, v.location, v.workplace, v.salary_min, v.currency, v.source,"
             " v.url, v.first_seen, v.published_at, v.verdict, v.score, v.reasons_json, c.aderencia,"
             " c.status AS c_status, c.etapa")


def talent_painel(conn) -> dict:
    """Área do Talent: perfil (do arquivo do dono), estratégia, avaliações, revisões e resultados, como foram gravados."""
    perfil = alfaiate.profile()
    vaga = "v.rowid AS n, v.title, v.company, v.source"
    avaliacoes = conn.execute(f"SELECT a.*, {vaga} FROM talent_avaliacoes a JOIN carreira_vagas v ON v.id = a.vaga_id "
                              "ORDER BY a.id DESC LIMIT 60").fetchall()
    revisoes = conn.execute(f"SELECT r.*, {vaga} FROM talent_revisoes r JOIN carreira_vagas v ON v.id = r.vaga_id "
                            "ORDER BY r.id DESC LIMIT 60").fetchall()
    analise = conn.execute("SELECT * FROM talent_analises ORDER BY id DESC LIMIT 1").fetchone()
    ind = talent.indicadores(conn)
    atuais = [a for a in avaliacoes if a["id"] == max(b["id"] for b in avaliacoes if b["vaga_id"] == a["vaga_id"])]
    perfis: dict[str, int] = {}
    for a in atuais:
        if a["elegivel"]:
            perfis[a["perfil_curriculo"]] = perfis.get(a["perfil_curriculo"], 0) + 1
    j = json.loads
    return {
        "perfil": {"secoes": talent.secoes(perfil) if perfil else {}, "arquivo": perfil is not None,
                   "pontos_fortes": [t for t in ind["requisitos"] if t["atendido"]][:8],
                   "lacunas": [t for t in ind["requisitos"] if t["ausente"]][:8]},
        "estrategia": {
            "rubrica": talent.RUBRICA, "pesos": [{"criterio": talent.CRITERIO_NOME[k], "peso": v}
                                                 for k, v in talent.PESOS.items()],
            "limiar": candidatura.MIN_ADERENCIA, "max_rodadas": talent.MAX_RODADAS, "min_amostra": talent.MIN_AMOSTRA,
            "criterios": [line.strip("- ").strip() for line in (match.__doc__ or "").splitlines() if line.startswith("- ")],
            "perfis": sorted(({"perfil": k, "vagas": v} for k, v in perfis.items()), key=lambda d: -d["vagas"]),
            "analise": {"created_at": analise["created_at"], "recomendacoes": j(analise["recomendacoes_json"])}
            if analise else None},
        "avaliacoes": [{"id": a["id"], "n": a["n"], "title": a["title"], "company": a["company"], "elegivel": bool(a["elegivel"]),
                        "pontuacao": a["pontuacao"], "rubrica": a["rubrica"], "filtros": j(a["filtros_json"]),
                        "criterios": j(a["criterios_json"]), "requisitos": j(a["requisitos_json"]),
                        "posicionamento": a["posicionamento"], "perfil_curriculo": a["perfil_curriculo"],
                        "destaques": j(a["destaques_json"]), "orientacoes": j(a["orientacoes_json"]),
                        "justificativa": a["justificativa"], "created_at": a["created_at"]} for a in avaliacoes],
        "revisoes": [{"id": r["id"], "n": r["n"], "title": r["title"], "company": r["company"],
                      "curriculo_id": r["curriculo_id"], "rodada": r["rodada"], "resultado": r["resultado"],
                      "checagens": j(r["checagens_json"]), "problemas": j(r["problemas_json"]), "resumo": r["resumo"],
                      "created_at": r["created_at"]} for r in revisoes],
        "resultados": ind,
        "propostas": [dict(p) for p in conn.execute("SELECT * FROM talent_propostas ORDER BY status = 'pendente' DESC, "
                                                    "id DESC LIMIT 50")],
    }


def register(app: FastAPI, conn, *, mentor, current_user, log_access) -> None:
    async def worker(body: dict) -> dict:
        result = await mentor.call({"op": "navegador", **body}, timeout=60)
        if result.get("type") == "error":
            raise HTTPException(status_code=503, detail=result.get("message") or "Worker do mentor indisponível.")
        result.pop("type", None)
        return result

    def vaga_row(n: int):
        row = conn.execute(f"SELECT {VAGA_COLS}, v.description FROM carreira_vagas v "
                           "LEFT JOIN carreira_candidaturas c ON c.vaga_id = v.id WHERE v.rowid = ?", (n,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Vaga não encontrada.")
        return row

    @app.get("/api/carreira/navegador")
    async def navegador_tela(user: str = Depends(current_user)):
        return await worker({"acao": "tela"})

    @app.post("/api/carreira/navegador")
    async def navegador_acao(body: Acao, user: str = Depends(current_user)):
        if body.acao in ("iniciar", "encerrar", "abrir"):  # o que se digita (talvez senha) nunca entra no log
            log_access(user, f"carreira.navegador.{body.acao}", body.url[:200] if body.acao == "abrir" else "")
        return await worker(body.model_dump(exclude_none=True))

    @app.get("/api/carreira/resumo")
    async def resumo(user: str = Depends(current_user)):
        return {"metricas": metricas(conn), "agente": agente(conn), "proximas": proximas(conn),
                "atividade": atividade(conn, 25)}

    @app.get("/api/carreira/atividade")
    async def atividade_lista(limit: int = Query(60, ge=1, le=300), user: str = Depends(current_user)):
        return atividade(conn, limit)

    @app.get("/api/carreira/agente")
    async def agente_estado(user: str = Depends(current_user)):
        return agente(conn)

    @app.get("/api/carreira/vagas")
    async def vagas(q: str = Query("", max_length=120), empresa: str = Query("", max_length=120),
                    local: str = Query("", max_length=120), modalidade: str = Query("", max_length=80),
                    senioridade_: str = Query("", alias="senioridade", max_length=80),
                    compat: str = Query("compativel,talvez", max_length=60), fonte: str = Query("", max_length=200),
                    status: str = Query("", max_length=120), salario_min: float | None = Query(None, ge=0),
                    aderencia_min: int | None = Query(None, ge=0, le=100), desde: str = Query("", max_length=10),
                    ordem: Literal["relevancia", "data"] = "relevancia", limit: int = Query(50, ge=1, le=200),
                    offset: int = Query(0, ge=0), user: str = Depends(current_user)):
        # shortcut: filtra em Python sobre todas as vagas (centenas); com dezenas de milhares, mover os filtros para SQL.
        rows = conn.execute(f"SELECT {VAGA_COLS}, v.description FROM carreira_vagas v "
                            "LEFT JOIN carreira_candidaturas c ON c.vaga_id = v.id").fetchall()
        sets = {k: {x for x in val.split(",") if x} for k, val in
                (("modalidade", modalidade), ("senioridade", senioridade_), ("compat", compat), ("fonte", fonte),
                 ("status", status))}
        words = [w for w in q.lower().split() if w]
        items = []
        for r in rows:
            item = _vaga(r)
            item["coluna"] = coluna(r["c_status"], r["etapa"]) if r["c_status"] else "sem_candidatura"
            text = f"{r['title']} {r['company']} {r['location']} {r['description']}".lower()
            if ((words and not all(w in text for w in words))
                    or (empresa and empresa.lower() not in r["company"].lower())
                    or (local and local.lower() not in r["location"].lower())
                    or (sets["modalidade"] and r["workplace"] not in sets["modalidade"])
                    or (sets["senioridade"] and item["senioridade"] not in sets["senioridade"])
                    or (sets["compat"] and r["verdict"] not in sets["compat"])
                    or (sets["fonte"] and r["source"] not in sets["fonte"])
                    or (sets["status"] and item["coluna"] not in sets["status"])
                    or (salario_min is not None and (r["salary_min"] or 0) < salario_min)
                    or (aderencia_min is not None and (r["aderencia"] or -1) < aderencia_min)
                    or (desde and r["first_seen"][:10] < desde)):
                continue
            items.append(item)
        if ordem == "data":
            items.sort(key=lambda i: i["first_seen"], reverse=True)
        else:
            items.sort(key=lambda i: (i["aderencia"] if i["aderencia"] is not None else -1, i["score"], i["first_seen"]),
                       reverse=True)
        fontes = [r[0] for r in conn.execute("SELECT DISTINCT source FROM carreira_vagas ORDER BY source")]
        return {"total": len(items), "items": items[offset:offset + limit], "fontes": fontes}

    @app.get("/api/carreira/vagas/{n}")
    async def vaga(n: int, user: str = Depends(current_user)):
        row = vaga_row(n)
        cand = conn.execute("SELECT * FROM carreira_candidaturas WHERE vaga_id = ?", (row["id"],)).fetchone()
        dups = conn.execute(f"SELECT d.n, x.title, x.source FROM ({registro.DUPLICATES_SQL}) d "
                            "JOIN carreira_vagas x ON x.id = d.id", (row["id"],)).fetchall()
        events = conn.execute("SELECT * FROM carreira_eventos WHERE vaga_id = ? ORDER BY created_at, id",
                              (row["id"],)).fetchall()
        return _vaga(row) | {
            "description": row["description"],
            "candidatura": None if cand is None else {
                "status": cand["status"], "etapa": cand["etapa"], "coluna": coluna(cand["status"], cand["etapa"]),
                "aderencia": cand["aderencia"], "resumo": cand["resumo"], "lacunas": json.loads(cand["lacunas_json"]),
                "curriculo_id": cand["curriculo_id"], "updated_at": cand["updated_at"]},
            "duplicatas": [dict(d) for d in dups],
            "eventos": [_event(e) for e in events]}

    @app.get("/api/carreira/candidaturas")
    async def candidaturas(user: str = Depends(current_user)):
        rows = conn.execute(
            f"SELECT {VAGA_COLS}, c.created_at AS c_created, c.updated_at AS c_updated, c.curriculo_id,"
            " (SELECT MIN(created_at) FROM carreira_eventos x WHERE x.vaga_id = v.id"
            "  AND x.tipo IN ('candidatura_enviada', 'envio_confirmado')) AS enviada_em,"
            " (SELECT MAX(created_at) FROM carreira_eventos x WHERE x.vaga_id = v.id) AS ultimo_evento,"
            " (SELECT motivo FROM carreira_envios e WHERE e.vaga_id = v.id ORDER BY e.id DESC LIMIT 1) AS motivo"
            " FROM carreira_candidaturas c JOIN carreira_vagas v ON v.id = c.vaga_id ORDER BY c.updated_at DESC"
        ).fetchall()
        return [_vaga(r) | {"coluna": coluna(r["c_status"], r["etapa"]), "criada_em": r["c_created"],
                            "enviada_em": r["enviada_em"], "curriculo_id": r["curriculo_id"],
                            "atualizada_em": max(filter(None, (r["c_updated"], r["ultimo_evento"]))),
                            "motivo": r["motivo"] or ""} for r in rows]

    @app.get("/api/carreira/candidaturas/{n}")
    async def candidatura_detalhe(n: int, user: str = Depends(current_user)):
        row = vaga_row(n)
        cand = conn.execute("SELECT * FROM carreira_candidaturas WHERE vaga_id = ?", (row["id"],)).fetchone()
        if cand is None:
            raise HTTPException(status_code=404, detail="Esta vaga ainda não tem candidatura.")
        envios = conn.execute("SELECT * FROM carreira_envios WHERE vaga_id = ? ORDER BY id", (row["id"],)).fetchall()
        events = conn.execute("SELECT * FROM carreira_eventos WHERE vaga_id = ? ORDER BY created_at, id",
                              (row["id"],)).fetchall()
        emails = conn.execute("SELECT received_at, subject, tipo, resumo, created_at FROM carreira_emails "
                              "WHERE vaga_id = ? ORDER BY created_at", (row["id"],)).fetchall()
        return _vaga(row) | {
            "status": cand["status"], "etapa": cand["etapa"], "coluna": coluna(cand["status"], cand["etapa"]),
            "aderencia": cand["aderencia"], "resumo": cand["resumo"], "lacunas": json.loads(cand["lacunas_json"]),
            "idioma": cand["idioma"], "carta": cand["carta"], "curriculo_id": cand["curriculo_id"],
            "criada_em": cand["created_at"], "atualizada_em": cand["updated_at"],
            "envios": [{"id": e["id"], "status": e["status"], "motivo": e["motivo"], "url_final": e["url_final"],
                        "evidencia": e["evidencia"], "respostas": json.loads(e["respostas_json"]),
                        "curriculo_id": e["curriculo_id"], "execucao_id": e["execucao_id"], "agente": "aplicador",
                        "created_at": e["created_at"]} for e in envios],
            "eventos": [_event(e) for e in events],
            "emails": [dict(m) for m in emails]}

    @app.post("/api/carreira/candidaturas/{n}/acao")
    async def candidatura_acao(n: int, body: CandidaturaAcao, user: str = Depends(current_user)):
        row = vaga_row(n)
        cand = conn.execute("SELECT status, etapa FROM carreira_candidaturas WHERE vaga_id = ?", (row["id"],)).fetchone()
        if cand is None:
            raise HTTPException(status_code=404, detail="Esta vaga ainda não tem candidatura.")
        now, vid = db.utcnow(), row["id"]
        if body.acao == "confirmar_envio":
            if cand["status"] == "candidatada":
                raise HTTPException(status_code=409, detail="A candidatura já consta como enviada.")
            conn.execute("UPDATE carreira_candidaturas SET status = 'candidatada', updated_at = ? WHERE vaga_id = ?",
                         (now, vid))
            registro.evento(conn, vid, "envio_confirmado", "dono", anterior=cand["status"])
        elif body.acao == "nao_enviada":
            if cand["status"] not in ("incerta", "precisa_de_voce"):
                raise HTTPException(status_code=409, detail="Só um envio incerto ou pendente pode ser marcado como não enviado.")
            attempts = conn.execute(f"SELECT COUNT(*) FROM carreira_envios WHERE vaga_id = ? AND {candidatura.ATTEMPT}",
                                    (vid,)).fetchone()[0]
            new = "curriculo" if attempts < candidatura.MAX_ATTEMPTS else "falhou"  # volta à fila só se houver tentativa
            conn.execute("UPDATE carreira_candidaturas SET status = ?, updated_at = ? WHERE vaga_id = ?", (new, now, vid))
            registro.evento(conn, vid, "envio_negado", "dono", anterior=cand["status"], novo=new)
        elif body.acao == "etapa":
            if body.etapa is None:
                raise HTTPException(status_code=422, detail="Informe a etapa.")
            conn.execute("UPDATE carreira_candidaturas SET etapa = ?, status = 'candidatada', updated_at = ? "
                         "WHERE vaga_id = ?", (body.etapa, now, vid))
            registro.evento(conn, vid, "etapa_atualizada", "dono", etapa=body.etapa, anterior=cand["etapa"])
        else:
            if cand["status"] == "retirada":
                raise HTTPException(status_code=409, detail="A candidatura já foi retirada.")
            conn.execute("UPDATE carreira_candidaturas SET status = 'retirada', updated_at = ? WHERE vaga_id = ?",
                         (now, vid))
            registro.evento(conn, vid, "retirada", "dono", anterior=cand["status"])
        log_access(user, f"carreira.candidatura.{body.acao}", str(n))
        return await candidatura_detalhe(n, user)

    @app.get("/api/carreira/talent")
    async def talent_area(user: str = Depends(current_user)):
        return talent_painel(conn)

    @app.post("/api/carreira/talent/propostas/{pid}")
    async def talent_proposta(pid: int, body: PropostaDecisao, user: str = Depends(current_user)):
        """Decisão do dono numa proposta do Talent. Registra a decisão; o perfil e o currículo-base continuam sendo
        editados só pelo dono."""
        cur = conn.execute("UPDATE talent_propostas SET status = ?, decidida_em = ? WHERE id = ? AND status = 'pendente'",
                           (body.decisao, db.utcnow(), pid))
        if not cur.rowcount:
            raise HTTPException(status_code=409, detail="Proposta inexistente ou já decidida.")
        log_access(user, f"carreira.talent.proposta.{body.decisao}", str(pid))
        return dict(conn.execute("SELECT * FROM talent_propostas WHERE id = ?", (pid,)).fetchone())
