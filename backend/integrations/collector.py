# SPDX-License-Identifier: AGPL-3.0-or-later
"""Coletor de dados externos: único lugar do backend que busca dados públicos na internet.

Roda como serviço próprio (deploy/systemd/lastro-coletor.service), fora do web app (que não tem rede) e fora
do worker dos agentes (que nunca escolhe o que buscar). Respeita as fontes: APIs públicas oficiais e arquivos de
dados abertos, poucas requisições (a cada 6 h por padrão; o arquivo do Tesouro, no máximo uma vez a cada 20 h e só
se mudou), sem scraping. O FRED exige chave própria (FRED_API_KEY); sem ela, as séries do FRED ficam
"indisponível" — nunca inventadas. Limite do fornecedor (HTTP 429) é respeitado: a próxima tentativa espera.

Cada valor vai para `market_data` (último valor, para os agentes) e para `market_observations` (histórico com
revisões, para o Radar e o Diário de Oportunidades).

Uso: python -m integrations.collector [--loop]
"""

import argparse
import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from app import db
from radar import observations

from .catalog import SERIES, Series, clean_value

log = logging.getLogger("lastro.coletor")
TIMEOUT = httpx.Timeout(20.0)
MAX_BYTES = 512 * 1024
INTERVAL_SECONDS = 6 * 3600
USER_AGENT = "Lastro/0.4 (coletor de series publicas; uso pessoal)"  # cabeçalho HTTP: só ASCII

# Tesouro Transparente (dados abertos): preços e taxas diários de todos os títulos do Tesouro Direto (~15 MB).
TESOURO_URL = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/"
               "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv")
TESOURO_PAGE = "https://www.tesourotransparente.gov.br/ckan/dataset/taxas-dos-titulos-ofertados-pelo-tesouro-direto"
TESOURO_MAX_BYTES = 40 * 1024 * 1024
TESOURO_INTERVAL = timedelta(hours=20)
TESOURO_KEEP_DAYS = 400
# Rótulos e códigos vêm daqui, nunca do arquivo: tipo desconhecido é descartado (texto de terceiros fora do prompt).
TESOURO_TYPES = {
    "Tesouro Selic": "selic", "Tesouro Prefixado": "pre", "Tesouro Prefixado com Juros Semestrais": "pre_js",
    "Tesouro IPCA+": "ipca", "Tesouro IPCA+ com Juros Semestrais": "ipca_js",
    "Tesouro IGPM+ com Juros Semestrais": "igpm_js", "Tesouro Educa+": "educa",
    "Tesouro Renda+ Aposentadoria Extra": "renda",
}
TESOURO_LABELS = {v: k for k, v in TESOURO_TYPES.items()}
# Colunas do arquivo → métrica. "Compra" é a taxa/preço de quem aplica; "venda" é o que o Tesouro paga na recompra
# antes do vencimento (marcação a mercado).
TESOURO_METRICS = (("taxa_compra", 3, "% a.a."), ("taxa_venda", 4, "% a.a."), ("pu_compra", 5, "R$"),
                   ("pu_venda", 6, "R$"))
TESOURO_HEADER = "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha"
_BR_DECIMAL = re.compile(r"^-?\d{1,9}(,\d{1,8})?$")


def _parse_bcb(payload) -> list[tuple[str, str]]:
    rows = []
    for item in payload[-600:]:
        day, month, year = str(item["data"]).split("/")
        rows.append((date(int(year), int(month), int(day)).isoformat(), clean_value(item["valor"])))
    return rows


def _parse_fred(payload) -> list[tuple[str, str]]:
    return [(date.fromisoformat(o["date"]).isoformat(), clean_value(o["value"]))
            for o in payload.get("observations", []) if o.get("value") not in (".", "", None)]


def _parse_sidra(payload) -> list[tuple[str, str]]:
    """SIDRA: a primeira linha é o cabeçalho; período em D3C (AAAAMM). '...', '-' e 'X' (sem dado) são ignorados."""
    rows = []
    for item in payload[1:]:
        period, value = str(item["D3C"]), str(item["V"]).strip()
        if value in ("...", "..", "-", "X", ""):
            continue
        if not re.fullmatch(r"\d{6}", period):
            raise ValueError("período inválido")
        rows.append((date(int(period[:4]), int(period[4:]), 1).isoformat(), clean_value(value)))
    return rows


PARSERS = {"bcb_sgs": _parse_bcb, "fred": _parse_fred, "ibge_sidra": _parse_sidra}


def request_for(series: Series) -> tuple[str, dict] | None:
    if series.source == "bcb_sgs" and series.history_days:
        # "ultimos/N" aceita no máximo 20 valores: histórico longo vai por intervalo de datas.
        start = date.today() - timedelta(days=series.history_days)
        return f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series.code}/dados", {
            "formato": "json", "dataInicial": start.strftime("%d/%m/%Y"), "dataFinal": date.today().strftime("%d/%m/%Y")}
    if series.source == "bcb_sgs":
        return f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series.code}/dados/ultimos/12", {"formato": "json"}
    if series.source == "ibge_sidra":
        table, variable = series.code.split("/")
        return f"https://apisidra.ibge.gov.br/values/t/{table}/n1/all/v/{variable}/p/last%2012", {}
    if series.source == "fred":
        key = os.environ.get("FRED_API_KEY")
        if not key:
            return None
        return "https://api.stlouisfed.org/fred/series/observations", {
            "series_id": series.code, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": "12"}
    return None


async def fetch_series(client: httpx.AsyncClient, series: Series) -> list[tuple[str, str]]:
    req = request_for(series)
    if req is None:
        raise RuntimeError("fonte não configurada (chave de API ausente)")
    url, params = req
    response = await client.get(url, params=params)
    response.raise_for_status()
    if len(response.content) > MAX_BYTES:
        raise RuntimeError("resposta grande demais")
    return PARSERS[series.source](response.json())


def ensure_catalog_series(conn, series: Series, now: str) -> None:
    observations.ensure_series(conn, series.id, source=series.source, label=series.label, unit=series.unit,
                               frequency=series.frequency, category="macro", max_age_days=series.max_age_days,
                               currency="BRL" if series.unit.startswith("R$") else None, url=series.url, now=now)


def store_rows(conn, series: Series, rows: list[tuple[str, str]], error: str | None) -> None:
    now = db.utcnow()
    ensure_catalog_series(conn, series, now)
    for reference_date, value in rows:
        observations.record(conn, series.id, reference_date, value, fetched_at=now)
        conn.execute("INSERT INTO market_data (source, series_id, reference_date, value, unit, label, fetched_at) "
                     "VALUES (?,?,?,?,?,?,?) ON CONFLICT(source, series_id, reference_date) DO UPDATE SET "
                     "value = excluded.value, fetched_at = excluded.fetched_at",
                     (series.source, series.id, reference_date, value, series.unit, series.label, now))
    conn.execute("INSERT INTO market_fetch_status (source, series_id, checked_at, ok, error) VALUES (?,?,?,?,?) "
                 "ON CONFLICT(source, series_id) DO UPDATE SET checked_at = excluded.checked_at, ok = excluded.ok, "
                 "error = excluded.error", (series.source, series.id, now, 0 if error else 1, error))


async def collect_once(conn, fetch=fetch_series) -> dict:
    """Busca todas as séries; uma fonte fora do ar não impede as outras e mantém o último valor bom no cache."""
    results = {}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as client:
        for series in SERIES.values():
            try:
                rows = await fetch(client, series)
                store_rows(conn, series, rows, None)
                results[series.id] = f"ok ({len(rows)})"
            except Exception as exc:  # noqa: BLE001 — indisponibilidade vira estado, não derruba o coletor
                store_rows(conn, series, [], f"{type(exc).__name__}: {str(exc)[:160]}")
                results[series.id] = f"erro: {type(exc).__name__}"
    return results


# ---------- Tesouro Direto (arquivo de dados abertos) ----------

def _br(text: str) -> str:
    text = text.strip()
    if not _BR_DECIMAL.match(text):
        raise ValueError("número inválido")
    return clean_value(text.replace(",", "."))


def _br_date(text: str) -> str:
    day, month, year = text.strip().split("/")
    return date(int(year), int(month), int(day)).isoformat()


def parse_tesouro(lines, *, since: str) -> tuple[list[tuple], int]:
    """Linhas do CSV → [(tipo, vencimento, data_base, {métrica: valor})] a partir de `since`, e quantas linhas foram
    descartadas (tipo desconhecido ou valor inválido). Cabeçalho diferente do esperado para tudo."""
    rows, rejected = [], 0
    it = iter(lines)
    header = next(it, "").lstrip("﻿").strip()
    if not header.startswith(TESOURO_HEADER):
        raise ValueError("cabeçalho do arquivo do Tesouro mudou: revise o conector antes de confiar nos dados")
    for line in it:
        parts = line.rstrip("\r\n").split(";")
        if len(parts) < 7:
            continue
        try:
            base = _br_date(parts[2])
            if base < since:
                continue
            kind = TESOURO_TYPES.get(parts[0].strip())
            if kind is None:
                raise ValueError("tipo desconhecido")
            values = {name: _br(parts[col]) for name, col, _unit in TESOURO_METRICS if parts[col].strip()}
            rows.append((kind, _br_date(parts[1]), base, values))
        except (ValueError, IndexError):
            rejected += 1
    return rows, rejected


def tesouro_series_id(kind: str, maturity: str, metric: str) -> str:
    return f"td_{kind}_{maturity}_{metric}"


def store_tesouro(conn, rows: list[tuple]) -> dict:
    now = db.utcnow()
    counts = {"nova": 0, "revisao": 0, "igual": 0}
    seen = set()
    conn.execute("BEGIN")
    try:
        for kind, maturity, base, values in sorted(rows, key=lambda r: r[2]):
            for metric, _col, unit in TESOURO_METRICS:
                if metric not in values:
                    continue
                sid = tesouro_series_id(kind, maturity, metric)
                if sid not in seen:
                    seen.add(sid)
                    observations.ensure_series(
                        conn, sid, source="tesouro_direto", label=f"{TESOURO_LABELS[kind]} {maturity[:4]}",
                        unit=unit, frequency="diaria", category="renda_fixa", max_age_days=7,
                        currency="BRL" if unit == "R$" else None, url=TESOURO_PAGE,
                        meta={"tipo": kind, "vencimento": maturity, "metrica": metric}, now=now)
                counts[observations.record(conn, sid, base, values[metric], fetched_at=now)] += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return counts


def _set_source_status(conn, source: str, *, ok: bool, error: str | None, next_at: datetime,
                       modified: str | None = None) -> None:
    conn.execute("INSERT INTO market_source_status (source, checked_at, ok, error, next_at, modified) "
                 "VALUES (?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET checked_at = excluded.checked_at, "
                 "ok = excluded.ok, error = excluded.error, next_at = excluded.next_at, "
                 "modified = COALESCE(excluded.modified, modified)",
                 (source, db.utcnow(), 1 if ok else 0, error, next_at.isoformat(timespec="seconds"), modified))


def _retry_after(value: str | None) -> int:
    return int(value) if value and value.isdigit() else 900


async def collect_tesouro(conn, client: httpx.AsyncClient, *, now: datetime | None = None) -> str:
    """Arquivo do Tesouro: no máximo uma vez a cada 20 h, condicional (If-Modified-Since), 429 respeitado."""
    now = now or datetime.now(timezone.utc)
    status = conn.execute("SELECT * FROM market_source_status WHERE source = 'tesouro_direto'").fetchone()
    if status and status["next_at"] and datetime.fromisoformat(status["next_at"]) > now:
        return "aguardando o próximo horário"
    headers = {"If-Modified-Since": status["modified"]} if status and status["modified"] else {}
    try:
        async with client.stream("GET", TESOURO_URL, headers=headers) as response:
            if response.status_code == 304:
                _set_source_status(conn, "tesouro_direto", ok=True, error=None, next_at=now + TESOURO_INTERVAL)
                return "sem mudança"
            if response.status_code == 429:
                wait = max(_retry_after(response.headers.get("retry-after")), 60) * 4
                _set_source_status(conn, "tesouro_direto", ok=False, error="limite de requisições do fornecedor (429)",
                                   next_at=now + timedelta(seconds=wait))
                return "erro: limite do fornecedor"
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > TESOURO_MAX_BYTES:
                    raise RuntimeError("arquivo grande demais")
                chunks.append(chunk)
            modified = response.headers.get("last-modified")
        since = (now.date() - timedelta(days=TESOURO_KEEP_DAYS)).isoformat()
        rows, rejected = parse_tesouro(b"".join(chunks).decode("latin-1").splitlines(), since=since)
        counts = store_tesouro(conn, rows)
        _set_source_status(conn, "tesouro_direto", ok=True, error=None, next_at=now + TESOURO_INTERVAL,
                           modified=modified if modified and modified.isascii() and len(modified) < 64 else None)
        return f"ok ({counts['nova']} novas, {counts['revisao']} revisões, {rejected} descartadas)"
    except Exception as exc:  # noqa: BLE001 — indisponibilidade vira estado, não derruba o coletor
        _set_source_status(conn, "tesouro_direto", ok=False, error=f"{type(exc).__name__}: {str(exc)[:160]}",
                           next_at=now + timedelta(hours=1))
        return f"erro: {type(exc).__name__}"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):  # a URL do FRED leva a chave na query: fora do log
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="lastro-coletor")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    conn = db.connect(Path(os.environ.get("LASTRO_DB", "/var/lib/patrimonio/lastro.db")))
    db.migrate(conn)
    while True:
        log.info("coleta %s: %s", datetime.now().isoformat(timespec="seconds"), await collect_once(conn))
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), headers={"User-Agent": USER_AGENT},
                                     follow_redirects=False) as client:
            log.info("tesouro: %s", await collect_tesouro(conn, client))
        if not args.loop:
            return
        await asyncio.sleep(int(os.environ.get("LASTRO_COLLECT_INTERVAL", INTERVAL_SECONDS)))


if __name__ == "__main__":
    asyncio.run(main())
