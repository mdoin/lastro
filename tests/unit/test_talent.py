# SPDX-License-Identifier: AGPL-3.0-or-later
"""Talent (docs/CARREIRA.md): registro, rubrica com filtros obrigatórios, revisão com limite de rodadas, integração
com Alfaiate e Aplicador, memória e análise de resultados.

Todas as vagas são fictícias, marcadas "[TESTE]", e os agentes são simulados: nada sai para a internet nem para
plataforma de vagas.
"""
import asyncio
import json
import sqlite3

import pytest

from app import db, store
from carreira import alfaiate, candidatura, hunter, registro, sources, talent

PERFIL = """# Pessoa de Teste — perfil base (DADO DE TESTE)
Nível: júnior. Contato: teste@example.com
## Experiência
- Junior Software Engineer — Empresa Fictícia · ago/2026 – atual
  - Construiu servidores MCP que expõem PostgreSQL como ferramentas para agentes.
  - Criou APIs em FastAPI com Python.
## Formação
- Tecnólogo em ADS (em andamento)
"""
CV_OK = ("# Pessoa de Teste\nteste@example.com\n## Experiência\n- Junior Software Engineer — Empresa Fictícia · "
         "ago/2026 – atual: APIs em FastAPI com Python e servidores MCP com PostgreSQL.\n## Formação\n- Tecnólogo em ADS")
CV_INVENTADO = CV_OK.replace("PostgreSQL.", "PostgreSQL e Kubernetes, reduzindo custos em 40%.")


@pytest.fixture(autouse=True)
def _arquivos_de_teste(monkeypatch, tmp_path):
    (tmp_path / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (tmp_path / "respostas.md").write_text("Respostas de teste", encoding="utf-8")
    for k, f in (("PERFIL", "perfil.md"), ("RESPOSTAS", "respostas.md"), ("CURRICULO", "sem-curriculo.md")):
        monkeypatch.setenv(f"CARREIRA_{k}", str(tmp_path / f))


def vaga(title="[TESTE] Desenvolvedor Python Júnior", description="Requisitos: Python, FastAPI. Desejável: Docker.",
         workplace="remoto", location="", jid=None):
    return sources.Job(id=jid or f"gupy:{title}", source="gupy", url=f"https://teste.example/{abs(hash(title))}",
                       title=title, company="ACME Teste", location=location, workplace=workplace, salary_min=None,
                       currency=None, description=description, published_at=None)


def avaliacao(senioridade="junior", situacao="atendido", evidencia="Criou APIs em FastAPI com Python", **extra) -> str:
    return json.dumps({"requisitos": [
        {"texto": "Python", "tipo": "obrigatorio", "categoria": "tecnico", "situacao": situacao, "evidencia": evidencia},
        {"texto": "FastAPI", "tipo": "obrigatorio", "categoria": "tecnico", "situacao": situacao, "evidencia": evidencia},
        {"texto": "Docker", "tipo": "desejavel", "categoria": "tecnico", "situacao": "ausente", "evidencia": ""}],
        "senioridade": senioridade, "anos_experiencia": None, "contratacao": "clt", "perfil_curriculo": "backend",
        "posicionamento": "Backend Python júnior com APIs FastAPI e PostgreSQL",
        "destaques": [{"item": "servidores MCP com PostgreSQL", "motivo": "a vaga pede integração de dados"}],
        "orientacoes": ["Reduzir a parte de agentes e destacar FastAPI e PostgreSQL, pois a vaga prioriza backend Python."],
        "justificativa": "Atende Python e FastAPI; Docker é desejável e ausente.", **extra})


ALFAIATE = lambda cv: json.dumps({"aderencia": 99, "resumo": "ok", "idioma": "pt", "lacunas": [], "curriculo_md": cv,  # noqa: E731
                                  "carta": "Olá", "alteracoes": ["resumo focado em backend"]})
APROVADO = json.dumps({"resultado": "aprovado", "resumo": "Pronto para envio.", "problemas": []})


class Mentor:
    """Agentes simulados por papel/modo; cada resposta pode ser uma lista consumida em ordem."""
    def __init__(self, **answers):
        self.answers, self.requests = answers, []

    async def stream(self, request):
        self.requests.append(request)
        answer = self.answers[request.get("mode") or request["role"]]
        yield {"type": "done", "text": answer.pop(0) if isinstance(answer, list) else answer}

    def kinds(self):
        return [r.get("mode") or r["role"] for r in self.requests]


def setup(tmp_path, *jobs):
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    hunter.store(conn, list(jobs) or [vaga()])
    return conn


def run(coro):
    return asyncio.run(coro)


# --- registro e permissões ------------------------------------------------------------------------------------

def test_registro_talent_sem_ferramentas_nem_navegador():
    from mentor.session import load_prompt, session_spec
    from mentor.tools import ROLE_CAPABILITIES, tools_for
    from team.agents import AGENTS

    spec = AGENTS["talent"]
    assert spec.kind == "internal" and not spec.chat_enabled and spec.max_turns == 1
    caps = ROLE_CAPABILITIES["talent"]
    assert caps.data is False and caps.browser is None and not caps.research and not caps.memory
    assert tools_for(caps) == []
    for mode in ("talent_avaliacao", "talent_revisao"):
        session = session_spec(role="talent", workdir=__import__("pathlib").Path("."), mode=mode)
        assert session.tools == []  # permissão real: o servidor MCP da sessão não registra ferramenta nenhuma
        assert session.system_prompt.startswith("Você é o Talent") and "mentor financeiro" not in session.system_prompt
    assert "pontuação universal de ATS" in load_prompt("talent") and "2026-11-05" in load_prompt("talent")


def test_talent_nao_le_cofre_respostas_nem_aciona_aplicador(tmp_path):
    conn = setup(tmp_path)
    mentor = Mentor(talent_avaliacao=avaliacao())
    run(talent.avaliar_pendentes(conn, mentor))
    [req] = mentor.requests
    assert req["role"] == "talent" and "aplicacao" not in req and "Respostas de teste" not in req["text"]
    source = open(talent.__file__, encoding="utf-8").read()
    assert "cofre" not in source.split('"""', 2)[2] and "apply_pending" not in source and "answers()" not in source


# --- avaliação: filtros obrigatórios e rubrica ----------------------------------------------------------------

def test_avaliacao_elegivel_com_rubrica_transparente_e_evento(tmp_path):
    conn = setup(tmp_path)
    mentor = Mentor(talent_avaliacao=avaliacao())
    assert run(talent.avaliar_pendentes(conn, mentor)) == ["gupy:[TESTE] Desenvolvedor Python Júnior"]
    req = mentor.requests[0]
    assert req["mode"] == "talent_avaliacao" and req["effort"] == "low" and "DADO NÃO CONFIÁVEL" in req["text"]
    a = conn.execute("SELECT * FROM talent_avaliacoes").fetchone()
    criterios = json.loads(a["criterios_json"])
    assert sum(c["peso"] for c in criterios) == 100 and round(sum(c["pontos"] for c in criterios)) == a["pontuacao"]
    assert a["elegivel"] == 1 and a["pontuacao"] >= candidatura.MIN_ADERENCIA and a["rubrica"] == talent.RUBRICA
    assert all(f["ok"] for f in json.loads(a["filtros_json"]))
    reqs = json.loads(a["requisitos_json"])
    assert [r["situacao"] for r in reqs] == ["atendido", "atendido", "ausente"] and reqs[0]["evidencia"]
    ev = conn.execute("SELECT origem, detalhe_json FROM carreira_eventos WHERE tipo = 'avaliada_talent'").fetchone()
    assert ev["origem"] == "talent" and json.loads(ev["detalhe_json"])["elegivel"] is True
    assert conn.execute("SELECT tipo, estado FROM carreira_execucoes").fetchall()[-1][:] == ("avaliacao", "concluida")
    assert run(talent.avaliar_pendentes(conn, mentor)) == [] and len(mentor.requests) == 1  # idempotente


def test_filtro_obrigatorio_vence_pontuacao_alta(tmp_path):
    conn = setup(tmp_path)
    run(talent.avaliar_pendentes(conn, Mentor(talent_avaliacao=avaliacao(senioridade="pleno"))))
    a = conn.execute("SELECT * FROM talent_avaliacoes").fetchone()
    assert a["pontuacao"] >= candidatura.MIN_ADERENCIA and a["elegivel"] == 0  # pontua bem, mas viola a regra do dono
    assert "acima de júnior" in json.loads(a["filtros_json"])[1]["motivo"]
    assert alfaiate.pending(conn, 10) == []  # o Alfaiate não recebe

    fora = vaga("[TESTE] Desenvolvedor Python Júnior", workplace="hibrido", location="Curitiba, PR", jid="gupy:fora")
    fs = talent.filtros(dict(fora), talent.parse_avaliacao(avaliacao(), PERFIL))
    assert fs[0]["ok"] is False and "Curitiba" in fs[0]["motivo"]


def test_evidencia_que_nao_esta_no_perfil_vira_ausente():
    extr = talent.parse_avaliacao(avaliacao(evidencia="5 anos de experiência com FastAPI em produção"), PERFIL)
    assert all(r["situacao"] == "ausente" and r.get("evidencia_recusada") for r in extr["requisitos"][:2])
    score, _ = talent.pontuar(dict(vaga()), extr)
    assert score < candidatura.MIN_ADERENCIA  # sem evidência, não há compatibilidade


def test_orientacao_generica_e_descartada_e_rota_de_modelo_do_agente(tmp_path):
    extr = talent.parse_avaliacao(avaliacao(orientacoes=["Melhorar o currículo", "Destacar FastAPI e PostgreSQL no "
                                                         "resumo, pois a vaga prioriza backend Python."]), PERFIL)
    assert extr["orientacoes"] == ["Destacar FastAPI e PostgreSQL no resumo, pois a vaga prioriza backend Python."]
    conn = setup(tmp_path)
    conn.execute("INSERT INTO provider_connections (id, provider, label, config_json, created_at, updated_at) "
                 "VALUES ('barata', 'ollama', 'Barata', '{}', 'x', 'x')") if _has(conn, "provider_connections") else None
    store.set_agent_model(conn, "talent", "barata", "modelo-pequeno")
    mentor = Mentor(talent_avaliacao=avaliacao())
    run(talent.avaliar_pendentes(conn, mentor))
    assert mentor.requests[0]["connection"] == "barata" and mentor.requests[0]["model"] == "modelo-pequeno"


def _has(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def test_resposta_invalida_tem_limite_de_tentativas(tmp_path):
    conn = setup(tmp_path)
    mentor = Mentor(talent_avaliacao="não é JSON")
    for _ in range(4):
        run(talent.avaliar_pendentes(conn, mentor))
    assert len(mentor.requests) == talent.MAX_FALHAS  # não reavalia indefinidamente
    assert conn.execute("SELECT COUNT(*) FROM talent_avaliacoes").fetchone()[0] == 0
    assert {r[0] for r in conn.execute("SELECT estado FROM carreira_execucoes WHERE tipo = 'avaliacao'")} == {"falhou"}


# --- Alfaiate orientado pelo Talent -----------------------------------------------------------------------------

def test_alfaiate_recebe_orientacao_e_herda_compatibilidade(tmp_path):
    conn = setup(tmp_path)
    mentor = Mentor(talent_avaliacao=avaliacao(), alfaiate=ALFAIATE(CV_OK))
    run(talent.avaliar_pendentes(conn, mentor))
    run(alfaiate.tailor_pending(conn, mentor))
    text = mentor.requests[1]["text"]
    assert "ORIENTAÇÃO DO TALENT" in text and "destacar FastAPI e PostgreSQL" in text
    assert "NÃO comprova" in text and "Docker" in text.split("NÃO comprova")[1]
    pontuacao = conn.execute("SELECT pontuacao FROM talent_avaliacoes").fetchone()[0]
    assert conn.execute("SELECT aderencia FROM carreira_candidaturas").fetchone()[0] == pontuacao  # não os 99 do Alfaiate


# --- revisão curricular -----------------------------------------------------------------------------------------

def test_checagens_detectam_informacao_inventada_e_estrutura():
    checks, problems = talent.checagens(CV_OK, PERFIL)
    assert problems == [] and all(c["ok"] for c in checks)
    _, problems = talent.checagens(CV_INVENTADO, PERFIL)
    trechos = " ".join(p["trecho"] for p in problems if p["criterio"] == "precisao_factual")
    assert "kubernetes" in trechos and "40" in trechos
    _, problems = talent.checagens("| a | b |\n|---|---|\nsem títulos", PERFIL)
    assert {p["criterio"] for p in problems} >= {"ats"}


def test_decisao_nao_aprova_fato_sem_comprovacao_e_recusa_reprovacao_generica():
    factual = [{"criterio": "precisao_factual", "gravidade": "bloqueante", "trecho": "liderou", "correcao": "x" * 30}]
    assert talent.decidir("aprovado", factual) == "correcoes"
    assert talent.decidir("bloqueado", factual) == "bloqueado"
    menor = [{"criterio": "clareza", "gravidade": "menor", "trecho": "", "correcao": "x" * 30}]
    assert talent.decidir("correcoes", menor) == "aprovado"  # ajuste fino não segura o envio nem gera ciclo
    with pytest.raises(ValueError):
        talent.parse_revisao(json.dumps({"resultado": "correcoes", "resumo": "x", "problemas": [
            {"criterio": "clareza", "gravidade": "importante", "trecho": "", "correcao": "Melhorar o currículo"}]}))


def preparar_candidatura(tmp_path, cv):
    conn = setup(tmp_path)
    mentor = Mentor(talent_avaliacao=avaliacao(), alfaiate=ALFAIATE(cv))
    run(talent.avaliar_pendentes(conn, mentor))
    run(alfaiate.tailor_pending(conn, mentor))
    return conn


def test_revisao_devolve_ao_alfaiate_e_so_aprovado_vai_ao_aplicador(tmp_path):
    conn = preparar_candidatura(tmp_path, CV_INVENTADO)
    assert candidatura.pending(conn, 10) == []  # sem revisão aprovada, o Aplicador não recebe
    mentor = Mentor(alfaiate=ALFAIATE(CV_OK), talent_revisao=APROVADO)
    assert run(talent.revisar_pendentes(conn, mentor)) == []
    # 1ª revisão foi só código (achou Kubernetes e 40%): sem chamada de IA; depois a correção e a revisão do agente
    assert mentor.kinds() == ["alfaiate", "talent_revisao"]
    pedido = mentor.requests[0]["text"]
    assert "CORREÇÕES PEDIDAS PELO TALENT" in pedido and "kubernetes" in pedido.lower() and "CURRÍCULO ANTERIOR" in pedido
    revs = conn.execute("SELECT rodada, resultado FROM talent_revisoes ORDER BY id").fetchall()
    assert [tuple(r) for r in revs] == [(1, "correcoes"), (2, "aprovado")]
    [pronta] = candidatura.pending(conn, 10)
    assert pronta["curriculo_md"] == CV_OK
    tipos = [r[0] for r in conn.execute("SELECT tipo FROM carreira_eventos ORDER BY id")]
    assert tipos[-3:] == ["revisao_correcoes", "curriculo_corrigido", "revisao_aprovado"]

    aplicador = Mentor(aplicador=json.dumps({"status": "enviada", "motivo": "ok", "evidencia": "Candidatura recebida"}))
    run(candidatura.apply_pending(conn, aplicador))
    [req] = aplicador.requests
    assert req["aplicacao"]["curriculo_md"] == CV_OK  # vai a versão aprovada, não a reprovada
    envio = conn.execute("SELECT curriculo_id FROM carreira_envios").fetchone()[0]
    assert conn.execute("SELECT resultado FROM talent_revisoes WHERE curriculo_id = ?", (envio,)).fetchone()[0] == "aprovado"


def test_sem_progresso_bloqueia_e_avisa(tmp_path):
    conn = preparar_candidatura(tmp_path, CV_INVENTADO)
    mentor = Mentor(alfaiate=ALFAIATE(CV_INVENTADO), talent_revisao=APROVADO)  # o Alfaiate repete a invenção
    avisos = run(talent.revisar_pendentes(conn, mentor))
    assert mentor.kinds() == ["alfaiate"] and len(avisos) == 1 and "sem progresso" in avisos[0]
    assert conn.execute("SELECT status FROM carreira_candidaturas").fetchone()[0] == "falhou"
    assert candidatura.pending(conn, 10) == []
    assert run(talent.revisar_pendentes(conn, mentor)) == [] and len(mentor.requests) == 1  # não volta a revisar


def test_limite_de_rodadas(tmp_path):
    conn = preparar_candidatura(tmp_path, CV_OK)
    reprova = [json.dumps({"resultado": "correcoes", "resumo": f"rodada {i}", "problemas": [
        {"criterio": "competencias", "gravidade": "importante", "trecho": f"trecho {i}",
         "correcao": f"Subir FastAPI para a primeira linha do resumo (pedido {i})."}]}) for i in range(5)]
    mentor = Mentor(alfaiate=[ALFAIATE(CV_OK + f"\n- versão {v}") for v in "abcde"], talent_revisao=reprova)
    avisos = run(talent.revisar_pendentes(conn, mentor))
    assert mentor.kinds().count("talent_revisao") == talent.MAX_RODADAS
    assert mentor.kinds().count("alfaiate") == talent.MAX_RODADAS - 1
    assert f"sem aprovação em {talent.MAX_RODADAS} revisões" in avisos[0]
    assert conn.execute("SELECT status FROM carreira_candidaturas").fetchone()[0] == "falhou"
    motivo = conn.execute("SELECT detalhe_json FROM carreira_eventos WHERE tipo = 'revisao_bloqueada'").fetchone()[0]
    assert "revisões" in json.loads(motivo)["motivo"]


def test_bloqueio_por_inconsistencia_factual(tmp_path):
    conn = preparar_candidatura(tmp_path, CV_OK)
    mentor = Mentor(talent_revisao=json.dumps({"resultado": "bloqueado", "resumo": "A vaga exige liderança formal.",
                    "problemas": [{"criterio": "precisao_factual", "gravidade": "bloqueante", "trecho": "liderou a equipe",
                                   "correcao": "Não há liderança formal no perfil: retirar 'liderou a equipe'."}]}))
    avisos = run(talent.revisar_pendentes(conn, mentor))
    assert "inconsistência factual" in avisos[0] and mentor.kinds() == ["talent_revisao"]
    assert conn.execute("SELECT resultado FROM talent_revisoes").fetchone()[0] == "bloqueado"


# --- orquestrador -----------------------------------------------------------------------------------------------

def test_fluxo_completo_na_fila_do_servico(tmp_path):
    conn = setup(tmp_path, vaga(), vaga("[TESTE] Desenvolvedor Python Júnior B", jid="gupy:b"))
    mentor = Mentor(talent_avaliacao=[avaliacao(), avaliacao(senioridade="senior")], alfaiate=ALFAIATE(CV_OK),
                    talent_revisao=APROVADO,
                    aplicador=json.dumps({"status": "enviada", "motivo": "ok", "evidencia": "Inscrição concluída"}))
    notices = run(hunter.fila_once(conn, mentor))
    assert mentor.kinds() == ["talent_avaliacao", "talent_avaliacao", "alfaiate", "talent_revisao", "aplicador"]
    assert "Candidatura enviada" in notices[0]
    assert conn.execute("SELECT COUNT(*) FROM talent_analises").fetchone()[0] == 1  # primeira análise periódica
    assert not talent.analise_devida(conn)
    origens = [r[0] for r in conn.execute("SELECT origem FROM carreira_eventos ORDER BY id")]
    assert origens.index("talent") < origens.index("alfaiate") < origens.index("aplicador")


# --- memória e resultados ---------------------------------------------------------------------------------------

def test_memoria_imutavel_e_decisao_unica(tmp_path):
    conn = setup(tmp_path)
    run(talent.avaliar_pendentes(conn, Mentor(talent_avaliacao=avaliacao())))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE talent_avaliacoes SET pontuacao = 100")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM talent_avaliacoes")
    conn.execute("INSERT INTO talent_propostas (alvo, proposta, origem, chave, created_at) VALUES ('perfil', 'p', 'o', 'k', 'x')")
    conn.execute("UPDATE talent_propostas SET status = 'aprovada', decidida_em = 'x' WHERE chave = 'k'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE talent_propostas SET status = 'recusada' WHERE chave = 'k'")


def test_analise_com_poucos_dados_e_descritiva_e_gera_propostas(tmp_path):
    jobs = [vaga(f"[TESTE] Dev Python Júnior {i}", jid=f"gupy:{i}") for i in range(4)]
    conn = setup(tmp_path, *jobs)
    run(talent.avaliar_pendentes(conn, Mentor(talent_avaliacao=[avaliacao() for _ in range(4)]), limit=10))
    ind = talent.indicadores(conn)
    assert ind["avaliadas"] == 4 and ind["enviadas"] == 0 and ind["amostra_suficiente"] is False
    docker = next(t for t in ind["requisitos"] if t["termo"] == "docker")
    assert docker["ausente"] == 4
    recs, props = talent.recomendacoes(ind, "# currículo-base sem a palavra")
    assert all(r["forca"] == "descritiva" for r in recs) and "menos que" in recs[0]["texto"]
    assert any("'docker'" in r["texto"] for r in recs)
    assert {p["chave"] for p in props} >= {"perfil:docker", "base:fastapi"}
    fastapi = next(p for p in props if p["chave"] == "base:fastapi")
    assert "Criou APIs em FastAPI" in fastapi["origem"]  # proposta com a origem verificada no perfil
    talent.analisar(conn)
    talent.analisar(conn)
    assert conn.execute("SELECT COUNT(*) FROM talent_propostas").fetchone()[0] == len(props)  # não repete


def test_migracao_22_preserva_historico_e_aceita_origem_talent(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    for number, path in db.MIGRATIONS:
        if number >= 22:
            break
        conn.executescript(path.read_text(encoding="utf-8"))
        if number > 1:
            conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, 'x')", (number,))
    hunter.store(conn, [vaga()])
    with registro.execucao(conn, "busca") as run_:
        run_["resultado"] = "ok"
    conn.execute("PRAGMA foreign_keys = ON")  # como em produção: o envio aponta para a execução recriada
    conn.execute("INSERT INTO carreira_envios (vaga_id, status, motivo, execucao_id, created_at) "
                 "SELECT id, 'falhou', 'x', ?, 'x' FROM carreira_vagas", (run_["id"],))
    antes = conn.execute("SELECT * FROM carreira_eventos").fetchall()
    db.migrate(conn)
    assert [tuple(r) for r in conn.execute("SELECT * FROM carreira_eventos")] == [tuple(r) for r in antes]
    assert conn.execute("SELECT resultado FROM carreira_execucoes").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT execucao_id FROM carreira_envios").fetchone()[0] == run_["id"]  # vínculo preservado
    registro.evento(conn, antes[0]["vaga_id"], "avaliada_talent", "talent")
    with registro.execucao(conn, "revisao"):
        pass
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM carreira_eventos")


# --- interface ---------------------------------------------------------------------------------------------------

def test_area_do_talent_na_interface(tmp_path):
    from fastapi.testclient import TestClient

    from app import auth
    from app.web import Settings, create_app

    app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "nao-existe.sock",
                              cookie_secure=False, run_scheduler=False))
    h = {"X-Lastro": "1"}
    with TestClient(app, base_url="http://lastro.test") as client:
        conn = app.state.conn
        assert client.get("/api/carreira/talent").status_code == 401
        assert client.post("/api/carreira/talent/propostas/1", json={"decisao": "aprovada"}, headers=h).status_code == 401
        auth.set_password(conn, "uma senha longa de teste")
        assert client.post("/api/auth/login", json={"password": "uma senha longa de teste"}, headers=h).status_code == 204
        hunter.store(conn, [vaga(f"[TESTE] Dev Python Júnior {i}", jid=f"gupy:{i}") for i in range(3)])
        run(talent.avaliar_pendentes(conn, Mentor(talent_avaliacao=[avaliacao() for _ in range(3)])))
        talent.analisar(conn)
        area = client.get("/api/carreira/talent").json()
        assert "Experiência" in area["perfil"]["secoes"] and area["perfil"]["lacunas"][0]["termo"] == "docker"
        assert len(area["avaliacoes"]) == 3 and area["avaliacoes"][0]["criterios"] and area["avaliacoes"][0]["filtros"]
        assert sum(p["peso"] for p in area["estrategia"]["pesos"]) == 100 and area["estrategia"]["criterios"]
        assert area["estrategia"]["analise"]["recomendacoes"] and area["resultados"]["avaliadas"] == 3
        pid = next(p["id"] for p in area["propostas"] if p["status"] == "pendente")
        ok = client.post(f"/api/carreira/talent/propostas/{pid}", json={"decisao": "recusada"}, headers=h)
        assert ok.status_code == 200 and ok.json()["status"] == "recusada"
        again = client.post(f"/api/carreira/talent/propostas/{pid}", json={"decisao": "aprovada"}, headers=h)
        assert again.status_code == 409  # decisão do dono é única
