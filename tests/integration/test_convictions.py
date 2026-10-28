# SPDX-License-Identifier: AGPL-3.0-or-later
"""Convicções: previsões que os agentes declaram no Conselho, guardadas como foram ditas, conferidas pelos dados
coletados (ou pela pessoa, quando não há condição verificável) e medidas com Brier e calibração."""
import asyncio
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from app import convictions, db, store
from app.orchestrator import Orchestrator
from crypto.assets import ASSETS
from integrations.catalog import SERIES
from mentor.session import PROMPTS

from .test_team import SNAP, FakeRuntime, done, drain

TODAY = date(2026, 10, 27)
PARECER = """**Posição:** contrária

## Tese
A reserva precisa vir antes.

## Evidências
Reserva do retrato de 2026-10-20.

## Fontes
Retrato da pessoa.

## Hipóteses
A renda segue estável.

## Riscos
Perda de liquidez.

## Lacunas
Horizonte não informado.

## Não agir
Manter a reserva é razoável.

## Previsões
- 70% · 2027-03-31 · selic_meta < 10.5 · A meta da Selic estará abaixo de 10,5% ao ano.
- 40% · 2027-01-31 · cripto:BTC > 150000 · O bitcoin estará acima de 150 mil USDT.
- 60% · 2027-06-30 · — · A pessoa terá recomposto 6 meses de reserva.
- 100% · 2027-01-01 · — · Certeza absoluta não é previsão.
- 50% · 2026-10-01 · — · Data no passado não vale.
- 55% · 2027-02-01 · poupanca_magica > 1 · Série que não existe no catálogo.
"""


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "lastro.db")
    db.migrate(connection)
    store.create_snapshot(connection, SNAP)
    yield connection
    connection.close()


def message(conn, text="x", agent="riscos"):
    conv = store.create_conversation(conn, "Conselho", kind="panel", channel="council")
    return store.add_message(conn, conv["id"], "assistant", text, agent_id=agent, kind="analysis")


def market(conn, series, ref, value):
    conn.execute("INSERT INTO market_data (source, series_id, reference_date, value, unit, label, fetched_at) "
                 "VALUES ('bcb_sgs', ?, ?, ?, '% a.a.', 'x', '2027-01-01T00:00:00Z')", (series, ref, value))


def test_parse_keeps_only_well_formed_lines():
    found, refused = convictions.parse(PARECER, TODAY)
    assert [(str(p["probability"]), p["due_on"]) for p in found] == [("0.70", "2027-03-31"), ("0.40", "2027-01-31"),
                                                                       ("0.60", "2027-06-30")]
    assert found[0]["check"] == {"kind": "serie", "series_id": "selic_meta", "op": "<", "value": "10.5"}
    assert found[1]["check"] == {"kind": "cripto", "symbol": "BTC", "op": ">", "value": "150000"}
    assert found[2]["check"] is None
    assert len(refused) == 3 and any("1–99%" in r for r in refused) and any("catálogo" in r for r in refused)


def test_council_records_predictions_once_and_audit_ignores_their_numbers(conn):
    conv = store.create_conversation(conn, "Conselho", kind="panel", channel="council")
    rt = FakeRuntime(lambda r, m, p, n: done(PARECER if m == "conselho_parecer" else "Fala."))
    o = Orchestrator(conn, rt.stream, today=lambda: TODAY, semantic_audit="off")
    o.submit(store.get_conversation(conn, conv["id"]), "/rapida Devo usar a reserva em bitcoin?")
    asyncio.run(drain(o))
    rows = convictions.listing(conn, store.OWNER)
    agents = {r["agent_id"] for r in rows}
    assert rows and len(rows) == 3 * len(agents) and "mentor" not in agents  # só quem deu parecer
    parecer = next(m for m in store.list_messages(conn, conv["id"]) if m["agent_id"] in agents)
    assert not any("70" in r or "150000" in r for r in (parecer["audit"] or {}).get("reasons", []))
    convictions.record(conn, user_id=store.OWNER, agent_id=parecer["agent_id"], message=parecer, today=TODAY)
    assert len(convictions.listing(conn, store.OWNER)) == len(rows)  # idempotente


def test_what_was_said_never_changes(conn):
    convictions.record(conn, user_id=store.OWNER, agent_id="riscos", message=message(conn, PARECER), today=TODAY)
    pid = convictions.listing(conn, store.OWNER)[0]["id"]
    for column, value in (("probability", "0.9"), ("due_on", "2030-01-01"), ("statement", "outra coisa")):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE predictions SET {column} = ? WHERE id = ?", (value, pid))


def test_data_resolves_after_the_source_publishes_past_the_date(conn):
    convictions.record(conn, user_id=store.OWNER, agent_id="economista", message=message(conn, PARECER), today=TODAY)
    market(conn, "selic_meta", "2027-03-25", "10.25")
    selic = lambda: next(r for r in convictions.listing(conn, store.OWNER) if r["check"] and r["check"].get("series_id"))  # noqa: E731
    convictions.resolve_due(conn, date(2027, 4, 1))
    assert selic()["status"] == "aberta"  # a fonte ainda não publicou nada depois da data: espera
    market(conn, "selic_meta", "2027-04-02", "10.25")
    convictions.resolve_due(conn, date(2027, 4, 3))
    selic = selic()
    assert selic["status"] == "aconteceu" and selic["resolved_by"] == "dados"
    assert selic["observed"]["reference_date"] == "2027-03-25" and selic["brier"] == str(Decimal("0.09"))
    with pytest.raises(sqlite3.IntegrityError):  # conferida uma vez, fica conferida
        conn.execute("UPDATE predictions SET status = 'nao_aconteceu' WHERE id = ?", (selic["id"],))


def test_crypto_is_checked_on_the_usdt_quote_and_missing_data_becomes_indeterminate(conn):
    convictions.record(conn, user_id=store.OWNER, agent_id="cripto", message=message(conn, PARECER, "cripto"), today=TODAY)
    for t, price in (("2027-01-31T20:00:00Z", "98000"), ("2027-02-01T10:00:00Z", "99000")):
        conn.execute("INSERT INTO crypto_quotes (source, symbol, stable_id, quote_currency, price, reference_time, "
                     "fetched_at, status) VALUES ('binance', 'BTC', 'bitcoin', 'USDT', ?, ?, ?, 'ok')", (price, t, t))
    convictions.resolve_due(conn, date(2027, 2, 2))
    btc = next(r for r in convictions.listing(conn, store.OWNER) if r["check"] and r["check"]["kind"] == "cripto")
    assert btc["status"] == "nao_aconteceu" and btc["observed"]["value"] == "98000"
    convictions.resolve_due(conn, date(2027, 6, 1))  # selic sem nenhum dado, 45 dias depois da data
    selic = next(r for r in convictions.listing(conn, store.OWNER) if r["check"] and r["check"]["kind"] == "serie")
    assert selic["status"] == "indeterminada" and selic["brier"] is None


def test_person_resolves_only_manual_ones_after_the_date(conn):
    convictions.record(conn, user_id=store.OWNER, agent_id="planejador", message=message(conn, PARECER), today=TODAY)
    rows = convictions.listing(conn, store.OWNER)
    manual = next(r for r in rows if r["check"] is None)
    auto = next(r for r in rows if r["check"])
    with pytest.raises(ValueError, match="data combinada"):
        convictions.resolve_manual(conn, store.OWNER, manual["id"], "aconteceu", "", TODAY)
    with pytest.raises(ValueError, match="dados da fonte"):
        convictions.resolve_manual(conn, store.OWNER, auto["id"], "aconteceu", "", date(2027, 5, 1))
    with pytest.raises(LookupError):
        convictions.resolve_manual(conn, "outra-conta", manual["id"], "aconteceu", "", date(2027, 7, 1))
    done_ = convictions.resolve_manual(conn, store.OWNER, manual["id"], "aconteceu", "Reserva recomposta.", date(2027, 7, 1))
    assert done_["status"] == "aconteceu" and done_["resolved_by"] == "pessoa"
    assert convictions.resolve_manual(conn, store.OWNER, auto["id"], "anulada", "", TODAY)["status"] == "anulada"


def test_brier_calibration_and_track_record_reach_the_agent(conn):
    rows = [{"agent_id": "riscos", "probability": p, "status": s} for p, s in (
        ("0.9", "aconteceu"), ("0.8", "aconteceu"), ("0.7", "nao_aconteceu"), ("0.2", "nao_aconteceu"),
        ("0.3", "aconteceu"), ("0.5", "aberta"), ("0.6", "indeterminada"))]
    s = convictions.stats(rows)
    # (0.01 + 0.04 + 0.49 + 0.04 + 0.49) / 5
    assert s["resolved"] == 5 and s["open"] == 1 and s["indeterminate"] == 1 and s["brier"] == "0.214"
    assert s["hits"] == 3 and s["small_sample"] is True
    assert [(b["from"], b["n"]) for b in s["buckets"]] == [(20, 2), (60, 1), (80, 2)]

    msg = message(conn, "- 80% · 2026-11-30 · — · A pessoa manterá os aportes em novembro.", "riscos")
    convictions.record(conn, user_id=store.OWNER, agent_id="riscos", message=msg, today=TODAY)
    pid = convictions.listing(conn, store.OWNER)[0]["id"]
    assert convictions.track_line(conn, store.OWNER, "riscos") is None  # nada conferido ainda
    convictions.resolve_manual(conn, store.OWNER, pid, "nao_aconteceu", "", date(2026, 12, 1))
    line = convictions.track_line(conn, store.OWNER, "riscos")
    assert "1 conferida(s), Brier 0.64" in line and "Amostra pequena" in line

    conv = store.create_conversation(conn, "Rui", channel="direct", agent_id="riscos")
    rt = FakeRuntime()
    o = Orchestrator(conn, rt.stream, today=lambda: TODAY, semantic_audit="off")
    o.submit(store.get_conversation(conn, conv["id"]), "Oi, Rui")
    asyncio.run(drain(o))
    assert "Seu histórico de previsões: 1 conferida(s)" in rt.prompt_for("riscos")
    assert convictions.by_agent(conn, store.OWNER)["riscos"]["brier"] == "0.64"


def test_prompts_list_exactly_what_the_lastro_can_check():
    """A lista de condições verificáveis é texto fixo nos prompts: não pode ficar para trás do catálogo."""
    for mode in ("conselho_parecer", "conselho_debate"):
        text = (PROMPTS / "modos" / f"{mode}.md").read_text(encoding="utf-8")
        assert "## Previsões" in text
        assert all(f"{s.id} em {s.unit}" in text for s in SERIES.values())
        assert all(f"cripto:{a.symbol}" in text for a in ASSETS.values() if a.binance_symbol)
        found, _ = convictions.parse(text, TODAY)  # o exemplo do prompt é uma linha válida
        assert len(found) == 1
