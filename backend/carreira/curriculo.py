# SPDX-License-Identifier: AGPL-3.0-or-later
"""Currículo-base estruturado e perfis de apresentação (docs/CARREIRA.md, "Currículos").

A fonte de verdade é a base em `carreira_base` (JSON versionado e imutável), não um PDF nem o Markdown de uma versão
anterior. Cada fato tem `status`: só `confirmado` entra num documento; `pendente` espera o dono validar na tela;
`inferido` é sugestão do agente e nunca vira fato; `descartado` fica no histórico e fora dos documentos.

Fluxo: base → análise da vaga (Alfaiate) → seleção (`montar`, determinística, só ids confirmados) → documento
(`documento.py`). O Alfaiate escolhe e ordena; não escreve realizações. O único texto livre dele é o resumo, que
passa por `checar_resumo` (tecnologias, números e senioridade têm de existir na base).
"""

import copy
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app import db

STATUS = ("confirmado", "pendente", "inferido", "descartado")
IDIOMAS = ("pt", "en")
CATEGORIAS = {"linguagens": ("Linguagens", "Languages"), "backend": ("Backend e APIs", "Backend & APIs"),
              "banco": ("Banco de dados", "Databases"), "ia": ("Inteligência artificial", "AI & LLMs"),
              "visao": ("Visão computacional", "Computer vision"), "automacao": ("Automação", "Automation"),
              "infra": ("Infraestrutura", "Infrastructure"), "frontend": ("Frontend", "Frontend")}
SECOES = {"resumo": ("Resumo", "Summary"), "experiencia": ("Experiência", "Experience"),
          "projetos": ("Projetos selecionados", "Selected projects"),
          "competencias": ("Competências técnicas", "Technical skills"),
          "formacao": ("Formação", "Education"), "cursos": ("Cursos e idiomas", "Courses & languages")}


@dataclass(frozen=True)
class Perfil:
    nome: str
    descricao: str
    pesos: dict
    categorias: tuple
    secoes: tuple
    realizacoes: int
    projetos: int
    anteriores_com_detalhe: bool  # experiência fora da área com bullet (Júnior) ou só a linha do cargo


PERFIS = {
    "backend": Perfil(
        "Software Engineer / Backend", "Python, APIs, PostgreSQL, integrações, arquitetura, automação e Linux; IA como "
        "diferencial", {"backend": 3, "api": 3, "banco": 3, "integracao": 3, "arquitetura": 2, "infra": 2,
                        "automacao": 2, "geral": 1, "confiabilidade": 1, "ia": 1, "mcp": 1},
        ("linguagens", "backend", "banco", "infra", "automacao", "ia", "frontend"),
        ("experiencia", "projetos", "competencias", "formacao", "cursos"), 5, 3, False),
    "ia": Perfil(
        "AI Engineer / Applied AI", "LLMs, agentes, MCP, function calling, integração de ferramentas, automação com IA, "
        "confiabilidade e sistemas reais com modelos", {"ia": 3, "agentes": 3, "mcp": 3, "llm": 3, "confiabilidade": 2,
                                                         "visao": 2, "automacao": 1, "integracao": 1, "backend": 1},
        ("ia", "visao", "linguagens", "backend", "banco", "automacao", "infra"),
        ("experiencia", "projetos", "competencias", "formacao", "cursos"), 5, 3, False),
    "junior": Perfil(
        "Estágio / Desenvolvedor Júnior", "formação em ADS, experiência prática, fundamentos, backend, bancos de dados e "
        "projetos; capacidade de desenvolver e manter sistemas", {"geral": 3, "backend": 2, "banco": 2, "api": 2,
                                                                  "automacao": 2, "integracao": 1, "ia": 1},
        ("linguagens", "backend", "banco", "frontend", "infra", "ia", "automacao"),
        ("formacao", "experiencia", "projetos", "competencias", "cursos"), 4, 3, True),
}

CLICHES = re.compile(r"apaixonad[oa]|altamente motivad|proativ[oa]|dedicad[oa]|sempre em busca|busca(ndo)? (de )?novos "
                     r"desafios|passionate|highly motivated|self-starter|go-getter|team player", re.I)
SENIORIDADE = re.compile(r"\b(s[eê]nior|pleno|lead|l[ií]der|tech lead|especialista|arquitet[oa]|principal|staff|head)\b",
                         re.I)
# Tecnologias comuns em vagas: citadas no resumo, precisam existir na base confirmada (barra keyword stuffing).
TECH_VOCAB = (
    "Java", "JavaScript", "TypeScript", "Golang", "Rust", "C#", "C++", "PHP", "Ruby", "Kotlin", "Swift", "Scala",
    "Elixir", "Django", "Flask", "FastAPI", "Spring", "Laravel", "Rails", "Node.js", "Express", "NestJS", "Fastify",
    "React", "Angular", "Vue", "Next.js", "Svelte", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "RabbitMQ",
    "Elasticsearch", "SQLite", "Oracle", "SQL Server", "AWS", "Azure", "GCP", "Google Cloud", "Kubernetes", "Docker",
    "Terraform", "Ansible", "Jenkins", "GitHub Actions", "CI/CD", "LangChain", "LlamaIndex", "LangGraph", "OpenAI",
    "Hugging Face", "PyTorch", "TensorFlow", "scikit-learn", "Pandas", "NumPy", "Spark", "Airflow", "dbt", "Power BI",
    "Tableau", "RAG", "MCP", "YOLO", "OpenCV", "Playwright", "Selenium", "GraphQL", "gRPC", "microsserviços",
    "microservices", "Celery", "Electron", "Flutter", "Android", "iOS", "Salesforce", "SAP", "n8n", "Zapier", "UiPath",
    "RPA", "Vertex AI", "Bedrock", "SageMaker", "Pinecone", "pgvector", "Weaviate", "OAuth2", "WebSocket", "Ollama",
    "fine-tuning", "MLOps", "Databricks", "Snowflake", "BigQuery")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


# --- Base: leitura, validação e versões --------------------------------------------------------------------

class BaseInvalida(ValueError):
    pass


def _texto(value, campo: str, limite: int, obrigatorio: bool = True) -> None:
    if not isinstance(value, str) or (obrigatorio and not value.strip()) or len(value) > limite:
        raise BaseInvalida(f"{campo}: texto ausente ou longo demais")


def _bilingue(value, campo: str, limite: int) -> None:
    if not isinstance(value, dict):
        raise BaseInvalida(f"{campo}: esperado {{pt, en}}")
    _texto(value.get("pt"), f"{campo}.pt", limite)
    _texto(value.get("en", ""), f"{campo}.en", limite, obrigatorio=False)


def _fato(item: dict, campo: str, ids: set) -> None:
    if not isinstance(item, dict):
        raise BaseInvalida(f"{campo}: item inválido")
    _texto(item.get("id"), f"{campo}.id", 60)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", item["id"]) or item["id"] in ids:
        raise BaseInvalida(f"{campo}: id '{item['id']}' inválido ou repetido")
    ids.add(item["id"])
    if item.get("status") not in STATUS:
        raise BaseInvalida(f"{item['id']}: status precisa ser um de {', '.join(STATUS)}")
    _texto(item.get("fonte", ""), f"{item['id']}.fonte", 300, obrigatorio=False)


def validar_base(base: dict) -> dict:
    """Confere a estrutura (fronteira de confiança: edições da tela). Devolve a própria base."""
    if not isinstance(base, dict):
        raise BaseInvalida("base precisa ser um objeto")
    pessoa = base.get("pessoa") or {}
    for campo in ("nome", "cidade", "uf", "telefone", "email"):
        _texto(pessoa.get(campo), f"pessoa.{campo}", 120)
    for campo in ("linkedin", "github"):
        if pessoa.get(campo) and not re.fullmatch(r"https://[\w.-]+/[\w./-]*", pessoa[campo]):
            raise BaseInvalida(f"pessoa.{campo}: use o endereço https completo")
    for perfil in PERFIS:
        _bilingue((base.get("titulos") or {}).get(perfil), f"titulos.{perfil}", 120)
        _bilingue((base.get("resumos") or {}).get(perfil), f"resumos.{perfil}", 700)
    ids: set = set()
    for exp in base.get("experiencias") or []:
        _fato(exp, "experiencia", ids)
        _texto(exp.get("empresa"), f"{exp['id']}.empresa", 120)
        if not exp.get("cargos"):
            raise BaseInvalida(f"{exp['id']}: pelo menos um cargo")
        for cargo in exp["cargos"]:
            _bilingue(cargo, f"{exp['id']}.cargo", 120)
            if not re.fullmatch(r"\d{4}-\d{2}", cargo.get("inicio") or "") or not (
                    cargo.get("fim") is None or re.fullmatch(r"\d{4}-\d{2}", cargo["fim"])):
                raise BaseInvalida(f"{exp['id']}: datas no formato AAAA-MM (fim nulo = atual)")
        for item in exp.get("realizacoes") or []:
            _fato(item, f"{exp['id']}.realizacao", ids)
            _bilingue(item, item["id"], 400)
    for proj in base.get("projetos") or []:
        _fato(proj, "projeto", ids)
        _texto(proj.get("nome"), f"{proj['id']}.nome", 120)
        _bilingue(proj.get("descricao"), f"{proj['id']}.descricao", 400)
        for d in proj.get("destaques") or []:
            _bilingue(d, f"{proj['id']}.destaque", 400)
        if proj.get("link") and not str(proj["link"]).startswith("https://"):
            raise BaseInvalida(f"{proj['id']}: link precisa ser https")
    for key in ("competencias", "formacao", "cursos", "idiomas"):
        for item in base.get(key) or []:
            _fato(item, key, ids)
    for item in base.get("competencias") or []:
        _texto(item.get("nome"), f"{item['id']}.nome", 80)
        if item.get("categoria") not in CATEGORIAS:
            raise BaseInvalida(f"{item['id']}: categoria desconhecida")
    for q in base.get("perguntas") or []:
        _texto(q.get("id"), "pergunta.id", 60)
        _texto(q.get("pergunta"), f"{q['id']}.pergunta", 400)
        _texto(q.get("resposta", ""), f"{q['id']}.resposta", 2000, obrigatorio=False)
    return base


def base_atual(conn):
    """Linha da versão vigente da base (id, conteudo_json, origem, nota, created_at) ou None."""
    return conn.execute("SELECT * FROM carreira_base ORDER BY id DESC LIMIT 1").fetchone()


def carregar(conn) -> tuple[int, dict] | None:
    row = base_atual(conn)
    return (row["id"], json.loads(row["conteudo_json"])) if row else None


def salvar(conn, base: dict, origem: str, nota: str) -> int:
    validar_base(base)
    return conn.execute("INSERT INTO carreira_base (conteudo_json, origem, nota, created_at) VALUES (?, ?, ?, ?) "
                        "RETURNING id", (json.dumps(base, ensure_ascii=False), origem, nota[:300], db.utcnow())
                        ).fetchone()[0]


def importar_arquivo(conn) -> int | None:
    """Primeira base: importa CARREIRA_BASE (JSON do dono, fora do repositório) se ainda não há nenhuma."""
    path = Path(os.environ.get("CARREIRA_BASE", "/var/lib/patrimonio/carreira/base.json"))
    if base_atual(conn) is not None or not path.is_file():
        return None
    return salvar(conn, json.loads(path.read_text(encoding="utf-8")), "importacao", f"importada de {path.name}")


def _itens(base: dict):
    """Todos os fatos com id: (tipo, item)."""
    for exp in base.get("experiencias") or []:
        yield "experiencia", exp
        for r in exp.get("realizacoes") or []:
            yield "realizacao", r
    for key, tipo in (("projetos", "projeto"), ("competencias", "competencia"), ("formacao", "formacao"),
                      ("cursos", "curso"), ("idiomas", "idioma")):
        for item in base.get(key) or []:
            yield tipo, item


def editar(base: dict, item_id: str, *, status: str | None = None, pt: str | None = None,
           en: str | None = None) -> dict:
    """Nova base com o fato alterado pelo dono (texto e/ou status). O texto editado vale como confirmado por ele."""
    nova = copy.deepcopy(base)
    for tipo, item in _itens(nova):
        if item.get("id") != item_id:
            continue
        if status is not None:
            if status not in STATUS:
                raise BaseInvalida("status inválido")
            item["status"] = status
        if pt is not None or en is not None:
            alvo = {"realizacao": item, "idioma": item, "projeto": item.get("descricao"),
                    "formacao": item.get("curso")}.get(tipo)
            if tipo in ("competencia", "curso"):
                if pt is not None:
                    item["nome"] = pt
            elif alvo is None:
                raise BaseInvalida("esse item não tem texto editável")
            else:
                if pt is not None:
                    alvo["pt"] = pt
                if en is not None:
                    alvo["en"] = en
            item["fonte"] = f"editado pelo dono em {db.utcnow()[:10]}"
        return validar_base(nova)
    raise KeyError(item_id)


def responder(base: dict, pergunta_id: str, resposta: str, descartar: bool = False) -> dict:
    nova = copy.deepcopy(base)
    for q in nova.get("perguntas") or []:
        if q.get("id") == pergunta_id:
            q.update(resposta=resposta.strip()[:2000], status="descartada" if descartar else "respondida",
                     respondida_em=db.utcnow())
            return validar_base(nova)
    raise KeyError(pergunta_id)


def pendencias(base: dict) -> dict:
    itens = [{"id": item["id"], "tipo": tipo, "status": item["status"],
              "texto": _rotulo(tipo, item)} for tipo, item in _itens(base) if item.get("status") in ("pendente", "inferido")]
    itens += [{"id": p["id"], "tipo": "projeto", "status": "divulgacao", "texto": f"{p['nome']}: divulgação como projeto "
               "não autorizada (aparece só como realização na experiência)"}
              for p in base.get("projetos") or [] if p.get("corporativo") and p.get("divulgacao") != "autorizada"
              and p.get("status") == "confirmado"]
    return {"itens": itens, "perguntas": [q for q in base.get("perguntas") or [] if q.get("status") == "aberta"]}


def _rotulo(tipo: str, item: dict) -> str:
    if tipo == "realizacao" or tipo == "idioma":
        return item.get("pt", "")
    if tipo == "projeto":
        return f"{item.get('nome')}: {item.get('descricao', {}).get('pt', '')}"
    if tipo == "experiencia":
        return item.get("empresa", "")
    if tipo == "formacao":
        return item.get("curso", {}).get("pt", "")
    return item.get("nome", "")


# --- Fatos confirmados -----------------------------------------------------------------------------------------

def ok(item: dict) -> bool:
    return item.get("status") == "confirmado"


def projetos_publicaveis(base: dict) -> list[dict]:
    """Confirmados e, se corporativos, com divulgação autorizada pelo dono."""
    return [p for p in base.get("projetos") or [] if ok(p) and (not p.get("corporativo")
                                                               or p.get("divulgacao") == "autorizada")]


def corpus(base: dict) -> str:
    """Todo o texto confirmado e os títulos: o que um resumo pode citar (os resumos-padrão também são conferidos)."""
    parts = [json.dumps(base.get("titulos"), ensure_ascii=False)]
    parts += [json.dumps(item, ensure_ascii=False) for _tipo, item in _itens(base) if ok(item)]
    return " ".join(parts)


def checar_resumo(texto: str, base: dict) -> list[str]:
    """Problemas de um resumo escrito pelo agente. Vazio = pode usar."""
    problems = []
    if not 120 <= len(texto or "") <= 560:
        problems.append("tamanho fora de 120–560 caracteres")
    if CLICHES.search(texto or ""):
        problems.append("clichê")
    fonte = _norm(corpus(base))
    numeros = set(re.findall(r"\d+", re.sub(r"\b(\d{4})-\d{2}\b", r"\1", fonte)))  # mês de AAAA-MM não conta
    for n in set(re.findall(r"\d+", texto or "")):
        if n not in numeros:
            problems.append(f"número sem fonte: {n}")
    for term in TECH_VOCAB:
        if re.search(rf"(?<![\w.]){re.escape(term)}(?![\w])", texto or "", re.I) and _norm(term) not in fonte:
            problems.append(f"tecnologia sem evidência: {term}")
    for m in SENIORIDADE.finditer(texto or ""):
        if _norm(m.group(0)) not in fonte:
            problems.append(f"senioridade sem fonte: {m.group(0)}")
    return problems


def perfil_sugerido(title: str, description: str = "") -> str:
    """Perfil pelo texto da vaga, sem modelo (o Alfaiate pode trocar por um dos três)."""
    t = _norm(title)
    if re.search(r"\b(estagi|estagio|intern|trainee|aprendiz)", t):
        return "junior"
    if re.search(r"\b(ia|ai|llm|machine learning|ml|genai|gen ai|inteligencia artificial|agentes?|agents?|nlp|"
                 r"data scien|cientista de dados|rpa)\b", t):
        return "ia"
    if re.search(r"\b(backend|back-end|back end|python|api|software engineer|engenheir|integra)", t):
        return "backend"
    d = _norm(description)
    return "ia" if len(re.findall(r"\b(llm|agentes?|agents?|rag|mcp|openai|langchain)\b", d)) >= 3 else (
        "backend" if re.search(r"\b(python|backend|back-end|api|postgres|sql)\b", d) else "junior")


# --- Montagem do documento (determinística) --------------------------------------------------------------------

MESES = {"pt": "jan fev mar abr mai jun jul ago set out nov dez".split(),
         "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()}


def _mes(ym: str | None, lang: str) -> str:
    if ym is None:
        return "atual" if lang == "pt" else "Present"
    y, m = ym.split("-")
    return f"{MESES[lang][int(m) - 1]}/{y}" if lang == "pt" else f"{MESES[lang][int(m) - 1]} {y}"


def periodo(inicio: str, fim: str | None, lang: str) -> str:
    return f"{_mes(inicio, lang)} – {_mes(fim, lang)}"


def _t(value, lang: str) -> str:
    """Texto no idioma; sem tradução, cai no português (a validação aponta)."""
    if isinstance(value, dict):
        return (value.get(lang) or value.get("pt") or "").strip()
    return (value or "").strip()


def _score(item: dict, perfil: Perfil) -> int:
    """Soma dos 3 maiores pesos das tags: item com muitas tags não ganha só por quantidade."""
    return sum(sorted((perfil.pesos.get(t, 0) for t in item.get("tags") or []), reverse=True)[:3])


def _escolher(itens: list[dict], perfil: Perfil, ordem: list[str] | None, limite: int) -> list[dict]:
    """Os ids pedidos (na ordem pedida) e, até o limite, os mais relevantes do perfil. Um por `grupo`."""
    by_id = {i["id"]: i for i in itens}
    pedidos = [by_id[i] for i in dict.fromkeys(ordem or []) if i in by_id]
    resto = sorted((i for i in itens if i not in pedidos), key=lambda i: -_score(i, perfil))  # estável: empate = ordem da base
    out, grupos = [], set()
    for item in pedidos + ([] if len(pedidos) >= 3 else resto):
        if item.get("grupo") and item["grupo"] in grupos:
            continue
        grupos.add(item.get("grupo"))
        out.append(item)
        if len(out) >= limite:
            break
    # Sem ordem da vaga, a ordem da base (a do dono) vale para a leitura; com ela, a mais relevante para a vaga primeiro.
    return out if pedidos else sorted(out, key=itens.index)


def montar(base: dict, perfil_id: str, lang: str = "pt", selecao: dict | None = None, corte: int = 0) -> dict:
    """Documento neutro (seções e itens) só com fatos confirmados. `corte` (0–5) tira, nesta ordem, o projeto menos
    relevante, a realização menos relevante, uma categoria de competências, o destaque dos projetos e mais um
    projeto: para caber em uma página sem diminuir a fonte."""
    perfil, sel = PERFIS[perfil_id], selecao or {}
    pessoa = base["pessoa"]
    usados: list[str] = []
    n_proj = max(1, perfil.projetos - (corte >= 1) - (corte >= 5))
    n_real = max(3, perfil.realizacoes - (corte >= 2))
    n_cat = 5 - (corte >= 3)
    n_destaques = 0 if corte >= 4 else 1

    contatos = [{"texto": pessoa["telefone"], "url": "tel:+55" + re.sub(r"\D", "", pessoa["telefone"])},
                {"texto": pessoa["email"], "url": f"mailto:{pessoa['email']}"}]
    for campo in ("linkedin", "github"):
        if pessoa.get(campo):
            contatos.append({"texto": re.sub(r"^https://(www\.)?", "", pessoa[campo]).rstrip("/"), "url": pessoa[campo]})
    local = f"{pessoa['cidade']}, {pessoa['uf']}" + (", Brazil" if lang == "en" else "")

    secoes = {}
    exp_itens = []
    for exp in [e for e in base.get("experiencias") or [] if ok(e)]:
        cargos = exp["cargos"]
        realizacoes = [r for r in exp.get("realizacoes") or [] if ok(r)]
        if exp.get("area") == "software":
            bullets = _escolher(realizacoes, perfil, sel.get("realizacoes"), n_real)
        else:
            bullets = realizacoes[:1] if perfil.anteriores_com_detalhe else []
        usados += [exp["id"]] + [b["id"] for b in bullets]
        anteriores = cargos[1:]
        nota = ""
        if anteriores:
            nota = ("Antes, na mesma empresa: " if lang == "pt" else "Previously at the company: ") + "; ".join(
                f"{_t(c, lang)} ({periodo(c['inicio'], c['fim'], lang)})" for c in anteriores) + "."
        exp_itens.append({"titulo": _t(cargos[0], lang), "sub": f"{exp['empresa']} · {exp.get('local', '')}".strip(" ·"),
                          "meta": periodo(cargos[0]["inicio"], cargos[0]["fim"], lang), "nota": nota,
                          "bullets": [_t(b, lang) for b in bullets]})
    secoes["experiencia"] = exp_itens

    projetos = _escolher(projetos_publicaveis(base), perfil, sel.get("projetos"), n_proj)
    usados += [p["id"] for p in projetos]
    secoes["projetos"] = [{
        "titulo": p["nome"], "meta": {"producao": ("em produção", "in production"), "uso_pessoal": ("em uso pessoal",
                                       "personal use"), "prototipo": ("protótipo", "prototype")}.get(
            p.get("situacao"), ("", ""))[IDIOMAS.index(lang)],
        "sub": ", ".join(p.get("tecnologias") or []), "texto": _t(p["descricao"], lang),
        "link": p.get("link") or "", "bullets": [_t(d, lang) for d in (p.get("destaques") or [])[:n_destaques]]}
        for p in projetos]

    skills = [s for s in base.get("competencias") or [] if ok(s)]
    destaque = [i for i in sel.get("competencias") or []]
    linhas = []
    for cat in perfil.categorias:
        nomes = sorted((s for s in skills if s["categoria"] == cat),
                       key=lambda s: (s["id"] not in destaque, skills.index(s)))[:7]
        if nomes:
            usados += [s["id"] for s in nomes]
            linhas.append({"rotulo": CATEGORIAS[cat][IDIOMAS.index(lang)], "texto": ", ".join(s["nome"] for s in nomes)})
    secoes["competencias"] = linhas[:n_cat]

    formacao = []
    for f in [f for f in base.get("formacao") or [] if ok(f)]:
        usados.append(f["id"])
        situacao = (f"em andamento, conclusão prevista em {f['conclusao']}" if lang == "pt"
                    else f"in progress, expected {f['conclusao']}") if f.get("situacao") == "em_andamento" else (
            f.get("conclusao") or "")
        formacao.append({"titulo": _t(f["curso"], lang), "texto": f"{f['instituicao']} · {situacao}".strip(" ·")})
    secoes["formacao"] = formacao

    cursos = [c for c in base.get("cursos") or [] if ok(c)]
    usados += [c["id"] for c in cursos]
    linhas = [{"texto": f"{c['nome']} — {c['instituicao']}" + (f" · {c['data']}" if c.get("data") else "")
               + (f" ({_t(c['detalhe'], lang)})" if c.get("detalhe") else "")} for c in cursos]
    idiomas = [i for i in base.get("idiomas") or [] if ok(i)]
    usados += [i["id"] for i in idiomas]
    if idiomas:
        linhas.append({"rotulo": "Idiomas" if lang == "pt" else "Languages",
                       "texto": " · ".join(_t(i, lang) for i in idiomas)})
    secoes["cursos"] = linhas

    resumo = (sel.get("resumo") or "").strip() or _t(base["resumos"][perfil_id], lang)
    return {"perfil": perfil_id, "idioma": lang, "nome": pessoa["nome"], "titulo": _t(base["titulos"][perfil_id], lang),
            "local": local, "contatos": contatos, "resumo": resumo,
            "secoes": [{"id": s, "titulo": SECOES[s][IDIOMAS.index(lang)], "itens": secoes[s]}
                       for s in perfil.secoes if secoes.get(s)],
            "rotulo_resumo": SECOES["resumo"][IDIOMAS.index(lang)], "ids": usados, "corte": corte}


def faltando_traducao(base: dict, doc: dict) -> list[str]:
    """Ids usados num documento em inglês sem texto em inglês."""
    if doc["idioma"] != "en":
        return []
    out = []
    for tipo, item in _itens(base):
        if item.get("id") in doc["ids"]:
            alvo = {"realizacao": item, "idioma": item, "projeto": item.get("descricao"),
                    "formacao": item.get("curso")}.get(tipo)
            if alvo is not None and not (alvo.get("en") or "").strip():
                out.append(item["id"])
    return out


def ids_confirmados(base: dict) -> set:
    return {item["id"] for _tipo, item in _itens(base) if ok(item)}


# --- Texto para os agentes ------------------------------------------------------------------------------------

def perfil_texto(base: dict) -> str:
    """Os fatos confirmados em texto corrido: o PERFIL que Aplicador e Treinador recebem (substitui o perfil.md)."""
    p = base["pessoa"]
    lines = [f"# {p['nome']} — perfil (currículo-base do Lastro; só fatos confirmados pelo dono)"]
    if p.get("pronomes"):
        lines.append(f"Pronomes: {p['pronomes']}")
    lines.append(f"Contato: {p['cidade']}, {p['uf']} · {p['email']} · {p['telefone']} · {p.get('linkedin', '')} · "
                 f"{p.get('github', '')}")
    for campo in ("disponibilidade", "nivel"):
        if p.get(campo):
            lines.append(f"{campo.capitalize()}: {p[campo]}")
    lines.append("\n## Experiência")
    for exp in [e for e in base.get("experiencias") or [] if ok(e)]:
        cargos = "; ".join(f"{c['pt']} ({periodo(c['inicio'], c['fim'], 'pt')})" for c in exp["cargos"])
        lines.append(f"- {exp['empresa']} ({_t(exp.get('descricao'), 'pt')}), {exp.get('local', '')}: {cargos}")
        lines += [f"  - {r['pt']}" for r in exp.get("realizacoes") or [] if ok(r)]
    lines.append("\n## Projetos")
    for proj in projetos_publicaveis(base):
        lines.append(f"- {proj['nome']} ({', '.join(proj.get('tecnologias') or [])}): {proj['descricao']['pt']}")
        lines += [f"  - {d['pt']}" for d in proj.get("destaques") or []]
    lines.append("\n## Competências")
    for cat, (rotulo, _en) in CATEGORIAS.items():
        nomes = [s["nome"] for s in base.get("competencias") or [] if ok(s) and s["categoria"] == cat]
        if nomes:
            lines.append(f"- {rotulo}: {', '.join(nomes)}")
    lines.append("\n## Formação")
    lines += [f"- {f['curso']['pt']} — {f['instituicao']} · " + (f"em andamento, conclusão prevista em {f['conclusao']}"
              if f.get("situacao") == "em_andamento" else str(f.get("conclusao") or ""))
              for f in base.get("formacao") or [] if ok(f)]
    lines.append("\n## Cursos (cursos livres, não certificações de fornecedor)")
    lines += [f"- {c['nome']} — {c['instituicao']} · {c.get('data', '')}" for c in base.get("cursos") or [] if ok(c)]
    lines.append("\n## Idiomas")
    lines += [f"- {i['pt']}" for i in base.get("idiomas") or [] if ok(i)]
    return "\n".join(lines)


def catalogo(base: dict) -> str:
    """Fatos confirmados com id, para o Alfaiate escolher (ele devolve ids, não reescreve realizações)."""
    lines = ["PERFIS DE APRESENTAÇÃO:"]
    lines += [f"- {k}: {p.nome} — prioriza {p.descricao}" for k, p in PERFIS.items()]
    lines.append("\nREALIZAÇÕES (experiência; escolha por id):")
    for exp in [e for e in base.get("experiencias") or [] if ok(e)]:
        for r in exp.get("realizacoes") or []:
            if ok(r):
                lines.append(f"[{r['id']}] ({exp['empresa']}; {', '.join(r.get('tags') or [])}) {r['pt']}")
    lines.append("\nPROJETOS (escolha por id):")
    for p in projetos_publicaveis(base):
        lines.append(f"[{p['id']}] {p['nome']} ({', '.join(p.get('tecnologias') or [])}; situação: "
                     f"{p.get('situacao') or 'não informada'}) {p['descricao']['pt']}")
    lines.append("\nCOMPETÊNCIAS (destaque por id):")
    lines += [f"[{s['id']}] {s['nome']} ({s['categoria']})" for s in base.get("competencias") or [] if ok(s)]
    return "\n".join(lines)
