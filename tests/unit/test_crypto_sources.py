# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fontes cripto sem rede: httpx.MockTransport, relógio e sleep falsos."""
import json
import traceback
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from crypto import assets
from crypto.models import ConversionRefused, Quote, convert
from crypto.sources import (
    BinancePublic, CoinGeckoDemo, DefiLlama, HostNotAllowed, NotConfigured, ProviderBlocked, QuotaExceeded,
    UnsupportedAsset, UpstreamError, _Http, cache_clear, check_url,
)

UTC = timezone.utc
T0 = datetime(2026, 10, 27, 12, 0, 30, tzinfo=UTC)
T0_MS = int(T0.timestamp() * 1000)
KEY = "CG-segredoDemo123456"


class Clock:
    def __init__(self, t=T0):
        self.t, self.slept = t, []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += timedelta(seconds=seconds)


class Mock:
    """Transporte que responde a partir de uma fila (ou função) e guarda as requisições."""
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request):
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item(request) if callable(item) else item

    @property
    def transport(self):
        return httpx.MockTransport(self)


def ok(payload, **headers):
    return httpx.Response(200, content=json.dumps(payload).encode(), headers=headers)


def raw(body: str, **headers):
    return httpx.Response(200, content=body.encode(), headers=headers)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_clear()
    yield
    cache_clear()


def binance(mock, clock=None, **kw):
    clock = clock or Clock()
    return BinancePublic(transport=mock.transport, clock=clock, sleep=clock.sleep, min_interval=0, rng=lambda: 0.5,
                         **kw)


def gecko(mock, key=KEY, clock=None, **kw):
    clock = clock or Clock()
    return CoinGeckoDemo(key, transport=mock.transport, clock=clock, sleep=clock.sleep, min_interval=0, **kw)


def llama(mock):
    clock = Clock()
    return DefiLlama(transport=mock.transport, clock=clock, sleep=clock.sleep)


TICKER = {"symbol": "BTCUSDT", "lastPrice": "0.00001234", "priceChangePercent": "-1.250", "volume": "123.45678900",
          "quoteVolume": "9876543.21000000", "highPrice": "0.00001300", "lowPrice": "0.00001200",
          "closeTime": T0_MS - 1000, "openTime": T0_MS - 86400000}


# ---------- normalização e Decimal ----------

def test_binance_stats_are_exact_decimals_labeled_usdt():
    mock = Mock(raw(json.dumps(TICKER)))
    q = binance(mock).stats_24h("BTC")
    assert q.price == Decimal("0.00001234") and str(q.price) == "0.00001234"
    assert q.quote_volume_24h == Decimal("9876543.21000000") and q.change_24h_pct == Decimal("-1.250")
    assert q.quote_currency == "USDT" and q.stable_id == "binance:BTCUSDT" and q.status == "fresh"
    assert q.reference_time == T0 - timedelta(seconds=1)
    assert mock.requests[0].url.params["symbol"] == "BTCUSDT"


def test_coingecko_json_numbers_parse_without_float_drift():
    body = '{"tether": {"usd": 0.00001234, "usd_24h_change": 0.1, "last_updated_at": %d}}' % int(T0.timestamp())
    q = gecko(Mock(raw(body))).simple_price(["tether"], vs=("usd",))[0]
    assert q.price == Decimal("0.00001234") and q.change_24h_pct == Decimal("0.1")
    assert q.asset_symbol == "USDT" and q.quote_currency == "USD"


def test_binance_price_uses_server_date_as_reference():
    mock = Mock(ok({"symbol": "ETHUSDT", "price": "2500.10000000"}, date="Tue, 27 Oct 2026 12:00:00 GMT"))
    q = binance(mock).price("ETH")
    assert q.price == Decimal("2500.10000000") and q.reference_time == datetime(2026, 10, 27, 12, tzinfo=UTC)
    assert q.quality["referencia"] == "Date do servidor"


def test_klines_parse_and_validate_arguments():
    row = [T0_MS - 3600000, "1.0", "2.0", "0.5", "1.5", "10.0", T0_MS - 1, "15.0", 3, "1", "1", "0"]
    mock = Mock(ok([row]))
    series = binance(mock).klines("SOL", "1h", 2)
    assert series.quote_currency == "USDT" and len(series) == 1 and series[0].close == Decimal("1.5")
    assert series[0].quote_volume == Decimal("15.0")
    for bad in (dict(interval="1m"), dict(limit=501), dict(limit=0)):
        with pytest.raises(ValueError):
            binance(mock).klines("SOL", **{"interval": "1h", "limit": 10, **bad})
    assert len(mock.requests) == 1


def test_exchange_info_falls_back_to_one_by_one_when_a_pair_is_unknown():
    def handler(request):
        symbols = json.loads(request.url.params["symbols"])
        if "XYZUSDT" in symbols:
            return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})
        return ok({"symbols": [{"symbol": s, "status": "TRADING" if s == "BTCUSDT" else "HALT",
                                "baseAsset": s[:-4], "quoteAsset": "USDT"} for s in symbols]})

    info = binance(Mock(handler)).exchange_info(["BTCUSDT", "ETHUSDT", "XYZUSDT"])
    assert info["BTCUSDT"].trading and not info["ETHUSDT"].trading
    assert info["XYZUSDT"].status == "INEXISTENTE"


# ---------- USDT ≠ USD e conversão explícita ----------

def _usdt_usd(price="0.9990", age=timedelta(0)):
    return Quote("coingecko", "USDT", "coingecko:tether/usd", "USD", Decimal(price), T0 - age, T0 - age)


def test_usdt_price_is_never_labeled_usd_and_conversion_needs_a_fresh_rate():
    q = binance(Mock(raw(json.dumps(TICKER)))).stats_24h("BTC")
    with pytest.raises(ConversionRefused, match="ausente"):
        convert(q, "USD", None, now=T0)
    with pytest.raises(ConversionRefused, match="desatualizada"):
        convert(q, "USD", _usdt_usd(age=timedelta(hours=2)), now=T0)
    with pytest.raises(ConversionRefused, match="não é"):
        convert(q, "BRL", _usdt_usd(), now=T0)
    usd = convert(q, "USD", _usdt_usd(), "CoinGecko tether/usd", now=T0)
    assert usd.quote_currency == "USD" and usd.price == Decimal("0.00001234") * Decimal("0.9990")
    assert usd.quality["conversao"]["fonte"] == "CoinGecko tether/usd"
    assert usd.quality["conversao"]["taxa"] == "0.9990" and usd.stable_id == "binance:BTCUSDT>USD"


def test_usd_to_brl_with_ptax_rate():
    ptax = Quote("bcb_sgs", "USD", "bcb:ptax", "BRL", Decimal("5.4321"), T0 - timedelta(days=1), T0)
    brl = convert(Quote("coingecko", "BTC", "x", "USD", Decimal("100"), T0, T0), "BRL", ptax, now=T0)
    assert brl.price == Decimal("543.2100") and brl.quote_currency == "BRL"
    assert brl.reference_time == T0 - timedelta(days=1)  # a mais antiga das duas


# ---------- validação de identificadores ----------

@pytest.mark.parametrize("bad", ["BTC/../x", "btcusdt?x=1", "http://evil", "ＢＴＣ", "BTC\n", "", "B", "BTC%2F", None, 1])
def test_identifiers_are_validated_before_any_request(bad):
    mock = Mock(ok({}))
    for fn in (assets.validate_symbol, assets.validate_binance_pair, assets.validate_coingecko_id,
               assets.validate_slug, assets.validate_chain):
        with pytest.raises(assets.InvalidIdentifier):
            fn(bad)
    with pytest.raises(assets.InvalidIdentifier):
        binance(mock).price(bad)
    with pytest.raises(assets.InvalidIdentifier):
        gecko(mock).market_chart(bad, "brl", 7)
    with pytest.raises(assets.InvalidIdentifier):
        llama(mock).protocol(bad)
    assert mock.requests == []


def test_chain_name_cannot_carry_path_or_scheme():
    for bad in ("http://evil", "../x", "a/b", "eth?x=1", "Éthereum"):
        with pytest.raises(assets.InvalidIdentifier):
            assets.validate_chain(bad)


def test_asset_without_binance_pair_is_refused():
    mock = Mock(ok({}))
    with pytest.raises(UnsupportedAsset):
        binance(mock).price("USDT")
    with pytest.raises(assets.InvalidIdentifier):
        binance(mock).price("DOGE")  # fora do registro
    assert mock.requests == []


# ---------- hosts e redirecionamento ----------

@pytest.mark.parametrize("url", ["https://evil.com/api", "http://api.llama.fi/protocols", "https://api.llama.fi:8443/x",
                                 "https://user@api.llama.fi/x", "https://api.coingecko.com.evil.com/x",
                                 "https://data-api.binance.vision.evil/x", "file:///etc/passwd"])
def test_host_allowlist_refuses_everything_else(url):
    with pytest.raises(HostNotAllowed):
        check_url(url)


def test_http_layer_refuses_foreign_base_and_redirects_are_not_followed():
    with pytest.raises(HostNotAllowed):
        _Http("x", "https://evil.com")
    mock = Mock(httpx.Response(302, headers={"location": "https://evil.com/"}))
    with pytest.raises(UpstreamError):
        llama(mock).chains()
    assert [r.url.host for r in mock.requests] == ["api.llama.fi"]


# ---------- limites, falhas e saúde ----------

def test_429_with_retry_after_waits_and_retries():
    clock = Clock()
    mock = Mock(httpx.Response(429, headers={"retry-after": "3"}), raw(json.dumps(TICKER)))
    q = binance(mock, clock).stats_24h("BTC")
    assert q.price == Decimal("0.00001234") and clock.slept == [3.0] and len(mock.requests) == 2


def test_418_blocks_the_provider_until_retry_after():
    clock = Clock()
    mock = Mock(httpx.Response(418, headers={"retry-after": "120"}), raw(json.dumps(TICKER)))
    provider = binance(mock, clock)
    with pytest.raises(ProviderBlocked):
        provider.stats_24h("BTC")
    health = provider.health()
    assert health["blocked_until"] == (T0 + timedelta(seconds=120)).isoformat(timespec="seconds")
    assert "418" in health["last_error"]
    with pytest.raises(ProviderBlocked):
        provider.stats_24h("BTC")
    assert len(mock.requests) == 1 and clock.slept == []
    clock.t += timedelta(seconds=121)
    assert provider.stats_24h("BTC").price == Decimal("0.00001234")


@pytest.mark.parametrize("error", [httpx.ConnectError("x"), httpx.ReadTimeout("x")])
def test_network_errors_retry_a_few_times_then_show_in_health(error):
    clock = Clock()
    mock = Mock(error)
    provider = binance(mock, clock, max_retries=2)
    with pytest.raises(UpstreamError, match="3 tentativa"):
        provider.price("BTC")
    assert len(mock.requests) == 3 and len(clock.slept) == 2 and clock.slept[1] > clock.slept[0]
    health = provider.health()
    assert health["consecutive_failures"] == 3 and health["last_error"].startswith("rede")
    assert health["last_ok_at"] is None and health["calls_today"] == 3


def test_other_4xx_is_not_retried():
    mock = Mock(httpx.Response(404))
    with pytest.raises(UpstreamError) as info:
        binance(mock).price("BTC")
    assert info.value.status == 404 and len(mock.requests) == 1


def test_503_without_retry_after_backs_off_then_succeeds():
    clock = Clock()
    mock = Mock(httpx.Response(503), ok({"symbol": "BTCUSDT", "price": "1"}))
    assert binance(mock, clock).price("BTC").price == Decimal("1") and len(clock.slept) == 1


def test_cache_hit_avoids_second_request_across_instances():
    mock = Mock(ok({"symbol": "BTCUSDT", "price": "1"}))
    binance(mock).price("BTC")
    binance(mock).price("BTC")
    assert len(mock.requests) == 1
    cache_clear()
    binance(mock).price("BTC")
    assert len(mock.requests) == 2


def test_binance_weight_header_is_tracked_and_backs_off():
    clock = Clock()
    mock = Mock(ok({"symbol": "BTCUSDT", "price": "1"}, **{"x-mbx-used-weight-1m": "4799"}))
    provider = binance(mock, clock, weight_fraction=0.8)
    provider.price("BTC")
    assert provider.health()["used_weight_1m"] == 4799
    with pytest.raises(ProviderBlocked):
        provider.price("ETH")  # 4799 + 2 > 4800
    assert len(mock.requests) == 1
    clock.t = T0.replace(second=0) + timedelta(minutes=1)
    mock.responses = [ok({"symbol": "ETHUSDT", "price": "2"}, **{"x-mbx-used-weight-1m": "2"})]
    assert provider.price("ETH").price == Decimal("2")


def test_oversized_response_is_refused():
    mock = Mock(raw(json.dumps([{"name": "x", "tvl": 1}] * 10)))
    http = llama(mock)._http
    with pytest.raises(UpstreamError, match="grande"):
        http.get("/v2/chains", ttl=0, transform=lambda x: x, max_bytes=10)
    assert len(mock.requests) == 1


# ---------- CoinGecko: chave e cota ----------

def test_coingecko_without_key_never_calls_the_network():
    mock = Mock(ok({}))
    provider = gecko(mock, key=None)
    assert provider.configured is False and provider.health()["configured"] is False
    for call in (lambda: provider.simple_price(["bitcoin"]), lambda: provider.markets(["bitcoin"]),
                 lambda: provider.market_chart("bitcoin", "brl", 7), provider.coins_list):
        with pytest.raises(NotConfigured):
            call()
    assert mock.requests == []


def test_coingecko_key_only_travels_in_the_header():
    mock = Mock(ok({"bitcoin": {"brl": 1, "last_updated_at": int(T0.timestamp())}}), httpx.Response(500))
    provider = gecko(mock, max_retries=0)
    provider.simple_price(["bitcoin"], vs=("brl",))
    request = mock.requests[0]
    assert request.headers["x-cg-demo-api-key"] == KEY
    assert KEY not in str(request.url)
    cache_clear()
    with pytest.raises(UpstreamError) as info:
        provider.simple_price(["bitcoin"], vs=("brl",))
    exposed = [repr(provider), str(provider.__dict__), str(provider.health()), str(provider.quota()), str(info.value),
               repr(info.value), "".join(traceback.format_exception(info.value))]
    assert not any(KEY in text for text in exposed)


def test_coingecko_poll_is_refused_first_to_keep_the_monthly_reserve():
    mock = Mock(ok({"bitcoin": {"brl": 1, "last_updated_at": int(T0.timestamp())}}))
    provider = gecko(mock, month_limit=100, poll_reserve=Decimal("0.15"), used_month=85)
    with pytest.raises(QuotaExceeded, match="reserva"):
        provider.simple_price(["bitcoin"], vs=("brl",), purpose="poll")
    assert mock.requests == []
    provider.simple_price(["bitcoin"], vs=("brl",), purpose="user")
    quota = provider.quota()
    assert quota["used_month"] == 86 and quota["remaining"] == 14 and quota["remaining_for_poll"] == 0
    assert quota["reset_at"] == "2026-11-01T00:00:00+00:00"


def test_coingecko_minute_limit():
    mock = Mock(ok([{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}]))
    provider = gecko(mock, minute_limit=1)
    provider.coins_list()
    cache_clear()
    with pytest.raises(QuotaExceeded, match="minuto"):
        provider.coins_list()
    assert len(mock.requests) == 1


def test_coingecko_missing_price_is_unavailable_and_old_is_stale():
    stamp = int((T0 - timedelta(hours=1)).timestamp())
    mock = Mock(ok({"bitcoin": {"brl": 350000.5, "last_updated_at": stamp}}))
    quotes = {q.asset_symbol: q for q in gecko(mock).simple_price(["bitcoin", "ethereum"], vs=("brl",))}
    assert quotes["BTC"].status == "stale" and quotes["BTC"].price == Decimal("350000.5")
    assert quotes["ETH"].status == "unavailable" and quotes["ETH"].price is None


def test_markets_and_market_chart_normalize():
    mock = Mock(ok([{"id": "bitcoin", "current_price": 1.5, "market_cap": 10, "total_volume": 2,
                     "price_change_percentage_24h": -0.5, "high_24h": 2, "low_24h": 1,
                     "last_updated": "2026-10-27T12:00:00.000Z"}]),
                ok({"prices": [[T0_MS, 1.25]], "market_caps": [[T0_MS, 10]], "total_volumes": [[T0_MS, 3]]}))
    provider = gecko(mock)
    q = provider.markets(["bitcoin"], "brl")[0]
    assert q.price == Decimal("1.5") and q.quote_currency == "BRL" and q.market_cap == 10
    point = provider.market_chart("bitcoin", "usd", 7)[0]
    assert point.price == Decimal("1.25") and point.volume == 3
    with pytest.raises(ValueError):
        provider.market_chart("bitcoin", "usd", 366)


# ---------- DefiLlama ----------

def test_defillama_protocols_are_trimmed_and_slugs_validated():
    rows = [{"id": "1", "name": "Aave V3", "slug": "aave-v3", "category": "Lending", "chains": ["Ethereum"],
             "tvl": 1.5e10, "change_1d": 0.5, "change_7d": -2.25, "chainTvls": {"Ethereum": 1},
             "description": "x" * 999},
            {"name": "Mal", "slug": "../admin", "tvl": 1}, {"name": "Sem slug", "tvl": 1}]
    protocols = llama(Mock(ok(rows))).protocols()
    assert len(protocols) == 1
    p = protocols[0]
    assert (p.slug, p.name, p.category, p.chains) == ("aave-v3", "Aave V3", "Lending", ("Ethereum",))
    assert p.tvl == Decimal("1.5E+10") and p.change_7d == Decimal("-2.25")
    assert not hasattr(p, "chainTvls") and not hasattr(p, "description")


def test_defillama_chain_history_and_protocol_detail():
    day = 86400
    mock = Mock(ok([{"date": 1761523200 + i * day, "tvl": 100 + i} for i in range(3)]),
                ok({"name": "Lido", "category": "Liquid Staking", "chains": ["Ethereum"],
                    "tvl": [{"date": 1761523200, "totalLiquidityUSD": 5.5}]}))
    provider = llama(mock)
    history = provider.chain_tvl_history("OP Mainnet")
    assert [p.tvl for p in history] == [100, 101, 102]
    assert mock.requests[0].url.raw_path == b"/v2/historicalChainTvl/OP%20Mainnet"
    detail = provider.protocol("lido")
    assert detail.tvl_history[0].tvl == Decimal("5.5") and detail.slug == "lido"


def test_malformed_payload_becomes_upstream_error_and_health_failure():
    provider = llama(Mock(ok({"unexpected": True})))
    with pytest.raises(UpstreamError, match="formato"):
        provider.chain_tvl_history()
    assert provider.health()["consecutive_failures"] == 1


def test_stale_quote_is_marked_stale():
    old = dict(TICKER, closeTime=T0_MS - 20 * 60 * 1000)
    q = binance(Mock(raw(json.dumps(old)))).stats_24h("BTC")
    assert q.status == "stale"
    assert q.with_status(T0 - timedelta(minutes=15)).status == "fresh"
