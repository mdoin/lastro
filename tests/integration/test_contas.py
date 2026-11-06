# SPDX-License-Identifier: AGPL-3.0-or-later
"""Central de Contas e Acessos (docs/CONTAS.md): cofre cifrado, isolamento por agente e domínio, pendências,
retomada das candidaturas e rotas web sem segredo em resposta ou log."""
import asyncio
import json
import logging
import os
import stat

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient

from app import auth, contas, db
from app.mentor_client import MentorClient
from app.web import Settings, create_app
from carreira import candidatura, hunter, sources
from mentor import cofre as cofre_mod
from mentor.aplicador import parece_logado

H = {"X-Lastro": "1"}
PASSWORD = "uma senha longa de teste"
VALOR_SIGILOSO = "S3nh@-da-Gupy-que-nao-pode-vazar"
KEY = bytes(range(32))
OUTRO_VALOR = "outro valor"


@pytest.fixture(autouse=True)
def _arquivos(monkeypatch, tmp_path):
    for var, name in (("CARREIRA_CURRICULO", "curriculo.md"), ("CARREIRA_PERFIL", "perfil.md"),
                      ("CARREIRA_RESPOSTAS", "respostas.md")):
        monkeypatch.setenv(var, str(tmp_path / name))


def make(tmp_path, key=KEY, legacy=None):
    return cofre_mod.Cofre(tmp_path / "cofre.enc", key, legacy=legacy)


# ---------- cofre ----------

def test_cofre_cifra_em_repouso_com_permissao_restrita(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    c = make(tmp_path)
    view = c.save("gupy", usuario="maite@x.example", senha=VALOR_SIGILOSO, dominios=["gupy.io"])
    raw = (tmp_path / "cofre.enc").read_bytes()
    assert VALOR_SIGILOSO.encode() not in raw and b"maite@x.example" not in raw  # nada em texto puro
    assert stat.S_IMODE(os.stat(tmp_path / "cofre.enc").st_mode) == 0o600
    assert "senha" not in view and view["tem_senha"] and view["usuario_dica"] == "ma…@x.example"
    assert make(tmp_path).for_agent("aplicador")["gupy"]["senha"] == VALOR_SIGILOSO  # persiste e relê com a mesma chave
    assert VALOR_SIGILOSO not in caplog.text and "maite@x.example" not in caplog.text
    assert VALOR_SIGILOSO not in json.dumps(c.public())


def test_cofre_recusa_chave_errada_adulteracao_e_ausencia_de_chave(tmp_path):
    make(tmp_path).save("gupy", senha=VALOR_SIGILOSO, dominios=["gupy.io"])
    with pytest.raises(InvalidTag):
        make(tmp_path, key=bytes(32)).for_agent("aplicador")
    doc = json.loads((tmp_path / "cofre.enc").read_text())
    blob = bytearray(__import__("base64").b64decode(doc["dados"]))
    blob[0] ^= 1
    doc["dados"] = __import__("base64").b64encode(bytes(blob)).decode()
    (tmp_path / "cofre.enc").write_text(json.dumps(doc))
    with pytest.raises(InvalidTag):
        make(tmp_path).for_agent("aplicador")
    sem = make(tmp_path, key=None)
    assert not sem.disponivel and sem.for_agent("aplicador") == {} and sem.public() == []
    with pytest.raises(cofre_mod.CofreError):
        sem.save("gupy", senha="x", dominios=["gupy.io"])


def test_chave_vem_da_credencial_do_systemd(tmp_path, monkeypatch):
    (tmp_path / "lastro-cofre").write_text(KEY.hex() + "\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert cofre_mod.load_key() == KEY
    (tmp_path / "lastro-cofre").write_text("curta")
    monkeypatch.delenv("LASTRO_COFRE_KEY_FILE", raising=False)
    assert cofre_mod.load_key() is None


def test_isolamento_entre_agentes_e_validacao(tmp_path):
    c = make(tmp_path)
    c.save("gupy", senha=VALOR_SIGILOSO, dominios=["gupy.io"])
    assert "gupy" in c.for_agent("aplicador")
    for agent in ("mentor", "carteiro", "pesquisador", ""):
        assert c.for_agent(agent) == {}  # agente sem autorização não recebe nada
    for bad in ({"agentes": ["mentor"]}, {"dominios": ["http://evil.example"]}, {"dominios": ["1.2.3.4"]},
                {"dominios": []}, {"usuario": "a\nb"}, {"senha": "x" * 600}):
        with pytest.raises(cofre_mod.CofreError):
            c.save("gupy", **{"senha": VALOR_SIGILOSO, "dominios": ["gupy.io"], **bad})
    with pytest.raises(cofre_mod.CofreError):
        c.save("../etc", senha=VALOR_SIGILOSO, dominios=["gupy.io"])


def test_mudar_dominio_sem_senha_nao_leva_a_senha_para_outro_site(tmp_path):
    c = make(tmp_path)
    c.save("gupy", usuario="eu", senha=VALOR_SIGILOSO, dominios=["gupy.io"])
    with pytest.raises(cofre_mod.CofreError):
        c.save("gupy", dominios=["evil.example"])
    assert c.for_agent("aplicador")["gupy"]["dominios"] == ["gupy.io"]  # nada mudou
    c.save("gupy", senha=OUTRO_VALOR, dominios=["gupy.io"])  # atualização com a senha: ok
    assert c.for_agent("aplicador")["gupy"]["senha"] == OUTRO_VALOR
    assert c.delete("gupy") and c.for_agent("aplicador") == {} and not c.delete("gupy")


def test_migracao_do_cofre_antigo_em_texto_puro(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    legacy = tmp_path / "cofre.json"
    legacy.write_text(json.dumps({"gupy": {"usuario": "eu", "senha": VALOR_SIGILOSO, "dominios": ["gupy.io"]},
                                  "lixo": "não é credencial"}))
    c = make(tmp_path, legacy=legacy)
    assert c.for_agent("aplicador") == {"gupy": {"usuario": "eu", "senha": VALOR_SIGILOSO, "dominios": ["gupy.io"]}}
    assert not legacy.exists() and (tmp_path / "cofre.json.importado").exists()  # o operador apaga após conferir
    assert VALOR_SIGILOSO.encode() not in (tmp_path / "cofre.enc").read_bytes() and VALOR_SIGILOSO not in caplog.text
    assert make(tmp_path, key=None, legacy=legacy).for_agent("aplicador") == {}  # sem chave, nada de texto puro


def test_operacao_contas_do_worker_nunca_devolve_segredo(tmp_path):
    c = make(tmp_path)
    saved = asyncio.run(cofre_mod.handle(None, {"acao": "salvar", "plataforma": "gupy", "usuario": "eu",
                                                "senha": VALOR_SIGILOSO, "dominios": ["gupy.io"]}, cofre=c))
    listed = asyncio.run(cofre_mod.handle(None, {"acao": "listar"}, cofre=c))
    assert saved["ok"] and listed["credenciais"][0]["plataforma"] == "gupy"
    assert VALOR_SIGILOSO not in json.dumps(saved) + json.dumps(listed)
    bad = asyncio.run(cofre_mod.handle(None, {"acao": "salvar", "plataforma": "gupy", "senha": VALOR_SIGILOSO,
                                              "dominios": ["nao valido"]}, cofre=c))
    assert not bad["ok"] and VALOR_SIGILOSO not in json.dumps(bad)
    with pytest.raises(ValueError):
        asyncio.run(cofre_mod.handle(None, {"acao": "ler_senha", "plataforma": "gupy"}, cofre=c))
    sem_browser = asyncio.run(cofre_mod.handle(None, {"acao": "verificar", "plataforma": "gupy",
                                                      "dominios": ["gupy.io"], "url": "https://login.gupy.io/x"}, cofre=c))
    assert sem_browser["estado"] == "erro"


@pytest.mark.parametrize("url, senha, ok", [
    ("https://www.linkedin.com/feed/", False, True),
    ("https://www.linkedin.com/login?session_redirect=x", False, False),
    ("https://www.linkedin.com/checkpoint/challenge/x", False, False),
    ("https://login.gupy.io/candidates/signin", False, False),
    ("https://login.gupy.io/candidates/applications", True, False),  # campo de senha na tela: não está logado
    ("https://evil.example/feed/", False, False),  # redirecionou para fora dos domínios
    ("http://www.linkedin.com/feed/", False, False),
])
def test_deteccao_de_sessao(url, senha, ok):
    assert parece_logado(url, ["linkedin.com", "gupy.io"], senha) is ok


# ---------- pendências e retomada ----------

def job(title, source="gupy"):
    return sources.Job(id=f"{source}:{title}", source=source, url=f"https://x.example/{title}", title=title,
                       company="ACME", location="", workplace="remoto", salary_min=None, currency=None,
                       description="python llm", published_at=None)


def setup_apply(tmp_path, jobs):
    (tmp_path / "perfil.md").write_text("perfil", encoding="utf-8")
    (tmp_path / "respostas.md").write_text("respostas", encoding="utf-8")
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    hunter.store(conn, jobs)
    now = db.utcnow()
    for (vid,) in conn.execute("SELECT id FROM carreira_vagas").fetchall():
        cv = conn.execute("INSERT INTO carreira_curriculos (tipo, vaga_id, conteudo_md, created_at) VALUES ('vaga', ?, "
                          "'# CV', ?) RETURNING id", (vid, now)).fetchone()[0]
        conn.execute("INSERT INTO carreira_candidaturas (vaga_id, status, aderencia, resumo, lacunas_json, idioma, "
                     "curriculo_md, carta, curriculo_id, created_at, updated_at) VALUES (?, 'curriculo', 90, 'ok', '[]', "
                     "'pt', '# CV', 'carta', ?, ?, ?)", (vid, cv, now, now))
        conn.execute("INSERT INTO talent_revisoes (vaga_id, curriculo_id, rodada, resultado, checagens_json, "
                     "problemas_json, resumo, created_at) VALUES (?, ?, 1, 'aprovado', '[]', '[]', 'teste', ?)",
                     (vid, cv, now))
    return conn


class Mentor:
    """Aplicador falso: sem acesso na Gupy, envio confirmado nas outras."""

    def __init__(self):
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        answer = ({"status": "sem_acesso", "plataforma": "gupy", "acesso": "sessao_expirada",
                   "motivo": "A Gupy pediu para entrar de novo."} if "Dev Gupy" in request["text"] else
                  {"status": "enviada", "motivo": "ok", "evidencia": "Candidatura enviada!"})
        yield {"type": "done", "text": json.dumps(answer)}


def test_plataforma_sem_acesso_espera_e_as_outras_seguem_e_retoma(tmp_path, monkeypatch):
    conn = setup_apply(tmp_path, [job("Dev Gupy A"), job("Dev Gupy B"), job("Dev Catho", source="catho")])
    monkeypatch.setattr(candidatura, "PER_CYCLE", 10)
    mentor = Mentor()
    notices = asyncio.run(candidatura.apply_pending(conn, mentor))
    status = dict(conn.execute("SELECT v.source || ':' || v.title, c.status FROM carreira_candidaturas c "
                               "JOIN carreira_vagas v ON v.id = c.vaga_id").fetchall())
    assert status["catho:Dev Catho"] == "candidatada"  # a outra plataforma não parou
    assert sorted(status[k] for k in status if k.startswith("gupy")) == ["aguardando_acesso", "curriculo"]
    assert len([r for r in mentor.requests if "Dev Gupy" in r["text"]]) == 1  # a 2ª da Gupy nem foi tentada
    assert conn.execute("SELECT COUNT(*) FROM carreira_envios e JOIN carreira_vagas v ON v.id = e.vaga_id "
                        "WHERE v.source = 'gupy'").fetchone()[0] == 0  # espera por acesso não gasta tentativa
    pend = conn.execute("SELECT * FROM contas_pendencias").fetchall()
    assert len(pend) == 1 and pend[0]["tipo"] == "sessao_expirada" and pend[0]["plataforma"] == "gupy"
    assert conn.execute("SELECT estado FROM contas_plataformas WHERE id = 'gupy'").fetchone()[0] == "sessao_expirada"
    assert sum("Preciso de acesso" in n for n in notices) == 1
    assert conn.execute("SELECT COUNT(*) FROM notifications WHERE kind = 'acesso_pendente'").fetchone()[0] == 1

    assert asyncio.run(candidatura.apply_pending(conn, mentor)) == []  # Gupy bloqueada: nada novo, sem aviso repetido
    assert candidatura.pending(conn, 10) == []

    resumed = contas.resolver_acesso(conn, "gupy", "sessão confirmada")
    assert len(resumed) == 1
    assert conn.execute("SELECT valor FROM carreira_estado WHERE chave = 'retomar'").fetchone() is not None
    assert {r["title"] for r in candidatura.pending(conn, 10)} == {"Dev Gupy A", "Dev Gupy B"}
    asyncio.run(hunter.esperar_fila(conn, 3600, tick=3600))  # acorda na hora com o sinal (não dorme 1 h)
    assert conn.execute("SELECT valor FROM carreira_estado WHERE chave = 'retomar'").fetchone() is None


def test_pendencia_nao_duplica_e_login_falho_nao_vira_cadastro(tmp_path):
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    a = contas.abrir_pendencia(conn, plataforma_nome="LinkedIn", tipo="login", agente="aplicador", motivo="pediu login")
    b = contas.abrir_pendencia(conn, plataforma_nome="linkedin", tipo="login", agente="aplicador", motivo="de novo")
    assert a[0] == b[0] and a[1] and not b[1]
    assert conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 1
    conn.execute("UPDATE contas_plataformas SET tem_credencial = 1 WHERE id = 'gupy'")
    pid, _ = contas.abrir_pendencia(conn, plataforma_nome="gupy", tipo="cadastro", agente="aplicador", motivo="falhou")
    assert conn.execute("SELECT tipo FROM contas_pendencias WHERE id = ?", (pid,)).fetchone()[0] == "login"
    pid, _ = contas.abrir_pendencia(conn, plataforma_nome="Nova Plataforma!", tipo="cadastro", agente="aplicador",
                                    motivo="sem conta")
    row = conn.execute("SELECT * FROM contas_plataformas WHERE id = 'nova-plataforma'").fetchone()
    assert row["url_oficial"] == "" and row["estado"] == "nao_configurada"  # endereço não vem da página
    assert contas.plataforma_id("../../etc") == "etc" and contas.plataforma_id("") == "desconhecida"
    contas.resolver(conn, a[0], resolucao="x", estado="descartada")
    assert contas.abrir_pendencia(conn, plataforma_nome="linkedin", tipo="login", agente="aplicador", motivo="y")[1]


# ---------- rotas web ----------

@pytest.fixture
def web(tmp_path, monkeypatch):
    c = make(tmp_path)
    calls = []

    async def fake_call(self, request, timeout=15):  # o socket do worker, direto na operação real do cofre
        calls.append(request)
        if request.get("acao") in ("verificar", "desconectar"):
            return {"type": "done", "ok": True, "estado": "conectada" if request["acao"] == "verificar" else
                    "nao_configurada", "pagina": "www.linkedin.com/feed/"}
        return {"type": "done", **await cofre_mod.handle(None, request, cofre=c)}

    monkeypatch.setattr(MentorClient, "call", fake_call)
    app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "nao-existe.sock",
                              cookie_secure=False, run_scheduler=False))
    with TestClient(app, base_url="http://lastro.test") as client:
        conn = app.state.conn
        auth.set_password(conn, PASSWORD)
        yield client, conn, c, calls


def login(client):
    assert client.post("/api/auth/login", json={"password": PASSWORD}, headers=H).status_code == 204


def test_rotas_exigem_login_e_cabecalho(web):
    client, *_ = web
    assert client.get("/api/contas").status_code == 401
    assert client.put("/api/contas/gupy/credencial", json={}, headers=H).status_code == 401
    login(client)
    assert client.post("/api/contas/gupy/verificar").status_code == 403  # sem X-Lastro (CSRF)
    assert client.post("/api/contas/gupy/verificar", headers={**H, "Origin": "https://evil.example"}).status_code == 403


def test_credencial_pela_interface_com_reautenticacao_sem_vazar(web, caplog):
    client, conn, c, calls = web
    caplog.set_level(logging.DEBUG)
    login(client)
    body = {"usuario": "maite@x.example", "senha": VALOR_SIGILOSO, "senha_dono": "errada"}
    assert client.put("/api/contas/gupy/credencial", json=body, headers=H).status_code == 403
    assert c.for_agent("aplicador") == {}  # nada gravado sem a senha do dono
    r = client.put("/api/contas/gupy/credencial", json={**body, "senha_dono": PASSWORD}, headers=H)
    assert r.status_code == 200 and VALOR_SIGILOSO not in r.text
    assert c.for_agent("aplicador")["gupy"] == {"usuario": "maite@x.example", "senha": VALOR_SIGILOSO, "dominios": ["gupy.io"]}
    listed = client.get("/api/contas")
    assert VALOR_SIGILOSO not in listed.text and "maite@x.example" not in listed.text
    gupy = next(p for p in listed.json()["plataformas"] if p["id"] == "gupy")
    assert gupy["tem_credencial"] and gupy["credencial"]["usuario_dica"] == "ma…@x.example"
    bad = client.put("/api/contas/gupy/credencial", json={**body, "senha": "x" * 600, "senha_dono": PASSWORD}, headers=H)
    assert bad.status_code == 422 and "xxxx" not in bad.text  # o 422 não ecoa o valor enviado
    audit = json.dumps([list(r) for r in conn.execute("SELECT * FROM audit_log")])
    assert VALOR_SIGILOSO not in audit and VALOR_SIGILOSO not in caplog.text
    assert client.post("/api/contas/gupy/revogar", json={"senha_dono": PASSWORD}, headers=H).json() == {"revogada": True}
    assert c.for_agent("aplicador") == {}
    assert client.put("/api/contas/inexistente/credencial", json={**body, "senha_dono": PASSWORD},
                      headers=H).status_code == 404


def test_reautenticacao_limita_tentativas(web):
    client, *_ = web
    login(client)
    codes = [client.post("/api/contas/gupy/revogar", json={"senha_dono": f"errada{i}"}, headers=H).status_code
             for i in range(12)]
    assert codes[0] == 403 and codes[-1] == 429
    assert client.post("/api/contas/gupy/revogar", json={"senha_dono": PASSWORD}, headers=H).status_code == 429


def test_verificar_sessao_resolve_pendencia_e_desconectar(web):
    client, conn, _c, calls = web
    login(client)
    pid, _ = contas.abrir_pendencia(conn, plataforma_nome="linkedin", tipo="login", agente="aplicador", motivo="m")
    data = client.get("/api/contas").json()
    assert [p["id"] for p in data["pendencias"]] == [pid] and data["pendencias"][0]["estado"] == "aberta"
    r = client.post(f"/api/contas/pendencias/{pid}/resolver", json={"acao": "verificar"}, headers=H)
    assert r.status_code == 200 and r.json()["estado"] == "conectada"
    row = conn.execute("SELECT estado, ultima_autenticacao, ultima_verificacao FROM contas_plataformas "
                       "WHERE id = 'linkedin'").fetchone()
    assert row["estado"] == "conectada" and row["ultima_autenticacao"] and row["ultima_verificacao"]
    assert conn.execute("SELECT estado FROM contas_pendencias WHERE id = ?", (pid,)).fetchone()[0] == "resolvida"
    assert calls[-1]["url"] == "https://www.linkedin.com/feed/" and calls[-1]["dominios"] == ["linkedin.com"]
    assert client.post("/api/contas/linkedin/desconectar", json={"senha_dono": PASSWORD}, headers=H).status_code == 200
    assert conn.execute("SELECT estado FROM contas_plataformas WHERE id = 'linkedin'").fetchone()[0] == "nao_configurada"
    assert client.post("/api/contas/gmail/desconectar", json={"senha_dono": PASSWORD}, headers=H).status_code == 409


def test_migracoes_numeradas_fora_de_ordem_nao_sao_puladas(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    late = tmp_path / "020_atrasada.sql"
    late.write_text("CREATE TABLE chegou_depois (x INTEGER);", encoding="utf-8")
    monkeypatch.setattr(db, "MIGRATIONS", tuple(sorted((*db.MIGRATIONS, (20, late)))) if 20 not in dict(db.MIGRATIONS)
                        else tuple((n, late if n == 20 else p) for n, p in db.MIGRATIONS))
    conn.execute("DELETE FROM schema_version WHERE version = 20")
    db.migrate(conn)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'chegou_depois'").fetchone()
