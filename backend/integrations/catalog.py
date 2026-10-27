"""Catálogo das séries externas e leitura do cache (sem rede).

Só números e datas vindos das fontes entram no banco e, daí, nos agentes: rótulos, unidades e fontes vêm
deste catálogo. Assim nenhum texto de terceiros chega ao prompt (defesa contra injeção pelos dados externos).
"""

from dataclasses import dataclass
from datetime import date

from financial_engine.money import to_decimal


@dataclass(frozen=True)
class Series:
    id: str
    source: str           # bcb_sgs | fred
    code: str             # código na fonte
    label: str
    unit: str
    max_age_days: int     # depois disso o dado é "desatualizado"
    url: str              # página pública da série (para citação)


SERIES = {s.id: s for s in (
    Series("selic_meta", "bcb_sgs", "432", "Meta da taxa Selic (Copom)", "% a.a.", 10,
           "https://www3.bcb.gov.br/sgspub (série 432)"),
    Series("cdi", "bcb_sgs", "4389", "Taxa CDI anualizada (base 252)", "% a.a.", 10,
           "https://www3.bcb.gov.br/sgspub (série 4389)"),
    Series("ipca_mensal", "bcb_sgs", "433", "IPCA — variação mensal (IBGE, via BCB/SGS)", "% no mês", 75,
           "https://www3.bcb.gov.br/sgspub (série 433)"),
    Series("ipca_12m", "bcb_sgs", "13522", "IPCA acumulado em 12 meses (IBGE, via BCB/SGS)", "% em 12 meses", 75,
           "https://www3.bcb.gov.br/sgspub (série 13522)"),
    Series("dolar_ptax", "bcb_sgs", "1", "Dólar comercial PTAX — venda", "R$/US$", 10,
           "https://www3.bcb.gov.br/sgspub (série 1)"),
    Series("fed_funds", "fred", "FEDFUNDS", "Federal Funds Effective Rate (mensal)", "% a.a.", 75,
           "https://fred.stlouisfed.org/series/FEDFUNDS"),
    Series("treasury_10y", "fred", "DGS10", "Treasury 10 anos (EUA)", "% a.a.", 10,
           "https://fred.stlouisfed.org/series/DGS10"),
)}

SOURCE_NAMES = {"bcb_sgs": "Banco Central do Brasil — SGS", "fred": "Federal Reserve Bank of St. Louis — FRED"}
# Fontes previstas e ainda não conectadas (ver docs/PENDING.md): nunca simuladas.
NOT_CONNECTED = ("IBGE/SIDRA (direto)", "CVM", "Tesouro Direto", "ANBIMA", "B3", "SEC")


def validity(series: Series, reference_date: str | None, today: date) -> str:
    if not reference_date:
        return "indisponivel"
    return "valido" if (today - date.fromisoformat(reference_date)).days <= series.max_age_days else "desatualizado"


def latest(conn, today: date) -> list[dict]:
    """Último valor de cada série do catálogo, com fonte, datas, unidade e validade."""
    out = []
    for s in SERIES.values():
        # A série 432 (meta Selic) vem projetada para os próximos dias: só vale o que já é passado ou hoje.
        row = conn.execute("SELECT reference_date, value, fetched_at FROM market_data WHERE source = ? AND series_id = ? "
                           "AND reference_date <= ? ORDER BY reference_date DESC LIMIT 1",
                           (s.source, s.id, today.isoformat())).fetchone()
        status = conn.execute("SELECT checked_at, ok, error FROM market_fetch_status WHERE source = ? AND series_id = ?",
                              (s.source, s.id)).fetchone()
        out.append({"series_id": s.id, "label": s.label, "source": SOURCE_NAMES[s.source], "source_code": s.code,
                    "url": s.url, "unit": s.unit, "value": row["value"] if row else None,
                    "reference_date": row["reference_date"] if row else None,
                    "fetched_at": row["fetched_at"] if row else None,
                    "last_check": status["checked_at"] if status else None,
                    "last_check_ok": bool(status["ok"]) if status else None,
                    "validity": validity(s, row["reference_date"] if row else None, today),
                    "realtime": False})
    return out


def history(conn, series_id: str, limit: int = 12) -> list[dict]:
    s = SERIES[series_id]
    rows = conn.execute("SELECT reference_date, value FROM market_data WHERE source = ? AND series_id = ? "
                        "ORDER BY reference_date DESC LIMIT ?", (s.source, s.id, limit)).fetchall()
    return [dict(r) for r in rows]


def clean_value(text) -> str:
    """Valor vindo de fonte externa: só número decimal plausível passa."""
    value = to_decimal(str(text).strip())
    if abs(value) >= 10**7:
        raise ValueError("valor fora do intervalo")
    return str(value)
