# SPDX-License-Identifier: AGPL-3.0-or-later
"""Documentos do currículo: HTML A4 → PDF (Chrome do worker), DOCX e Markdown, com validação de cada arquivo.

Um só layout, pensado para leitura humana e para ATS: uma coluna, fundo branco, texto grafite, sem ícones, tabelas,
imagens, colunas ou letras espaçadas (espaçamento entre letras faz extratores separarem as letras). Fonte Arial; no
servidor ela resolve para Liberation Sans (métricas idênticas às da Arial), incorporada ao PDF como TrueType com
mapa Unicode: o texto continua selecionável e pesquisável. O DOCX usa estilos de parágrafo (Título, Cabeçalho 1/2,
Lista) e pede Arial, presente em qualquer leitor comum.

A validação extrai o texto do PDF (pypdf) e do DOCX e confere com o que o documento deveria conter, mais fontes,
links, metadados, ordem de leitura, títulos órfãos e uma inspeção visual das páginas renderizadas (pdftoppm). Passar
nela não garante compatibilidade com todo ATS: garante que o texto está lá, inteiro e na ordem certa.
"""

import asyncio
import base64
import hashlib
import html as html_lib
import io
import json
import re
import subprocess
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

from app import db

from . import curriculo

PLACEHOLDER = re.compile(r"\{\{|\}\}|\bTODO\b|\bnull\b|\bNone\b|\bundefined\b|\bNaN\b|lorem ipsum|\bPENDENTE\b|\[\s*\]", re.I)
MAX_PAGINAS = 2
POUCO_NA_ULTIMA = 0.5  # segunda página até meio cheia: tenta caber em uma tirando o menos relevante (nunca a fonte)
INK = 200  # cinza abaixo disto é tinta (0 preto, 255 branco)
MARGENS_MM = (13, 15, 12, 15)  # topo, direita, base, esquerda


class DocumentoInvalido(ValueError):
    def __init__(self, relatorio: dict):
        super().__init__("; ".join(relatorio["erros"][:5]))
        self.relatorio = relatorio


# --- HTML (vira o PDF) ----------------------------------------------------------------------------------------

CSS = """
@page { size: A4; margin: %smm %smm %smm %smm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; }
body { margin: 0; font-family: Arial, "Liberation Sans", Helvetica, sans-serif; font-size: 10pt; line-height: 1.35;
       color: #1f2328; background: #fff; }
a { color: inherit; text-decoration: none; }
header { margin-bottom: 9pt; }
h1 { font-size: 22pt; line-height: 1.1; margin: 0; font-weight: 700; color: #111418; }
.titulo { font-size: 11.5pt; margin: 3pt 0 5pt; color: #3a414b; }
.contatos { font-size: 9.5pt; color: #3a414b; }
.contatos .sep { color: #9aa1ab; padding: 0 3pt; }
h2 { font-size: 11.5pt; font-weight: 700; margin: 10pt 0 4.5pt; padding-bottom: 2.5pt; border-bottom: 0.75pt solid #c4c9d0;
     color: #111418; break-after: avoid; page-break-after: avoid; }
section:first-of-type h2 { margin-top: 4pt; }
.item { margin: 0 0 6pt; }
.item:last-child { margin-bottom: 0; }
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 10pt;
        break-after: avoid; page-break-after: avoid; }
.head b { font-size: 10.5pt; }
.meta { font-size: 9.5pt; color: #4b525c; white-space: nowrap; }
.sub { color: #3a414b; }
.nota { font-size: 9.5pt; color: #4b525c; margin: 1pt 0 0; }
p { margin: 1.5pt 0 0; }
ul { margin: 2.5pt 0 0; padding-left: 12pt; }
li { margin: 0 0 1.5pt; padding-left: 1pt; break-inside: avoid; page-break-inside: avoid; }
.linha { margin: 0 0 2.5pt; }
.linha b { font-weight: 700; }
""" % MARGENS_MM


def _a(text: str) -> str:
    return html_lib.escape(text or "", quote=True)


def _e(text: str) -> str:
    # Palavra com hífen ("e-mail") não quebra no hífen: o texto extraído sairia "e- mail".
    return re.sub(r"\w+(?:-\w+)+", lambda m: f'<span style="white-space:nowrap">{m.group(0)}</span>',
                  html_lib.escape(text or "", quote=True))


def html(doc: dict) -> str:
    sep = '<span class="sep">·</span>'
    contatos = sep.join([_e(doc["local"])] + [f'<a href="{_a(c["url"])}">{_e(c["texto"])}</a>' for c in doc["contatos"]])
    out = [f'<!doctype html><html lang="{"pt-BR" if doc["idioma"] == "pt" else "en"}"><head><meta charset="utf-8">',
           f"<title>{_a(titulo_documento(doc))}</title><style>{CSS}</style></head><body>",
           f'<header><h1>{_e(doc["nome"])}</h1><div class="titulo">{_e(doc["titulo"])}</div>',
           f'<div class="contatos">{contatos}</div></header>',
           f'<section><h2>{_e(doc["rotulo_resumo"])}</h2><p>{_e(doc["resumo"])}</p></section>']
    for secao in doc["secoes"]:
        out.append(f'<section><h2>{_e(secao["titulo"])}</h2>')
        for item in secao["itens"]:
            if item.get("titulo"):
                sub = f' <span class="sub">— {_e(item["sub"])}</span>' if item.get("sub") else ""
                link = (f' <span class="sub">· <a href="{_a(item["link"])}">'
                        f'{_e(re.sub(r"^https://(www[.])?", "", item["link"]))}</a></span>') if item.get("link") else ""
                out.append(f'<div class="item"><div class="head"><span><b>{_e(item["titulo"])}</b>{sub}{link}</span>'
                           f'<span class="meta">{_e(item.get("meta", ""))}</span></div>')
                if item.get("nota"):
                    out.append(f'<div class="nota">{_e(item["nota"])}</div>')
                if item.get("texto"):
                    out.append(f"<p>{_e(item['texto'])}</p>")
                if item.get("bullets"):
                    out.append("<ul>" + "".join(f"<li>{_e(b)}</li>" for b in item["bullets"]) + "</ul>")
                out.append("</div>")
            else:
                rotulo = f'<b>{_e(item["rotulo"])}:</b> ' if item.get("rotulo") else ""
                out.append(f'<div class="linha">{rotulo}{_e(item["texto"])}</div>')
        out.append("</section>")
    out.append("</body></html>")
    return "".join(out)


def titulo_documento(doc: dict) -> str:
    return f"{doc['nome']} — {'Currículo' if doc['idioma'] == 'pt' else 'Résumé'} ({doc['titulo']})"


def nome_arquivo(doc: dict) -> str:
    nome = unicodedata.normalize("NFKD", doc["nome"]).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", f"{nome} {'Curriculo' if doc['idioma'] == 'pt' else 'Resume'}").strip("-")


# --- Markdown (WhatsApp, diferenças entre versões, compatibilidade) ------------------------------------------

def markdown(doc: dict) -> str:
    contatos = " · ".join([doc["local"]] + [f"[{c['texto']}]({c['url']})" for c in doc["contatos"]])
    lines = [f"# {doc['nome']}", f"**{doc['titulo']}**", contatos, "", f"## {doc['rotulo_resumo']}", doc["resumo"]]
    for secao in doc["secoes"]:
        lines += ["", f"## {secao['titulo']}"]
        for item in secao["itens"]:
            if item.get("titulo"):
                head = " · ".join(x for x in (f"{item['titulo']} — {item['sub']}" if item.get("sub") else item["titulo"],
                                              item.get("meta"), item.get("link")) if x)
                lines.append(f"### {head}")
                lines += [x for x in (item.get("nota"), item.get("texto")) if x]
                lines += [f"- {b}" for b in item.get("bullets") or []]
            else:
                lines.append(f"- **{item['rotulo']}:** {item['texto']}" if item.get("rotulo") else f"- {item['texto']}")
    return "\n".join(lines) + "\n"


# --- DOCX (Office Open XML mínimo, só biblioteca padrão) ------------------------------------------------------

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
TEXT_WIDTH = 11906 - 2 * 1000  # A4 menos margens de 1000 twips (~17,6 mm)

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/>
<w:color w:val="1F2328"/><w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="pt-BR"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:qFormat/><w:pPr><w:spacing w:after="40"/></w:pPr><w:rPr><w:b/><w:color w:val="111418"/><w:sz w:val="44"/>
<w:szCs w:val="44"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:color w:val="3A414B"/>
<w:sz w:val="23"/><w:szCs w:val="23"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Contatos"><w:name w:val="Contatos"/><w:basedOn w:val="Normal"/><w:pPr>
<w:spacing w:after="120"/></w:pPr><w:rPr><w:color w:val="3A414B"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="2"
w:color="C4C9D0"/></w:pBdr><w:spacing w:before="220" w:after="90"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/>
<w:color w:val="111418"/><w:sz w:val="23"/><w:szCs w:val="23"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:tabs><w:tab w:val="right" w:pos="{TEXT_WIDTH}"/></w:tabs>
<w:spacing w:before="100" w:after="20"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:sz w:val="21"/><w:szCs w:val="21"/>
</w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Nota"><w:name w:val="Nota"/><w:basedOn w:val="Normal"/><w:rPr>
<w:color w:val="4B525C"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr>
<w:numPr><w:numId w:val="1"/></w:numPr><w:spacing w:before="20" w:after="20"/><w:ind w:left="300" w:hanging="200"/>
</w:pPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:rPr><w:color w:val="1F2328"/></w:rPr>
</w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {W}><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0">
<w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr>
<w:ind w:left="300" w:hanging="200"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/></w:rPr></w:lvl>
</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>"""


def _run(text: str, bold: bool = False, color: str | None = None) -> str:
    props = ("<w:b/>" if bold else "") + (f'<w:color w:val="{color}"/>' if color else "")
    return f'<w:r>{f"<w:rPr>{props}</w:rPr>" if props else ""}<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r>'


def _p(style: str, runs: str) -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{runs}</w:p>'


def docx(doc: dict) -> bytes:
    rels, body = [], []

    def link(url: str, text: str) -> str:
        rid = f"rIdL{len(rels) + 1}"
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    f'relationships/hyperlink" Target="{xml_escape(url, {chr(34): "&quot;"})}" TargetMode="External"/>')
        return (f'<w:hyperlink r:id="{rid}"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                f'<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:hyperlink>')

    body.append(_p("Title", _run(doc["nome"])))
    body.append(_p("Subtitle", _run(doc["titulo"])))
    sep = _run(" · ", color="9AA1AB")
    body.append(_p("Contatos", sep.join([_run(doc["local"])] + [link(c["url"], c["texto"]) for c in doc["contatos"]])))
    body.append(_p("Heading1", _run(doc["rotulo_resumo"])))
    body.append(_p("Normal", _run(doc["resumo"])))
    for secao in doc["secoes"]:
        body.append(_p("Heading1", _run(secao["titulo"])))
        for item in secao["itens"]:
            if item.get("titulo"):
                runs = _run(item["titulo"], bold=True) + (_run(f" — {item['sub']}") if item.get("sub") else "")
                if item.get("link"):
                    runs += _run(" · ") + link(item["link"], re.sub(r"^https://(www[.])?", "", item["link"]))
                if item.get("meta"):
                    runs += '<w:r><w:tab/></w:r>' + _run(item["meta"], color="4B525C")
                body.append(_p("Heading2", runs))
                if item.get("nota"):
                    body.append(_p("Nota", _run(item["nota"])))
                if item.get("texto"):
                    body.append(_p("Normal", _run(item["texto"])))
                body += [_p("ListBullet", _run(b)) for b in item.get("bullets") or []]
            else:
                runs = (_run(f"{item['rotulo']}: ", bold=True) if item.get("rotulo") else "") + _run(item["texto"])
                body.append(_p("Normal", runs))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="900" w:right="1000" w:bottom="900" '
                'w:left="1000" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr></w:body></w:document>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.'
                'openxmlformats.org/package/2006/relationships"><Relationship Id="rIdS" Type="http://schemas.'
                'openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship '
                'Id="rIdN" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" '
                f'Target="numbering.xml"/>{"".join(rels)}</Relationships>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.'
            'openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{xml_escape(titulo_documento(doc))}</dc:title><dc:creator>{xml_escape(doc["nome"])}</dc:creator>'
            f'<dc:language>{"pt-BR" if doc["idioma"] == "pt" else "en"}</dc:language></cp:coreProperties>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/'
             'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-'
             'package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override '
             'PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
             'wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/'
             'vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.'
             'xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
             '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-'
             'properties+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.'
                 'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
                 'openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
                 'core-properties" Target="docProps/core.xml"/></Relationships>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("[Content_Types].xml", types), ("_rels/.rels", root_rels), ("docProps/core.xml", core),
                           ("word/document.xml", document), ("word/styles.xml", STYLES),
                           ("word/numbering.xml", NUMBERING), ("word/_rels/document.xml.rels", doc_rels)):
            z.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), data)  # data fixa: mesmo conteúdo, mesmo arquivo
    return buffer.getvalue()


# --- Validação ------------------------------------------------------------------------------------------------

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").replace("­", "").replace("​", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def esperado(doc: dict) -> list[str]:
    """Trechos que têm de sair no texto extraído (início de cada bullet: o bastante para achar texto ausente)."""
    out = [doc["nome"], doc["titulo"], doc["rotulo_resumo"], " ".join(doc["resumo"].split()[:10])]
    out += [c["texto"] for c in doc["contatos"]]
    for secao in doc["secoes"]:
        out.append(secao["titulo"])
        for item in secao["itens"]:
            out += [x for x in (item.get("titulo"), item.get("meta"), item.get("rotulo")) if x]
            out += [" ".join(b.split()[:10]) for b in item.get("bullets") or []]
            if item.get("texto"):
                out.append(" ".join(item["texto"].split()[:10]))
    return [x for x in out if x]


def _conteudo(base: dict, doc: dict) -> list[str]:
    erros = [f"fato não confirmado no documento: {i}" for i in doc["ids"] if i not in curriculo.ids_confirmados(base)]
    erros += [f"resumo: {p}" for p in curriculo.checar_resumo(doc["resumo"], base)]
    erros += [f"sem tradução para inglês: {i}" for i in curriculo.faltando_traducao(base, doc)]
    if not {"experiencia", "formacao"} <= {s["id"] for s in doc["secoes"]}:
        erros.append("faltam seções obrigatórias (experiência e formação)")
    if not any(c["url"].startswith("mailto:") for c in doc["contatos"]):
        erros.append("sem e-mail de contato")
    return erros


def _texto_ok(texto: str, doc: dict, rotulo: str) -> list[str]:
    erros = []
    flat = _norm(texto)
    faltando = [x for x in esperado(doc) if _norm(x) not in flat]
    erros += [f"{rotulo}: texto ausente ou quebrado: “{x[:60]}”" for x in faltando[:8]]
    if "�" in texto or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", texto):
        erros.append(f"{rotulo}: caracteres corrompidos")
    if m := PLACEHOLDER.search(texto):
        erros.append(f"{rotulo}: campo de modelo não preenchido ({m.group(0)})")
    pos = 0
    for titulo in [doc["nome"], doc["rotulo_resumo"]] + [s["titulo"] for s in doc["secoes"]]:
        pos = flat.find(_norm(titulo), pos)  # cada título depois do anterior (a palavra pode aparecer antes no texto)
        if pos < 0:
            erros.append(f"{rotulo}: ordem de leitura diferente da ordem das seções ({titulo})")
            break
    return erros


def validar_pdf(base: dict, doc: dict, pdf: bytes) -> dict:
    from pypdf import PdfReader

    erros, avisos = _conteudo(base, doc), []
    try:
        reader = PdfReader(io.BytesIO(pdf))
        paginas = [p.extract_text() or "" for p in reader.pages]
    except Exception as exc:  # noqa: BLE001 — PDF que não abre é o pior erro possível
        return {"ok": False, "erros": [f"PDF não abre ({type(exc).__name__})"], "avisos": [], "paginas": 0}
    texto = "\n".join(paginas)
    erros += _texto_ok(texto, doc, "PDF")
    if len(paginas) > MAX_PAGINAS:
        erros.append(f"{len(paginas)} páginas (máximo {MAX_PAGINAS})")
    meta = reader.metadata or {}
    if not meta.get("/Title") or not meta.get("/Author"):
        erros.append("metadados sem título ou autor")
    titulos = {_norm(s["titulo"]) for s in doc["secoes"]} | {_norm(doc["rotulo_resumo"])}
    for i, pagina in enumerate(paginas[:-1], 1):
        linhas = [ln for ln in pagina.splitlines() if ln.strip()]
        if linhas and _norm(linhas[-1]) in titulos:
            erros.append(f"título “{linhas[-1].strip()}” isolado no fim da página {i}")
    links, fontes = set(), []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            uri = (annot.get_object().get("/A") or {}).get("/URI")
            if uri:
                links.add(str(uri))
        for font in ((page.get("/Resources") or {}).get("/Font") or {}).values():
            font = font.get_object()
            desc = font.get("/FontDescriptor") or (font["/DescendantFonts"][0].get_object().get("/FontDescriptor")
                                                   if font.get("/DescendantFonts") else None)
            desc = desc.get_object() if desc is not None else {}
            fontes.append(str(font.get("/BaseFont", "?")))
            if font.get("/Subtype") == "/Type3":
                erros.append(f"fonte Type3 (texto difícil de extrair): {font.get('/BaseFont')}")
            elif not any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                erros.append(f"fonte não incorporada: {font.get('/BaseFont')}")
            if "/ToUnicode" not in font:
                erros.append(f"fonte sem mapa Unicode (texto não pesquisável): {font.get('/BaseFont')}")
    for c in doc["contatos"]:
        if c["url"].startswith(("mailto:", "https:")) and c["url"] not in links:
            erros.append(f"link não clicável: {c['texto']}")
    visual = inspecao_visual(pdf)
    erros += visual["erros"]
    ultima = visual["ocupacao"][-1] if visual["ocupacao"] else 0
    if len(paginas) == 2 and ultima < POUCO_NA_ULTIMA:
        avisos.append(f"segunda página com pouco conteúdo ({ultima:.0%})")
    return {"ok": not erros, "erros": erros, "avisos": avisos, "paginas": len(paginas), "ocupacao": visual["ocupacao"],
            "fontes": sorted(set(fontes)), "links": sorted(links), "caracteres": len(texto),
            "verificado_em": db.utcnow()}


def validar_docx(doc: dict, data: bytes) -> dict:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
            ElementTree.fromstring(z.read("word/styles.xml"))
            rels = z.read("word/_rels/document.xml.rels").decode()
            imagens = [n for n in z.namelist() if n.startswith("word/media/")]
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erros": [f"DOCX não abre ({type(exc).__name__})"], "avisos": []}
    paragrafos = ["".join(t.text or "" for t in p.iter(f"{{{ns['w']}}}t")) for p in root.iter(f"{{{ns['w']}}}p")]
    erros = _texto_ok("\n".join(paragrafos), doc, "DOCX")
    erros += [f"DOCX: link ausente: {c['texto']}" for c in doc["contatos"]
              if c["url"].startswith(("mailto:", "https:")) and xml_escape(c["url"]) not in rels]
    if imagens:
        erros.append("DOCX com imagens")
    return {"ok": not erros, "erros": erros, "paragrafos": len(paragrafos)}


def inspecao_visual(pdf: bytes, dpi: int = 50) -> dict:
    """Renderiza as páginas (cinza) e confere: nada encostando na borda (texto cortado ou fora da margem), nenhuma
    página em branco e quanto da altura útil cada página ocupa."""
    erros, ocupacao = [], []
    band = round(8 / 25.4 * dpi)  # 8 mm: dentro das margens de 14–16 mm, nada pode ter tinta aqui
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "cv.pdf"
        src.write_bytes(pdf)
        try:
            subprocess.run(["pdftoppm", "-gray", "-r", str(dpi), str(src), str(Path(tmp) / "p")], check=True,
                           timeout=60, capture_output=True)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"erros": [], "ocupacao": [], "aviso": f"inspeção visual indisponível ({type(exc).__name__})"}
        for i, path in enumerate(sorted(Path(tmp).glob("p-*.pgm")), 1):
            w, h, px = _pgm(path.read_bytes())
            rows = [px[y * w:(y + 1) * w] for y in range(h)]
            ink_rows = [y for y, row in enumerate(rows) if min(row) < INK]
            if not ink_rows:
                erros.append(f"página {i} em branco")
                ocupacao.append(0.0)
                continue
            borda = any(min(rows[y]) < INK for y in list(range(band)) + list(range(h - band, h)))
            borda = borda or any(min(row[:band]) < INK or min(row[w - band:]) < INK for row in rows)
            if borda:
                erros.append(f"página {i}: conteúdo encostando na borda (texto cortado ou fora da margem)")
            top, bottom = round(MARGENS_MM[0] / 25.4 * dpi), h - round(MARGENS_MM[2] / 25.4 * dpi)
            ocupacao.append(round(max(0.0, min(1.0, (ink_rows[-1] - top) / (bottom - top))), 3))
    return {"erros": erros, "ocupacao": ocupacao}


def _pgm(data: bytes) -> tuple[int, int, bytes]:
    parts = data.split(maxsplit=4)  # P5, largura, altura, máximo, pixels
    if parts[0] != b"P5":
        raise ValueError("PGM inesperado")
    w, h = int(parts[1]), int(parts[2])
    return w, h, parts[4][-w * h:]


def previa_png(pdf: bytes, pagina: int, dpi: int = 110) -> bytes | None:
    """Uma página do PDF exato em PNG (pré-visualização na tela; o PDF em si abre em outra aba)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "cv.pdf"
        src.write_bytes(pdf)
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(pagina), "-l", str(pagina), "-singlefile",
                        str(src), str(Path(tmp) / "p")], check=True, timeout=60, capture_output=True)
        out = Path(tmp) / "p.png"
        return out.read_bytes() if out.is_file() else None


# --- Geração --------------------------------------------------------------------------------------------------

def metadados(pdf: bytes, doc: dict) -> bytes:
    """O Chrome grava só o título: acrescenta autor, assunto e palavras-chave (sem mexer no conteúdo nem nos links)."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    writer.add_metadata({"/Title": titulo_documento(doc), "/Author": doc["nome"],
                         "/Subject": doc["titulo"], "/Creator": "Lastro · Carreira"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


async def imprimir(mentor, page_html: str) -> bytes:
    """HTML → PDF no Chrome do worker do mentor (operação `pdf`: sem JavaScript e sem rede)."""
    result = await mentor.call({"op": "pdf", "html": page_html}, timeout=90)
    if result.get("type") != "done" or not result.get("pdf"):
        raise RuntimeError(result.get("message") or "o worker não gerou o PDF")
    return base64.b64decode(result["pdf"])


async def produzir(mentor, base: dict, perfil: str, idioma: str, selecao: dict | None = None) -> tuple[dict, bytes, bytes, dict]:
    """Monta, imprime e valida. Segunda página quase vazia: tira o item menos relevante e tenta de novo (nunca
    diminui a fonte). Devolve (documento, pdf, docx, relatório)."""
    tentativas = []
    for corte in range(6):
        doc = curriculo.montar(base, perfil, idioma, selecao, corte)
        pdf = metadados(await imprimir(mentor, html(doc)), doc)
        relatorio = await asyncio.to_thread(validar_pdf, base, doc, pdf)
        tentativas.append((doc, pdf, relatorio))
        if not (relatorio["paginas"] == 2 and relatorio["ocupacao"] and relatorio["ocupacao"][-1] < POUCO_NA_ULTIMA):
            break
    else:  # nem cortando coube em uma: melhor duas páginas completas que uma linha solta na segunda
        tentativas.append(tentativas[0])
    doc, pdf, relatorio = tentativas[-1]
    data = docx(doc)
    relatorio["docx"] = validar_docx(doc, data)
    relatorio["ok"] = relatorio["ok"] and relatorio["docx"]["ok"]
    relatorio["erros"] = relatorio["erros"] + relatorio["docx"]["erros"]
    return doc, pdf, data, relatorio


def gravar(conn, *, tipo: str, base_id: int, doc: dict, pdf: bytes, data: bytes, relatorio: dict,
           vaga_id: str | None = None, origem_id: int | None = None, alteracoes: list | None = None,
           analise: dict | None = None) -> int:
    if not relatorio["ok"]:
        raise DocumentoInvalido(relatorio)
    return conn.execute(
        "INSERT INTO carreira_curriculos (tipo, vaga_id, origem_id, conteudo_md, alteracoes_json, created_at, perfil,"
        " idioma, base_id, documento_json, pdf, docx, validacao_json, sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
        " ?, ?, ?) RETURNING id",
        (tipo, vaga_id, origem_id, markdown(doc), json.dumps(alteracoes or [], ensure_ascii=False), db.utcnow(),
         doc["perfil"], doc["idioma"], base_id, json.dumps({**doc, "analise": analise} if analise else doc,
                                                           ensure_ascii=False), pdf, data,
         json.dumps(relatorio, ensure_ascii=False), hashlib.sha256(pdf).hexdigest())).fetchone()[0]


async def versoes_dos_perfis(conn, mentor, idioma: str = "pt") -> list[int]:
    """Versão geral de cada perfil para a base vigente (uma vez por versão da base). Devolve os ids criados."""
    atual = curriculo.carregar(conn)
    if atual is None:
        return []
    base_id, base = atual
    feitos = []
    for perfil in curriculo.PERFIS:
        if conn.execute("SELECT 1 FROM carreira_curriculos WHERE tipo = 'base' AND base_id = ? AND perfil = ? AND "
                        "idioma = ?", (base_id, perfil, idioma)).fetchone():
            continue
        doc, pdf, data, relatorio = await produzir(mentor, base, perfil, idioma)
        feitos.append(gravar(conn, tipo="base", base_id=base_id, doc=doc, pdf=pdf, data=data, relatorio=relatorio))
    return feitos


def versao_do_perfil(conn, base_id: int, perfil: str, idioma: str = "pt"):
    return conn.execute("SELECT id, pdf, docx FROM carreira_curriculos WHERE tipo = 'base' AND base_id = ? AND "
                        "perfil = ? AND idioma = ? ORDER BY id DESC LIMIT 1", (base_id, perfil, idioma)).fetchone()
