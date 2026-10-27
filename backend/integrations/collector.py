"""Coletor de dados externos: único lugar do backend que busca dados públicos na internet.

Roda como serviço próprio (deploy/systemd/lastro-coletor.service), fora do web app (que não tem rede) e fora
do worker dos agentes (que nunca escolhe o que buscar). Respeita as fontes: APIs públicas oficiais, poucas
requisições (a cada 6 h por padrão), sem scraping. O FRED exige chave própria (FRED_API_KEY); sem ela, as
séries do FRED ficam "indisponível" — nunca inventadas.

Uso: python -m integrations.collector [--loop]
"""

import argparse
import asyncio
import logging
import os
from datetime import date, datetime
from pathlib import Path

import httpx

from app import db

from .catalog import SERIES, Series, clean_value

log = logging.getLogger("lastro.coletor")
TIMEOUT = httpx.Timeout(20.0)
MAX_BYTES = 512 * 1024
INTERVAL_SECONDS = 6 * 3600
USER_AGENT = "Lastro/0.3 (coletor de series publicas; uso pessoal)"  # cabeçalho HTTP: só ASCII


def _parse_bcb(payload) -> list[tuple[str, str]]:
    rows = []
    for item in payload[-24:]:
        day, month, year = str(item["data"]).split("/")
        rows.append((date(int(year), int(month), int(day)).isoformat(), clean_value(item["valor"])))
    return rows


def _parse_fred(payload) -> list[tuple[str, str]]:
    return [(date.fromisoformat(o["date"]).isoformat(), clean_value(o["value"]))
            for o in payload.get("observations", []) if o.get("value") not in (".", "", None)]


def request_for(series: Series) -> tuple[str, dict] | None:
    if series.source == "bcb_sgs":
        return f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series.code}/dados/ultimos/12", {"formato": "json"}
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
    payload = response.json()
    return _parse_bcb(payload) if series.source == "bcb_sgs" else _parse_fred(payload)


def store_rows(conn, series: Series, rows: list[tuple[str, str]], error: str | None) -> None:
    now = db.utcnow()
    for reference_date, value in rows:
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
        if not args.loop:
            return
        await asyncio.sleep(int(os.environ.get("LASTRO_COLLECT_INTERVAL", INTERVAL_SECONDS)))


if __name__ == "__main__":
    asyncio.run(main())
