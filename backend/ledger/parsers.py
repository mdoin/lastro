# SPDX-License-Identifier: AGPL-3.0-or-later
"""Leitura determinística de extratos, faturas de cartão e comprovantes (CSV, OFX e texto de PDF/OCR).

A entrada é NÃO CONFIÁVEL: o conteúdo é só dado (nada é executado, renderizado ou obedecido), tamanhos são
limitados, caracteres de controle são removidos e números longos (conta/cartão) saem mascarados nos 4 últimos
dígitos. Avisos não repetem o conteúdo das linhas, para não refletir texto do documento para quem os lê.
"""

import csv
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from financial_engine.money import MAX_ABS, parse_brl
from team.auditor import fold

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_DESC = 200
MAX_TEXT_CHARS = 2_000_000
MAX_WARNINGS = 50


@dataclass
class ParsedItem:
    date: date
    amount: Decimal
    description: str
    currency: str = "BRL"
    counterparty: str = ""
    external_id: str = ""
    installment: tuple[int, int] | None = None
    pending: bool = False
    hint: str = ""
    accrual_date: date | None = None
    line_ref: str = ""
    confidence: str = "alta"


@dataclass
class Balance:
    date: date
    amount: Decimal
    currency: str = "BRL"
    line_ref: str = ""


@dataclass
class ParsedDocument:
    doc_type: str
    source_format: str
    institution: str = ""
    account: str = ""
    currency: str = "BRL"
    items: list[ParsedItem] = field(default_factory=list)
    balances: list[Balance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class UnsupportedDocument(ValueError):
    """Documento recusado; a mensagem é em português e segura para mostrar ao usuário."""


# --- texto -------------------------------------------------------------------------------------------------------

# Controles C0/C1, larguras zero e marcas de direção bidi (usadas para disfarçar texto).
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩﻿]")
_LONG_NUMBER = re.compile(r"\b\d(?:[ .-]?\d){11,18}\b")


def _strip(text: str, limit: int = MAX_DESC) -> str:
    return " ".join(_CTRL.sub(" ", text or "").split())[:limit]


def _clean(text: str, limit: int = MAX_DESC) -> str:
    """Texto exibível: sem controles, espaços colapsados e cartão/conta mascarados nos 4 últimos dígitos."""
    text = " ".join(_CTRL.sub(" ", text or "").split())
    return _LONG_NUMBER.sub(lambda m: "****" + re.sub(r"\D", "", m.group())[-4:], text)[:limit]


def _last4(text: str) -> str:
    return re.sub(r"\D", "", text or "")[-4:]


def _fold_line(line: str) -> str:
    """fold() que preserva o tamanho, para casar no texto dobrado e recortar o original na mesma posição."""
    return line.lower() if line.isascii() else "".join((fold(c) or c)[0] for c in line)


def _cap_warnings(doc: ParsedDocument) -> ParsedDocument:
    if len(doc.warnings) > MAX_WARNINGS:
        extra = len(doc.warnings) - MAX_WARNINGS
        doc.warnings = doc.warnings[:MAX_WARNINGS] + [f"... e mais {extra} avisos."]
    return doc


# --- valores e datas ---------------------------------------------------------------------------------------------

_DOT_DECIMAL = re.compile(r"^[+-]?\d+\.\d{1,2}$")


def parse_amount(text: str) -> Decimal:
    """Valor em Decimal: "1.234,56", "R$ 38,00", "38,00 D"/"38,00 C", "(38,00)", "38,00-" e OFX "-38.00"."""
    s = _strip(text, 64).replace("R$", "").replace(" ", "").replace("−", "-")
    suffix = s[-1:].upper()
    if suffix in ("D", "C"):
        s = s[:-1]
    if s.endswith("-") and not s.startswith(("-", "(")):
        s = "-" + s[:-1]
    s = s.removeprefix("+")
    if not s:
        raise ValueError("Valor vazio.")
    # Sem vírgula e com 1-2 casas após o ponto é decimal com ponto (OFX); o resto segue o padrão brasileiro.
    value = Decimal(s) if "," not in s and _DOT_DECIMAL.match(s) else parse_brl(s)
    if abs(value) >= MAX_ABS:
        raise ValueError("Valor grande demais.")
    if suffix == "D":
        return -abs(value)
    return abs(value) if suffix == "C" else value


_MONTHS = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
           "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}
# Casar sempre no texto dobrado (minúsculo, sem acento). Sem ano, só "dd/mm" (ponto e hífen confundem com valores).
_DATE_RE = re.compile(
    r"(?<!\d)(?:(?P<iso>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})"
    r"|(?P<d>\d{1,2})(?P<sep>[/.-])(?P<m>\d{1,2})(?P=sep)(?P<y>\d{4}|\d{2})"
    r"|(?P<sd>\d{1,2})/(?P<sm>\d{1,2})"
    r"|(?P<nd>\d{1,2})\s+(?:de\s+)?(?P<nm>jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\.?(?:\s+de)?\s+"
    r"(?P<ny>\d{4}))(?!\d)"
)
_REF_LABEL = re.compile(r"periodo|emissao|emitid|vencimento|referencia|referente|gerado em|fechamento|data base")


def _date_from_match(m: re.Match, ref: date | None) -> tuple[date, bool]:
    """(data, ano_inferido). Datas sem ano usam o ano da referência, recuando um ano se ficariam bem depois dela."""
    if m["iso"]:
        return date(int(m["iso"]), int(m["im"]), int(m["id"])), False
    if m["nd"]:
        return date(int(m["ny"]), _MONTHS[m["nm"]], int(m["nd"])), False
    if m["y"]:
        year = int(m["y"])
        if year < 100:
            year += 2000 if year < 70 else 1900
        return date(year, int(m["m"]), int(m["d"])), False
    if ref is None:
        raise ValueError("data sem ano e sem data de referência no documento")
    when = date(ref.year, int(m["sm"]), int(m["sd"]))
    return (when.replace(year=when.year - 1) if when > ref + timedelta(days=45) else when), True


def _reference_date(text: str) -> date | None:
    """Data de emissão/período do documento; sem rótulo, a data completa mais recente."""
    labeled, every = [], []
    for line in fold(text).splitlines():
        for m in _DATE_RE.finditer(line):
            if m["sd"]:
                continue
            try:
                when, _ = _date_from_match(m, None)
            except ValueError:
                continue
            every.append(when)
            if _REF_LABEL.search(line):
                labeled.append(when)
    return max(labeled or every, default=None)


def _inferred_warning(ref: date) -> str:
    return f"Datas sem ano: ano inferido a partir de {ref:%d/%m/%Y}; confira os lançamentos."


# --- classificação de lançamentos --------------------------------------------------------------------------------

_HINTS = (
    ("pagamento_fatura", re.compile(r"pagamento (de |da )?fatura|pgto\.? (de |da )?fatura|\bpag\.? fatura"
                                    r"|pagamento (de |do )?cartao")),
    ("estorno", re.compile(r"estorno|^est\.|chargeback")),
    ("reembolso", re.compile(r"reembolso")),
    ("transferencia", re.compile(r"(?=.*\b(?:transf|ted\b|doc\b|pix\b))(?=.*(?:mesma titularidade|entre contas"
                                 r"|conta propria))")),
    ("salario", re.compile(r"salario|\bfolha\b")),
)
_INSTALLMENT = (
    re.compile(r"\bparc(?:ela)?\.?\s*(\d{1,3})\s*(?:/|de)\s*(\d{1,3})\b"),
    re.compile(r"(?:^|\s)(\d{1,3})/(\d{1,3})$"),
)
_PENDING = re.compile(r"pendente|agendad|a confirmar|previst|lancamentos? futuros?")
_SKIP_ROW = ("total", "subtotal")


def _hint(folded: str) -> str:
    return next((name for name, rx in _HINTS if rx.search(folded)), "")


def _installment(folded: str) -> tuple[int, int] | None:
    for rx in _INSTALLMENT:
        m = rx.search(folded)
        if m and 1 <= int(m[1]) <= int(m[2]) and int(m[2]) >= 2:
            return int(m[1]), int(m[2])
    return None


def _is_balance(description: str) -> bool:
    # "SALDO", "SALDO ANTERIOR", "S A L D O", "Saldo do dia"...
    return re.sub(r"[^a-z]", "", fold(description)).startswith("saldo")


def _item(when: date, amount: Decimal, raw: str, *, pending: bool = False, **kw) -> ParsedItem:
    description = _clean(raw)
    folded = fold(description)
    kw.setdefault("installment", _installment(folded))
    return ParsedItem(date=when, amount=amount, description=description, hint=_hint(folded),
                      pending=pending or bool(_PENDING.search(folded)), **kw)


# --- detecção de formato -----------------------------------------------------------------------------------------

def _decode(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise UnsupportedDocument("Arquivo grande demais (máximo 10 MB).")
    if b"\x00" in data:
        raise UnsupportedDocument("Arquivo binário não suportado.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    controls = sum(1 for c in text[:65536] if c < " " and c not in "\t\r\n")
    if controls > len(text[:65536]) // 100:
        raise UnsupportedDocument("Arquivo binário não suportado.")
    return text


def _delimiter(text: str) -> str | None:
    """Delimitador com mais linhas de mesma largura (≥ 2 colunas), ponderado pela largura."""
    lines = [line for line in text.splitlines() if line.strip()][:50]
    best, best_score = None, 0
    for delim in (";", "\t", ","):
        try:
            widths = Counter(len(row) for row in csv.reader(lines, delimiter=delim))
        except csv.Error:
            continue
        width, freq = widths.most_common(1)[0] if widths else (0, 0)
        if width >= 2 and freq >= 2 and freq * width > best_score:
            best, best_score = delim, freq * width
    return best


def sniff(data: bytes, filename: str = "") -> str:
    """Tipo pelo conteúdo. O nome do arquivo é ignorado de propósito: extensão não é prova de nada."""
    head = data[:16]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if not data:
        raise UnsupportedDocument("Arquivo vazio.")
    text = _decode(data)
    start = text[:2048].upper()
    if "OFXHEADER" in start or "<OFX>" in start:
        return "ofx"
    if _delimiter(text):
        return "csv"
    raise UnsupportedDocument("Formato não suportado: envie PDF, imagem (PNG/JPG), OFX ou CSV.")


# --- CSV ---------------------------------------------------------------------------------------------------------

def _header_role(cell: str) -> str | None:
    h = " ".join(fold(cell).replace("_", " ").split()).strip(" :")
    if not h:
        return None
    if h in ("date", "dt") or h.startswith("data"):
        return "date"
    if "debito" in h or "saida" in h or h in ("debit", "withdrawal"):
        return "debit"
    if "credito" in h or "entrada" in h or h in ("credit", "deposit"):
        return "credit"
    if h.startswith("saldo") or h == "balance":
        return "balance"
    if h.startswith("valor") or h in ("amount", "montante", "value"):
        return "amount"
    if h.startswith(("descricao", "historico", "lancamento", "memo", "description", "estabelecimento", "titulo",
                     "title", "detalhe")):
        return "desc"
    if h in ("id", "identificador", "fitid") or h.startswith(("documento", "n documento", "no documento", "doc")):
        return "id"
    if "parcela" in h or h == "installment":
        return "installment"
    if h in ("status", "situacao"):
        return "status"
    return None


def _header(row: list[str]) -> dict[str, int] | None:
    roles: dict[str, int] = {}
    for i, cell in enumerate(row):
        role = _header_role(cell)
        if role and role not in roles:
            roles[role] = i
    has_value = {"amount", "debit", "credit"} & roles.keys()
    return roles if "date" in roles and has_value else None


def _amount_or_reason(text: str) -> Decimal:
    try:
        return parse_amount(text)
    except (ValueError, ArithmeticError):
        raise ValueError("valor inválido") from None  # não repete o texto da linha no aviso


def _csv_row(row: list[str], roles: dict[str, int], ref: date | None, n: int):
    def cell(role: str) -> str:
        i = roles.get(role)
        return row[i].strip() if i is not None and i < len(row) else ""

    description = cell("desc")
    if any(fold(c).strip().startswith(_SKIP_ROW) for c in (description, cell("date"))):
        return None, False
    m = _DATE_RE.match(fold(cell("date")).strip())
    if not m:
        raise ValueError("data inválida")
    try:
        when, inferred = _date_from_match(m, ref)
    except ValueError:
        raise ValueError("data inválida") from None
    if _is_balance(description):
        raw = cell("amount") or cell("balance") or cell("credit") or cell("debit")
        return Balance(date=when, amount=_amount_or_reason(raw), line_ref=f"linha {n}"), inferred

    if "amount" in roles:
        amount = _amount_or_reason(cell("amount"))
    else:
        debit, credit = cell("debit"), cell("credit")
        if debit and _amount_or_reason(debit) != 0:
            amount = -abs(_amount_or_reason(debit))
        elif credit:
            amount = abs(_amount_or_reason(credit))
        else:
            raise ValueError("valor ausente")
    kw = {}
    parcel = _installment("parc " + fold(cell("installment"))) if cell("installment") else None
    if parcel:
        kw["installment"] = parcel
    status = fold(cell("status"))
    return _item(when, amount, description, pending=bool(_PENDING.search(status)), external_id=_strip(cell("id"), 100),
                 line_ref=f"linha {n}", **kw), inferred


def parse_csv(data: bytes) -> ParsedDocument:
    text = _decode(data)
    delim = _delimiter(text)
    if not delim:
        raise UnsupportedDocument("CSV sem delimitador reconhecível (use ponto e vírgula, vírgula ou tabulação).")
    doc = ParsedDocument(doc_type="extrato", source_format="csv")
    ref = _reference_date(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    roles, rows, inferred_any = None, 0, False
    try:
        for row in reader:
            n = reader.line_num
            if roles is None:
                if n > 50:
                    break
                roles = _header(row)
                continue
            if not any(c.strip() for c in row):
                continue
            rows += 1
            if rows > MAX_ROWS:
                doc.warnings.append(f"Limite de {MAX_ROWS} linhas atingido; o restante (linha {n} em diante) ignorado.")
                break
            try:
                entry, inferred = _csv_row(row, roles, ref, n)
            except ValueError as exc:
                doc.warnings.append(f"Linha {n} ignorada: {exc}.")
                continue
            inferred_any |= inferred
            if isinstance(entry, Balance):
                doc.balances.append(entry)
            elif entry:
                doc.items.append(entry)
    except csv.Error:
        doc.warnings.append(f"CSV malformado a partir da linha {reader.line_num}; o restante foi ignorado.")
    if roles is None:
        raise UnsupportedDocument("Não encontrei o cabeçalho do CSV (colunas de data e valor).")
    if not doc.items and not doc.balances:
        doc.warnings.append("Nenhum lançamento encontrado no CSV.")
    if inferred_any:
        doc.warnings.append(_inferred_warning(ref))
    return _cap_warnings(doc)


# --- OFX ---------------------------------------------------------------------------------------------------------

def _unescape(text: str) -> str:
    # Só as cinco entidades básicas, sem DTD nem expansão recursiva.
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(entity, char)
    return text


def _tag(block: str, name: str) -> str:
    # Serve para SGML (<TRNAMT>-38.00 sem fechamento) e XML (<TRNAMT>-38.00</TRNAMT>).
    m = re.search(rf"<{name}>([^<\r\n]*)", block, re.I)
    return _unescape(m[1]).strip() if m else ""


def _ofx_date(text: str) -> date:
    m = re.match(r"(\d{4})(\d{2})(\d{2})", text)
    if not m:
        raise ValueError("data inválida")
    return date(int(m[1]), int(m[2]), int(m[3]))


def parse_ofx(data: bytes) -> ParsedDocument:
    text = _decode(data)
    start = re.search(r"<OFX>", text, re.I)
    if not start:
        raise UnsupportedDocument("Arquivo OFX sem o bloco <OFX>.")
    body = text[start.start():]
    if re.search(r"<(CREDITCARDMSGSRSV1|CCSTMTRS)>", body, re.I):
        doc_type = "fatura_cartao"
    elif re.search(r"<(BANKMSGSRSV1|STMTRS)>", body, re.I):
        doc_type = "extrato"
    else:
        doc_type = "desconhecido"
    doc = ParsedDocument(doc_type=doc_type, source_format="ofx",
                         institution=_clean(_tag(body, "ORG") or _tag(body, "BANKID"), 80),
                         account=_last4(_tag(body, "ACCTID")),
                         currency=_strip(_tag(body, "CURDEF"), 3).upper() or "BRL")

    for kind in ("LEDGERBAL", "AVAILBAL"):
        for m in re.finditer(rf"<{kind}>(.*?)(?=</{kind}>|<LEDGERBAL>|<AVAILBAL>|</STMTRS>|</CCSTMTRS>|\Z)",
                             body, re.I | re.S):
            try:
                when, amount = _ofx_date(_tag(m[1], "DTASOF")), parse_amount(_tag(m[1], "BALAMT"))
                doc.balances.append(Balance(date=when, amount=amount, currency=doc.currency, line_ref=kind))
            except (ValueError, ArithmeticError):
                doc.warnings.append(f"Saldo {kind} ignorado: data ou valor inválido.")

    blocks = re.finditer(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>|\Z)", body, re.I | re.S)
    for n, m in enumerate(blocks, 1):
        if n > MAX_ROWS:
            doc.warnings.append(f"Limite de {MAX_ROWS} lançamentos atingido; o restante foi ignorado.")
            break
        block = m[1]
        try:
            when, amount = _ofx_date(_tag(block, "DTPOSTED")), parse_amount(_tag(block, "TRNAMT"))
        except (ValueError, ArithmeticError):
            doc.warnings.append(f"STMTTRN {n} ignorado: data ou valor inválido.")
            continue
        name, memo = _tag(block, "NAME"), _tag(block, "MEMO")
        description = " - ".join(x for x in dict.fromkeys((name, memo)) if x)
        doc.items.append(_item(when, amount, description, currency=doc.currency, counterparty=_clean(name, 120),
                               external_id=_strip(_tag(block, "FITID"), 100), line_ref=f"STMTTRN {n}",
                               pending=_tag(block, "TRNTYPE").upper() == "HOLD"))
    if not doc.items and not doc.balances:
        doc.warnings.append("Nenhum lançamento encontrado no OFX.")
    return _cap_warnings(doc)


# --- texto de PDF/OCR --------------------------------------------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"(?<![\w,.])\(?[-+]?\s?(?:R\$\s?)?[-+]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}\)?(?:\s?[DC](?![A-Za-z])|-(?!\w))?",
    re.I,
)
_BANKS = {"nubank": "Nubank", "itau": "Itaú", "bradesco": "Bradesco", "santander": "Santander",
          "banco do brasil": "Banco do Brasil", "caixa economica": "Caixa", "banco inter": "Banco Inter",
          "c6 bank": "C6 Bank", "btg": "BTG Pactual", "sicoob": "Sicoob", "sicredi": "Sicredi",
          "mercado pago": "Mercado Pago", "picpay": "PicPay", "pagbank": "PagBank"}
# Rótulos só valem no início da linha: "transfira o valor de R$ 10.000" no meio de uma frase não é campo.
_L_AMOUNT = (re.compile(r"\s*valor (?:pago|total|transferido|enviado|recebido|do pix|da transferencia)\b"),
             re.compile(r"\s*valor\b"))
_L_DATE = (re.compile(r"\s*(?:pago em|realizad[oa] em|efetuad[oa] em|agendad[oa] para|data d[oa] (?:pagamento|"
                      r"transferencia|transacao|pix))\b"),
           re.compile(r"\s*data\b"))
_L_TO = re.compile(r"\s*(?:destinatario|favorecido|recebedor|beneficiario|estabelecimento|destino|para)\b")
_L_FROM = re.compile(r"\s*(?:pagador|remetente|origem|de)\b")
_L_NAME = re.compile(r"\s*nome\b")
_L_ID = re.compile(r"\s*(?:id da transacao|id de transacao|id/transacao|identificador|codigo de autenticacao|"
                   r"autenticacao|end to end|end-to-end|e2e|codigo da transacao|codigo|id)\b")
_NEG_STRONG = re.compile(r"pix enviado|transferencia enviada|transferencia realizada|pix realizado|"
                         r"pagamento (?:efetuado|realizado)|voce (?:pagou|enviou|transferiu)")
_NEG_WEAK = re.compile(r"comprovante de (?:pagamento|transferencia)")
_POS = re.compile(r"recebid[oa]|comprovante de recebimento|voce recebeu")


def _detect_type(ftext: str) -> str:
    """O tipo cuja palavra-chave aparece primeiro: documentos se nomeiam no cabeçalho."""
    found = []
    for kind, rx in (("comprovante", r"comprovante"), ("recibo", r"\brecibo\b"), ("extrato", r"\bextrato\b"),
                     ("fatura_cartao", r"\bfatura\b")):
        m = re.search(rx, ftext)
        if m and (kind != "fatura_cartao" or re.search(r"vencimento|cartao", ftext)):
            found.append((m.start(), kind))
    return min(found)[1] if found else "desconhecido"


def _label_value(lines: list[str], flines: list[str], labels) -> str:
    """Valor depois do rótulo, na mesma linha ou na próxima linha não vazia."""
    for rx in labels if isinstance(labels, tuple) else (labels,):
        for i, fl in enumerate(flines):
            m = rx.match(fl)
            if not m:
                continue
            value = lines[i][m.end():].strip(" :-\t")
            if not value:
                value = next((x for x in lines[i + 1:i + 3] if x), "")
            if value:
                return value
    return ""


def _parse_receipt(doc: ParsedDocument, lines: list[str], flines: list[str], refs: list[str]) -> None:
    ftext = "\n".join(flines)
    value = _label_value(lines, flines, _L_AMOUNT)
    m = _AMOUNT_RE.search(value)
    if not m and doc.doc_type == "recibo":  # "Recebi de ... a quantia de R$ 500,00"
        m = re.search(r"(?:quantia|importancia) de\s*", ftext)
        m = m and _AMOUNT_RE.match("\n".join(lines), m.end())
    if not m:
        doc.warnings.append("Não encontrei um campo de valor rotulado (ex.: \"Valor: R$ 38,00\"); nada foi importado.")
        return
    amount = abs(parse_amount(m[0]))
    dm = _DATE_RE.search(_fold_line(_label_value(lines, flines, _L_DATE)))
    dm = dm if dm and not dm["sd"] else next((x for x in _DATE_RE.finditer(ftext) if not x["sd"]), None)
    try:
        when = _date_from_match(dm, None)[0] if dm else None
    except ValueError:
        when = None
    if not when or amount == 0:
        doc.warnings.append("Comprovante sem data ou valor válido; nada foi importado.")
        return

    pos, strong, weak = _POS.search(ftext), _NEG_STRONG.search(ftext), _NEG_WEAK.search(ftext)
    confidence = "media"
    if pos and not strong:
        sign, parties = 1, (_L_FROM, _L_TO)
    elif strong or weak:
        sign, parties = -1, (_L_TO, _L_FROM)
    else:
        sign, parties, confidence = -1, (_L_TO, _L_FROM), "baixa"
        doc.warnings.append("Não ficou claro se o dinheiro entrou ou saiu; registrado como saída, confira.")
    counterparty = ""
    for rx in (*parties, _L_NAME):
        counterparty = re.sub(r"(?i)^nome\s*:?\s*", "", _label_value(lines, flines, rx))
        if counterparty:
            break
    counterparty = _clean(counterparty, 120)
    title = next((x for x in lines if x), "")
    description = f"{title} - {counterparty}" if counterparty else title
    doc.items.append(_item(when, sign * amount, description, currency=doc.currency, counterparty=counterparty,
                           external_id=_strip(_label_value(lines, flines, _L_ID), 100),
                           pending=bool(re.search(r"agendad", ftext)), line_ref=refs[0] if refs else "",
                           confidence=confidence))


def _parse_statement(doc: ParsedDocument, lines: list[str], flines: list[str], refs: list[str]) -> None:
    ref = _reference_date("\n".join(lines))
    accrual = None
    if doc.doc_type == "fatura_cartao":
        due = next((m for fl in flines if "vencimento" in fl for m in _DATE_RE.finditer(fl) if not m["sd"]), None)
        accrual = _date_from_match(due, None)[0] if due else None
    inferred_any = False
    for line, fl, where in zip(lines, flines, refs):
        dm = _DATE_RE.match(fl)
        if not dm or not line[dm.end():dm.end() + 1].isspace():
            continue
        rest = line[dm.end():]
        am = _AMOUNT_RE.search(rest)
        if not am:
            continue
        description = rest[:am.start()].strip()
        second = _DATE_RE.match(_fold_line(description))  # data de lançamento + data do valor
        description = description[second.end():].strip() if second else description
        if not description or fold(description).startswith(_SKIP_ROW):
            continue
        try:
            when, inferred = _date_from_match(dm, ref)
            amount = parse_amount(am[0])
        except (ValueError, ArithmeticError):
            doc.warnings.append(f"{where.capitalize()} ignorada: data ou valor inválido.")
            continue
        inferred_any |= inferred
        if _is_balance(description):
            doc.balances.append(Balance(date=when, amount=amount, currency=doc.currency, line_ref=where))
            continue
        # Na fatura, compra vem sem sinal e crédito com "-"; só D/C explícito dispensa a inversão.
        if doc.doc_type == "fatura_cartao" and am[0].strip()[-1:].upper() not in ("D", "C"):
            amount = -amount
        doc.items.append(_item(when, amount, description, currency=doc.currency, accrual_date=accrual,
                               line_ref=where, confidence="media"))
    if inferred_any:
        doc.warnings.append(_inferred_warning(ref))


def parse_text(text: str, source_format: str) -> ParsedDocument:
    doc = ParsedDocument(doc_type="desconhecido", source_format=source_format)
    text = unicodedata.normalize("NFC", text or "")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        doc.warnings.append("Texto grande demais; só o início foi lido.")
    pages = text.split("\f")
    lines, refs = [], []
    for p, page in enumerate(pages, 1):
        for n, raw in enumerate(page.splitlines(), 1):
            lines.append(_strip(raw, 2000))
            refs.append(f"página {p}, linha {n}" if len(pages) > 1 else f"linha {n}")
    flines = [_fold_line(x) for x in lines]
    ftext = "\n".join(flines)
    doc.doc_type = _detect_type(ftext)
    if doc.doc_type == "desconhecido":
        doc.warnings.append("Não reconheci o documento (extrato, fatura, comprovante ou recibo); nada foi importado.")
        return doc
    header = " ".join(flines[:5])
    doc.institution = next((name for key, name in _BANKS.items() if re.search(rf"\b{key}\b", header)), "")
    if doc.doc_type in ("comprovante", "recibo"):
        _parse_receipt(doc, lines, flines, refs)
    else:
        acc = re.search(r"\b(?:conta|cartao|final)\b[^\d\n]{0,20}(\d[\d .\-*x]{2,30})", ftext)
        doc.account = _last4(acc[1]) if acc and len(_last4(acc[1])) == 4 else ""
        _parse_statement(doc, lines, flines, refs)
        if not doc.items and not doc.balances:
            doc.warnings.append("Nenhum lançamento reconhecido (linhas com data, descrição e valor).")
    return _cap_warnings(doc)


# --- entrada -----------------------------------------------------------------------------------------------------

def pdf_text(data: bytes, *, max_pages: int = 30) -> str:
    """Só extrai texto (páginas separadas por \\f); nada é renderizado nem executado."""
    try:
        from pypdf import PdfReader  # dependência opcional (extra 'documents')
    except ImportError:
        msg = "Leitura de PDF indisponível nesta instalação (instale o extra 'documents')."
        raise UnsupportedDocument(msg) from None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UnsupportedDocument("PDF protegido por senha não é suportado.")
        if len(reader.pages) > max_pages:
            raise UnsupportedDocument(f"PDF com mais de {max_pages} páginas não é suportado.")
        return "\f".join(page.extract_text() or "" for page in reader.pages)
    except UnsupportedDocument:
        raise
    except Exception:  # PDF malformado pode estourar qualquer exceção do leitor
        raise UnsupportedDocument("Não foi possível ler o PDF.") from None


def parse(data: bytes, filename: str = "", *, ocr=None) -> ParsedDocument:
    if len(data) > MAX_BYTES:
        raise UnsupportedDocument("Arquivo grande demais (máximo 10 MB).")
    kind = sniff(data, filename)
    if kind == "csv":
        return parse_csv(data)
    if kind == "ofx":
        return parse_ofx(data)
    if kind == "pdf":
        return parse_text(pdf_text(data), "pdf")
    if ocr is None:
        raise UnsupportedDocument("Imagem sem OCR disponível nesta instalação; envie o PDF, OFX ou CSV.")
    text = ocr(data)
    if not isinstance(text, str):
        raise UnsupportedDocument("O OCR não devolveu texto.")
    return parse_text(text, "imagem")
