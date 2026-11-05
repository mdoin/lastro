# SPDX-License-Identifier: AGPL-3.0-or-later
"""Currículo-base estruturado, perfis, seleção do Alfaiate, documentos (DOCX/Markdown/HTML) e validação do PDF.

Pessoa e fatos sintéticos: nenhum dado real do dono entra no repositório.
"""
import asyncio
import base64
import copy
import io
import json
import os
import zipfile

import pytest

from app import db
from carreira import alfaiate, candidatura, curriculo, documento


def fato(i, pt, en, tags, status="confirmado", **extra):
    return {"id": i, "pt": pt, "en": en, "tags": tags, "status": status, "fonte": "teste", **extra}


BASE = {
    "pessoa": {"nome": "Ana Teste", "cidade": "Londrina", "uf": "PR", "telefone": "(43) 90000-0000",
               "email": "ana@exemplo.com", "linkedin": "https://www.linkedin.com/in/ana-teste",
               "github": "https://github.com/ana-teste"},
    "titulos": {p: {"pt": f"Desenvolvedora {p}", "en": f"Developer {p}"} for p in curriculo.PERFIS},
    "resumos": {p: {"pt": "Desenvolvedora na Empresa X, onde cria em Python ferramentas internas e integrações com "
                          "PostgreSQL usadas pela operação. Cursa Análise e Desenvolvimento de Sistemas (2028).",
                    "en": "Developer at Empresa X building internal tools and PostgreSQL integrations in Python for "
                          "the operations team. Pursuing a Systems Analysis degree (expected 2028)."}
                for p in curriculo.PERFIS},
    "experiencias": [
        {"id": "emp-x", "empresa": "Empresa X", "local": "Londrina, PR", "area": "software", "status": "confirmado",
         "fonte": "teste", "descricao": {"pt": "software", "en": "software"},
         "cargos": [{"pt": "Desenvolvedora Júnior", "en": "Junior Developer", "inicio": "2026-08", "fim": None},
                    {"pt": "Assistente", "en": "Assistant", "inicio": "2026-01", "fim": "2026-07"}],
         "realizacoes": [
             fato("x-agentes", "Criou agentes de IA que operam o ERP com aprovação humana.",
                  "Built AI agents that operate the ERP with human approval.", ["ia", "agentes", "llm"]),
             fato("x-api", "Desenvolveu APIs em Python e PostgreSQL para a operação.",
                  "Built Python and PostgreSQL APIs for operations.", ["backend", "api", "banco"]),
             fato("x-ferramentas", "Entregou 10 ferramentas internas que substituíram planilhas.",
                  "Delivered 10 internal tools that replaced spreadsheets.", ["geral", "backend", "automacao"]),
             fato("x-visao", "Contou pessoas com visão computacional.", "Counted people with computer vision.",
                  ["visao", "ia"], grupo="visao"),
             fato("x-visao2", "Contou veículos com visão computacional.", "Counted vehicles with computer vision.",
                  ["visao", "ia"], grupo="visao"),
             fato("x-inventado", "Liderou um time de 30 pessoas.", "Led a team of 30.", ["geral"], status="inferido"),
         ]},
        {"id": "loja", "empresa": "Loja Y", "local": "Londrina, PR", "area": "outra", "status": "confirmado",
         "fonte": "teste", "descricao": {"pt": "varejo", "en": "retail"},
         "cargos": [{"pt": "Vendedora", "en": "Salesperson", "inicio": "2019-01", "fim": "2020-07"}],
         "realizacoes": [fato("y-planilhas", "Automatizou as próprias planilhas.", "Automated her own spreadsheets.",
                              ["geral"])]},
    ],
    "projetos": [
        {"id": "proj-a", "nome": "Projeto A", "status": "confirmado", "fonte": "teste", "situacao": "uso_pessoal",
         "corporativo": False, "divulgacao": "autorizada", "link": "", "tags": ["ia", "backend", "geral"],
         "tecnologias": ["Python", "FastAPI"], "descricao": {"pt": "Assistente pessoal com agentes.",
                                                             "en": "Personal assistant with agents."},
         "destaques": [{"pt": "Ferramentas somente leitura.", "en": "Read-only tools."}]},
        {"id": "proj-interno", "nome": "Sistema Interno Secreto", "status": "confirmado", "fonte": "teste",
         "corporativo": True, "divulgacao": "pendente", "tags": ["ia", "backend"], "tecnologias": [],
         "descricao": {"pt": "Sistema da empresa.", "en": "Company system."}},
    ],
    "competencias": [
        {"id": "sk-python", "categoria": "linguagens", "nome": "Python", "status": "confirmado"},
        {"id": "sk-sql", "categoria": "linguagens", "nome": "SQL", "status": "confirmado"},
        {"id": "sk-fastapi", "categoria": "backend", "nome": "FastAPI", "status": "confirmado"},
        {"id": "sk-postgres", "categoria": "banco", "nome": "PostgreSQL", "status": "confirmado"},
        {"id": "sk-mcp", "categoria": "ia", "nome": "MCP", "status": "confirmado"},
        {"id": "sk-kafka", "categoria": "backend", "nome": "Kafka", "status": "pendente"},
    ],
    "formacao": [{"id": "ads", "curso": {"pt": "Tecnólogo em ADS", "en": "Associate degree in ADS"},
                  "instituicao": "Faculdade Z", "situacao": "em_andamento", "conclusao": "2028",
                  "status": "confirmado"}],
    "cursos": [{"id": "curso-ml", "nome": "Introdução ao ML", "instituicao": "Escola W", "data": "2026",
                "status": "confirmado"}],
    "idiomas": [{"id": "pt", "pt": "Português (nativo)", "en": "Portuguese (native)", "status": "confirmado"},
                {"id": "en", "pt": "Inglês (B2)", "en": "English (B2)", "status": "confirmado"}],
    "perguntas": [{"id": "q1", "alvo": "x-ferramentas", "pergunta": "Quantas pessoas usam?", "resposta": "",
                   "status": "aberta"}],
}


def test_base_valida_e_rejeita_status_e_id_repetido():
    curriculo.validar_base(copy.deepcopy(BASE))
    ruim = copy.deepcopy(BASE)
    ruim["competencias"][0]["status"] = "talvez"
    with pytest.raises(curriculo.BaseInvalida):
        curriculo.validar_base(ruim)
    ruim = copy.deepcopy(BASE)
    ruim["competencias"][1]["id"] = "sk-python"
    with pytest.raises(curriculo.BaseInvalida):
        curriculo.validar_base(ruim)


def test_montar_usa_so_fatos_confirmados_e_projetos_autorizados():
    doc = curriculo.montar(BASE, "backend")
    texto = json.dumps(doc, ensure_ascii=False)
    assert "Liderou" not in texto and "Kafka" not in texto  # inferido e pendente ficam fora
    assert "Sistema Interno Secreto" not in texto  # corporativo sem autorização não vira projeto
    assert "Projeto A" in texto
    assert texto.count("visão computacional") <= 1  # um por grupo
    assert set(doc["ids"]) <= curriculo.ids_confirmados(BASE)
    exp = next(s for s in doc["secoes"] if s["id"] == "experiencia")["itens"]
    assert exp[0]["titulo"] == "Desenvolvedora Júnior" and exp[0]["meta"] == "ago/2026 – atual"
    assert "Assistente (jan/2026 – jul/2026)" in exp[0]["nota"]
    assert exp[1]["bullets"] == []  # experiência fora da área: só a linha do cargo fora do perfil Júnior


def test_perfis_mudam_ordem_e_destaques():
    junior = curriculo.montar(BASE, "junior")
    assert [s["id"] for s in junior["secoes"]][0] == "formacao"
    assert next(s for s in junior["secoes"] if s["id"] == "experiencia")["itens"][1]["bullets"]  # anterior com detalhe
    ia = curriculo.montar(BASE, "ia")
    linhas = next(s for s in ia["secoes"] if s["id"] == "competencias")["itens"]
    assert linhas[0]["rotulo"] == "Inteligência artificial"
    en = curriculo.montar(BASE, "backend", "en")
    assert en["secoes"][0]["titulo"] == "Experience" and en["local"].endswith("Brazil")
    assert curriculo.faltando_traducao(BASE, en) == []


def test_corte_tira_conteudo_sem_mudar_fonte():
    cheio, curto = curriculo.montar(BASE, "backend"), curriculo.montar(BASE, "backend", corte=5)
    projetos = [next(s for s in d["secoes"] if s["id"] == "projetos")["itens"][0]["bullets"] for d in (cheio, curto)]
    assert projetos[0] and not projetos[1]
    assert documento.CSS in documento.html(curto)  # mesmo estilo (mesmo tamanho de fonte) em qualquer corte


def test_checar_resumo_barra_tecnologia_numero_cliche_e_senioridade():
    assert curriculo.checar_resumo(BASE["resumos"]["backend"]["pt"], BASE) == []
    ruim = ("Profissional apaixonado por tecnologia, sênior, com 8 anos de Kubernetes e Python em produção, "
            "integrações e ferramentas internas para equipes de operação.")
    problemas = " | ".join(curriculo.checar_resumo(ruim, BASE))
    assert "clichê" in problemas and "Kubernetes" in problemas and "8" in problemas and "sênior" in problemas


def test_perfil_sugerido_pelo_titulo():
    assert curriculo.perfil_sugerido("Estágio em desenvolvimento") == "junior"
    assert curriculo.perfil_sugerido("Desenvolvedor de IA Júnior") == "ia"
    assert curriculo.perfil_sugerido("Desenvolvedor Backend Python Jr") == "backend"


def test_editar_e_responder_criam_versao_nova(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    v1 = curriculo.salvar(conn, BASE, "importacao", "teste")
    nova = curriculo.editar(BASE, "sk-kafka", status="confirmado")
    nova = curriculo.responder(nova, "q1", "Umas 20 pessoas")
    v2 = curriculo.salvar(conn, nova, "dono", "edição")
    assert v2 > v1 and curriculo.carregar(conn)[1]["perguntas"][0]["status"] == "respondida"
    assert curriculo.pendencias(BASE)["perguntas"] and not curriculo.pendencias(nova)["perguntas"]
    with pytest.raises(Exception):
        conn.execute("UPDATE carreira_base SET nota = 'x' WHERE id = ?", (v1,))
    with pytest.raises(KeyError):
        curriculo.editar(BASE, "nao-existe", status="confirmado")


def test_parse_selecao_descarta_id_desconhecido_e_resumo_sem_fonte():
    saida = json.dumps({"aderencia": 80, "resumo": "ok", "perfil": "ia", "idioma": "pt",
                        "realizacoes": ["x-api", "x-inventado", "nao-existe"], "projetos": ["proj-interno", "proj-a"],
                        "competencias": ["sk-mcp"], "resumo_profissional": "Especialista sênior em Kubernetes com 12 "
                        "anos de experiência em sistemas distribuídos e plataformas de dados de grande escala.",
                        "carta": "Tenho 12 anos de Kubernetes.", "lacunas": [], "alteracoes": []})
    r = alfaiate.parse_selecao(saida, BASE)
    assert r["selecao"]["realizacoes"] == ["x-api"]  # inferido e inexistente fora
    assert r["selecao"]["projetos"] == ["proj-interno", "proj-a"]  # o filtro de divulgação é do montar
    assert r["selecao"]["resumo"] == "" and r["carta"] == "" and r["perfil"] == "ia"
    doc = curriculo.montar(BASE, "ia", "pt", r["selecao"])
    assert "Sistema Interno Secreto" not in json.dumps(doc, ensure_ascii=False)


def test_docx_e_markdown_tem_todo_o_texto_e_links():
    doc = curriculo.montar(BASE, "backend")
    data = documento.docx(doc)
    assert documento.validar_docx(doc, data)["ok"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "word/media/" not in " ".join(z.namelist())
        assert "mailto:ana@exemplo.com" in z.read("word/_rels/document.xml.rels").decode()
    assert documento.docx(doc) == data  # mesmo documento, mesmo arquivo
    md = documento.markdown(doc)
    assert md.startswith("# Ana Teste") and "## Experiência" in md and "[ana@exemplo.com](mailto:" in md
    page = documento.html(doc)
    assert 'href="https://github.com/ana-teste"' in page and "<script" not in page and "<table" not in page
    assert '<span style="white-space:nowrap">ana-teste</span>' not in page.split("<body>")[0]  # atributos intactos


def test_validacao_aponta_fato_nao_confirmado_e_texto_ausente():
    doc = curriculo.montar(BASE, "backend")
    doc["ids"].append("x-inventado")
    assert any("não confirmado" in e for e in documento._conteudo(BASE, doc))
    erros = documento._texto_ok("Ana Teste {{nome}}", doc, "PDF")
    assert any("ausente" in e for e in erros) and any("modelo" in e for e in erros)


CHROME = "/usr/bin/google-chrome"


@pytest.mark.skipif(not os.path.exists(CHROME), reason="sem Chrome para imprimir o PDF")
def test_pdf_real_passa_na_validacao_completa():
    pytest.importorskip("pypdf")
    playwright = pytest.importorskip("playwright.async_api")

    async def run():
        async with playwright.async_playwright() as p:
            browser = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = await (await browser.new_context(java_script_enabled=False)).new_page()

            class Mentor:
                async def call(self, req, timeout=0):
                    await page.set_content(req["html"])
                    pdf = await page.pdf(prefer_css_page_size=True, print_background=True, tagged=True)
                    return {"type": "done", "pdf": base64.b64encode(pdf).decode()}
            try:
                return await documento.produzir(Mentor(), BASE, "backend", "pt")
            finally:
                await browser.close()
    doc, pdf, data, rel = asyncio.run(run())
    assert rel["ok"], rel["erros"]
    assert rel["paginas"] == 1 and rel["links"] and all("LiberationSans" in f or "Arial" in f for f in rel["fontes"])
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    assert reader.metadata["/Author"] == "Ana Teste"
    assert "Desenvolvedora Júnior" in reader.pages[0].extract_text()


class FakeMentor:
    """Alfaiate devolve uma seleção; o 'PDF' é falso e a validação é substituída (o PDF real tem teste próprio)."""
    def __init__(self, selecao):
        self.selecao, self.requests = selecao, []

    async def stream(self, request):
        self.requests.append(request)
        tools = [{"anexo": "pdf"}] if request.get("role") == "aplicador" else []
        text = json.dumps(self.selecao) if request.get("role") == "alfaiate" else json.dumps(
            {"status": "enviada", "motivo": "ok", "evidencia": "Candidatura enviada"})
        yield {"type": "done", "text": text, "tools": tools}


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("CARREIRA_PERFIL", str(tmp_path / "perfil.md"))
    monkeypatch.setenv("CARREIRA_RESPOSTAS", str(tmp_path / "respostas.md"))
    monkeypatch.setenv("CARREIRA_CURRICULO", str(tmp_path / "curriculo.md"))
    (tmp_path / "perfil.md").write_text("# Ana\n- Python", encoding="utf-8")
    (tmp_path / "respostas.md").write_text("- Nome: Ana", encoding="utf-8")

    async def produzir(mentor, base, perfil, idioma, selecao=None):
        doc = curriculo.montar(base, perfil, idioma, selecao)
        return doc, b"%PDF-1.7 teste", documento.docx(doc), {"ok": True, "erros": [], "avisos": [], "paginas": 1}
    monkeypatch.setattr(documento, "produzir", produzir)
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    curriculo.salvar(conn, BASE, "importacao", "teste")
    now = db.utcnow()
    conn.execute("INSERT INTO carreira_vagas (id, source, url, title, company, workplace, verdict, score, reasons_json,"
                 " first_seen, last_seen) VALUES ('gupy:1', 'gupy', 'https://x.example/1', 'Dev Python Jr', 'ACME', "
                 "'remoto', 'compativel', 80, '[]', ?, ?)", (now, now))
    conn.execute("INSERT INTO talent_avaliacoes (vaga_id, entrada_sha, rubrica, elegivel, pontuacao, filtros_json, "
                 "criterios_json, requisitos_json, posicionamento, perfil_curriculo, destaques_json, orientacoes_json, "
                 "justificativa, created_at) VALUES ('gupy:1', 's', 'r', 1, 85, '[]', '[]', '[]', 'p', 'ia', '[]', "
                 "'[]', 'j', ?)", (now,))
    return conn


SELECAO = {"aderencia": 70, "resumo": "combina", "perfil": "backend", "idioma": "pt",
           "realizacoes": ["x-api", "x-agentes", "x-ferramentas"], "projetos": ["proj-a"], "competencias": ["sk-mcp"],
           "resumo_profissional": "", "lacunas": [], "carta": "Olá, trabalho com Python e PostgreSQL.", "alteracoes": []}


def test_alfaiate_gera_documento_pelo_perfil_do_talent_e_aplicador_anexa_o_arquivo(tmp_path, monkeypatch):
    conn = _setup(tmp_path, monkeypatch)
    mentor = FakeMentor(SELECAO)
    assert asyncio.run(alfaiate.tailor_pending(conn, mentor)) == ["gupy:1"]
    cand = conn.execute("SELECT * FROM carreira_candidaturas").fetchone()
    cv = conn.execute("SELECT * FROM carreira_curriculos WHERE id = ?", (cand["curriculo_id"],)).fetchone()
    assert cv["perfil"] == "ia" and cv["pdf"] and cv["docx"] and cv["sha256"]  # o Talent decide o perfil
    assert cand["aderencia"] == 85 and cand["curriculo_md"] == cv["conteudo_md"]
    assert json.loads(cv["documento_json"])["analise"]["perfil_fonte"] == "talent"
    conn.execute("INSERT INTO talent_revisoes (vaga_id, curriculo_id, rodada, resultado, checagens_json, problemas_json,"
                 " resumo, created_at) VALUES ('gupy:1', ?, 1, 'aprovado', '[]', '[]', 'ok', ?)",
                 (cv["id"], db.utcnow()))
    assert asyncio.run(candidatura.apply_pending(conn, mentor)) == []  # dono ainda não liberou o gerador novo
    conn.execute("INSERT INTO carreira_estado (chave, valor) VALUES ('curriculo_liberado', 'agora')")
    asyncio.run(candidatura.apply_pending(conn, mentor))
    req = mentor.requests[-1]
    assert base64.b64decode(req["aplicacao"]["pdf_b64"]) == cv["pdf"]
    envio = conn.execute("SELECT * FROM carreira_envios").fetchone()
    assert envio["curriculo_id"] == cv["id"] and envio["anexo"] == "pdf"
    assert "Ana Teste" in req["text"]  # o PERFIL do aplicador vem da base estruturada


def test_versao_antiga_na_fila_e_refeita_pela_base(tmp_path, monkeypatch):
    conn = _setup(tmp_path, monkeypatch)
    now = db.utcnow()
    old = conn.execute("INSERT INTO carreira_curriculos (tipo, vaga_id, conteudo_md, created_at) VALUES ('vaga', "
                       "'gupy:1', '# CV antigo', ?) RETURNING id", (now,)).fetchone()[0]
    conn.execute("INSERT INTO carreira_candidaturas (vaga_id, status, aderencia, resumo, lacunas_json, idioma, "
                 "curriculo_md, carta, curriculo_id, created_at, updated_at) VALUES ('gupy:1', 'curriculo', 80, 'r', "
                 "'[]', 'pt', '# CV antigo', 'c', ?, ?, ?)", (old, now, now))
    assert candidatura.pending(conn, 5) == []  # sem PDF validado não vai para envio
    asyncio.run(alfaiate.tailor_pending(conn, FakeMentor(SELECAO)))
    cand = conn.execute("SELECT curriculo_id FROM carreira_candidaturas").fetchone()
    assert cand["curriculo_id"] != old
    assert conn.execute("SELECT conteudo_md FROM carreira_curriculos WHERE id = ?", (old,)).fetchone()[0] == "# CV antigo"


def test_rotas_da_base_versionam_e_liberam(tmp_path):
    from fastapi.testclient import TestClient

    from app import auth
    from app.web import Settings, create_app

    app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "nao-existe.sock",
                              cookie_secure=False, run_scheduler=False))
    h = {"X-Lastro": "1"}
    with TestClient(app, base_url="http://lastro.test") as client:
        conn = app.state.conn
        assert client.get("/api/carreira/base").status_code == 401
        auth.set_password(conn, "uma senha longa de teste")
        assert client.post("/api/auth/login", json={"password": "uma senha longa de teste"}, headers=h).status_code == 204
        assert client.get("/api/carreira/base").status_code == 404  # sem base: modo antigo
        curriculo.salvar(conn, BASE, "importacao", "teste")
        view = client.get("/api/carreira/base").json()
        assert {i["id"] for i in view["pendencias"]["itens"]} >= {"x-inventado", "sk-kafka", "proj-interno"}
        assert view["liberado_em"] is None and [p["perfil"] for p in view["perfis"]] == list(curriculo.PERFIS)
        r = client.post("/api/carreira/base/itens/x-api", json={"pt": "Desenvolveu APIs em Python."}, headers=h)
        assert r.status_code == 200
        assert curriculo.carregar(conn)[1]["experiencias"][0]["realizacoes"][1]["pt"] == "Desenvolveu APIs em Python."
        assert client.post("/api/carreira/base/itens/nao-existe", json={"status": "confirmado"}, headers=h).status_code == 404
        assert client.post("/api/carreira/base/perguntas/q1", json={"resposta": ""}, headers=h).status_code == 422
        assert client.post("/api/carreira/base/perguntas/q1", json={"resposta": "20 pessoas"}, headers=h).status_code == 200
        assert len(client.get("/api/carreira/base").json()["historico"]) == 3
        assert client.post("/api/carreira/base/liberar", json={"liberar": True}, headers=h).json()["liberado_em"]
        assert candidatura.liberado(conn)
        assert client.post("/api/carreira/base/liberar", json={"liberar": False}, headers=h).json()["liberado_em"] is None
        assert client.post("/api/carreira/base/gerar", headers=h).status_code == 503  # worker ausente: erro claro
        assert client.get("/api/carreira/curriculos/999/documento?formato=pdf").status_code == 404
