# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fontes públicas de mercado cripto: único módulo de crypto/ com rede (httpx), só leitura, só GET.

Barreiras: lista fechada de hosts (https, sem porta, sem credenciais, sem seguir redirecionamento), identificadores
validados antes de virar URL (crypto.assets), ritmo mínimo por fornecedor, prazo por requisição, poucas novas
tentativas com espera exponencial + jitter, Retry-After respeitado em 429/418/503 (418 da Binance = IP banido: o
fornecedor fica bloqueado até o prazo e isso aparece na saúde), 4xx nunca repetido (exceto 429), resposta com
tamanho máximo. Um cache em memória com TTL, compartilhado entre instâncias, evita chamadas repetidas.

Cliente síncrono de propósito: determinístico nos testes (transport/clock/sleep injetados). Em código assíncrono,
chame via asyncio.to_thread.

Verificado nas documentações oficiais em 2026-10-27:
- Binance Spot REST (https://developers.binance.com/docs/binance-spot-api-docs/rest-api): data-api.binance.vision é a
  base só de dados públicos de mercado; limite REQUEST_WEIGHT de 6000/min por IP (rateLimits do exchangeInfo);
  cabeçalho X-MBX-USED-WEIGHT-1M traz o peso usado; 429 = limite, 418 = IP banido por insistir após 429 (de 2 min a
  3 dias), ambos com Retry-After em segundos. Pesos: ticker/price com symbol = 2; ticker/24hr com symbol = 2;
  klines = 2 (limit padrão 500, máx. 1000; intervalos incluem 1h, 4h, 1d); exchangeInfo = 20 (symbols como array
  JSON; símbolo inexistente devolve erro para o pedido inteiro).
- CoinGecko Demo (https://docs.coingecko.com/demo/reference/authentication, https://www.coingecko.com/en/api/pricing):
  base https://api.coingecko.com/api/v3, chave no cabeçalho x-cg-demo-api-key (a query x_cg_demo_api_key é
  desaconselhada pela própria doc: vaza em logs); 10.000 chamadas/mês e 100/min; cada resposta 200 gasta 1 crédito;
  histórico do market_chart limitado a 365 dias no Demo; atribuição obrigatória (guia de marca
  https://brand.coingecko.com/resources/attribution-guide aceita "Data provided by CoinGecko" com link para
  https://www.coingecko.com).
- DefiLlama (https://api-docs.defillama.com/llms-free.txt): /protocols, /protocol/{slug}, /v2/chains,
  /v2/historicalChainTvl e /v2/historicalChainTvl/{chain} estão na API gratuita (api.llama.fi, sem autenticação);
  a doc não publica limite de taxa nem exige atribuição — citamos a fonte mesmo assim. Endpoints Pro ficam de fora.
"""

import json
import random
import re
import time
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Callable, Protocol
from urllib.parse import quote, urlsplit

import httpx

from . import assets
from .models import (
    UTC, CandleSeries, Candle, ChainInfo, ChartPoint, CoinRef, DataError, PairInfo, ProtocolDetail, ProtocolInfo,
    Quote, TvlPoint, clean_text, dec, from_iso, from_ms, from_s, iso, json_loads, status_at,
)

ALLOWED_HOSTS = frozenset({"data-api.binance.vision", "api.coingecko.com", "api.llama.fi"})
USER_AGENT = "Lastro/0.4 (dados publicos de cripto; uso pessoal)"  # cabeçalho HTTP: só ASCII
MAX_BYTES = 2 * 1024 * 1024
CACHE_MAX = 256
_PARSE_ERRORS = (KeyError, TypeError, IndexError, ValueError, AttributeError)


def utcnow() -> datetime:
    return datetime.now(UTC)


class SourceError(Exception):
    """Base dos erros das fontes cripto. Mensagens curtas, nunca com chave, URL completa ou payload."""


class HostNotAllowed(SourceError):
    pass


class NotConfigured(SourceError):
    pass


class QuotaExceeded(SourceError):
    pass


class UnsupportedAsset(SourceError):
    pass


class ProviderBlocked(SourceError):
    def __init__(self, message: str, until: datetime | None):
        super().__init__(message)
        self.until = until


class UpstreamError(SourceError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def check_url(url: str) -> str:
    """Só https, host exato da lista, sem porta nem credenciais."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in ALLOWED_HOSTS:
        raise HostNotAllowed("host fora da lista permitida")
    return url


# ---------- cache compartilhado ----------

@dataclass(frozen=True)
class Fetched:
    value: object             # já normalizado (imutável: tuplas e dataclasses congeladas)
    fetched_at: datetime
    server_time: datetime | None  # cabeçalho Date do fornecedor


_CACHE: dict[tuple, tuple[datetime, Fetched]] = {}


def cache_clear() -> None:
    _CACHE.clear()


def _cache_put(key: tuple, expires: datetime, fetched: Fetched, now: datetime) -> None:
    if len(_CACHE) >= CACHE_MAX:
        for k in [k for k, (exp, _) in _CACHE.items() if exp <= now]:
            del _CACHE[k]
        while len(_CACHE) >= CACHE_MAX:
            del _CACHE[next(iter(_CACHE))]  # o mais antigo inserido
    _CACHE[key] = (expires, fetched)


# ---------- saúde e camada HTTP ----------

@dataclass
class Health:
    provider: str
    configured: bool = True
    last_ok_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    latency_ms: int | None = None
    blocked_until: datetime | None = None
    calls_today: int = 0
    calls_month: int = 0
    used_weight_1m: int | None = None  # só Binance
    day: str = ""
    month: str = ""

    def as_dict(self) -> dict:
        return {f.name: iso(v) if isinstance(v, datetime) else v
                for f in fields(self) for v in [getattr(self, f.name)] if f.name not in ("day", "month")}


class _Http:
    def __init__(self, provider: str, base_url: str, *, transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], datetime] = utcnow, sleep: Callable[[float], None] = time.sleep,
                 timeout: float = 10.0, min_interval: float = 0.0, max_retries: int = 2, backoff: float = 0.5,
                 max_backoff: float = 30.0, max_wait: float = 60.0, rng: Callable[[], float] = random.random,
                 on_response: Callable[[httpx.Response], None] | None = None):
        self.provider, self.base_url = provider, check_url(base_url)
        self.clock, self.sleep, self.rng = clock, sleep, rng
        self.min_interval, self.max_retries, self.backoff = min_interval, max_retries, backoff
        self.max_backoff, self.max_wait, self.on_response = max_backoff, max_wait, on_response
        self.health = Health(provider)
        self._last_sent: datetime | None = None
        self._client = httpx.Client(transport=transport, timeout=httpx.Timeout(timeout), follow_redirects=False,
                                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, params: dict | None = None, *, ttl: float, transform: Callable, max_bytes: int = MAX_BYTES,
            headers: dict | None = None, before_send: Callable[[], None] | None = None) -> Fetched:
        params = {k: str(v) for k, v in (params or {}).items()}
        url = check_url(self.base_url + path)
        key = (self.provider, path, tuple(sorted(params.items())))
        hit = _CACHE.get(key)
        if hit and hit[0] > self.clock():
            return hit[1]
        for attempt in range(self.max_retries + 1):
            now = self.clock()
            self._roll(now)
            h = self.health
            if h.blocked_until and now < h.blocked_until:
                raise ProviderBlocked(f"{self.provider} bloqueado até {iso(h.blocked_until)}", h.blocked_until)
            if before_send:
                before_send()
            self._pace()
            h.calls_today += 1
            h.calls_month += 1
            started = time.monotonic()
            response, body, error = self._send(url, params, headers, max_bytes)
            if error:  # fora do except: nenhuma exceção do httpx (com a requisição dentro) fica encadeada
                self._fail(error)
                if error.startswith("rede") and attempt < self.max_retries:
                    self.sleep(self._delay(attempt))
                    continue
                raise UpstreamError(f"{self.provider}: {error} após {attempt + 1} tentativa(s)")
            if self.on_response:
                self.on_response(response)
            status = response.status_code
            if status == 200:
                try:
                    value = transform(json_loads(body))
                except _PARSE_ERRORS:
                    value = None
                if value is None:
                    self._fail("formato inesperado na resposta")
                    raise UpstreamError(f"{self.provider}: formato inesperado em {path}", status)
                fetched = Fetched(value, self.clock(), _server_time(response))
                h.last_ok_at, h.consecutive_failures = fetched.fetched_at, 0
                h.latency_ms = int((time.monotonic() - started) * 1000)
                _cache_put(key, fetched.fetched_at + timedelta(seconds=ttl), fetched, fetched.fetched_at)
                return fetched
            wait = _retry_after(response, now)
            if status == 418:  # IP banido: nada de nova tentativa até o prazo
                h.blocked_until = now + timedelta(seconds=wait if wait is not None else 120)
                self._fail("HTTP 418: IP banido pelo fornecedor")
                raise ProviderBlocked(f"{self.provider} baniu o IP até {iso(h.blocked_until)}", h.blocked_until)
            self._fail(f"HTTP {status}")
            if status in (429, 503) or status >= 500:
                delay = wait if wait is not None else self._delay(attempt)
                if attempt < self.max_retries and delay <= self.max_wait:
                    self.sleep(delay)
                    continue
                if status in (429, 503):
                    h.blocked_until = self.clock() + timedelta(seconds=delay)
                    raise ProviderBlocked(f"{self.provider}: HTTP {status}, aguardar até {iso(h.blocked_until)}",
                                          h.blocked_until)
            raise UpstreamError(f"{self.provider}: HTTP {status} em {path}", status)  # 3xx/4xx: sem nova tentativa
        raise AssertionError("inalcançável")

    def _send(self, url, params, headers, max_bytes) -> tuple[httpx.Response | None, bytes, str | None]:
        try:
            with self._client.stream("GET", url, params=params, headers=headers) as response:
                chunks, size = [], 0
                if response.status_code == 200:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            return None, b"", "resposta grande demais"
                        chunks.append(chunk)
                return response, b"".join(chunks), None
        except httpx.RequestError as exc:  # timeout, conexão, DNS, TLS
            return None, b"", f"rede: {type(exc).__name__}"

    def _pace(self) -> None:
        if self._last_sent is not None and self.min_interval:
            wait = self.min_interval - (self.clock() - self._last_sent).total_seconds()
            if wait > 0:
                self.sleep(wait)
        self._last_sent = self.clock()

    def _delay(self, attempt: int) -> float:
        base = min(self.max_backoff, self.backoff * 2 ** attempt)
        return base / 2 + self.rng() * base / 2  # exponencial com jitter

    def _roll(self, now: datetime) -> None:
        h = self.health
        if h.day != now.date().isoformat():
            h.day, h.calls_today = now.date().isoformat(), 0
        if h.month != now.strftime("%Y-%m"):
            h.month, h.calls_month = now.strftime("%Y-%m"), 0

    def _fail(self, message: str) -> None:
        h = self.health
        h.last_error, h.last_error_at = message[:160], self.clock()
        h.consecutive_failures += 1


def _retry_after(response: httpx.Response, now: datetime) -> float | None:
    value = (response.headers.get("retry-after") or "").strip()
    if value.isdigit():
        return min(float(value), 3 * 86400)
    try:
        return min(max((parsedate_to_datetime(value) - now).total_seconds(), 0.0), 3 * 86400)
    except (TypeError, ValueError):
        return None


def _server_time(response: httpx.Response) -> datetime | None:
    try:
        moment = parsedate_to_datetime(response.headers.get("date", ""))
        return moment.astimezone(UTC) if moment.tzinfo else None
    except (TypeError, ValueError):
        return None


class Provider(Protocol):
    name: str
    requires_key: bool
    configured: bool
    docs_url: str
    attribution: str

    def health(self) -> dict: ...


def _next_minute(now: datetime) -> datetime:
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1)


# ---------- Binance (pública, sem chave) ----------

class BinancePublic:
    name = "binance"
    requires_key = False
    configured = True
    docs_url = "https://developers.binance.com/docs/binance-spot-api-docs/rest-api"
    attribution = "Dados de mercado: Binance (API pública de dados de mercado)"
    BASE = "https://data-api.binance.vision"
    WEIGHT_LIMIT = 6000  # REQUEST_WEIGHT por minuto por IP (exchangeInfo.rateLimits)
    INTERVALS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}

    def __init__(self, *, weight_fraction: float = 0.8, **http_options):
        http_options.setdefault("min_interval", 0.2)
        self.weight_fraction = weight_fraction
        self._weight_minute: datetime | None = None
        self._http = _Http(self.name, self.BASE, on_response=self._track_weight, **http_options)

    def health(self) -> dict:
        return self._http.health.as_dict()

    def _track_weight(self, response: httpx.Response) -> None:
        used = response.headers.get("x-mbx-used-weight-1m", "")
        if used.isdigit():
            self._http.health.used_weight_1m = int(used)
            self._weight_minute = self._http.clock().replace(second=0, microsecond=0)

    def _check_weight(self, weight: int) -> None:
        h, now = self._http.health, self._http.clock()
        same_minute = self._weight_minute == now.replace(second=0, microsecond=0)
        if same_minute and h.used_weight_1m is not None and \
                h.used_weight_1m + weight > self.WEIGHT_LIMIT * self.weight_fraction:
            h.blocked_until = _next_minute(now)
            raise ProviderBlocked(f"binance: peso {h.used_weight_1m}/{self.WEIGHT_LIMIT} no minuto; aguardando",
                                  h.blocked_until)

    def _get(self, path, params, *, ttl, weight, transform, max_bytes=MAX_BYTES) -> Fetched:
        return self._http.get(path, params, ttl=ttl, transform=transform, max_bytes=max_bytes,
                              before_send=lambda: self._check_weight(weight))

    @staticmethod
    def _pair(symbol) -> tuple[assets.Asset, str]:
        asset = assets.get(symbol)
        if not asset.binance_symbol:
            raise UnsupportedAsset(f"{asset.symbol} não tem par na Binance")
        return asset, assets.validate_binance_pair(asset.binance_symbol)

    def exchange_info(self, symbols) -> dict[str, PairInfo]:
        """Quais pares existem e o status de cada (não supõe disponibilidade). Recebe nomes de pares."""
        pairs = sorted({assets.validate_binance_pair(s) for s in symbols})
        if not pairs:
            return {}

        def parse(payload):
            out = {}
            for s in payload["symbols"]:
                if s["symbol"] in pairs:
                    out[s["symbol"]] = PairInfo(s["symbol"], clean_text(s["status"], 20),
                                                clean_text(s["baseAsset"], 15), clean_text(s["quoteAsset"], 15))
            return out

        try:
            info = self._get("/api/v3/exchangeInfo", {"symbols": json.dumps(pairs, separators=(",", ":")),
                                                      "showPermissionSets": "false"},
                             ttl=3600, weight=20, transform=parse).value
        except UpstreamError as exc:
            if exc.status != 400:
                raise
            if len(pairs) > 1:  # um par inexistente derruba o pedido inteiro: consulta um a um
                return {k: v for p in pairs for k, v in self.exchange_info([p]).items()}
            info = {}
        return {p: info.get(p) or PairInfo(p, "INEXISTENTE", None, None) for p in pairs}

    def price(self, symbol) -> Quote:
        """Último preço (GET /api/v3/ticker/price). A resposta não traz hora: a referência é o Date do servidor."""
        asset, pair = self._pair(symbol)

        def parse(payload):
            return dec(payload["price"]) if payload["symbol"] == pair else None

        f = self._get("/api/v3/ticker/price", {"symbol": pair}, ttl=10, weight=2, transform=parse)
        reference = f.server_time or f.fetched_at
        quality = {"par": pair, "referencia": "Date do servidor" if f.server_time else "hora da coleta"}
        return Quote(self.name, asset.symbol, f"binance:{pair}", asset.binance_quote, f.value, reference, f.fetched_at,
                     quality=quality, status=status_at(self.name, reference, self._http.clock()))

    def stats_24h(self, symbol) -> Quote:
        """Janela móvel de 24 h (GET /api/v3/ticker/24hr); closeTime é a hora de referência."""
        asset, pair = self._pair(symbol)

        def parse(p):
            if p["symbol"] != pair:
                return None
            return (dec(p["lastPrice"]), from_ms(p["closeTime"]), dec(p["volume"]), dec(p["quoteVolume"]),
                    dec(p["priceChangePercent"]), dec(p["highPrice"]), dec(p["lowPrice"]))

        f = self._get("/api/v3/ticker/24hr", {"symbol": pair}, ttl=30, weight=2, transform=parse)
        price, reference, volume, quote_volume, change, high, low = f.value
        return Quote(self.name, asset.symbol, f"binance:{pair}", asset.binance_quote, price, reference, f.fetched_at,
                     volume_24h=volume, quote_volume_24h=quote_volume, change_24h_pct=change, high_24h=high,
                     low_24h=low, quality={"par": pair, "referencia": "closeTime do ticker 24h"},
                     status=status_at(self.name, reference, self._http.clock()))

    def klines(self, symbol, interval: str = "1h", limit: int = 500) -> CandleSeries:
        """Velas (GET /api/v3/klines). A última pode estar em andamento (close_time no futuro)."""
        asset, pair = self._pair(symbol)
        if interval not in self.INTERVALS:
            raise ValueError("intervalo deve ser 1h, 4h ou 1d")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit deve estar entre 1 e 500")

        def parse(rows):
            candles = tuple(sorted((Candle(from_ms(r[0]), from_ms(r[6]), dec(r[1]), dec(r[2]), dec(r[3]), dec(r[4]),
                                           dec(r[5]), dec(r[7])) for r in rows), key=lambda c: c.open_time))
            if any(None in (c.open, c.high, c.low, c.close, c.volume, c.quote_volume) for c in candles):
                return None
            return candles

        f = self._get("/api/v3/klines", {"symbol": pair, "interval": interval, "limit": limit}, ttl=60, weight=2,
                      transform=parse)
        return CandleSeries(self.name, asset.symbol, pair, interval, asset.binance_quote, f.fetched_at, f.value)


# ---------- CoinGecko Demo (chave própria) ----------

_KEY_RE = re.compile(r"[A-Za-z0-9_-]{8,128}")


class _Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<chave oculta>"

    __str__ = __repr__


class CoinGeckoDemo:
    """CoinGecko plano Demo. A chave só vai no cabeçalho x-cg-demo-api-key; sem chave, nada é chamado.

    Cota local (em memória; quem persiste pode semear com used_month): cada envio conta 1 crédito, mesmo se falhar
    (conservador: o CoinGecko só debita respostas 200). Chamadas agendadas passam purpose="poll" e são recusadas
    primeiro, preservando `poll_reserve` do mês para consultas da pessoa.
    """
    name = "coingecko"
    requires_key = True
    docs_url = "https://docs.coingecko.com/demo/reference/authentication"
    attribution = "Data provided by CoinGecko (https://www.coingecko.com)"
    BASE = "https://api.coingecko.com/api/v3"
    VS = {"brl": "BRL", "usd": "USD"}

    def __init__(self, api_key: str | None = None, *, month_limit: int = 10000, minute_limit: int = 100,
                 poll_reserve: Decimal = Decimal("0.15"), used_month: int = 0, **http_options):
        if api_key is not None and not _KEY_RE.fullmatch(api_key):
            raise ValueError("chave do CoinGecko em formato inválido")
        self._key = _Secret(api_key) if api_key else None
        self.configured = self._key is not None
        self.month_limit, self.minute_limit, self.poll_reserve = month_limit, minute_limit, Decimal(poll_reserve)
        http_options.setdefault("min_interval", 0.6)  # 100/min
        self._http = _Http(self.name, self.BASE, **http_options)
        self._http.health.configured = self.configured
        self._used_month, self._month = used_month, ""
        self._used_minute, self._minute = 0, None
        self._roll(self._http.clock(), keep_month=True)

    def __repr__(self) -> str:
        return f"CoinGeckoDemo(configured={self.configured})"

    def health(self) -> dict:
        return self._http.health.as_dict()

    # cota
    def _roll(self, now: datetime, keep_month: bool = False) -> None:
        month, minute = now.strftime("%Y-%m"), now.replace(second=0, microsecond=0)
        if month != self._month:
            self._month = month
            if not keep_month:
                self._used_month = 0
        if minute != self._minute:
            self._minute, self._used_minute = minute, 0

    def _poll_cap(self) -> int:
        return int(self.month_limit * (1 - self.poll_reserve))

    def quota(self) -> dict:
        now = self._http.clock()
        self._roll(now)
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        reset = (first.replace(year=first.year + 1, month=1) if first.month == 12
                 else first.replace(month=first.month + 1))
        return {"used_month": self._used_month, "limit_month": self.month_limit, "used_minute": self._used_minute,
                "limit_minute": self.minute_limit, "remaining": max(self.month_limit - self._used_month, 0),
                "remaining_for_poll": max(self._poll_cap() - self._used_month, 0), "reset_at": iso(reset),
                "minute_reset_at": iso(_next_minute(now))}

    def _spend(self, purpose: str) -> None:
        self._roll(self._http.clock())
        if self._used_month + 1 > self.month_limit:
            raise QuotaExceeded("coingecko: cota mensal esgotada")
        if purpose == "poll" and self._used_month + 1 > self._poll_cap():
            raise QuotaExceeded("coingecko: reserva do mês guardada para consultas da pessoa")
        if self._used_minute + 1 > self.minute_limit:
            raise QuotaExceeded("coingecko: limite por minuto atingido")
        self._used_month += 1
        self._used_minute += 1

    def _get(self, path, params, *, ttl, purpose, transform, max_bytes=MAX_BYTES) -> Fetched:
        if not self.configured:
            raise NotConfigured("coingecko: sem chave Demo configurada")
        if purpose not in ("poll", "user"):
            raise ValueError("purpose deve ser poll ou user")
        return self._http.get(path, params, ttl=ttl, transform=transform, max_bytes=max_bytes,
                              headers={"x-cg-demo-api-key": self._key.reveal()},
                              before_send=lambda: self._spend(purpose))

    def _vs(self, vs) -> str:
        if vs not in self.VS:
            raise ValueError("moeda deve ser brl ou usd")
        return vs

    @staticmethod
    def _symbol(coin_id: str) -> str:
        asset = assets.by_coingecko_id(coin_id)
        return asset.symbol if asset else coin_id

    def _quote(self, coin_id, vs, price, reference, fetched_at, **extra) -> Quote:
        status = "unavailable" if price is None or reference is None else \
            status_at(self.name, reference, self._http.clock())
        return Quote(self.name, self._symbol(coin_id), f"coingecko:{coin_id}/{vs}", self.VS[vs], price, reference,
                     fetched_at, quality={"atribuicao": self.attribution}, status=status, **extra)

    def simple_price(self, ids, vs=("brl", "usd"), *, purpose: str = "user") -> list[Quote]:
        """GET /simple/price com variação, volume e valor de mercado de 24 h; referência = last_updated_at."""
        ids = sorted({assets.validate_coingecko_id(i) for i in ids})
        vs = [self._vs(v) for v in dict.fromkeys(vs)]
        if not ids or not vs:
            return []

        def parse(payload):
            out = {}
            for cid in ids:
                row = payload.get(cid) or {}
                ref = from_s(row["last_updated_at"]) if row.get("last_updated_at") is not None else None
                out[cid] = (ref, tuple((v, dec(row.get(v)), dec(row.get(f"{v}_24h_vol")),
                                        dec(row.get(f"{v}_24h_change")), dec(row.get(f"{v}_market_cap"))) for v in vs))
            return out

        f = self._get("/simple/price", {"ids": ",".join(ids), "vs_currencies": ",".join(vs),
                                        "include_market_cap": "true", "include_24hr_vol": "true",
                                        "include_24hr_change": "true", "include_last_updated_at": "true",
                                        "precision": "full"}, ttl=60, purpose=purpose, transform=parse)
        return [self._quote(cid, v, price, ref, f.fetched_at, quote_volume_24h=vol, change_24h_pct=chg, market_cap=cap)
                for cid, (ref, rows) in f.value.items() for v, price, vol, chg, cap in rows]

    def markets(self, ids, vs: str = "brl", *, purpose: str = "user") -> list[Quote]:
        """GET /coins/markets: preço, valor de mercado, volume, máxima/mínima e variação de 24 h."""
        ids = sorted({assets.validate_coingecko_id(i) for i in ids})
        vs = self._vs(vs)
        if not ids:
            return []

        def parse(rows):
            return tuple((r["id"], dec(r.get("current_price")), from_iso(r["last_updated"]) if r.get("last_updated")
                          else None, dec(r.get("total_volume")), dec(r.get("price_change_percentage_24h")),
                          dec(r.get("market_cap")), dec(r.get("high_24h")), dec(r.get("low_24h")))
                         for r in rows if r.get("id") in ids)

        f = self._get("/coins/markets", {"vs_currency": vs, "ids": ",".join(ids), "per_page": 250, "page": 1,
                                         "precision": "full"}, ttl=60, purpose=purpose, transform=parse)
        return [self._quote(cid, vs, price, ref, f.fetched_at, quote_volume_24h=vol, change_24h_pct=chg,
                            market_cap=cap, high_24h=high, low_24h=low)
                for cid, price, ref, vol, chg, cap, high, low in f.value]

    def market_chart(self, coin_id, vs: str, days: int, *, purpose: str = "user") -> list[ChartPoint]:
        """GET /coins/{id}/market_chart. Demo: no máximo 365 dias. Granularidade automática (5 min / 1 h / 1 dia)."""
        coin_id, vs = assets.validate_coingecko_id(coin_id), self._vs(vs)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
            raise ValueError("days deve estar entre 1 e 365 no plano Demo")

        def parse(p):
            caps = {int(t): dec(v) for t, v in p.get("market_caps", [])}
            vols = {int(t): dec(v) for t, v in p.get("total_volumes", [])}
            return tuple(ChartPoint(from_ms(int(t)), dec(v), caps.get(int(t)), vols.get(int(t)))
                         for t, v in p["prices"] if v is not None)

        return list(self._get(f"/coins/{coin_id}/market_chart", {"vs_currency": vs, "days": days, "precision": "full"},
                              ttl=300 if days <= 1 else 3600, purpose=purpose, transform=parse).value)

    def coins_list(self, *, purpose: str = "user") -> list[CoinRef]:
        """GET /coins/list (cache de 24 h). Só entram ids no formato aceito."""
        def parse(rows):
            return tuple(CoinRef(r["id"], clean_text(r.get("symbol"), 20), clean_text(r.get("name")))
                         for r in rows if isinstance(r.get("id"), str) and assets.COINGECKO_ID_RE.fullmatch(r["id"]))

        return list(self._get("/coins/list", {}, ttl=86400, purpose=purpose, transform=parse,
                              max_bytes=16 * 1024 * 1024).value)


# ---------- DefiLlama (gratuita, sem chave) ----------

def _tvl_points(rows, value_key: str, keep: int = 400) -> tuple[TvlPoint, ...]:
    points = sorted((TvlPoint(from_s(r["date"]), dec(r[value_key])) for r in rows if r.get(value_key) is not None),
                    key=lambda p: p.time)
    return tuple(points[-keep:])


class DefiLlama:
    name = "defillama"
    requires_key = False
    configured = True
    docs_url = "https://api-docs.defillama.com/"
    attribution = "Dados de TVL: DefiLlama (https://defillama.com)"
    BASE = "https://api.llama.fi"

    def __init__(self, **http_options):
        http_options.setdefault("min_interval", 1.0)
        self._http = _Http(self.name, self.BASE, **http_options)

    def health(self) -> dict:
        return self._http.health.as_dict()

    def protocols(self) -> list[ProtocolInfo]:
        """GET /protocols (dezenas de MB): guarda só nome, slug, categoria, chains, TVL e variações de 1 e 7 dias."""
        def parse(rows):
            out = []
            for p in rows:
                slug = p.get("slug")
                if not isinstance(slug, str) or not assets.LLAMA_SLUG_RE.fullmatch(slug):
                    continue
                try:
                    out.append(ProtocolInfo(slug, clean_text(p.get("name")), clean_text(p.get("category"), 40),
                                            tuple(clean_text(c, 40) for c in (p.get("chains") or [])[:60]),
                                            dec(p.get("tvl")), dec(p.get("change_1d")), dec(p.get("change_7d"))))
                except DataError:
                    continue  # um item malformado não derruba a lista
            return tuple(out)

        return list(self._http.get("/protocols", ttl=3600, transform=parse, max_bytes=96 * 1024 * 1024).value)

    def protocol(self, slug) -> ProtocolDetail:
        """GET /protocol/{slug}: identificação e histórico de TVL (últimos 400 pontos)."""
        slug = assets.validate_slug(slug)

        def parse(p):
            return ProtocolDetail(slug, clean_text(p.get("name")), clean_text(p.get("category"), 40),
                                  tuple(clean_text(c, 40) for c in (p.get("chains") or [])[:60]),
                                  _tvl_points(p.get("tvl") or [], "totalLiquidityUSD"))

        return self._http.get(f"/protocol/{slug}", ttl=3600, transform=parse, max_bytes=96 * 1024 * 1024).value

    def chains(self) -> list[ChainInfo]:
        """GET /v2/chains: TVL atual por chain."""
        def parse(rows):
            return tuple(ChainInfo(clean_text(r["name"], 40), dec(r.get("tvl")), clean_text(r.get("tokenSymbol"), 15),
                                   r["gecko_id"] if isinstance(r.get("gecko_id"), str)
                                   and assets.COINGECKO_ID_RE.fullmatch(r["gecko_id"]) else None)
                         for r in rows)

        return list(self._http.get("/v2/chains", ttl=3600, transform=parse).value)

    def chain_tvl_history(self, chain: str | None = None) -> list[TvlPoint]:
        """GET /v2/historicalChainTvl[/{chain}]: TVL diário (sem liquid staking nem dupla contagem)."""
        path = "/v2/historicalChainTvl" + ("" if chain is None else "/" + quote(assets.validate_chain(chain), safe=""))
        return list(self._http.get(path, ttl=3600, transform=lambda rows: _tvl_points(rows, "tvl", keep=4000),
                                   max_bytes=8 * 1024 * 1024).value)
