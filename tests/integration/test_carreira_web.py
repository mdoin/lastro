# SPDX-License-Identifier: AGPL-3.0-or-later
"""Módulo Carreira (migração 018): migração de dados antigos, deduplicação, envio incerto, execuções e rotas web."""
import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.web import Settings, create_app
from carreira import alfaiate, candidatura, hunter, registro, sources

H = {"X-Lastro": "1"}
PASSWORD = "uma senha longa de teste"


@pytest.fixture(autouse=True)
def _sem_arquivos_do_dono(monkeypatch, tmp_path):
    monkeypatch.setenv("CARREIRA_CURRICULO", str(tmp_path / "curriculo.md"))
    monkeypatch.setenv("CARREIRA_PERFIL", str(tmp_path / "perfil.md"))
    monkeypatch.setenv("CARREIRA_RESPOSTAS", str(tmp_path / "respostas.md"))


def job(title, company="ACME", location="", workplace="remoto", source="gupy", url=None, jid=None):
    return sources.Job(id=jid or f"{source}:{title}:{location}", source=source, url=url or f"https://x.example/{title}",
                       title=title, company=company, location=location, workplace=workplace, salary_min=None,
                       currency=None, description="python llm", published_at=None)


def cand(conn, vaga_id, status="curriculo", aderencia=90):
    now = db.utcnow()
    cv = conn.execute("INSERT INTO carreira_curriculos (tipo, vaga_id, conteudo_md, created_at) VALUES ('vaga', ?, "
                      "'# CV', ?) RETURNING id", (vaga_id, now)).fetchone()[0]
    conn.execute("INSERT INTO carreira_candidaturas (vaga_id, status, aderencia, resumo, lacunas_json, idioma, "
                 "curriculo_md, carta, curriculo_id, created_at, updated_at) VALUES (?, ?, ?, 'ok', '[]', 'pt', "
                 "'# CV', 'carta', ?, ?, ?)", (vaga_id, status, aderencia, cv, now, now))
    return cv


def test_migracao_separa_etapa_preserva_historico_e_e_imutavel(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    for number, path in db.MIGRATIONS[:17]:  # banco como estava na v17
        conn.executescript(path.read_text(encoding="utf-8"))
        if number > 1:
            conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, 'x')", (number,))
    conn.execute("INSERT INTO carreira_vagas (id, source, url, title, workplace, verdict, score, reasons_json, "
                 "first_seen, last_seen) VALUES ('gupy:1', 'gupy', 'https://a.gupy.io/job/1', 'Dev', 'remoto', "
                 "'compativel', 80, '[]', '2026-11-01T00:00:00+00:00', 'x')")
    conn.execute("INSERT INTO carreira_candidaturas (vaga_id, status, aderencia, resumo, lacunas_json, idioma, "
                 "curriculo_md, carta, created_at, updated_at) VALUES ('gupy:1', 'entrevista', 70, 'r', '[]', 'pt', "
                 "'# CV antigo', 'c', '2026-11-02T00:00:00+00:00', 'x')")
    conn.execute("INSERT INTO carreira_envios (vaga_id, status, motivo, created_at) VALUES ('gupy:1', 'enviada', "
                 "'ok', '2026-11-03T00:00:00+00:00')")
    assert db.migrate(conn) == db.LATEST_VERSION
    row = conn.execute("SELECT status, etapa, curriculo_id FROM carreira_candidaturas").fetchone()
    assert (row["status"], row["etapa"]) == ("candidatada", "entrevista")  # não são mais o mesmo campo
    assert conn.execute("SELECT conteudo_md FROM carreira_curriculos WHERE id = ?", (row["curriculo_id"],)
                        ).fetchone()[0] == "# CV antigo"
    assert conn.execute("SELECT curriculo_id FROM carreira_envios").fetchone()[0] == row["curriculo_id"]
    tipos = [r[0] for r in conn.execute("SELECT tipo FROM carreira_eventos ORDER BY created_at")]
    assert tipos == ["descoberta", "curriculo_preparado", "candidatura_enviada"]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    for sql in ("UPDATE carreira_eventos SET tipo = 'x'", "DELETE FROM carreira_eventos",
                "UPDATE carreira_curriculos SET conteudo_md = 'x'"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)


def test_deduplicacao_por_url_canonica_e_chave_sem_juntar_vagas_diferentes(tmp_path):
    assert registro.url_canonica("https://www.linkedin.com/comm/jobs/view/4465379983/?trk=x") == \
        registro.url_canonica("https://br.linkedin.com/jobs/view/dev-python-4465379983")
    assert registro.url_canonica("https://br.indeed.com/viewjob?jk=1&from=mail") == "https://br.indeed.com/viewjob?jk=1&from=mail"
    assert registro.url_canonica("https://acme.gupy.io/job/7?utm_source=x") == "https://acme.gupy.io/job/7"
    assert registro.chave("ACME Ltda.", "Dev Python", "Londrina, PR", "presencial") == \
        registro.chave("acme", "Dev  Python", "Londrina", "presencial")
    assert registro.chave("", "Dev", "", "remoto") is None  # sem empresa não junta nada

    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    hunter.store(conn, [
        job("Desenvolvedor Python Júnior", source="linkedin", url="https://www.linkedin.com/jobs/view/123456789/"),
        job("Dev Júnior", company="Outra", source="email-linkedin", jid="email:x",
            url="https://www.linkedin.com/comm/jobs/view/123456789?trk=mail"),
        job("Desenvolvedor Python Júnior", source="gupy", location="Austin", workplace="presencial"),
        job("Desenvolvedor Python Júnior", source="catho", location="San Jose", workplace="presencial")])
    ids = {r["source"]: r["id"] for r in conn.execute("SELECT id, source FROM carreira_vagas")}
    cand(conn, ids["linkedin"], status="candidatada")
    assert registro.candidatura_anterior(conn, ids["email-linkedin"])["status"] == "candidatada"  # mesma URL
    assert registro.candidatura_anterior(conn, ids["gupy"]) is None  # mesma empresa e cargo, outra cidade
    assert ids["email-linkedin"] not in [r["id"] for r in alfaiate.pending(conn, 10)]


class FakeMentor:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.requests = answer, error, []

    async def stream(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        yield {"type": "done", "text": self.answer}


def setup_apply(tmp_path, n=1):
    (tmp_path / "perfil.md").write_text("perfil", encoding="utf-8")
    (tmp_path / "respostas.md").write_text("respostas", encoding="utf-8")
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    hunter.store(conn, [job(f"Dev Python Júnior {i}") for i in range(n)])
    for (vid,) in conn.execute("SELECT id FROM carreira_vagas").fetchall():
        cand(conn, vid)
    return conn


@pytest.mark.parametrize("mentor, status, retried", [
    (FakeMentor(json.dumps({"status": "enviada", "motivo": "cliquei em enviar"})), "incerta", False),
    (FakeMentor(error=TimeoutError()), "incerta", False),
    (FakeMentor("texto que não é JSON"), "incerta", False),
    (FakeMentor(error=ConnectionRefusedError()), "curriculo", True),
])
def test_envio_sem_evidencia_e_desconhecido_e_nao_repete(tmp_path, mentor, status, retried):
    conn = setup_apply(tmp_path)
    asyncio.run(candidatura.apply_pending(conn, mentor))
    assert conn.execute("SELECT status FROM carreira_candidaturas").fetchone()[0] == status
    asyncio.run(candidatura.apply_pending(conn, mentor))
    assert len(mentor.requests) == (2 if retried else 1)


def test_envio_com_evidencia_registra_tudo(tmp_path):
    conn = setup_apply(tmp_path)
    ok = FakeMentor(json.dumps({"status": "enviada", "motivo": "ok", "evidencia": "Candidatura realizada com sucesso",
                                "url_final": "https://a.gupy.io/ok", "respostas": [{"pergunta": "P", "resposta": "R"}]}))
    [notice] = asyncio.run(candidatura.apply_pending(conn, ok))
    assert "Candidatura enviada" in notice
    envio = conn.execute("SELECT * FROM carreira_envios").fetchone()
    assert envio["status"] == "enviada" and envio["evidencia"] and envio["curriculo_id"] and envio["execucao_id"]
    assert conn.execute("SELECT status FROM carreira_candidaturas").fetchone()[0] == "candidatada"


def test_execucao_interrompida_e_travada(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    with pytest.raises(RuntimeError), registro.execucao(conn, "busca"):
        raise RuntimeError("x")
    with registro.execucao(conn, "busca"):
        pass
    conn.execute("INSERT INTO carreira_execucoes (tipo, estado, started_at, updated_at) VALUES "
                 "('busca', 'executando', '2020-01-01T00:00:00+00:00', 'x')")
    from app import carreira_web

    assert carreira_web.agente(conn)["estado"] == "travado"
    assert registro.interromper_pendentes(conn) == 1
    states = [r[0] for r in conn.execute("SELECT estado FROM carreira_execucoes ORDER BY id")]
    assert states == ["falhou", "concluida", "interrompida"]


@pytest.fixture
def web(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "nao-existe.sock",
                              cookie_secure=False, run_scheduler=False))
    with TestClient(app, base_url="http://lastro.test") as client:
        yield client, app.state.conn


def test_rotas_exigem_login(web):
    client, _ = web
    for path in ("/api/carreira/resumo", "/api/carreira/vagas", "/api/carreira/candidaturas", "/api/carreira/agente",
                 "/api/carreira/curriculos", "/api/carreira/curriculos/1/documento", "/api/carreira/atividade"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/carreira/candidaturas/1/acao", json={"acao": "retirar"}, headers=H).status_code == 401


def test_resumo_vagas_candidaturas_curriculos_e_acoes(web, tmp_path):
    client, conn = web
    auth.set_password(conn, PASSWORD)
    assert client.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 204

    empty = client.get("/api/carreira/resumo").json()
    assert empty["metricas"]["total"] == 0 and empty["metricas"]["taxa_resposta"] is None
    assert empty["agente"]["estado"] == "ocioso" and empty["atividade"] == []

    (tmp_path / "curriculo.md").write_text("# Maitê\nPython", encoding="utf-8")
    base = registro.sincronizar_base(conn)
    assert registro.sincronizar_base(conn) == base  # sem mudança, sem versão nova
    hunter.store(conn, [job("Desenvolvedor Python Júnior"), job("Estágio em Dados", company="Beta"),
                        job("Vendedor", company="Gama")])
    ids = [r[0] for r in conn.execute("SELECT id FROM carreira_vagas ORDER BY rowid")]
    cand(conn, ids[0], status="candidatada")
    cand(conn, ids[1], status="incerta")
    registro.avancar_etapa(conn, ids[0], "recusada", "carteiro")

    m = client.get("/api/carreira/resumo").json()["metricas"]
    assert (m["total"], m["enviadas"], m["rejeicoes"], m["aguardando"], m["incertas"]) == (3, 1, 1, 0, 1)
    assert m["taxa_resposta"] == 1.0  # o envio incerto não conta como enviado

    vagas = client.get("/api/carreira/vagas", params={"compat": ""}).json()
    assert vagas["total"] == 3
    assert client.get("/api/carreira/vagas", params={"senioridade": "estagio", "compat": ""}).json()["total"] == 1
    assert client.get("/api/carreira/vagas", params={"q": "python júnior"}).json()["total"] == 1
    assert client.get("/api/carreira/vagas", params={"status": "encerrada", "compat": ""}).json()["total"] == 1

    board = {c["n"]: c["coluna"] for c in client.get("/api/carreira/candidaturas").json()}
    assert board == {1: "encerrada", 2: "preparando"}

    detail = client.get("/api/carreira/candidaturas/2").json()
    assert detail["status"] == "incerta" and detail["curriculo_id"]
    assert client.post("/api/carreira/candidaturas/2/acao", json={"acao": "confirmar_envio"}, headers=H).json()[
        "coluna"] == "enviada"
    after = client.post("/api/carreira/candidaturas/2/acao", json={"acao": "etapa", "etapa": "entrevista"},
                        headers=H).json()
    assert after["coluna"] == "entrevista"
    assert [e["tipo"] for e in after["eventos"]][-2:] == ["envio_confirmado", "etapa_atualizada"]
    assert client.post("/api/carreira/candidaturas/2/acao", json={"acao": "confirmar_envio"}, headers=H
                       ).status_code == 409
    assert client.post("/api/carreira/candidaturas/3/acao", json={"acao": "retirar"}, headers=H).status_code == 404

    cvs = client.get("/api/carreira/curriculos").json()
    assert [c["tipo"] for c in cvs].count("base") == 1 and next(c for c in cvs if c["tipo"] == "base")["vigente"]
    html = client.get(f"/api/carreira/curriculos/{base}/documento")
    assert html.headers["content-type"].startswith("text/html") and "<h1>Maitê</h1>" in html.text
    md = client.get(f"/api/carreira/curriculos/{base}/documento", params={"formato": "md"})
    assert md.text == "# Maitê\nPython" and "attachment" in md.headers["content-disposition"]

    feed = client.get("/api/carreira/atividade").json()
    assert "Vendedor" not in {e["title"] for e in feed if e["tipo"] == "descoberta"}  # vaga fora não polui o feed
