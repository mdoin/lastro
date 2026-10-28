# SPDX-License-Identifier: AGPL-3.0-or-later
"""Monitor cripto: coleta → sinais → eventos → alerta ou reunião extraordinária → notificação (docs/CRYPTO.md).

Provedores e runtime do Conselho são simulados (respostas controladas); banco, regras, sinais, orquestrador e rotas
são os reais.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import auth, store
from app.web import Settings, create_app
from crypto import service
from crypto.models import Candle, CandleSeries, ChainInfo, Quote, TvlPoint
from crypto.sources import NotConfigured

from .test_team import SNAP, FakeRuntime, conn, done, drain, orch, structured  # noqa: F401

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)  # 12:00 em São Paulo: fora do horário de silêncio


def series(symbol: str, pair: str, *, drop: Decimal = Decimal("0"), spike: Decimal = Decimal("1"), hours: int = 220,
           base: Decimal = Decimal("100000"), end: datetime = NOW) -> CandleSeries:
    """Mercado calmo (oscilações pequenas e regulares) e, se pedido, uma última vela com queda e volume anormal."""
    candles, price = [], base
    for i in range(hours):
        open_time = end - timedelta(hours=hours - i)
        wiggle = Decimal("0.002") if i % 2 else Decimal("-0.0019")
        new = price * (1 + wiggle)
        volume = Decimal("10") + Decimal(i % 3)
        if i == hours - 1 and drop:
            new, volume = price * (1 - drop), volume * spike
        candles.append(Candle(open_time, open_time + timedelta(hours=1) - timedelta(milliseconds=1), price,
                              max(price, new), min(price, new), new.quantize(Decimal("0.01")), volume, volume * new))
        price = new
    return CandleSeries("binance", symbol, pair, "1h", "USDT", end, tuple(candles))


class FakeBinance:
    def __init__(self, drops=None, ref_lag=timedelta(0)):
        self.drops, self.ref_lag, self.calls = drops or {}, ref_lag, 0

    def health(self):
        return {"provider": "binance", "last_ok_at": NOW.isoformat()}

    def stats_24h(self, symbol):
        self.calls += 1
        pair = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "USDC": "USDCUSDT"}[symbol]
        price = Decimal("1.0001") if symbol == "USDC" else Decimal("91234.56789012")
        return Quote("binance", symbol, f"binance:{pair}", "USDT", price, NOW - self.ref_lag, NOW,
                     volume_24h=Decimal("1234.5"), quote_volume_24h=Decimal("112000000.10"),
                     change_24h_pct=Decimal("-7.9"))

    def klines(self, symbol, interval="1h", limit=400):
        pair = f"{symbol}USDT"
        drop, spike = self.drops.get(symbol, (Decimal("0"), Decimal("1")))
        return series(symbol, pair, drop=drop, spike=spike, end=NOW - self.ref_lag)


class FakeGecko:
    configured = False

    def health(self):
        return {"provider": "coingecko", "configured": False}

    def simple_price(self, *a, **k):
        raise NotConfigured("sem chave")


class FakeLlama:
    def health(self):
        return {"provider": "defillama"}

    def chains(self):
        return [ChainInfo("Ethereum", Decimal("46400000000"), "ETH", "ethereum")]

    def chain_tvl_history(self, chain=None):
        return [TvlPoint(NOW - timedelta(days=30 - d), Decimal("46000000000") + d) for d in range(30)]


def monitor(conn, o=None, **binance):
    return service.Monitor(conn, orchestrator=o, now=lambda: NOW, owner_id="teste",
                           providers={"binance": FakeBinance(**binance), "coingecko": FakeGecko(), "defillama": FakeLlama()})


CRASH = {"BTC": (Decimal("0.09"), Decimal("6"))}
OPT_IN = {"autonomous": True, "deliver": "analises", "quiet_start": "00:00", "quiet_end": "00:00"}


def notes(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM notifications ORDER BY created_at")]


# coleta, normalização e estado ----------------------------------------------------------------------------------------
def test_collection_normalizes_and_persists_with_exact_decimals(conn):
    m = monitor(conn)
    out = asyncio.run(m.tick())
    assert out["trabalhos"]["binance"]["ok"] and out["trabalhos"]["coingecko"]["erro"] == "não configurada (sem chave)"
    q = service.latest_quote(conn, "BTC", now=NOW)
    assert q.price == Decimal("91234.56789012") and q.quote_currency == "USDT" and q.status == "fresh"
    assert conn.execute("SELECT COUNT(*) FROM crypto_candles WHERE pair = 'BTCUSDT'").fetchone()[0] == 220
    assert service.tvl_points(conn, "chain", "Ethereum")[-1].tvl == Decimal("46000000029")
    calls = m.providers["binance"].calls
    asyncio.run(m.tick())  # nada vencido: não chama de novo
    assert m.providers["binance"].calls == calls
    jobs = {r["job"]: r for r in conn.execute("SELECT * FROM crypto_jobs")}
    assert jobs["binance"]["runs"] == 1 and jobs["binance"]["lease_owner"] is None
    # outro processo não pega o trabalho enquanto a trava de um está valendo (um só coletor)
    conn.execute("UPDATE crypto_jobs SET last_run_at = NULL, lease_owner = 'outro', lease_until = ? WHERE job = 'binance'",
                 ((NOW + timedelta(minutes=5)).isoformat(),))
    assert m._lease("binance", NOW, False) is False
    assert m._lease("binance", NOW + timedelta(minutes=11), False) is True  # trava expirada: retomada


# sinais → evento → decisão ----------------------------------------------------------------------------------------
def test_relevant_event_without_opt_in_is_pending_and_notified_but_no_meeting(conn):
    m = monitor(conn, orch(conn, FakeRuntime()), drops=CRASH)
    asyncio.run(m.tick())
    ev = conn.execute("SELECT * FROM crypto_events WHERE asset = 'BTC'").fetchone()
    assert ev["severity"] == "conselho" and ev["status"] == "pendente" and ev["run_id"] is None
    assert "reuniões autônomas desligadas" in ev["reason"]
    assert "compre" not in ev["hypothesis"].lower() and "oportunidade" not in ev["hypothesis"].lower()
    [n] = [n for n in notes(conn) if n["kind"] == "cripto_alerta"]
    assert n["ref"] == ev["id"] and "pendente" in n["body"]
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0  # nenhum modelo foi chamado


def test_autonomous_meeting_is_convened_once_and_receives_updates(conn):
    rt = FakeRuntime(lambda role, mode, prompt, n: done(
        structured("contrária", f"P-{role}") if mode == "conselho_parecer" else
        '{"falas": [], "encerrar": true}' if mode == "conselho_pauta" else
        "## Conclusão\nAcompanhar; não há fundamento para mudança imediata.\n\n## Divergências\nNenhuma relevante."
        if mode == "conselho_sintese" else "VEREDITO: PASSA\n- ok" if role == "auditor" else f"{role} ok"))
    o = orch(conn, rt)
    service.save_prefs(conn, store.OWNER, {**OPT_IN, "holdings": {"BTC": "5000"}})
    m = monitor(conn, o, drops=CRASH)
    asyncio.run(m.tick())
    ev = conn.execute("SELECT * FROM crypto_events WHERE asset = 'BTC'").fetchone()
    assert ev["status"] == "reuniao" and ev["run_id"] and ev["conversation_id"]
    run = store.get_run(conn, ev["run_id"])
    assert run["route"]["origin"]["kind"] == "crypto" and run["route"]["origin"]["event_id"] == ev["id"]
    assert run["route"]["lineup"][:3] == ["mentor", "cripto", "riscos"] and "planejador" in run["route"]["lineup"]
    context = store.get_message(conn, run["message_id"])
    assert context["agent_id"] == "lastro" and "observação, não recomendação" in context["content"]
    assert "BTC: R$ 5000" in context["content"]  # exposição informada vai para o Conselho; ausente, diria "não presuma"
    started = [n for n in notes(conn) if n["kind"] == "cripto_reuniao"]
    assert started and started[0]["link"] == f"/mentor/{ev['conversation_id']}" and "convocou" in started[0]["body"]

    # BTC continua caindo: o mesmo evento é atualizado, sem segunda reunião
    m.now = lambda: NOW + timedelta(hours=1)
    asyncio.run(m.tick(force=True))
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'council'").fetchone()[0] == 1
    assert conn.execute("SELECT updates FROM crypto_events WHERE id = ?", (ev["id"],)).fetchone()[0] >= 1
    updates = [x for x in store.list_messages(conn, ev["conversation_id"]) if "Atualização do Radar" in x["content"]]
    assert updates

    asyncio.run(drain(o))  # a reunião roda no Conselho deliberativo real
    record = json.loads(conn.execute("SELECT record_json FROM council_records WHERE run_id = ?", (ev["run_id"],)).fetchone()[0])
    assert record["origem"]["event_id"] == ev["id"] and "consumo" in record
    verdict = [n for n in notes(conn) if n["kind"] == "reuniao_concluida"]
    assert verdict and "Acompanhar" in verdict[0]["body"]


def test_limits_quiet_hours_stale_data_and_budget_block_meetings(conn):
    o = orch(conn, FakeRuntime())
    service.save_prefs(conn, store.OWNER, {**OPT_IN, "max_meetings_per_day": 1})
    m = monitor(conn, o, drops={**CRASH, "ETH": (Decimal("0.09"), Decimal("6"))})
    asyncio.run(m.tick())
    statuses = {r["asset"]: (r["status"], r["reason"]) for r in conn.execute("SELECT * FROM crypto_events")}
    assert sorted(s for s, _ in statuses.values()) == ["pendente", "reuniao"]  # o 2º evento esbarra no limite
    assert any("limite de 1" in r or "em andamento" in r for _, r in statuses.values())

    other = monitor(conn, o, drops=CRASH)
    service.save_prefs(conn, store.OWNER, {**OPT_IN, "quiet_start": "08:00", "quiet_end": "20:00"})
    row = other._event(conn.execute("SELECT id FROM crypto_events WHERE status = 'pendente'").fetchone()[0])
    assert "horário de silêncio" in other.blockers(row, service.prefs(conn, store.OWNER), NOW)

    service.save_prefs(conn, store.OWNER, {**OPT_IN, "monthly_token_budget": 10})
    conn.execute("INSERT INTO council_records (run_id, user_id, conversation_id, mode, topic, record_json, created_at) "
                 "VALUES ('x', ?, 'c', 'completo', 't', ?, ?)",
                 (store.OWNER, json.dumps({"origem": {"kind": "crypto"}, "consumo": {"tokens": 50}}), NOW.isoformat()))
    assert "orçamento mensal de IA atingido" in other.blockers(row, service.prefs(conn, store.OWNER), NOW)


def test_stale_or_quiet_market_never_convenes(conn):
    service.save_prefs(conn, store.OWNER, OPT_IN)
    m = monitor(conn, orch(conn, FakeRuntime()), drops=CRASH, ref_lag=timedelta(hours=3))  # dados de 3 h atrás
    asyncio.run(m.tick())
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert all(r["severity"] != "conselho" for r in conn.execute("SELECT * FROM crypto_events"))
    calm = monitor(conn, orch(conn, FakeRuntime()))
    conn.execute("DELETE FROM crypto_candles")
    conn.execute("UPDATE crypto_jobs SET last_run_at = NULL")
    asyncio.run(calm.tick())  # oscilação comum: nada de evento, nada de notificação
    assert conn.execute("SELECT COUNT(*) FROM crypto_events").fetchone()[0] == 0


# rotas, chave e isolamento ---------------------------------------------------------------------------------------------
@pytest.fixture
def web(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "lastro.db", mentor_socket=tmp_path / "none.sock",
                              cookie_secure=False, run_scheduler=False, run_orchestrator=False))
    with TestClient(app, base_url="http://lastro.test") as client:
        auth.set_password(app.state.conn, "uma senha longa e boa")
        client.post("/api/auth/login", json={"password": "uma senha longa e boa"}, headers={"X-Lastro": "1"})
        store.create_snapshot(app.state.conn, SNAP)
        app.state.crypto._providers = {"binance": FakeBinance(drops=CRASH), "coingecko": FakeGecko(),
                                       "defillama": FakeLlama()}
        app.state.crypto.now = lambda: NOW
        app.state.crypto.collect_in_web = True  # em produção quem coleta é o lastro-coletor (web sem internet)
        yield client, app


H = {"X-Lastro": "1"}


def test_routes_keep_the_coingecko_key_write_only(web, tmp_path):
    client, app = web
    fake_key = "CG-" + "teste" * 4  # montada em partes: o teste de higiene recusa segredos literais
    assert client.put("/api/crypto/coingecko-key", json={"key": fake_key}, headers=H).status_code == 204
    key_file = tmp_path / "coingecko.key"
    assert key_file.read_text() == fake_key
    if os.name == "posix":
        assert key_file.stat().st_mode & 0o077 == 0
    overview = client.get("/api/crypto/overview").text
    assert fake_key not in overview and '"configured":true' in overview.replace(" ", "")
    audit = " ".join(r[0] for r in app.state.conn.execute("SELECT resource FROM audit_log"))
    assert fake_key not in audit
    assert client.put("/api/crypto/coingecko-key", json={"key": "chave com espaço!"}, headers=H).status_code == 422
    assert client.delete("/api/crypto/coingecko-key", headers=H).status_code == 204 and not key_file.exists()


def test_routes_collect_overview_prefs_and_notifications(web):
    client, app = web
    out = client.post("/api/crypto/collect", headers=H).json()
    assert out["trabalhos"]["binance"]["ok"]
    ov = client.get("/api/crypto/overview").json()
    btc = next(a for a in ov["assets"] if a["symbol"] == "BTC")
    assert btc["quotes"][0]["currency"] == "USDT" and btc["series"] and btc["indicators"]["volatilidade"]["value"]
    assert any(e["asset"] == "BTC" and e["severity"] == "conselho" for e in ov["events"])
    assert "Data provided by CoinGecko" in ov["attribution"]
    assert client.put("/api/crypto/prefs", json={"watchlist": ["BTC", "XYZ"]}, headers=H).status_code == 422
    assert client.put("/api/crypto/prefs", json={"watchlist": ["../x"]}, headers=H).status_code == 422
    p = client.put("/api/crypto/prefs", json={"autonomous": True, "deliver": "analises", "watchlist": ["BTC"]},
                   headers=H).json()
    assert p["autonomous"] is True and p["watchlist"] == ["BTC"]
    notes_ = client.get("/api/notifications").json()
    assert notes_["unread"] >= 1
    nid = notes_["items"][0]["id"]
    assert client.post(f"/api/notifications/{nid}/read", headers=H).status_code == 204
    conn = app.state.conn
    conn.execute("INSERT INTO users (id, created_at) VALUES ('outra', '2026-10-01')")
    service.notify(conn, "outra", kind="x", severity="risco", title="dela", body="", ref="1")
    assert all(i["title"] != "dela" for i in client.get("/api/notifications").json()["items"])
    theirs = conn.execute("SELECT id FROM notifications WHERE user_id = 'outra'").fetchone()[0]
    assert client.post(f"/api/notifications/{theirs}/read", headers=H).status_code == 404
    event = next(e for e in ov["events"] if e["asset"] == "BTC")
    conn.execute("UPDATE crypto_events SET user_id = 'outra' WHERE id = ?", (event["id"],))
    assert client.post(f"/api/crypto/events/{event['id']}/convene", headers=H).status_code == 404


def test_production_web_only_requests_collection_and_evaluates_new_data(web, conn):
    client, app = web
    app.state.crypto.collect_in_web = False
    out = client.post("/api/crypto/collect", headers=H).json()
    assert out["requested"] is True and app.state.crypto.providers["binance"].calls == 0  # nenhum acesso à rede
    tested = client.post("/api/crypto/providers/binance/test", headers=H).json()
    assert tested["ok"] is None and "coletor" in tested["detail"]
    # o coletor (outro processo) coleta sem avaliar; o web avalia só quando há dado novo
    collector = monitor(conn, drops=CRASH)
    asyncio.run(collector.tick(collect=True, evaluate=False))
    assert conn.execute("SELECT COUNT(*) FROM crypto_events").fetchone()[0] == 0
    evaluator = monitor(conn)
    first = asyncio.run(evaluator.tick(collect=False))
    again = asyncio.run(evaluator.tick(collect=False))
    assert first["eventos"] and again["eventos"] == []  # mesmo dado: nada reavaliado, nenhuma atualização inflada
