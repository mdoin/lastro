# SPDX-License-Identifier: AGPL-3.0-or-later
"""Motor determinístico de sinais cripto: funções puras sobre séries Decimal, sem rede e sem IA.

Cada indicador devolve Measure(valor, motivo): com amostra insuficiente o valor é None e o motivo diz por quê —
nada é calculado com poucos pontos. detect() transforma indicadores em Signal com evidências numéricas, fontes,
qualidade do dado e uma hipótese neutra (observação a investigar, nunca recomendação).

Unidades: retornos e variações em % no período; volatilidade realizada = desvio-padrão amostral dos log-retornos
POR VELA, em % (anualiza só se periods_per_year for informado); volume relativo em "vezes a mediana"; concentração
como fração 0..1.

Severidade (limiares em THRESHOLDS, escalados pela sensibilidade da pessoa). O movimento de preço é medido em
z-score: o log-retorno da última vela fechada contra a média e o desvio das até 168 velas anteriores — 3% numa
semana calma pesa mais que 3% numa semana agitada.
- preco: |z| ≥ z → "atencao"; |z| ≥ z_risk → "risco"; "conselho" só se |z| ≥ z E volume relativo ≥ rel_volume
  E dado fresco com qualidade "boa" E o ativo está na carteira informada ou na lista de acompanhamento.
- volume: volume relativo ≥ rel_volume sem movimento de preço → "comum" ("atencao" se ≥ 2×); muito abaixo do
  usual (≤ 1/(2×rel_volume)) → "liquidez"/"comum".
- volatilidade: volatilidade das últimas 24 velas ≥ vol_ratio × a das anteriores → "atencao".
- stablecoin: |preço − paridade|/paridade ≥ peg_pct → "atencao"; ≥ peg_risk_pct → "risco"; "conselho" só com
  risco + dado fresco medido na moeda da paridade (USD; contra USDT é "limitada") + ativo na carteira/lista.
- defi: |variação do TVL em 7 dias| ≥ tvl_pct → "atencao"; ≥ tvl_risk_pct → "risco".
- concentracao: fatia do ativo na carteira informada acima do limite da pessoa → "risco".
Qualidade "limitada" (dado velho ou medido em moeda substituta) nunca passa de "risco"; "insuficiente" (dado
muito velho) fica em "comum". Dado velho nunca gera "conselho".
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from statistics import median
from typing import NamedTuple, Sequence

from .assets import Asset
from .models import DEFAULT_MAX_AGE, MAX_AGE, UTC, Candle, CandleSeries, Quote, TvlPoint, status_at

CATEGORIES = ("preco", "volume", "volatilidade", "concentracao", "liquidez", "stablecoin", "defi")
SEVERITIES = ("comum", "atencao", "risco", "conselho")
QUALITY_WEIGHT = {"boa": Decimal("1"), "limitada": Decimal("0.6"), "insuficiente": Decimal("0.2")}
QUALITY_CAP = {"boa": "conselho", "limitada": "risco", "insuficiente": "comum"}
WINDOWS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "24h": timedelta(days=1), "7d": timedelta(days=7)}
Z_LOOKBACK, Z_MIN_POINTS, VOL_SHORT = 168, 30, 24
_FORBIDDEN = re.compile(r"compr[ae]|vend[ae]|barat|oportunidade|imperd[ií]vel", re.IGNORECASE)
_HUNDRED = Decimal(100)


class Measure(NamedTuple):
    value: Decimal | None
    reason: str = ""


def _none(reason: str) -> Measure:
    return Measure(None, reason)


def _insufficient(have: int, need: int, what: str = "pontos") -> Measure:
    return _none(f"amostra insuficiente: {have} {what}, mínimo {need}")


# ---------- indicadores ----------

def window_return(closes: Sequence[Decimal], periods: int) -> Measure:
    """Variação % entre o preço de `periods` velas atrás e o último."""
    if periods < 1:
        return _none("janela menor que o intervalo das velas")
    if len(closes) < periods + 1:
        return _insufficient(len(closes), periods + 1, "preços")
    old = closes[-1 - periods]
    if old <= 0:
        return _none("preço não positivo")
    return Measure((closes[-1] / old - 1) * _HUNDRED)


def returns_by_window(candles: Sequence[Candle]) -> dict[str, Measure]:
    """Retornos de 1 h, 4 h, 24 h e 7 d quando o intervalo das velas e a amostra permitem."""
    if len(candles) < 2:
        return {name: _insufficient(len(candles), 2, "velas") for name in WINDOWS}
    step = candles[-1].open_time - candles[-2].open_time
    closes = [c.close for c in candles]
    return {name: _none("janela não é múltiplo do intervalo das velas") if span % step
            else window_return(closes, span // step) for name, span in WINDOWS.items()}


def log_returns(closes: Sequence[Decimal]) -> list[Decimal]:
    with localcontext() as ctx:
        ctx.prec = 34
        return [(b / a).ln() for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]


def _mean_stdev(xs: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    with localcontext() as ctx:
        ctx.prec = 34
        mean = sum(xs, Decimal(0)) / len(xs)
        return mean, (sum(((x - mean) ** 2 for x in xs), Decimal(0)) / (len(xs) - 1)).sqrt()


def realized_volatility(closes: Sequence[Decimal], *, min_points: int = 20,
                        periods_per_year: int | None = None) -> Measure:
    """Desvio-padrão amostral dos log-retornos, em % por vela (× √periods_per_year se informado)."""
    rets = log_returns(closes)
    if len(rets) < min_points:
        return _insufficient(len(rets), min_points, "retornos")
    _, sd = _mean_stdev(rets)
    if periods_per_year:
        sd *= Decimal(periods_per_year).sqrt()
    return Measure(sd * _HUNDRED)


def relative_volume(candles: Sequence[Candle], *, min_points: int = 7, lookback: int = 30) -> Measure:
    """Volume da última vela ÷ mediana de janelas comparáveis: para velas intradiárias, a mesma hora dos dias
    anteriores (evita confundir o ciclo do dia com anomalia); para velas diárias, os dias anteriores."""
    if len(candles) < 2:
        return _insufficient(len(candles), 2, "velas")
    last, prior = candles[-1], list(candles[:-1])
    if last.open_time - prior[-1].open_time < timedelta(days=1):
        prior = [c for c in prior if (last.open_time - c.open_time) % timedelta(days=1) == timedelta(0)]
    sample = [c.volume for c in prior][-lookback:]
    if len(sample) < min_points:
        return _insufficient(len(sample), min_points, "janelas comparáveis")
    base = median(sample)
    if base <= 0:
        return _none("volume de referência zero")
    return Measure(last.volume / base)


def max_drawdown(closes: Sequence[Decimal], *, min_points: int = 10) -> Measure:
    """Maior queda % de um pico até um vale posterior na janela (número positivo)."""
    if len(closes) < min_points:
        return _insufficient(len(closes), min_points, "preços")
    peak, worst = closes[0], Decimal(0)
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            worst = max(worst, (peak - c) / peak)
    return Measure(worst * _HUNDRED)


def correlation(a: Sequence[Candle], b: Sequence[Candle], *, min_points: int = 30) -> Measure:
    """Pearson entre os log-retornos de dois ativos, só nos instantes presentes nas duas séries."""
    closes_b = {c.open_time: c.close for c in b}
    aligned = [(c.close, closes_b[c.open_time]) for c in a if c.open_time in closes_b]
    if len(aligned) - 1 < min_points:
        return _insufficient(max(len(aligned) - 1, 0), min_points, "retornos alinhados")
    ra, rb = log_returns([x for x, _ in aligned]), log_returns([y for _, y in aligned])
    if len(ra) != len(rb) or len(ra) < min_points:
        return _none("preços não positivos na série")
    (ma, sa), (mb, sb) = _mean_stdev(ra), _mean_stdev(rb)
    if sa == 0 or sb == 0:
        return _none("série sem variação")
    with localcontext() as ctx:
        ctx.prec = 34
        cov = sum(((x - ma) * (y - mb) for x, y in zip(ra, rb)), Decimal(0)) / (len(ra) - 1)
        return Measure(cov / (sa * sb))


def peg_deviation(price: Decimal | None, peg: Decimal | None) -> Measure:
    """|preço − paridade| / paridade, em %."""
    if price is None:
        return _none("preço indisponível")
    if peg is None or peg <= 0:
        return _none("ativo sem paridade")
    return Measure(abs(price - peg) / peg * _HUNDRED)


def tvl_change(points: Sequence[TvlPoint], days: int) -> Measure:
    """Variação % do TVL entre o ponto de `days` dias antes do último e o último (lacuna > 2 dias = recusa)."""
    pts = sorted(points, key=lambda p: p.time)
    if len(pts) < 2:
        return _insufficient(len(pts), 2)
    target = pts[-1].time - timedelta(days=days)
    past = [p for p in pts if p.time <= target]
    if not past:
        return _none("histórico mais curto que a janela")
    if target - past[-1].time > timedelta(days=2):
        return _none("lacuna no histórico")
    if past[-1].tvl <= 0:
        return _none("TVL de referência zero")
    return Measure((pts[-1].tvl / past[-1].tvl - 1) * _HUNDRED)


def concentration(holdings: dict[str, Decimal] | None, symbol: str) -> Measure:
    """Fatia (0..1) do ativo no total informado (valores na mesma moeda)."""
    if holdings is None:
        return _none("carteira não informada")
    total = sum((v for v in holdings.values() if v > 0), Decimal(0))
    if total <= 0:
        return _none("carteira vazia")
    return Measure(max(holdings.get(symbol, Decimal(0)), Decimal(0)) / total)


# ---------- preferências, sinal e evento ----------

@dataclass(frozen=True)
class Thresholds:
    z: Decimal
    z_risk: Decimal
    rel_volume: Decimal
    vol_ratio: Decimal
    peg_pct: Decimal
    peg_risk_pct: Decimal
    tvl_pct: Decimal
    tvl_risk_pct: Decimal


THRESHOLDS = {s: Thresholds(*(Decimal(v) for v in vals)) for s, vals in {
    "baixa": ("3.0", "4.5", "3.0", "2.5", "0.5", "2.0", "30", "50"),
    "media": ("2.5", "4.0", "2.0", "2.0", "0.3", "1.0", "20", "40"),
    "alta": ("2.0", "3.5", "1.5", "1.5", "0.1", "0.5", "10", "25"),
}.items()}


@dataclass(frozen=True)
class Prefs:
    sensitivity: str = "media"                 # baixa | media | alta
    muted: frozenset = frozenset()             # categorias silenciadas
    concentration_limit: Decimal = Decimal("0.25")
    watchlist: frozenset = frozenset()         # símbolos que a pessoa acompanha

    def __post_init__(self):
        if self.sensitivity not in THRESHOLDS:
            raise ValueError("sensibilidade deve ser baixa, media ou alta")
        if not set(self.muted) <= set(CATEGORIES):
            raise ValueError("categoria silenciada desconhecida")
        if not Decimal(0) < self.concentration_limit <= 1:
            raise ValueError("limite de concentração deve estar entre 0 e 1")


@dataclass(frozen=True)
class TvlInput:
    label: str                       # slug do protocolo ou nome da chain (já validados na coleta)
    points: Sequence[TvlPoint]
    source: str = "defillama"
    fetched_at: datetime | None = None


@dataclass
class Signal:
    category: str
    asset: str
    indicators: dict[str, str]
    evidence: list[str]
    sources: list[dict]
    observed_at: datetime
    severity: str
    data_quality: str
    relevance: Decimal
    hypothesis: str
    dedup_key: str
    direction: str = "neutra"  # alta | queda | neutra

    def __post_init__(self):
        if self.category not in CATEGORIES or self.severity not in SEVERITIES or self.data_quality not in QUALITY_CAP:
            raise ValueError("categoria, severidade ou qualidade inválida")
        if _FORBIDDEN.search(self.hypothesis):
            raise ValueError("hipótese com linguagem de recomendação")


@dataclass
class Event:
    asset: str
    start: datetime
    end: datetime
    signals: list[Signal] = field(default_factory=list)

    @property
    def severity(self) -> str:
        return max((s.severity for s in self.signals), key=SEVERITIES.index)

    @property
    def relevance(self) -> Decimal:
        return max(s.relevance for s in self.signals)

    @property
    def direction(self) -> str:
        found = {s.direction for s in self.signals} - {"neutra"}
        return found.pop() if len(found) == 1 else ("misto" if found else "neutra")

    @property
    def dedup_key(self) -> str:
        return self.signals[0].dedup_key

    @property
    def categories(self) -> list[str]:
        return sorted({s.category for s in self.signals})


def group(signals: Sequence[Signal], window: timedelta) -> list[Event]:
    """Junta sinais do mesmo ativo observados até `window` depois do primeiro do evento (queda, repique e nova
    queda viram um só evento): menos alertas repetidos."""
    events, current = [], {}
    for s in sorted(signals, key=lambda s: (s.asset, s.observed_at)):
        event = current.get(s.asset)
        if event is None or s.observed_at - event.start > window:
            event = current[s.asset] = Event(s.asset, s.observed_at, s.observed_at)
            events.append(event)
        event.signals.append(s)
        event.end = s.observed_at
    return sorted(events, key=lambda e: e.start)


def cooldown_ok(last_event_time: datetime | None, now: datetime, cooldown: timedelta) -> bool:
    return last_event_time is None or now - last_event_time >= cooldown


# ---------- detecção ----------

def _fmt(value: Decimal, places: int = 2, signed: bool = False) -> str:
    text = f"{value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):{'+' if signed else ''}f}"
    return text.replace(".", ",")


def _when(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _ind(measure: Measure) -> str:
    return str(measure.value.quantize(Decimal("0.0001"))) if measure.value is not None else f"n/d ({measure.reason})"


def _bucket(moment: datetime, hours: int = 4) -> str:
    seconds = int(moment.timestamp()) // (hours * 3600) * hours * 3600
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y%m%dT%H")


def _cap(severity: str, quality: str) -> str:
    return min(severity, QUALITY_CAP[quality], key=SEVERITIES.index)


@dataclass(frozen=True)
class _Exposure:
    weight: Decimal
    engaged: bool  # na carteira ou na lista de acompanhamento
    evidence: str


def _exposure(symbol: str, prefs: Prefs, portfolio: dict | None) -> _Exposure:
    held = portfolio is not None and portfolio.get(symbol, Decimal(0)) > 0
    watched = symbol in prefs.watchlist
    unknown = "" if portfolio is not None else "; exposição desconhecida: carteira não informada"
    if held:
        return _Exposure(Decimal("1"), True, f"{symbol} está na carteira informada")
    if watched:
        return _Exposure(Decimal("0.7"), True, f"{symbol} está na lista de acompanhamento{unknown}")
    if portfolio is None:
        return _Exposure(Decimal("0.3"), False, "exposição desconhecida: carteira não informada")
    return _Exposure(Decimal("0.4"), False, f"a carteira informada não tem {symbol}")


def _relevance(magnitude: Decimal, quality: str, exposure: _Exposure) -> Decimal:
    magnitude = min(max(magnitude, Decimal(0)), Decimal(1))
    score = (magnitude * 5 + QUALITY_WEIGHT[quality] * 2 + exposure.weight * 3) / 10
    return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _series_quality(series: CandleSeries, last_close: datetime, step: timedelta, now: datetime) -> tuple[str, str]:
    max_age = MAX_AGE.get(series.source, DEFAULT_MAX_AGE)
    age = max(now - series.fetched_at, now - last_close - step)
    note = f"dados coletados em {_when(series.fetched_at)}, última vela fechada em {_when(last_close)}"
    if age <= max_age:
        return "boa", note
    level = "limitada" if age <= 6 * max_age else "insuficiente"
    return level, f"{note}: desatualizados (limite de {int(max_age.total_seconds() // 60)} min)"


def _market_signals(asset: Asset, series: CandleSeries, stats: Quote | None, th: Thresholds, exposure: _Exposure,
                    now: datetime) -> list[Signal]:
    closed = [c for c in series.candles if c.close_time <= now]  # a vela em andamento distorce volume e retorno
    if len(closed) < 2:
        return []
    step = closed[-1].open_time - closed[-2].open_time
    closes = [c.close for c in closed]
    rets = log_returns(closes[-(Z_LOOKBACK + 2):])
    if len(rets) < Z_MIN_POINTS + 1:
        return []
    mean, sd = _mean_stdev(rets[:-1])
    if sd == 0:
        return []
    z = (rets[-1] - mean) / sd
    move = window_return(closes, 1).value
    rv = relative_volume(closed)
    windows = returns_by_window(closed)
    quality, freshness = _series_quality(series, closed[-1].close_time, step, now)
    last = closed[-1]
    pair = f"{asset.symbol}/{series.quote_currency}"
    sources = [{"source": series.source, "reference_time": last.close_time.isoformat(),
                "fetched_at": series.fetched_at.isoformat()}]
    base_evidence = [f"{pair}: variação de {_fmt(move, signed=True)}% na vela de {series.interval} encerrada em "
                     f"{_when(last.close_time)} ({series.source})"]
    if windows["24h"].value is not None:
        base_evidence.append(f"variação em 24 h: {_fmt(windows['24h'].value, signed=True)}%")
    if stats is not None and stats.change_24h_pct is not None and stats.reference_time is not None:
        base_evidence.append(f"ticker 24 h ({stats.source}, ref. {_when(stats.reference_time)}): "
                             f"{_fmt(stats.change_24h_pct, signed=True)}%")
        sources.append({"source": stats.source, "reference_time": stats.reference_time.isoformat(),
                        "fetched_at": stats.fetched_at.isoformat()})
    rv_text = (f"volume da vela: {_fmt(rv.value)}× a mediana de janelas comparáveis" if rv.value is not None
               else f"volume relativo indisponível ({rv.reason})")
    indicators = {"retorno_ultima_vela_pct": _ind(Measure(move)), "zscore": _ind(Measure(z)),
                  "desvio_por_vela_pct": _ind(Measure(sd * _HUNDRED)), "volume_relativo": _ind(rv),
                  **{f"retorno_{k}_pct": _ind(m) for k, m in windows.items()}}
    common = dict(asset=asset.symbol, sources=sources, observed_at=now, data_quality=quality)
    signals = []

    if abs(z) >= th.z:
        direction = "queda" if z < 0 else "alta"
        abnormal = rv.value is not None and rv.value >= th.rel_volume
        if abnormal and quality == "boa" and exposure.engaged:
            severity = "conselho"
        else:
            severity = "risco" if abs(z) >= th.z_risk else "atencao"
        signals.append(Signal(
            category="preco", indicators=indicators, severity=_cap(severity, quality), direction=direction,
            evidence=base_evidence + [f"retorno da vela a {_fmt(z, signed=True)} desvios-padrão da média das "
                                      f"{len(rets) - 1} velas anteriores (desvio típico {_fmt(sd * _HUNDRED)}% "
                                      f"por vela)", rv_text, freshness, exposure.evidence],
            relevance=_relevance(abs(z) / (2 * th.z_risk), quality, exposure),
            hypothesis=f"O preço de {asset.symbol} teve {direction} de {_fmt(abs(move))}% na última vela de "
                       f"{series.interval}, fora do padrão recente ({_fmt(abs(z))} desvios). Precisa ser investigado "
                       "se há evento, notícia ou falha de dados que explique o movimento.",
            dedup_key=f"preco:{asset.symbol}:{direction}:{_bucket(last.close_time)}", **common))
    elif rv.value is not None and rv.value >= th.rel_volume:
        signals.append(Signal(
            category="volume", indicators=indicators, severity=_cap(
                "atencao" if rv.value >= 2 * th.rel_volume else "comum", quality),
            evidence=base_evidence + [rv_text, freshness, exposure.evidence],
            relevance=_relevance(rv.value / (4 * th.rel_volume), quality, exposure),
            hypothesis=f"O volume negociado de {asset.symbol} na última vela de {series.interval} ficou "
                       f"{_fmt(rv.value)}× acima do usual sem movimento de preço proporcional. Precisa ser "
                       "investigada a origem desse volume.",
            dedup_key=f"volume:{asset.symbol}:neutra:{_bucket(last.close_time)}", **common))
    elif rv.value is not None and rv.value <= 1 / (2 * th.rel_volume):
        signals.append(Signal(
            category="liquidez", indicators=indicators, severity="comum",
            evidence=base_evidence + [rv_text, freshness, exposure.evidence],
            relevance=_relevance(Decimal("0.3"), quality, exposure),
            hypothesis=f"O volume negociado de {asset.symbol} na última vela de {series.interval} ficou em "
                       f"{_fmt(rv.value)}× o usual. Precisa ser verificado se há menos liquidez ou falha na coleta.",
            dedup_key=f"liquidez:{asset.symbol}:neutra:{_bucket(last.close_time)}", **common))

    short = realized_volatility(closes[-(VOL_SHORT + 1):], min_points=VOL_SHORT)
    baseline = realized_volatility(closes[-(Z_LOOKBACK + 1):-VOL_SHORT], min_points=2 * VOL_SHORT)
    if short.value is not None and baseline.value:
        ratio = short.value / baseline.value
        if ratio >= th.vol_ratio:
            signals.append(Signal(
                category="volatilidade", severity=_cap("atencao", quality),
                indicators={"volatilidade_recente_pct": _ind(short), "volatilidade_anterior_pct": _ind(baseline),
                            "razao": _ind(Measure(ratio))},
                evidence=base_evidence + [f"oscilação típica de {_fmt(short.value)}% por vela nas últimas {VOL_SHORT} "
                                          f"velas contra {_fmt(baseline.value)}% antes ({_fmt(ratio)}×)", freshness,
                                          exposure.evidence],
                relevance=_relevance(ratio / (2 * th.vol_ratio), quality, exposure),
                hypothesis=f"A oscilação de {asset.symbol} nas últimas {VOL_SHORT} velas de {series.interval} está "
                           f"{_fmt(ratio)}× acima da anterior. Precisa ser investigado o que mudou no comportamento "
                           "do ativo.",
                dedup_key=f"volatilidade:{asset.symbol}:neutra:{_bucket(last.close_time)}", **common))
    return signals


def _peg_signals(asset: Asset, quote: Quote, th: Thresholds, exposure: _Exposure, now: datetime) -> list[Signal]:
    if asset.kind != "stablecoin" or quote.reference_time is None:
        return []
    dev = peg_deviation(quote.price, asset.peg)
    if dev.value is None or dev.value < th.peg_pct:
        return []
    status = status_at(quote.source, quote.reference_time, now)
    same_currency = quote.quote_currency == asset.peg_currency
    quality = "insuficiente" if status == "unavailable" else (
        "boa" if status == "fresh" and same_currency else "limitada")
    severity = "risco" if dev.value >= th.peg_risk_pct else "atencao"
    if severity == "risco" and quality == "boa" and exposure.engaged:
        severity = "conselho"
    direction = "queda" if quote.price < asset.peg else "alta"
    evidence = [f"{asset.symbol}/{quote.quote_currency} a {quote.price} em {_when(quote.reference_time)} "
                f"({quote.source}): desvio de {_fmt(dev.value, 3)}% da paridade de {asset.peg} {asset.peg_currency}"]
    if not same_currency:
        evidence.append(f"medido contra {quote.quote_currency}, não {asset.peg_currency}: o desvio pode ser de "
                        "qualquer uma das duas moedas")
    if status != "fresh":
        evidence.append(f"cotação {status} (coletada em {_when(quote.fetched_at)})")
    return [Signal(
        category="stablecoin", asset=asset.symbol, severity=_cap(severity, quality), data_quality=quality,
        direction=direction, indicators={"desvio_paridade_pct": _ind(dev), "preco": str(quote.price)},
        evidence=evidence + [exposure.evidence], observed_at=now,
        sources=[{"source": quote.source, "reference_time": quote.reference_time.isoformat(),
                  "fetched_at": quote.fetched_at.isoformat()}],
        relevance=_relevance(dev.value / (2 * th.peg_risk_pct), quality, exposure),
        hypothesis=f"{asset.symbol} está {_fmt(dev.value, 3)}% {'abaixo' if direction == 'queda' else 'acima'} da "
                   f"paridade de 1 {asset.peg_currency}. Precisa ser verificado se é ruído de mercado ou perda de "
                   "lastro.",
        dedup_key=f"stablecoin:{asset.symbol}:{direction}:{_bucket(quote.reference_time)}")]


def _tvl_signals(asset: Asset, tvl: TvlInput, th: Thresholds, exposure: _Exposure, now: datetime) -> list[Signal]:
    week, day = tvl_change(tvl.points, 7), tvl_change(tvl.points, 1)
    if week.value is None or abs(week.value) < th.tvl_pct:
        return []
    last = max(tvl.points, key=lambda p: p.time)
    quality = "boa" if status_at(tvl.source, last.time, now) == "fresh" else "limitada"
    direction = "queda" if week.value < 0 else "alta"
    severity = "risco" if abs(week.value) >= th.tvl_risk_pct else "atencao"
    return [Signal(
        category="defi", asset=asset.symbol, severity=_cap(severity, quality), data_quality=quality,
        direction=direction, indicators={"tvl_7d_pct": _ind(week), "tvl_1d_pct": _ind(day), "tvl_usd": str(last.tvl)},
        evidence=[f"TVL de {tvl.label}: {_fmt(week.value, signed=True)}% em 7 dias até {_when(last.time)} "
                  f"({tvl.source}), US$ {_fmt(last.tvl, 0)}", exposure.evidence],
        sources=[{"source": tvl.source, "reference_time": last.time.isoformat(),
                  "fetched_at": tvl.fetched_at.isoformat() if tvl.fetched_at else None}],
        observed_at=now, relevance=_relevance(abs(week.value) / (2 * th.tvl_risk_pct), quality, exposure),
        hypothesis=f"O TVL de {tvl.label} variou {_fmt(week.value, signed=True)}% em 7 dias. Precisa ser investigado "
                   "se houve saída de recursos, mudança de preço dos ativos depositados ou falha de dados.",
        dedup_key=f"defi:{asset.symbol}:{direction}:{_bucket(last.time, 24)}")]


def _concentration_signals(asset: Asset, portfolio: dict, prefs: Prefs, exposure: _Exposure,
                           now: datetime) -> list[Signal]:
    share = concentration(portfolio, asset.symbol)
    if share.value is None or share.value <= prefs.concentration_limit:
        return []
    pct, limit = share.value * _HUNDRED, prefs.concentration_limit * _HUNDRED
    return [Signal(
        category="concentracao", asset=asset.symbol, severity="risco", data_quality="boa", direction="neutra",
        indicators={"fatia": _ind(share), "limite": str(prefs.concentration_limit)},
        evidence=[f"{asset.symbol} é {_fmt(pct, 1)}% do total da carteira informada; "
                  f"limite definido: {_fmt(limit, 1)}%",
                  exposure.evidence],
        sources=[{"source": "carteira informada", "reference_time": now.isoformat(), "fetched_at": now.isoformat()}],
        observed_at=now, relevance=_relevance(share.value / (2 * prefs.concentration_limit), "boa", exposure),
        hypothesis=f"{asset.symbol} representa {_fmt(pct, 1)}% da carteira informada, acima do limite de "
                   f"{_fmt(limit, 1)}% definido pela pessoa. É uma observação sobre exposição, para revisão.",
        dedup_key=f"concentracao:{asset.symbol}:neutra:{_bucket(now, 24)}")]


def detect(asset: Asset, candles: CandleSeries | None, *, stats: Quote | None = None, peg: Quote | None = None,
           tvl: TvlInput | None = None, portfolio: dict[str, Decimal] | None = None, prefs: Prefs,
           now: datetime) -> list[Signal]:
    """Sinais do ativo em `now`. `peg` é a cotação observada da stablecoin; `portfolio` = símbolo → valor (mesma
    moeda); sem carteira, a relevância cai e a evidência diz que a exposição é desconhecida."""
    th = THRESHOLDS[prefs.sensitivity]
    exposure = _exposure(asset.symbol, prefs, portfolio)
    signals = []
    if candles is not None:
        signals += _market_signals(asset, candles, stats, th, exposure, now)
    if peg is not None:
        signals += _peg_signals(asset, peg, th, exposure, now)
    if tvl is not None:
        signals += _tvl_signals(asset, tvl, th, exposure, now)
    if portfolio is not None:
        signals += _concentration_signals(asset, portfolio, prefs, exposure, now)
    return [s for s in signals if s.category not in prefs.muted]
