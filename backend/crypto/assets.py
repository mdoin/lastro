# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registro dos criptoativos acompanhados e validação de todo identificador que chega a uma URL.

Acrescentar um ativo é acrescentar uma linha em ASSETS. Nenhum texto sem validação é interpolado em URL:
símbolo, id do CoinGecko, par da Binance, slug e nome de chain do DefiLlama passam pelas regex abaixo (só ASCII,
tamanho limitado, sem "/", "?", ":" ou "%"), o que fecha injeção de caminho/consulta e SSRF.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}$")
COINGECKO_ID_RE = re.compile(r"^[a-z0-9-]{2,64}$")
BINANCE_PAIR_RE = re.compile(r"^[A-Z0-9]{5,20}$")
# DefiLlama: slug de protocolo ("aave-v3") e nome de chain ("Ethereum", "OP Mainnet"). Primeiro caractere
# alfanumérico: nem "." nem ".." viram segmento de caminho.
LLAMA_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,63}$")
CHAIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .-]{1,39}$")


class InvalidIdentifier(ValueError):
    """Identificador fora do formato permitido (o valor não é ecoado na mensagem)."""


def _check(pattern: re.Pattern, value, what: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InvalidIdentifier(f"{what} inválido")
    return value


def validate_symbol(value) -> str:
    return _check(SYMBOL_RE, value, "símbolo")


def validate_coingecko_id(value) -> str:
    return _check(COINGECKO_ID_RE, value, "id do CoinGecko")


def validate_binance_pair(value) -> str:
    return _check(BINANCE_PAIR_RE, value, "par da Binance")


def validate_slug(value) -> str:
    return _check(LLAMA_SLUG_RE, value, "slug do DefiLlama")


def validate_chain(value) -> str:
    return _check(CHAIN_RE, value, "chain do DefiLlama")


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    coingecko_id: str
    binance_symbol: str | None
    kind: str                      # "coin" | "stablecoin"
    peg: Decimal | None = None
    peg_currency: str | None = None  # "USD" | None
    binance_quote: str = "USDT"    # moeda de cotação do par na Binance: preço em USDT nunca é rotulado USD

    def __post_init__(self):
        validate_symbol(self.symbol)
        validate_coingecko_id(self.coingecko_id)
        if self.binance_symbol is not None:
            validate_binance_pair(self.binance_symbol)
            if not self.binance_symbol.endswith(self.binance_quote):
                raise ValueError("par da Binance não termina na moeda de cotação declarada")
        if self.kind not in ("coin", "stablecoin"):
            raise ValueError("kind deve ser coin ou stablecoin")
        if (self.kind == "stablecoin") != (self.peg is not None) or (self.peg is None) != (self.peg_currency is None):
            raise ValueError("stablecoin exige peg e peg_currency; moeda comum não tem")
        if self.peg_currency not in (None, "USD"):
            raise ValueError("peg_currency só pode ser USD")


ASSETS: dict[str, Asset] = {a.symbol: a for a in (
    Asset("BTC", "Bitcoin", "bitcoin", "BTCUSDT", "coin"),
    Asset("ETH", "Ethereum", "ethereum", "ETHUSDT", "coin"),
    Asset("SOL", "Solana", "solana", "SOLUSDT", "coin"),
    # USDT é a própria moeda de cotação da Binance: o preço dele em USD vem do CoinGecko.
    Asset("USDT", "Tether", "tether", None, "stablecoin", Decimal("1"), "USD"),
    # USDCUSDT mede USDC contra USDT, não contra o dólar: um desvio pode ser de qualquer um dos dois.
    Asset("USDC", "USD Coin", "usd-coin", "USDCUSDT", "stablecoin", Decimal("1"), "USD"),
)}
_BY_COINGECKO = {a.coingecko_id: a for a in ASSETS.values()}


def get(symbol) -> Asset:
    asset = ASSETS.get(validate_symbol(symbol))
    if asset is None:
        raise InvalidIdentifier("ativo fora do registro")
    return asset


def by_coingecko_id(coingecko_id: str) -> Asset | None:
    return _BY_COINGECKO.get(coingecko_id)
