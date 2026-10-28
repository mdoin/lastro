# SPDX-License-Identifier: AGPL-3.0-or-later
"""Motor de sinais cripto: determinístico, sem rede."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crypto.assets import ASSETS
from crypto.models import Candle, CandleSeries, Quote, TvlPoint
from crypto.signals import (
    _FORBIDDEN, Prefs, Signal, TvlInput, concentration, cooldown_ok, correlation, detect, group, max_drawdown,
    peg_deviation, realized_volatility, relative_volume, returns_by_window, tvl_change, window_return,
)

UTC = timezone.utc
START = datetime(2026, 10, 18, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
PATTERN = [Decimal(x) for x in ("0.6", "-0.4", "0.3", "-0.7", "0.5", "-0.3")]  # desvio típico ~0,5% por vela
BTC, USDT, USDC = ASSETS["BTC"], ASSETS["USDT"], ASSETS["USDC"]
SEEN: list[Signal] = []


def make_series(last_move=None, last_volume=Decimal(100), n=200, delay=timedelta(seconds=30), volumes=None,
                moves=None):
    price, candles = Decimal(100), []
    for i in range(n):
        move = moves(i % 6) if moves and i >= n - 24 else PATTERN[i % 6]  # moves: regime das últimas 24 velas
        if i == n - 1 and last_move is not None:
            move = last_move
        new = price * (1 + move / 100)
        volume = last_volume if i == n - 1 else (volumes(i) if volumes else Decimal(100))
        t = START + i * HOUR
        candles.append(Candle(t, t + HOUR - timedelta(milliseconds=1), price, max(price, new), min(price, new), new,
                              volume, volume * new))
        price = new
    now = candles[-1].close_time + timedelta(minutes=1)
    return CandleSeries("binance", "BTC", "BTCUSDT", "1h", "USDT", now - delay, tuple(candles)), now


def run(asset=BTC, series=None, now=None, **kw):
    kw.setdefault("prefs", Prefs())
    out = detect(asset, series, now=now, **kw)
    SEEN.extend(out)
    return out


def by_category(signals, category):
    found = [s for s in signals if s.category == category]
    return found[0] if found else None


# ---------- indicadores ----------

def test_indicators_refuse_insufficient_samples_with_a_reason():
    closes = [Decimal(100 + i) for i in range(5)]
    for measure in (realized_volatility(closes), max_drawdown(closes), window_return(closes, 10)):
        assert measure.value is None and "insuficiente" in measure.reason
    short, _ = make_series(n=5)
    assert relative_volume(short.candles).value is None
    assert correlation(short.candles, short.candles).value is None
    assert returns_by_window(short.candles)["7d"].value is None
    assert concentration(None, "BTC").reason == "carteira não informada"
    assert tvl_change([TvlPoint(START, Decimal(1))], 7).value is None


def test_insufficient_candles_produce_no_signal():
    series, now = make_series(last_move=Decimal("-10"), last_volume=Decimal(1000), n=20)
    assert run(series=series, now=now, prefs=Prefs(watchlist=frozenset({"BTC"}))) == []


def test_indicator_values():
    assert peg_deviation(Decimal("0.995"), Decimal("1")).value == Decimal("0.500")
    assert max_drawdown([Decimal(x) for x in (100, 120, 90, 110, 100, 100, 100, 100, 100, 100)]).value == 25
    assert window_return([Decimal(100), Decimal(110)], 1).value == Decimal("10.0")
    series, _ = make_series()
    assert correlation(series.candles, series.candles).value.quantize(Decimal("0.0001")) == 1
    windows = returns_by_window(series.candles)
    assert all(windows[k].value is not None for k in ("1h", "4h", "24h", "7d"))
    assert concentration({"BTC": Decimal(60), "ETH": Decimal(40)}, "BTC").value == Decimal("0.6")
    vol = realized_volatility([c.close for c in series.candles])
    assert Decimal("0.4") < vol.value < Decimal("0.6")


def test_relative_volume_compares_same_hour_of_previous_days():
    # Às 00h o volume é sempre 100; nas outras horas, 1000. A última vela (00h) com 100 é normal, não "baixa".
    series, _ = make_series(n=193, volumes=lambda i: Decimal(100) if i % 24 == 0 else Decimal(1000))
    assert series.candles[-1].open_time.hour == 0
    assert relative_volume(series.candles).value == 1


# ---------- severidade ----------

def test_big_move_with_normal_volume_is_attention_not_council():
    series, now = make_series(last_move=Decimal("-1.6"))
    signal = by_category(run(series=series, now=now, prefs=Prefs(watchlist=frozenset({"BTC"}))), "preco")
    assert signal.severity == "atencao" and signal.direction == "queda" and signal.data_quality == "boa"
    assert any("desvios-padrão" in e for e in signal.evidence)
    assert signal.sources[0]["source"] == "binance"


def test_big_move_abnormal_volume_fresh_and_watched_is_council():
    series, now = make_series(last_move=Decimal("-1.6"), last_volume=Decimal(400))
    signal = by_category(run(series=series, now=now, prefs=Prefs(watchlist=frozenset({"BTC"}))), "preco")
    assert signal.severity == "conselho"
    assert Decimal(signal.indicators["volume_relativo"]) == 4
    assert signal.dedup_key.startswith("preco:BTC:queda:")


def test_stale_data_never_reaches_council():
    series, now = make_series(last_move=Decimal("-1.6"), last_volume=Decimal(400), delay=timedelta(hours=1))
    signal = by_category(run(series=series, now=now, prefs=Prefs(watchlist=frozenset({"BTC"}))), "preco")
    assert signal.severity != "conselho" and signal.data_quality == "limitada"
    assert any("desatualizados" in e for e in signal.evidence)
    very_old, now = make_series(last_move=Decimal("-1.6"), last_volume=Decimal(400), delay=timedelta(hours=3))
    assert by_category(run(series=very_old, now=now, prefs=Prefs(watchlist=frozenset({"BTC"}))), "preco").severity \
        == "comum"


def test_council_needs_exposure():
    series, now = make_series(last_move=Decimal("-1.6"), last_volume=Decimal(400))
    signal = by_category(run(series=series, now=now), "preco")
    assert signal.severity == "atencao"


def test_muted_category_is_suppressed():
    series, now = make_series(last_move=Decimal("-1.6"), last_volume=Decimal(400))
    signals = run(series=series, now=now, prefs=Prefs(muted=frozenset({"preco"}), watchlist=frozenset({"BTC"})))
    assert by_category(signals, "preco") is None


def test_sensitivity_changes_the_outcome():
    series, now = make_series(last_move=Decimal("-1.3"))
    z = Decimal(by_category(run(series=series, now=now, prefs=Prefs(sensitivity="alta")), "preco").indicators["zscore"])
    assert Decimal("-3") < z < Decimal("-2.5")
    assert by_category(run(series=series, now=now, prefs=Prefs(sensitivity="media")), "preco").severity == "atencao"
    assert by_category(run(series=series, now=now, prefs=Prefs(sensitivity="baixa")), "preco") is None


def test_same_move_weighs_less_in_a_wild_week():
    calm, now = make_series(last_move=Decimal("-1.6"))
    wild_pattern = [p * 4 for p in PATTERN]
    price, candles = Decimal(100), []
    for i, c in enumerate(calm.candles):
        move = Decimal("-1.6") if i == len(calm.candles) - 1 else wild_pattern[i % 6]
        new = price * (1 + move / 100)
        candles.append(Candle(c.open_time, c.close_time, price, max(price, new), min(price, new), new, c.volume,
                              c.quote_volume))
        price = new
    wild = CandleSeries(**{**calm.__dict__, "candles": tuple(candles)})
    assert by_category(run(series=calm, now=now), "preco") is not None
    assert by_category(run(series=wild, now=now), "preco") is None


def test_abnormal_volume_without_move_is_a_volume_signal():
    series, now = make_series(last_volume=Decimal(300))
    signals = run(series=series, now=now)
    assert by_category(signals, "preco") is None
    assert by_category(signals, "volume").severity == "comum"


def test_volatility_regime_change():
    series, now = make_series(moves=lambda k: PATTERN[k] * 3)
    signal = by_category(run(series=series, now=now), "volatilidade")
    assert signal.severity == "atencao" and Decimal(signal.indicators["razao"]) > 2


# ---------- stablecoin, DeFi, concentração ----------

def _peg_quote(price, currency="USD", source="coingecko", symbol="USDT", age=timedelta(minutes=1)):
    now = START + timedelta(days=9)
    return Quote(source, symbol, f"{source}:{symbol}", currency, Decimal(price), now - age, now - age), now


def test_stablecoin_depeg_half_percent_vs_five_basis_points():
    quote, now = _peg_quote("0.995")
    signal = by_category(run(USDT, None, now, peg=quote), "stablecoin")
    assert signal.severity == "atencao" and signal.direction == "queda" and signal.data_quality == "boa"
    quote, now = _peg_quote("0.9995")
    assert run(USDT, None, now, peg=quote) == []
    quote, now = _peg_quote("0.98")
    held = {"USDT": Decimal(10), "BTC": Decimal(90)}
    assert by_category(run(USDT, None, now, peg=quote, portfolio=held), "stablecoin").severity == "conselho"


def test_usdc_against_usdt_is_limited_quality_and_says_so():
    quote, now = _peg_quote("0.98", currency="USDT", source="binance", symbol="USDC")
    signal = by_category(run(USDC, None, now, peg=quote, portfolio={"USDC": Decimal(10), "BTC": Decimal(90)}),
                         "stablecoin")
    assert signal.data_quality == "limitada" and signal.severity == "risco"
    assert any("medido contra USDT" in e for e in signal.evidence)


def test_tvl_drop_signal():
    points = [TvlPoint(START + timedelta(days=i), Decimal(100 - 4 * i)) for i in range(10)]
    now = points[-1].time + HOUR
    signal = by_category(run(ASSETS["ETH"], None, now, tvl=TvlInput("Ethereum", points, fetched_at=now)), "defi")
    assert signal.severity == "atencao" and signal.direction == "queda"
    assert Decimal(signal.indicators["tvl_7d_pct"]) < -20


def test_concentration_above_user_limit_is_risk():
    now = START
    signal = by_category(run(BTC, None, now, portfolio={"BTC": Decimal(60), "ETH": Decimal(40)}), "concentracao")
    assert signal.severity == "risco" and "60,0%" in signal.evidence[0]
    assert run(BTC, None, now, portfolio={"BTC": Decimal(20), "ETH": Decimal(80)}) == []


def test_missing_portfolio_lowers_relevance_and_is_stated():
    series, now = make_series(last_move=Decimal("-1.6"))
    unknown = by_category(run(series=series, now=now), "preco")
    held = by_category(run(series=series, now=now, portfolio={"BTC": Decimal(10), "ETH": Decimal(90)}), "preco")
    assert unknown.relevance < held.relevance
    assert any("exposição desconhecida" in e for e in unknown.evidence)
    assert Decimal(0) <= unknown.relevance <= 1 and Decimal(0) <= held.relevance <= 1


# ---------- texto, agrupamento e cooldown ----------

def test_hypotheses_are_observations_never_recommendations():
    out = []
    for move, volume in ((Decimal("4"), Decimal(50)), (Decimal("-1.6"), Decimal(400)), (None, Decimal(300)),
                         (None, Decimal(5))):
        series, now = make_series(last_move=move, last_volume=volume)
        out += run(series=series, now=now, portfolio={"BTC": Decimal(9), "ETH": Decimal(1)})
    series, now = make_series(moves=lambda k: PATTERN[k] * 3)
    out += run(series=series, now=now)
    for price in ("0.995", "1.02"):
        quote, now = _peg_quote(price)
        out += run(USDT, None, now, peg=quote)
    points = [TvlPoint(START + timedelta(days=i), Decimal(100 + 9 * i)) for i in range(10)]
    out += run(ASSETS["ETH"], None, points[-1].time, tvl=TvlInput("lido", points))
    assert {s.category for s in out} == {"preco", "volume", "liquidez", "stablecoin", "defi", "concentracao",
                                         "volatilidade"}
    for s in out + SEEN:
        assert not _FORBIDDEN.search(s.hypothesis), s.hypothesis
        assert "Precisa ser" in s.hypothesis or "observação" in s.hypothesis
    with pytest.raises(ValueError):
        Signal("preco", "BTC", {}, [], [], START, "comum", "boa", Decimal(0), "Hora de comprar BTC barato", "k")


def test_group_merges_drop_bounce_and_new_drop_into_one_event():
    signals = []
    for hours, move in ((0, "-1.6"), (1, "1.6"), (2, "-1.6"), (10, "-1.6")):
        series, now = make_series(last_move=Decimal(move), n=200 + hours)
        signals.append(by_category(run(series=series, now=now), "preco"))
    events = group(signals, timedelta(hours=6))
    assert len(events) == 2
    first = events[0]
    assert len(first.signals) == 3 and first.direction == "misto" and first.severity == "atencao"
    assert first.dedup_key == signals[0].dedup_key and len(events[1].signals) == 1


def test_cooldown():
    assert cooldown_ok(None, START, HOUR)
    assert not cooldown_ok(START, START + timedelta(minutes=59), HOUR)
    assert cooldown_ok(START, START + HOUR, HOUR)
