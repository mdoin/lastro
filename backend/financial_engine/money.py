"""Valores monetários: sempre Decimal, nunca float binário."""

import re
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation

CENT = Decimal("0.01")
# Precisão de cálculo intermediário; o arredondamento para centavos só acontece na apresentação.
CALC_CONTEXT = Context(prec=34)

_BR_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")
_PLAIN_NUMBER = re.compile(r"^\d+(\.\d+)?$")
# Texto numérico aceito: sem notação exponencial e com tamanho limitado (um "1E+999999999" salvo num snapshot
# append-only quebraria todo cálculo posterior com estouro).
_DECIMAL_TEXT = re.compile(r"^[+-]?\d{1,15}(\.\d{1,18})?$")
MAX_ABS = Decimal(10) ** 15


def to_decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("Booleano não é valor numérico.")
    if isinstance(value, float):
        raise TypeError("float binário não é aceito; use str ou Decimal (ex.: '150.00').")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
        if abs(result) >= MAX_ABS:
            raise ValueError(f"Número grande demais: {value!r}")
    elif isinstance(value, str):
        text = value.strip()
        if not _DECIMAL_TEXT.match(text):
            raise ValueError(f"Número inválido: {value[:40]!r}")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Número inválido: {value[:40]!r}") from exc
    else:
        raise TypeError(f"Tipo não suportado: {type(value).__name__}")
    if not result.is_finite():
        raise ValueError(f"Número não finito: {value!r}")
    return result


def round_brl(value) -> Decimal:
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_brl(text: str) -> Decimal:
    """Converte texto digitado no padrão brasileiro ("R$ 1.234,56") em Decimal.

    Entradas ambíguas como "10.50" são recusadas em vez de adivinhadas:
    no Brasil o ponto separa milhar e a vírgula separa centavos.
    """
    s = text.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("-"):
        negative, s = True, s[1:]
    if not s:
        raise ValueError("Valor vazio.")

    if "," in s:
        integer, _, frac = s.rpartition(",")
        if "," in integer or not frac.isdigit():
            raise ValueError(f"Valor inválido: {text!r}")
        if "." in integer and not _BR_THOUSANDS.match(integer):
            raise ValueError(f"Separador de milhar inválido em {text!r}")
        number = f"{integer.replace('.', '') or '0'}.{frac}"
    elif "." in s:
        if not _BR_THOUSANDS.match(s):
            raise ValueError(
                f"Valor ambíguo {text!r}: use vírgula para centavos (ex.: 10,50) "
                "e ponto apenas para milhar (ex.: 1.000)."
            )
        number = s.replace(".", "")
    else:
        number = s

    if not _PLAIN_NUMBER.match(number):
        raise ValueError(f"Valor inválido: {text!r}")
    value = Decimal(number)
    return -value if negative else value


def format_brl(value) -> str:
    v = round_brl(value)
    sign = "-" if v < 0 else ""
    integer, frac = f"{abs(v):.2f}".split(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    return f"{sign}R$ {grouped},{frac}"


def format_pct(rate, places: int = 2) -> str:
    pct = (to_decimal(rate) * 100).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return f"{pct}".replace(".", ",") + "%"
