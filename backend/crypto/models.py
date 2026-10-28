# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tipos normalizados de mercado cripto (sem rede): cotação, vela, TVL, frescor e conversão explícita de moeda.

Todo número é Decimal: o JSON das fontes é lido com parse_float=Decimal, então "0.00001234" chega exato.
Preço em USDT nunca é rotulado USD; trocar de moeda só via convert(), que exige a taxa, a fonte e o frescor dela.
Textos de terceiros (nomes, categorias) passam por clean_text e nunca devem ir crus para um prompt.
"""

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

UTC = timezone.utc
QUOTE_CURRENCIES = frozenset({"USDT", "USD", "BRL"})
STATUSES = frozenset({"fresh", "stale", "unavailable"})
# Idade máxima antes de o dado virar "stale". Binance é tempo real; o CoinGecko atualiza em minutos; o TVL do
# DefiLlama e a PTAX do BCB (taxa USD→BRL) são diários.
MAX_AGE = {"binance": timedelta(minutes=10), "coingecko": timedelta(minutes=30),
           "defillama": timedelta(hours=36), "bcb_sgs": timedelta(days=4)}
DEFAULT_MAX_AGE = timedelta(minutes=10)

_NUMBER = re.compile(r"-?\d{1,30}(\.\d{1,30})?([eE][-+]?\d{1,3})?")
_LIMIT = Decimal(10) ** 20
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class DataError(ValueError):
    """Payload do fornecedor fora do formato esperado."""


def _reject_constant(name):
    raise DataError(f"constante não numérica no JSON: {name}")


def json_loads(body: bytes):
    """JSON → objetos Python com Decimal no lugar de float (NaN/Infinity recusados)."""
    return json.loads(body, parse_float=Decimal, parse_constant=_reject_constant)


def dec(value) -> Decimal | None:
    """Número vindo de fornecedor → Decimal finito e plausível; None continua None. float binário é recusado."""
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise DataError("número em formato não aceito")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str) and _NUMBER.fullmatch(value.strip()):
        result = Decimal(value.strip())
    else:
        raise DataError("número inválido")
    if not result.is_finite() or abs(result) >= _LIMIT:
        raise DataError("número fora do intervalo")
    return result


def _epoch(value, scale: int) -> datetime:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value // scale < 2**33:
        raise DataError("instante inválido")
    return _EPOCH + timedelta(milliseconds=value * 1000 // scale)


def from_ms(value) -> datetime:
    return _epoch(value, 1000)


def from_s(value) -> datetime:
    return _epoch(value, 1)


def from_iso(value) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise DataError("data inválida")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise DataError("data sem fuso")
    return parsed.astimezone(UTC)


def clean_text(value, limit: int = 80) -> str:
    """Texto de terceiros: só caracteres imprimíveis, tamanho limitado."""
    return "".join(ch for ch in str(value or "") if ch.isprintable())[:limit].strip()


def iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat(timespec="seconds") if moment else None


def status_at(source: str, reference_time: datetime | None, now: datetime,
              max_age: timedelta | None = None) -> str:
    if reference_time is None:
        return "unavailable"
    return "stale" if now - reference_time > (max_age or MAX_AGE.get(source, DEFAULT_MAX_AGE)) else "fresh"


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal        # na moeda-base (ex.: BTC)
    quote_volume: Decimal  # na moeda de cotação do par (ex.: USDT)


@dataclass(frozen=True)
class CandleSeries:
    """Velas de um par com a origem delas; se comporta como sequência de Candle."""
    source: str
    asset_symbol: str
    pair: str
    interval: str
    quote_currency: str
    fetched_at: datetime
    candles: tuple[Candle, ...]

    def __len__(self):
        return len(self.candles)

    def __iter__(self):
        return iter(self.candles)

    def __getitem__(self, index):
        return self.candles[index]


@dataclass(frozen=True)
class Quote:
    source: str
    asset_symbol: str
    stable_id: str                   # identificador estável do instrumento, ex.: "binance:BTCUSDT"
    quote_currency: str              # USDT | USD | BRL
    price: Decimal | None
    reference_time: datetime | None  # hora do dado segundo o fornecedor (UTC)
    fetched_at: datetime             # hora em que nós buscamos (UTC)
    volume_24h: Decimal | None = None        # na moeda-base
    quote_volume_24h: Decimal | None = None  # na moeda de cotação
    change_24h_pct: Decimal | None = None
    market_cap: Decimal | None = None        # na moeda de cotação
    high_24h: Decimal | None = None
    low_24h: Decimal | None = None
    quality: dict = field(default_factory=dict, hash=False)
    status: str = "fresh"

    def __post_init__(self):
        if self.quote_currency not in QUOTE_CURRENCIES:
            raise ValueError("moeda de cotação não suportada")
        if self.status not in STATUSES:
            raise ValueError("status inválido")
        if self.price is None and self.status != "unavailable":
            raise ValueError("cotação sem preço precisa ser 'unavailable'")

    def with_status(self, now: datetime, max_age: timedelta | None = None) -> "Quote":
        """Reavalia o frescor no instante `now` (cotações guardadas envelhecem)."""
        status = "unavailable" if self.price is None else status_at(self.source, self.reference_time, now, max_age)
        return replace(self, status=status)


class ConversionRefused(ValueError):
    """Conversão de moeda sem taxa, com taxa do par errado ou com taxa desatualizada."""


def convert(quote: Quote, to_currency: str, rate_quote: Quote | None, rate_source: str | None = None, *,
            now: datetime, max_rate_age: timedelta | None = None) -> Quote:
    """Converte `quote` para `to_currency` usando `rate_quote` (preço de 1 quote.quote_currency em to_currency).

    Ex.: USDT→USD exige a cotação USDT/USD (CoinGecko "tether" em usd); USD→BRL exige USD/BRL (ex.: PTAX do BCB,
    montada como Quote(source="bcb_sgs", asset_symbol="USD", quote_currency="BRL", ...)). A taxa usada, a fonte e a
    hora dela ficam em quality["conversao"]; a hora de referência do resultado é a mais antiga das duas.
    """
    if to_currency not in QUOTE_CURRENCIES:
        raise ConversionRefused("moeda de destino não suportada")
    if to_currency == quote.quote_currency:
        return quote
    if quote.price is None:
        raise ConversionRefused("cotação de origem indisponível")
    if rate_quote is None or rate_quote.price is None:
        raise ConversionRefused(f"taxa {quote.quote_currency}→{to_currency} ausente")
    if (rate_quote.asset_symbol, rate_quote.quote_currency) != (quote.quote_currency, to_currency):
        raise ConversionRefused(f"taxa informada não é {quote.quote_currency}→{to_currency}")
    if status_at(rate_quote.source, rate_quote.reference_time, now, max_rate_age) != "fresh":
        raise ConversionRefused(f"taxa {quote.quote_currency}→{to_currency} desatualizada")
    rate = rate_quote.price
    if rate <= 0:
        raise ConversionRefused("taxa não positiva")

    def scaled(value):
        return None if value is None else value * rate

    reference = min(t for t in (quote.reference_time, rate_quote.reference_time) if t is not None)
    conversion = {"de": quote.quote_currency, "para": to_currency, "taxa": str(rate),
                  "fonte": rate_source or rate_quote.source, "referencia_taxa": iso(rate_quote.reference_time)}
    converted = replace(quote, stable_id=f"{quote.stable_id}>{to_currency}", quote_currency=to_currency,
                        price=quote.price * rate, quote_volume_24h=scaled(quote.quote_volume_24h),
                        market_cap=scaled(quote.market_cap), high_24h=scaled(quote.high_24h),
                        low_24h=scaled(quote.low_24h), reference_time=reference,
                        quality={**quote.quality, "conversao": conversion})
    return converted.with_status(now)


@dataclass(frozen=True)
class PairInfo:
    symbol: str
    status: str               # TRADING, HALT, BREAK... ou INEXISTENTE quando a Binance não conhece o par
    base_asset: str | None
    quote_asset: str | None

    @property
    def trading(self) -> bool:
        return self.status == "TRADING"


@dataclass(frozen=True)
class ChartPoint:
    time: datetime
    price: Decimal
    market_cap: Decimal | None
    volume: Decimal | None


@dataclass(frozen=True)
class CoinRef:
    id: str
    symbol: str
    name: str


@dataclass(frozen=True)
class TvlPoint:
    time: datetime
    tvl: Decimal  # USD


@dataclass(frozen=True)
class ProtocolInfo:
    slug: str
    name: str
    category: str
    chains: tuple[str, ...]
    tvl: Decimal | None
    change_1d: Decimal | None  # % em 1 dia
    change_7d: Decimal | None  # % em 7 dias


@dataclass(frozen=True)
class ProtocolDetail:
    slug: str
    name: str
    category: str
    chains: tuple[str, ...]
    tvl_history: tuple[TvlPoint, ...]


@dataclass(frozen=True)
class ChainInfo:
    name: str
    tvl: Decimal | None
    token_symbol: str
    gecko_id: str | None
