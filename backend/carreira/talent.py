# SPDX-License-Identifier: AGPL-3.0-or-later
"""Talent: especialista em recrutamento da Carreira (docs/CARREIRA.md, seção Talent).

Fluxo na fila contínua do serviço lastro-carreira:
  Caçador → Talent avalia (filtros obrigatórios do dono + rubrica) → Alfaiate (com a orientação do Talent)
  → Talent revisa (checagens determinísticas + agente; até MAX_RODADAS) → Aplicador só recebe currículo aprovado
  → Carteiro registra respostas → Talent analisa os resultados (semanal, sem IA).

A sessão do agente `talent` não tem ferramenta nenhuma (team/agents.py): recebe texto e devolve JSON, conferido aqui.
As ferramentas do Talent são as funções deste módulo, e só elas gravam: avaliações, revisões, análises e propostas
(talent_*), o histórico da Carreira e o bloqueio de uma candidatura reprovada na revisão. Ele não lê o cofre nem as
respostas de formulário, não abre navegador, não envia candidatura e não altera perfil nem currículo-base: propõe
(talent_propostas) e o dono decide.
"""

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from app import db, store

from . import alfaiate, candidatura, match, registro

log = logging.getLogger("lastro.carreira")
RUBRICA = "2026-11-05.1"
PER_CYCLE = 3  # avaliações e revisões por volta da fila
MAX_RODADAS = 3  # revisões por vaga (1 + 2 correções); depois disso, bloqueada
MAX_FALHAS = 2  # respostas inválidas do agente por vaga antes de desistir dela
TIMEOUT_AVALIACAO, TIMEOUT_REVISAO = 180, 240
ANALISE_DIAS = 7
MIN_AMOSTRA = 10  # abaixo disso, por grupo, só observação descritiva
PERFIS = ("backend", "ia", "junior")
CRITERIOS_REVISAO = ("precisao_factual", "relevancia", "clareza", "realizacoes", "competencias", "estrutura", "ats")
GENERIC = re.compile(r"^\W*(melhorar|revisar|aprimorar|ajustar|otimizar)\b.{0,40}$|deixar .{0,20}(atrativ|melhor)", re.I)

# Rubrica: pesos somam 100. Filtros obrigatórios vêm antes e não são compensados por pontuação.
PESOS = {"tecnicos_obrigatorios": 40, "desejaveis": 10, "senioridade_experiencia": 15, "formacao_idiomas": 10,
         "local_modalidade": 10, "contratacao": 5, "remuneracao": 5, "area_preferida": 5}
CRITERIO_NOME = {"tecnicos_obrigatorios": "Requisitos técnicos obrigatórios", "desejaveis": "Requisitos desejáveis",
                 "senioridade_experiencia": "Senioridade e experiência", "formacao_idiomas": "Formação e idiomas",
                 "local_modalidade": "Local e modalidade", "contratacao": "Tipo de contratação",
                 "remuneracao": "Remuneração", "area_preferida": "Área preferida"}
# Termos de tecnologia conferidos no currículo: citado no currículo e ausente do perfil = afirmação sem comprovação.
TECH = ("java", "kotlin", "golang", "rust", "c#", ".net", "react", "angular", "vue", "node.js", "nodejs", "typescript",
        "javascript", "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "spark", "airflow", "kafka", "django",
        "flask", "fastapi", "postgresql", "mysql", "mongodb", "redis", "pytorch", "tensorflow", "langchain",
        "llamaindex", "scikit-learn", "pandas", "power bi", "tableau", "php", "ruby", "swift", "scala", "graphql",
        "elasticsearch", "snowflake", "databricks", "dbt", "selenium", "playwright", "yolo", "opencv", "linux", "git",
        "sql", "python", "mcp", "rag", "llm")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _sha(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _tech(text: str) -> set[str]:
    low = _norm(text)
    return {t for t in TECH if re.search(rf"(?<![\w.#]){re.escape(t)}(?![\w#])", low)}


def _json(output: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", output.strip())
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


def _s(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


async def ask(conn, mentor, text: str, mode: str, effort: str, timeout: int) -> str:
    """Sessão do agente `talent` no worker, com a conexão/modelo escolhidos para ele em Configurações (se houver)."""
    return await asyncio.wait_for(alfaiate.ask(mentor, text, role="talent", mode=mode, effort=effort,
                                               **store.ai_route(conn, "talent")), timeout)


# --- Ferramenta: consultar perfil -----------------------------------------------------------------------------

def secoes(perfil: str) -> dict[str, list[str]]:
    """Perfil do dono por seção (## Título → itens). Só leitura: o arquivo é do dono."""
    out, atual = {"Resumo": []}, "Resumo"
    for line in perfil.splitlines():
        if line.startswith("## "):
            atual = line[3:].strip()
            out[atual] = []
        elif line.strip() and not line.startswith("# "):
            out[atual].append(line.strip().removeprefix("- "))
    return {k: v for k, v in out.items() if v}


# --- Ferramenta: avaliar oportunidade -------------------------------------------------------------------------

def parse_avaliacao(output: str, perfil: str) -> dict:
    """Confere a extração do agente. Evidência que não está no perfil derruba o requisito para "ausente"."""
    data, corpus = _json(output), _norm(perfil)
    reqs = []
    for r in (data.get("requisitos") or [])[:15]:
        if not isinstance(r, dict) or not _s(r.get("texto"), 200):
            continue
        situacao = r.get("situacao") if r.get("situacao") in ("atendido", "parcial", "ausente") else "ausente"
        evidencia = _s(r.get("evidencia"), 200)
        sem_prova = situacao != "ausente" and (len(evidencia) < 3 or _norm(evidencia) not in corpus)
        reqs.append({"texto": _s(r["texto"], 200),
                     "tipo": "desejavel" if r.get("tipo") == "desejavel" else "obrigatorio",
                     "categoria": r.get("categoria") if r.get("categoria") in (
                         "tecnico", "experiencia", "formacao", "idioma", "outro") else "outro",
                     "situacao": "ausente" if sem_prova else situacao,
                     "evidencia": "" if sem_prova else evidencia,
                     **({"evidencia_recusada": True} if sem_prova else {})})
    anos = data.get("anos_experiencia")
    return {"requisitos": reqs,
            "senioridade": data.get("senioridade") if data.get("senioridade") in (
                "estagio", "junior", "pleno", "senior") else "nao_informada",
            "anos_experiencia": int(anos) if isinstance(anos, (int, float)) and 0 <= anos <= 30 else None,
            "contratacao": data.get("contratacao") if data.get("contratacao") in (
                "clt", "pj", "estagio") else "nao_informada",
            "perfil_curriculo": data.get("perfil_curriculo") if data.get("perfil_curriculo") in PERFIS else "junior",
            "posicionamento": _s(data.get("posicionamento"), 400),
            "destaques": [{"item": _s(d.get("item"), 200), "motivo": _s(d.get("motivo"), 300)}
                          for d in (data.get("destaques") or [])[:4] if isinstance(d, dict) and d.get("item")],
            "orientacoes": [_s(o, 300) for o in (data.get("orientacoes") or [])[:6]
                            if isinstance(o, str) and len(o.strip()) >= 20 and not GENERIC.search(o.strip())],
            "justificativa": _s(data.get("justificativa"), 800)}


def filtros(vaga, extr: dict) -> list[dict]:
    """Critérios obrigatórios do dono (match.py) e a mesma regra de senioridade aplicada à descrição."""
    verdict, _, reasons = match.evaluate(dict(vaga))
    out = [{"filtro": "Regras do dono: cargo, local, modalidade, salário e senioridade no título",
            "ok": verdict == "compativel", "motivo": "; ".join(reasons) or verdict}]
    acima = extr["senioridade"] in ("pleno", "senior")
    out.append({"filtro": "Senioridade pedida na descrição", "ok": not acima,
                "motivo": f"a descrição pede {extr['senioridade']}: pela sua regra, acima de júnior não entra na fila"
                if acima else f"senioridade {extr['senioridade'].replace('_', ' ')}"})
    return out


def pontuar(vaga, extr: dict) -> tuple[int, list[dict]]:
    reqs = extr["requisitos"]

    def cobertura(items) -> float | None:
        return sum({"atendido": 1, "parcial": 0.5}.get(r["situacao"], 0) for r in items) / len(items) if items else None

    def item(chave: str, frac: float, motivo: str) -> dict:
        return {"criterio": CRITERIO_NOME[chave], "peso": PESOS[chave], "pontos": round(PESOS[chave] * frac, 1),
                "motivo": motivo}

    def cobre(chave: str, items, vazio: float, sem: str) -> dict:
        c = cobertura(items)
        if c is None:
            return item(chave, vazio, sem)
        ok = sum(r["situacao"] == "atendido" for r in items)
        part = sum(r["situacao"] == "parcial" for r in items)
        return item(chave, c, f"{ok} atendido(s), {part} parcial(is), {len(items) - ok - part} ausente(s) de {len(items)}")

    tecnicos = [r for r in reqs if r["tipo"] == "obrigatorio" and r["categoria"] in ("tecnico", "experiencia", "outro")]
    anos = extr["anos_experiencia"]
    frac_anos, motivo_anos = (1, "pede até 1 ano ou não informa") if anos is None or anos <= 1 else (
        (0.67, "pede 2 anos") if anos == 2 else (0.33, f"pede {anos} anos"))
    remoto = vaga["workplace"] == "remoto"
    salario = vaga["salary_min"]
    contrato = extr["contratacao"]
    area = [n for n, rx in match.SKILLS.items() if rx.search(vaga["title"])]
    criterios = [
        cobre("tecnicos_obrigatorios", tecnicos, 0.5, "a vaga não lista requisitos obrigatórios: neutro"),
        cobre("desejaveis", [r for r in reqs if r["tipo"] == "desejavel"], 0.5, "sem desejáveis listados: neutro"),
        item("senioridade_experiencia", frac_anos, f"senioridade {extr['senioridade'].replace('_', ' ')}; {motivo_anos}"),
        cobre("formacao_idiomas", [r for r in reqs if r["tipo"] == "obrigatorio" and r["categoria"] in ("formacao", "idioma")],
              1, "sem exigência de formação ou idioma"),
        item("local_modalidade", 1 if remoto else 0.5,
             "remoto" if remoto else f"{vaga['workplace']} em {vaga['location']}: depende de salário ou porte"),
        item("contratacao", 0.5 if contrato == "pj" else 1,
             "PJ: você prefere CLT e aceita conversar" if contrato == "pj" else f"contratação {contrato.replace('_', ' ')}"),
        item("remuneracao", 1 if salario is not None else 0.5,
             f"salário publicado ({salario:.0f})" if salario is not None else "salário não publicado: neutro"),
        item("area_preferida", 1 if area else 0.5,
             "título em área preferida: " + ", ".join(area) if area else "área preferida não aparece no título"),
    ]
    return round(sum(c["pontos"] for c in criterios)), criterios


def entrada(perfil: str, vaga) -> str:
    return _sha(RUBRICA, perfil, vaga["title"], vaga["company"], vaga["location"], vaga["workplace"],
                str(vaga["salary_min"]), vaga["description"] or "")


def gravar_avaliacao(conn, vaga, perfil: str, extr: dict) -> dict:
    """Aplica filtros e rubrica à extração conferida e grava (idempotente pela entrada)."""
    fs = filtros(vaga, extr)
    pontuacao, criterios = pontuar(vaga, extr)
    elegivel = all(f["ok"] for f in fs) and pontuacao >= candidatura.MIN_ADERENCIA
    sha = entrada(perfil, vaga)
    conn.execute(
        "INSERT INTO talent_avaliacoes (vaga_id, entrada_sha, rubrica, elegivel, pontuacao, filtros_json, criterios_json,"
        " requisitos_json, posicionamento, perfil_curriculo, destaques_json, orientacoes_json, justificativa, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (vaga_id, entrada_sha) DO NOTHING",
        (vaga["id"], sha, RUBRICA, int(elegivel), pontuacao, *(json.dumps(x, ensure_ascii=False) for x in (
            fs, criterios, extr["requisitos"])), extr["posicionamento"], extr["perfil_curriculo"],
         json.dumps(extr["destaques"], ensure_ascii=False), json.dumps(extr["orientacoes"], ensure_ascii=False),
         extr["justificativa"], db.utcnow()))
    row = conn.execute("SELECT * FROM talent_avaliacoes WHERE vaga_id = ? AND entrada_sha = ?", (vaga["id"], sha)).fetchone()
    motivo = next((f["motivo"] for f in fs if not f["ok"]), None) or (
        "" if elegivel else f"compatibilidade {pontuacao} abaixo de {candidatura.MIN_ADERENCIA}")
    registro.evento(conn, vaga["id"], "avaliada_talent", "talent", avaliacao_id=row["id"], elegivel=elegivel,
                    pontuacao=pontuacao, perfil=extr["perfil_curriculo"], motivo=motivo)
    return dict(row)


def pendentes_avaliacao(conn, perfil: str, limit: int) -> list:
    """Compatíveis pelas regras, sem candidatura, sem avaliação para o perfil/rubrica atuais e sem falhas demais."""
    rows = conn.execute(
        "SELECT v.rowid AS n, v.* FROM carreira_vagas v LEFT JOIN carreira_candidaturas c ON c.vaga_id = v.id "
        "WHERE v.verdict = 'compativel' AND c.vaga_id IS NULL AND NOT EXISTS (SELECT 1 FROM carreira_candidaturas c2 "
        f"JOIN carreira_vagas o ON o.id = c2.vaga_id WHERE {registro.SAME_JOB}) "
        "AND (SELECT COUNT(*) FROM carreira_execucoes x WHERE x.vaga_id = v.id AND x.tipo = 'avaliacao' "
        "AND x.estado = 'falhou') < ? ORDER BY v.score DESC, v.first_seen", (MAX_FALHAS,)).fetchall()
    out = []
    for vaga in rows:
        if not conn.execute("SELECT 1 FROM talent_avaliacoes WHERE vaga_id = ? AND entrada_sha = ?",
                            (vaga["id"], entrada(perfil, vaga))).fetchone():
            out.append(vaga)
            if len(out) >= limit:
                break
    return out


async def avaliar_pendentes(conn, mentor, limit: int = PER_CYCLE) -> list[str]:
    perfil = alfaiate.profile()
    if perfil is None:
        return []
    done = []
    for vaga in pendentes_avaliacao(conn, perfil, limit):
        with registro.execucao(conn, "avaliacao", vaga["id"]) as run:
            try:
                extr = parse_avaliacao(await ask(conn, mentor, alfaiate.prompt(perfil, vaga), "talent_avaliacao", "low",
                                                 TIMEOUT_AVALIACAO), perfil)
            except Exception as exc:  # noqa: BLE001 — uma vaga que falha não para as outras; até MAX_FALHAS
                log.warning("talent: avaliação falhou em %s: %s", vaga["id"], type(exc).__name__)
                run["erro"] = f"resposta do Talent não aproveitada ({type(exc).__name__})"
                continue
            row = gravar_avaliacao(conn, vaga, perfil, extr)
            run["resultado"] = f"{'elegível' if row['elegivel'] else 'não elegível'} · compatibilidade {row['pontuacao']}"
            done.append(vaga["id"])
    return done


# --- Ferramenta: revisar currículo ----------------------------------------------------------------------------

def checagens(cv: str, fontes: str) -> tuple[list[dict], list[dict]]:
    """Checagens sem IA. `fontes` = perfil + currículo-base (o que o dono escreveu). Devolve (checagens, problemas)."""
    checks, problems = [], []

    def check(criterio: str, ok: bool, detalhe: str, problema: dict | None = None) -> None:
        checks.append({"criterio": criterio, "ok": ok, "detalhe": detalhe})
        if not ok and problema:
            problems.append({"criterio": criterio, **problema})

    novas = sorted(_tech(cv) - _tech(fontes))
    check("precisao_factual", not novas, "tecnologias do currículo conferidas no perfil" if not novas else
          "tecnologias fora do perfil: " + ", ".join(novas),
          {"gravidade": "bloqueante", "trecho": ", ".join(novas),
           "correcao": f"Remover {', '.join(novas)}: não aparece(m) no perfil nem no currículo-base."})
    known = set(re.findall(r"\d+", fontes))
    numeros = sorted({n for n in re.findall(r"\d+", cv) if n not in known}, key=len)
    check("precisao_factual", not numeros, "números e datas conferidos no perfil" if not numeros else
          "números sem origem no perfil: " + ", ".join(numeros[:8]),
          {"gravidade": "bloqueante", "trecho": ", ".join(numeros[:8]),
           "correcao": f"Remover ou corrigir os números {', '.join(numeros[:8])}: nenhum aparece no perfil; use só "
                       "datas e quantidades escritas lá."})
    titulos = " ".join(line for line in cv.splitlines() if line.lstrip().startswith("#")).lower()
    faltam = [nome for nome, rx in (("Experiência", r"experi[eê]ncia|experience"),
                                    ("Formação", r"forma[çc][ãa]o|educa|education")) if not re.search(rx, titulos)]
    check("ats", not faltam, "títulos de seção convencionais" if not faltam else "faltam títulos: " + ", ".join(faltam),
          {"gravidade": "importante", "trecho": "",
           "correcao": f"Usar títulos de seção convencionais ({', '.join(faltam)}) para a extração das plataformas."})
    layout = [nome for nome, rx in (("tabela", r"^\s*\|.*\|"), ("imagem", r"!\[|<img"), ("HTML", r"<(div|table|span)"))
              if re.search(rx, cv, re.M | re.I)]
    check("ats", not layout, "texto corrido em uma coluna" if not layout else "contém " + ", ".join(layout),
          {"gravidade": "importante", "trecho": ", ".join(layout),
           "correcao": "Trocar tabela/imagem/HTML por texto corrido em uma coluna: duas colunas se misturam na extração."})
    palavras = len(cv.split())
    check("estrutura", palavras <= 800, f"{palavras} palavras",
          {"gravidade": "importante", "trecho": "",
           "correcao": f"Cortar para até 800 palavras (hoje {palavras}): uma página para nível júnior; resumir o que "
                       "não se liga à vaga."})
    check("ats", "@" in cv, "contato presente" if "@" in cv else "sem e-mail de contato",
          {"gravidade": "importante", "trecho": "", "correcao": "Incluir o e-mail de contato do perfil no topo."})
    return checks, problems


def parse_revisao(output: str) -> dict:
    data = _json(output)
    problemas = []
    for p in (data.get("problemas") or [])[:12]:
        if not isinstance(p, dict) or p.get("criterio") not in CRITERIOS_REVISAO:
            continue
        correcao = _s(p.get("correcao"), 400)
        if len(correcao) < 20 or GENERIC.search(correcao):  # recomendação genérica não é executável
            continue
        problemas.append({"criterio": p["criterio"], "gravidade": p.get("gravidade") if p.get("gravidade") in (
            "bloqueante", "importante", "menor") else "importante", "trecho": _s(p.get("trecho"), 300),
            "correcao": correcao})
    resultado = data.get("resultado")
    if resultado not in ("aprovado", "correcoes", "bloqueado"):
        raise ValueError("resultado inválido")
    if resultado != "aprovado" and not problemas:  # reprovar sem dizer o quê, ou só com genérico, não é revisão
        raise ValueError("reprovação sem problema específico")
    return {"resultado": resultado, "resumo": _s(data.get("resumo"), 400), "problemas": problemas}


def decidir(llm_resultado: str, problemas: list[dict]) -> str:
    """O resultado segue os problemas, não só a palavra do agente: fato sem comprovação nunca é aprovado, e
    "bloqueado" exige uma inconsistência factual."""
    factual = any(p["criterio"] == "precisao_factual" for p in problemas)
    if llm_resultado == "bloqueado" and factual:
        return "bloqueado"
    return "correcoes" if any(p["gravidade"] in ("bloqueante", "importante") for p in problemas) else "aprovado"


def avaliacao_atual(conn, vaga_id: str):
    return conn.execute("SELECT * FROM talent_avaliacoes WHERE vaga_id = ? ORDER BY id DESC LIMIT 1",
                        (vaga_id,)).fetchone()


def _bloco_avaliacao(av) -> str:
    if av is None:
        return ""
    reqs = "; ".join(f"{r['texto']} ({r['situacao']})" for r in json.loads(av["requisitos_json"]))
    return (f"\nAVALIAÇÃO DO TALENT (compatibilidade {av['pontuacao']}, perfil {av['perfil_curriculo']}):\n"
            f"Posicionamento: {av['posicionamento']}\nRequisitos: {reqs}\n")


async def revisar(conn, mentor, cand, perfil: str, fontes: str) -> dict:
    """Revisa a versão atual do currículo de uma candidatura e grava (uma revisão por versão)."""
    av = avaliacao_atual(conn, cand["id"])
    rodada = conn.execute("SELECT COUNT(*) FROM talent_revisoes WHERE vaga_id = ?", (cand["id"],)).fetchone()[0] + 1
    checks, problemas = checagens(cand["curriculo_md"], fontes)
    if any(p["criterio"] == "precisao_factual" for p in problemas):  # o código já achou: não gasta chamada de IA
        llm = {"resultado": "correcoes", "resumo": "Checagem automática encontrou afirmações fora do perfil.",
               "problemas": []}
    else:
        text = (alfaiate.prompt(perfil, cand) + _bloco_avaliacao(av) +
                f"\nCURRÍCULO (gerado pelo Alfaiate; material a conferir):\n{cand['curriculo_md']}\n")
        llm = parse_revisao(await ask(conn, mentor, text, "talent_revisao", "medium", TIMEOUT_REVISAO))
    problemas += llm["problemas"]
    resultado = decidir(llm["resultado"], problemas)
    resumo = llm["resumo"] or {"aprovado": "Aprovado para envio.", "correcoes": "Correções pedidas ao Alfaiate.",
                               "bloqueado": "Bloqueado por inconsistência factual."}[resultado]
    conn.execute(
        "INSERT INTO talent_revisoes (vaga_id, curriculo_id, avaliacao_id, rodada, resultado, checagens_json,"
        " problemas_json, resumo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cand["id"], cand["curriculo_id"], av["id"] if av else None, rodada, resultado,
         json.dumps(checks, ensure_ascii=False), json.dumps(problemas, ensure_ascii=False), resumo, db.utcnow()))
    registro.evento(conn, cand["id"], f"revisao_{resultado}", "talent", curriculo_id=cand["curriculo_id"], rodada=rodada,
                    problemas=len(problemas), resumo=resumo)
    return {"resultado": resultado, "problemas": problemas, "rodada": rodada}


def _cand(conn, vaga_id: str):
    return conn.execute("SELECT v.rowid AS n, v.*, c.curriculo_md, c.curriculo_id, c.status FROM carreira_candidaturas c "
                        "JOIN carreira_vagas v ON v.id = c.vaga_id WHERE c.vaga_id = ?", (vaga_id,)).fetchone()


def _bloquear(conn, vaga_id: str, motivo: str) -> None:
    conn.execute("UPDATE carreira_candidaturas SET status = 'falhou', updated_at = ? WHERE vaga_id = ?",
                 (db.utcnow(), vaga_id))
    registro.evento(conn, vaga_id, "revisao_bloqueada", "talent", motivo=motivo)


def pendentes_revisao(conn, limit: int) -> list:
    """Candidaturas com currículo pronto cuja versão atual ainda não foi aprovada (sem revisão ou com correções)."""
    return conn.execute(
        "SELECT c.vaga_id FROM carreira_candidaturas c LEFT JOIN talent_revisoes r ON r.curriculo_id = c.curriculo_id "
        "WHERE c.status = 'curriculo' AND c.curriculo_id IS NOT NULL AND (r.id IS NULL OR r.resultado = 'correcoes') "
        "ORDER BY c.aderencia DESC, c.created_at LIMIT ?", (limit,)).fetchall()


async def revisar_pendentes(conn, mentor, limit: int = PER_CYCLE) -> list[str]:
    """Revisa e, quando há correções, devolve ao Alfaiate e revisa de novo, até MAX_RODADAS. Devolve avisos."""
    perfil = alfaiate.profile()
    if perfil is None:
        return []
    fontes = perfil + "\n" + (registro.curriculo_base_md() or "")
    avisos = []
    for (vaga_id,) in pendentes_revisao(conn, limit):
        anterior = None
        for _ in range(2 * MAX_RODADAS):  # revisão e correção alternadas; o teto real é MAX_RODADAS revisões
            cand = _cand(conn, vaga_id)
            rev = conn.execute("SELECT * FROM talent_revisoes WHERE curriculo_id = ?", (cand["curriculo_id"],)).fetchone()
            if rev is None:
                with registro.execucao(conn, "revisao", vaga_id) as run:
                    try:
                        out = await revisar(conn, mentor, cand, perfil, fontes)
                    except Exception as exc:  # noqa: BLE001 — resposta inválida: tenta na próxima volta, até MAX_FALHAS
                        run["erro"] = f"resposta do Talent não aproveitada ({type(exc).__name__})"
                        if _falhas(conn, vaga_id, "revisao") + 1 >= MAX_FALHAS:
                            _bloquear(conn, vaga_id, f"revisão falhou {MAX_FALHAS} vezes")
                        break
                    run["resultado"] = f"{out['resultado']} · rodada {out['rodada']} · {len(out['problemas'])} problema(s)"
                rev = conn.execute("SELECT * FROM talent_revisoes WHERE curriculo_id = ?", (cand["curriculo_id"],)).fetchone()
            if rev["resultado"] == "aprovado":
                break
            problemas = json.loads(rev["problemas_json"])
            factuais = sorted(p["trecho"] for p in problemas if p["criterio"] == "precisao_factual")
            motivo = ("inconsistência factual: " + rev["resumo"] if rev["resultado"] == "bloqueado" else
                      f"sem aprovação em {MAX_RODADAS} revisões" if rev["rodada"] >= MAX_RODADAS else
                      "sem progresso: a correção repetiu os mesmos fatos sem comprovação"
                      if factuais and factuais == anterior else None)
            if motivo:
                _bloquear(conn, vaga_id, motivo)
                avisos.append(f"*Talent bloqueou o currículo* de #{cand['n']} {cand['title'][:90]}\n{motivo}")
                break
            anterior = factuais
            if _falhas(conn, vaga_id, "curriculo") >= MAX_FALHAS:
                _bloquear(conn, vaga_id, f"o Alfaiate não conseguiu corrigir ({MAX_FALHAS} respostas inválidas)")
                break
            if not await alfaiate.corrigir(conn, mentor, vaga_id, problemas):
                break  # resposta inválida: a correção volta na próxima volta
    return avisos


def _falhas(conn, vaga_id: str, tipo: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM carreira_execucoes WHERE vaga_id = ? AND tipo = ? AND estado = 'falhou'",
                        (vaga_id, tipo)).fetchone()[0]


# --- Ferramentas: consultar resultados, produzir recomendações e propostas -------------------------------------

def _taxa(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def indicadores(conn) -> dict:
    """Desempenho das candidaturas a partir do que os agentes e o dono registraram. Sem IA, sem causalidade."""
    rows = conn.execute(
        "SELECT v.source, c.status, c.etapa, c.curriculo_id, k.origem_id,"
        " (SELECT perfil_curriculo FROM talent_avaliacoes a WHERE a.vaga_id = v.id ORDER BY a.id DESC LIMIT 1) AS perfil"
        " FROM carreira_candidaturas c JOIN carreira_vagas v ON v.id = c.vaga_id"
        " LEFT JOIN carreira_curriculos k ON k.id = c.curriculo_id WHERE c.status = 'candidatada'").fetchall()

    def grupo(chave) -> list[dict]:
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(chave(r) or "sem avaliação do Talent", []).append(r)
        return sorted(({"grupo": k, "enviadas": len(v), "respostas": sum(r["etapa"] is not None for r in v),
                        "entrevistas": sum(r["etapa"] in ("entrevista", "proposta") for r in v),
                        "amostra_suficiente": len(v) >= MIN_AMOSTRA} for k, v in out.items()),
                      key=lambda g: -g["enviadas"])

    enviadas = len(rows)
    respostas = sum(r["etapa"] is not None for r in rows)
    entrevistas = sum(r["etapa"] in ("entrevista", "proposta") for r in rows)
    termos: dict[str, dict] = {}
    avaliadas = conn.execute("SELECT a.requisitos_json, a.elegivel FROM talent_avaliacoes a WHERE a.id = "
                             "(SELECT MAX(id) FROM talent_avaliacoes b WHERE b.vaga_id = a.vaga_id)").fetchall()
    for av in avaliadas:
        for r in json.loads(av["requisitos_json"]):
            for t in _tech(r["texto"]) or {_norm(r["texto"])[:60]}:
                d = termos.setdefault(t, {"termo": t, "vagas": 0, "atendido": 0, "parcial": 0, "ausente": 0,
                                          "evidencia": ""})
                d["vagas"] += 1
                d[r["situacao"]] += 1
                d["evidencia"] = d["evidencia"] or r["evidencia"]
    motivos: dict[str, int] = {}
    for (fs,) in conn.execute("SELECT filtros_json FROM talent_avaliacoes WHERE elegivel = 0"):
        for f in json.loads(fs):
            if not f["ok"]:
                motivos[f["filtro"]] = motivos.get(f["filtro"], 0) + 1
    revisoes = dict(conn.execute("SELECT resultado, COUNT(*) FROM talent_revisoes GROUP BY resultado").fetchall())
    problemas: dict[str, int] = {}
    for (ps,) in conn.execute("SELECT problemas_json FROM talent_revisoes"):
        for p in json.loads(ps):
            problemas[p["criterio"]] = problemas.get(p["criterio"], 0) + 1
    return {
        "candidaturas": conn.execute("SELECT COUNT(*) FROM carreira_candidaturas").fetchone()[0],
        "enviadas": enviadas, "respostas": respostas, "entrevistas": entrevistas,
        "rejeicoes": sum(r["etapa"] == "recusada" for r in rows),
        "taxa_resposta": _taxa(respostas, enviadas), "taxa_entrevista": _taxa(entrevistas, enviadas),
        "amostra_suficiente": enviadas >= MIN_AMOSTRA, "min_amostra": MIN_AMOSTRA,
        "por_plataforma": grupo(lambda r: r["source"]), "por_perfil": grupo(lambda r: r["perfil"]),
        "por_base": grupo(lambda r: f"currículo-base v{r['origem_id']}" if r["origem_id"] else None),
        "avaliadas": len(avaliadas), "elegiveis": sum(a["elegivel"] for a in avaliadas),
        "requisitos": sorted(termos.values(), key=lambda d: -d["vagas"])[:15],
        "motivos_inelegivel": sorted(({"motivo": k, "vagas": v} for k, v in motivos.items()), key=lambda d: -d["vagas"]),
        "revisoes": revisoes,
        "problemas_revisao": sorted(({"criterio": k, "vezes": v} for k, v in problemas.items()), key=lambda d: -d["vezes"]),
        "rejeicoes_conhecidas": [dict(r) for r in conn.execute(
            "SELECT empresa, resumo, received_at FROM carreira_emails WHERE tipo = 'recusa' ORDER BY created_at DESC "
            "LIMIT 5").fetchall()],
    }


def recomendacoes(ind: dict, curriculo_base: str) -> tuple[list[dict], list[dict]]:
    """Recomendações fundamentadas nos indicadores e propostas ao dono. Devolve (recomendações, propostas)."""
    recs, props = [], []
    if not ind["amostra_suficiente"]:
        recs.append({"forca": "descritiva", "base": f"{ind['enviadas']} candidatura(s) enviada(s)",
                     "texto": f"Ainda há {ind['enviadas']} candidatura(s) enviada(s), menos que {ind['min_amostra']}: "
                              "as taxas são só descritivas e nenhuma plataforma ou perfil de currículo pode ser "
                              "apontado como melhor."})
    for g in ind["por_plataforma"] + ind["por_perfil"]:
        if g["amostra_suficiente"] and ind["amostra_suficiente"]:
            recs.append({"forca": "indicativa", "base": f"{g['enviadas']} enviadas em {g['grupo']}",
                         "texto": f"{g['grupo']}: {g['respostas']} resposta(s) em {g['enviadas']} envio(s) "
                                  f"({round(100 * g['respostas'] / g['enviadas'])}%). Associação observada, não causa."})
    limiar = max(3, ind["avaliadas"] * 0.3)
    for t in ind["requisitos"]:
        if t["termo"] not in TECH:
            continue
        if t["ausente"] >= limiar:
            recs.append({"forca": "descritiva", "base": f"{t['ausente']} de {ind['avaliadas']} vagas avaliadas",
                         "texto": f"'{t['termo']}' é requisito ausente em {t['ausente']} de {ind['avaliadas']} vagas "
                                  "avaliadas. Se você já usou, registre no perfil onde e como; se não, é o estudo de "
                                  "maior alcance agora."})
            props.append({"alvo": "perfil", "chave": f"perfil:{t['termo']}",
                          "proposta": f"Você tem experiência com {t['termo']}? Se sim, acrescente ao perfil com o "
                                      "contexto (empresa ou projeto). Se não, deixe como está.",
                          "origem": f"pedido em {t['vagas']} vaga(s) avaliada(s); ausente do perfil em {t['ausente']}"})
        elif t["atendido"] >= 3 and t["evidencia"] and t["termo"] not in _tech(curriculo_base):
            props.append({"alvo": "curriculo_base", "chave": f"base:{t['termo']}",
                          "proposta": f"Incluir '{t['termo']}' nas habilidades do currículo-base.",
                          "origem": f"pedido em {t['vagas']} vaga(s); comprovado no perfil: \"{t['evidencia'][:160]}\""})
    if ind["motivos_inelegivel"]:
        m = ind["motivos_inelegivel"][0]
        recs.append({"forca": "descritiva", "base": f"{m['vagas']} vaga(s)",
                     "texto": f"Motivo mais comum de vaga descartada: {m['motivo']} ({m['vagas']} vaga(s)). Seus "
                              "critérios não foram alterados; mudar é decisão sua."})
    total_rev = sum(ind["revisoes"].values())
    if ind["problemas_revisao"] and total_rev:
        p = ind["problemas_revisao"][0]
        recs.append({"forca": "descritiva", "base": f"{total_rev} revisão(ões)",
                     "texto": f"Problema mais frequente nas revisões do Talent: {p['criterio'].replace('_', ' ')} "
                              f"({p['vezes']} vez(es) em {total_rev} revisão(ões))."})
    return recs, props


def analisar(conn) -> int:
    """Análise periódica: grava indicadores e recomendações (talent_analises) e propostas novas. Devolve o id."""
    with registro.execucao(conn, "analise") as run:
        ind = indicadores(conn)
        recs, props = recomendacoes(ind, registro.curriculo_base_md() or "")
        now = db.utcnow()
        for p in props:
            conn.execute("INSERT INTO talent_propostas (alvo, proposta, origem, chave, created_at) VALUES (?, ?, ?, ?, ?) "
                         "ON CONFLICT (chave) DO NOTHING", (p["alvo"], p["proposta"], p["origem"], p["chave"], now))
        analise_id = conn.execute("INSERT INTO talent_analises (indicadores_json, recomendacoes_json, created_at) "
                                  "VALUES (?, ?, ?) RETURNING id", (json.dumps(ind, ensure_ascii=False),
                                                                    json.dumps(recs, ensure_ascii=False), now)).fetchone()[0]
        run["resultado"] = f"{len(recs)} recomendação(ões), {len(props)} proposta(s)"
    return analise_id


def analise_devida(conn, now: datetime | None = None) -> bool:
    last = conn.execute("SELECT created_at FROM talent_analises ORDER BY id DESC LIMIT 1").fetchone()
    now = now or datetime.now(timezone.utc)
    return last is None or now - datetime.fromisoformat(last[0]) >= timedelta(days=ANALISE_DIAS)
