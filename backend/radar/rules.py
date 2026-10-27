"""Regras do Radar: versionadas, validadas e avaliadas de forma determinística (sem rede e sem modelo de IA).

Cada alteração cria uma nova versão (a anterior fica no banco); o sinal guarda a versão que o disparou.
A avaliação é uma função pura dos pontos da série: recebe só o que já era conhecido na data avaliada,
então o mesmo código serve ao monitoramento e ao backtest sem usar informação futura.
"""

import fnmatch
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from financial_engine.money import to_decimal

from .observations import Point

KINDS = ("limite", "variacao", "queda", "reserva", "dado_desatualizado")
CATEGORIES = ("renda_fixa", "acoes", "etf", "fii", "macro", "patrimonio")
STATUSES = ("ativa", "pausada", "arquivada")
PRIORITY_LABELS = {1: "Informativo", 2: "Em observação", 3: "Potencialmente interessante",
                   4: "Alta prioridade para avaliação", 5: "Alerta de risco"}
DEFAULT_HORIZONS = (7, 30, 90, 180, 365)
_PATTERN = re.compile(r"^[a-z0-9_*.\-]{1,80}(,[a-z0-9_*.\-]{1,80}){0,9}$")
ONE = Decimal(1)


@dataclass(frozen=True)
class Trigger:
    reference_date: str
    observation_id: int | None
    condition: str
    values: dict
    magnitude: Decimal          # 0 = no limite; 1 = bem além do limite (base do score, não é probabilidade)


# ---------- validação e versões ----------

def _int(value, lo: int, hi: int, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}: número inteiro esperado.") from None
    if not lo <= number <= hi:
        raise ValueError(f"{field}: entre {lo} e {hi}.")
    return number


def _dec(value, field: str, *, positive: bool = False) -> str:
    try:
        number = to_decimal(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field}: número decimal esperado (ex.: \"7.00\").") from None
    if positive and number <= 0:
        raise ValueError(f"{field}: precisa ser positivo.")
    return str(number)


def validate(data: dict) -> dict:
    """Normaliza uma regra vinda da pessoa ou de uma proposta. Erro de validação vira ValueError legível."""
    kind, category = data.get("kind"), data.get("category")
    if kind not in KINDS:
        raise ValueError("kind: tipo de regra desconhecido.")
    if category not in CATEGORIES:
        raise ValueError("category: categoria desconhecida.")
    name = str(data.get("name", "")).strip()
    if not 3 <= len(name) <= 120:
        raise ValueError("name: entre 3 e 120 caracteres.")
    pattern = str(data.get("series_pattern", "")).strip()
    if kind == "reserva":
        if category != "patrimonio":
            raise ValueError("Regra de reserva pertence à categoria patrimônio.")
        pattern = ""
    elif not _PATTERN.match(pattern):
        raise ValueError("series_pattern: identificadores de série (letras minúsculas, números, _ . - e *).")
    raw = data.get("params") or {}
    if not isinstance(raw, dict):
        raise ValueError("params: objeto esperado.")
    params: dict = {}
    if kind == "limite":
        if raw.get("operador") not in (">=", "<="):
            raise ValueError("params.operador: >= ou <=.")
        params = {"operador": raw["operador"], "valor": _dec(raw.get("valor"), "params.valor"),
                  "tolerancia": _dec(raw.get("tolerancia", "0.5"), "params.tolerancia", positive=True)}
    elif kind == "variacao":
        if raw.get("unidade", "pp") not in ("pp", "pct"):
            raise ValueError("params.unidade: pp (pontos) ou pct (%).")
        if raw.get("direcao", "qualquer") not in ("alta", "baixa", "qualquer"):
            raise ValueError("params.direcao: alta, baixa ou qualquer.")
        params = {"janela_dias": _int(raw.get("janela_dias", 30), 1, 730, "params.janela_dias"),
                  "minimo": _dec(raw.get("minimo"), "params.minimo", positive=True),
                  "unidade": raw.get("unidade", "pp"), "direcao": raw.get("direcao", "qualquer")}
    elif kind == "queda":
        params = {"janela_dias": _int(raw.get("janela_dias", 60), 5, 730, "params.janela_dias"),
                  "queda_minima_pct": _dec(raw.get("queda_minima_pct"), "params.queda_minima_pct", positive=True)}
    elif kind == "reserva":
        params = {"meses_minimos": _dec(raw.get("meses_minimos", "3"), "params.meses_minimos", positive=True)}
    elif kind == "dado_desatualizado":
        params = {}
    params["rearme_dias"] = _int(raw.get("rearme_dias", params.get("janela_dias", 7)), 1, 365, "params.rearme_dias")
    for key in ("vencimento_min_anos", "vencimento_max_anos"):
        if raw.get(key) not in (None, ""):
            params[key] = _int(raw[key], 0, 80, f"params.{key}")
    horizons = data.get("horizons") or list(DEFAULT_HORIZONS)
    if not isinstance(horizons, list) or not 1 <= len(horizons) <= 8:
        raise ValueError("horizons: de 1 a 8 horizontes em dias.")
    horizons = sorted({_int(h, 1, 3650, "horizons") for h in horizons})
    if data.get("benchmark", "cdi") != "cdi":
        raise ValueError("benchmark: só o CDI está disponível como referência por enquanto.")
    status = data.get("status", "ativa")
    if status not in STATUSES:
        raise ValueError("status: ativa, pausada ou arquivada.")
    return {"name": name, "kind": kind, "category": category, "series_pattern": pattern, "params": params,
            "priority": _int(data.get("priority", 3), 1, 5, "priority"),
            "interval_minutes": _int(data.get("interval_minutes", 360), 5, 10080, "interval_minutes"),
            "horizons": horizons, "benchmark": "cdi", "status": status, "note": str(data.get("note", ""))[:500]}


def _row(r: sqlite3.Row) -> dict:
    out = dict(r)
    out["params"] = json.loads(out.pop("params_json"))
    out["horizons"] = json.loads(out.pop("horizons_json"))
    return out


def _insert(conn, rule_id: str, version: int, user_id: str, rule: dict, origin: str, now: str) -> dict:
    conn.execute(
        "INSERT INTO radar_rules (id, version, user_id, name, kind, category, series_pattern, params_json, priority, "
        "interval_minutes, horizons_json, benchmark, status, origin, note, created_at) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rule_id, version, user_id, rule["name"], rule["kind"], rule["category"], rule["series_pattern"],
         json.dumps(rule["params"], sort_keys=True), rule["priority"], rule["interval_minutes"],
         json.dumps(rule["horizons"]), rule["benchmark"], rule["status"], origin, rule["note"], now))
    return get(conn, rule_id, version)


def create(conn, user_id: str, data: dict, *, now: str, origin: str = "pessoa", rule_id: str | None = None) -> dict:
    return _insert(conn, rule_id or str(uuid.uuid4()), 1, user_id, validate(data), origin, now)


def get(conn, rule_id: str, version: int | None = None) -> dict | None:
    if version is None:
        row = conn.execute("SELECT * FROM radar_rules WHERE id = ? ORDER BY version DESC LIMIT 1", (rule_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM radar_rules WHERE id = ? AND version = ?", (rule_id, version)).fetchone()
    return _row(row) if row else None


def update(conn, user_id: str, rule_id: str, changes: dict, *, now: str, origin: str | None = None) -> dict | None:
    """Nova versão com as mudanças aplicadas sobre a vigente."""
    current = get(conn, rule_id)
    if not current or current["user_id"] != user_id:
        return None
    merged = {**current, **{k: v for k, v in changes.items() if k in (
        "name", "kind", "category", "series_pattern", "params", "priority", "interval_minutes", "horizons", "status",
        "note")}}
    if "params" in changes:
        merged["params"] = {**current["params"], **changes["params"]}
    return _insert(conn, rule_id, current["version"] + 1, user_id, validate(merged), origin or current["origin"], now)


def current(conn, user_id: str, *, include_archived: bool = False) -> list[dict]:
    rows = conn.execute("SELECT r.* FROM radar_rules r WHERE r.user_id = ? AND r.version = (SELECT MAX(version) FROM "
                        "radar_rules i WHERE i.id = r.id) ORDER BY r.priority DESC, r.name", (user_id,)).fetchall()
    return [_row(r) for r in rows if include_archived or r["status"] != "arquivada"]


def versions(conn, rule_id: str) -> list[dict]:
    return [_row(r) for r in conn.execute("SELECT * FROM radar_rules WHERE id = ? ORDER BY version", (rule_id,))]


# Regras iniciais (origem "sistema"): ids estáveis, então semear de novo não duplica. Todas editáveis pela pessoa.
DEFAULT_RULES = (
    ("sistema-ipca-taxa", {
        "name": "Tesouro IPCA+ com taxa real a partir de 7% a.a.", "kind": "limite", "category": "renda_fixa",
        "series_pattern": "td_ipca_*_taxa_compra", "priority": 3, "interval_minutes": 360,
        "params": {"operador": ">=", "valor": "7.00", "tolerancia": "0.50", "rearme_dias": 30, "vencimento_min_anos": 3},
        "note": "Exemplo do enunciado: taxa real igual ou superior ao limite, vencimento compatível (≥ 3 anos)."}),
    ("sistema-ipca-alta", {
        "name": "Alta forte nas taxas do Tesouro IPCA+ (30 dias)", "kind": "variacao", "category": "renda_fixa",
        "series_pattern": "td_ipca_*_taxa_compra", "priority": 3, "interval_minutes": 360,
        "params": {"janela_dias": 30, "minimo": "0.50", "unidade": "pp", "direcao": "alta", "rearme_dias": 30,
                   "vencimento_min_anos": 3},
        "note": "Taxa sobe = preço cai: hipótese para quem vai aplicar, risco de marcação para quem já tem."}),
    ("sistema-pre-taxa", {
        "name": "Tesouro Prefixado a partir de 14% a.a.", "kind": "limite", "category": "renda_fixa",
        "series_pattern": "td_pre_*_taxa_compra", "priority": 3, "interval_minutes": 360,
        "params": {"operador": ">=", "valor": "14.00", "tolerancia": "0.50", "rearme_dias": 30, "vencimento_min_anos": 2}}),
    ("sistema-selic", {
        "name": "Mudança na meta Selic", "kind": "variacao", "category": "macro", "series_pattern": "selic_meta",
        "priority": 1, "interval_minutes": 360, "horizons": [30, 90],
        "params": {"janela_dias": 60, "minimo": "0.25", "unidade": "pp", "direcao": "qualquer", "rearme_dias": 30}}),
    ("sistema-ipca-teto", {
        "name": "IPCA em 12 meses acima do teto da meta (4,5%)", "kind": "limite", "category": "macro",
        "series_pattern": "ipca_12m", "priority": 2, "interval_minutes": 720, "horizons": [30, 90, 180],
        "params": {"operador": ">=", "valor": "4.50", "tolerancia": "0.50", "rearme_dias": 30}}),
    ("sistema-dolar", {
        "name": "Dólar PTAX: variação de 5% em 30 dias", "kind": "variacao", "category": "macro",
        "series_pattern": "dolar_ptax", "priority": 2, "interval_minutes": 360, "horizons": [30, 90],
        "params": {"janela_dias": 30, "minimo": "5", "unidade": "pct", "direcao": "qualquer", "rearme_dias": 30}}),
    ("sistema-reserva", {
        "name": "Reserva de emergência abaixo de 3 meses", "kind": "reserva", "category": "patrimonio",
        "priority": 5, "interval_minutes": 720, "horizons": [30, 90], "params": {"meses_minimos": "3", "rearme_dias": 30}}),
    ("sistema-dados", {
        "name": "Séries oficiais desatualizadas", "kind": "dado_desatualizado", "category": "macro",
        "series_pattern": "selic_meta,cdi,cdi_diario,ipca_mensal,ipca_12m,dolar_ptax", "priority": 1,
        "interval_minutes": 720, "horizons": [7], "params": {"rearme_dias": 7}}),
)


def seed_defaults(conn, user_id: str, now: str) -> int:
    created = 0
    for rule_id, data in DEFAULT_RULES:
        if get(conn, rule_id) is None:
            create(conn, user_id, data, now=now, origin="sistema", rule_id=rule_id)
            created += 1
    return created


# ---------- seleção de séries ----------

def matching_series(rule: dict, series: list[dict], today: date) -> list[dict]:
    patterns = [p for p in rule["series_pattern"].split(",") if p]
    out = []
    for s in series:
        if not any(fnmatch.fnmatchcase(s["series_id"], p) for p in patterns):
            continue
        maturity = s["meta"].get("vencimento")
        if maturity:
            years = (date.fromisoformat(maturity) - today).days / 365.25
            if years <= 0:
                continue  # título vencido não é avaliado
            if "vencimento_min_anos" in rule["params"] and years < rule["params"]["vencimento_min_anos"]:
                continue
            if "vencimento_max_anos" in rule["params"] and years > rule["params"]["vencimento_max_anos"]:
                continue
        out.append(s)
    return out


# ---------- avaliação (função pura) ----------

def _cmp(op: str, value: Decimal, limit: Decimal) -> bool:
    return value >= limit if op == ">=" else value <= limit


def _rearmed(last_signal_date: str | None, ref: str, days: int) -> bool:
    return last_signal_date is None or date.fromisoformat(ref) - date.fromisoformat(last_signal_date) >= timedelta(days)


def _value_at_or_before(points: list[Point], day: str) -> Point | None:
    found = None
    for p in points:
        if p.reference_date > day:
            break
        found = p
    return found


def evaluate(rule: dict, points: list[Point], *, last_signal_date: str | None = None) -> Trigger | None:
    """Avalia a regra sobre `points` (ordem de data, só o que era conhecido). Usa o ponto mais recente."""
    if not points:
        return None
    params, last = rule["params"], points[-1]
    rearm = params.get("rearme_dias", 7)
    kind = rule["kind"]
    if kind == "limite":
        limit, tol = to_decimal(params["valor"]), to_decimal(params["tolerancia"])
        if not _cmp(params["operador"], last.value, limit):
            return None
        prev = points[-2] if len(points) > 1 else None
        crossed = prev is not None and not _cmp(params["operador"], prev.value, limit)
        if not crossed and not _rearmed(last_signal_date, last.reference_date, rearm):
            return None
        return Trigger(last.reference_date, last.obs_id,
                       f"{last.value} {'≥' if params['operador'] == '>=' else '≤'} limite de {limit}"
                       + (" (cruzou o limite)" if crossed else " (acima do limite há mais tempo)" if params['operador'] == '>='
                          else " (abaixo do limite há mais tempo)"),
                       {"valor": str(last.value), "limite": str(limit), "operador": params["operador"],
                        "cruzou": crossed, "anterior": str(prev.value) if prev else None},
                       min(abs(last.value - limit) / tol, ONE))
    if kind == "variacao":
        start_day = (date.fromisoformat(last.reference_date) - timedelta(params["janela_dias"])).isoformat()
        base = _value_at_or_before(points, start_day)
        if base is None or base.value == 0:
            return None
        change = last.value - base.value if params["unidade"] == "pp" else (last.value / base.value - ONE) * 100
        minimum = to_decimal(params["minimo"])
        direction = params["direcao"]
        hit = (change >= minimum if direction == "alta" else change <= -minimum if direction == "baixa"
               else abs(change) >= minimum)
        if not hit or not _rearmed(last_signal_date, last.reference_date, rearm):
            return None
        unit = "p.p." if params["unidade"] == "pp" else "%"
        return Trigger(last.reference_date, last.obs_id,
                       f"variação de {change.quantize(Decimal('0.01'))} {unit} em {params['janela_dias']} dias "
                       f"(de {base.value} em {base.reference_date} para {last.value})",
                       {"valor": str(last.value), "base": str(base.value), "data_base": base.reference_date,
                        "variacao": str(change.quantize(Decimal("0.0001"))), "unidade": params["unidade"]},
                       min(abs(change) / (2 * minimum), ONE))
    if kind == "queda":
        start_day = (date.fromisoformat(last.reference_date) - timedelta(params["janela_dias"])).isoformat()
        window = [p for p in points if p.reference_date >= start_day]
        peak = max(window, key=lambda p: p.value)
        if peak.value <= 0:
            return None
        drop = (ONE - last.value / peak.value) * 100
        minimum = to_decimal(params["queda_minima_pct"])
        if drop < minimum or not _rearmed(last_signal_date, last.reference_date, rearm):
            return None
        return Trigger(last.reference_date, last.obs_id,
                       f"queda de {drop.quantize(Decimal('0.01'))}% desde a máxima de {peak.value} "
                       f"({peak.reference_date}) em {params['janela_dias']} dias",
                       {"valor": str(last.value), "maxima": str(peak.value), "data_maxima": peak.reference_date,
                        "queda_pct": str(drop.quantize(Decimal("0.0001")))},
                       min(drop / (2 * minimum), ONE))
    raise ValueError(f"regra {kind} não é avaliada sobre série")


def evaluate_stale(rule: dict, meta: dict, last: Point | None, today: date, *, last_signal_date: str | None) -> Trigger | None:
    age = (today - date.fromisoformat(last.reference_date)).days if last else None
    if last is not None and age <= meta["max_age_days"]:
        return None
    ref = last.reference_date if last else today.isoformat()
    # Sem nenhum dado, a data de referência é "hoje": sem o rearme, dispararia todo dia.
    if last_signal_date == ref or (last is None and not _rearmed(last_signal_date, ref, rule["params"].get("rearme_dias", 7))):
        return None
    return Trigger(ref, last.obs_id if last else None,
                   f"última observação de {ref} ({age} dias; limite {meta['max_age_days']})" if last
                   else "nenhuma observação disponível",
                   {"idade_dias": age, "limite_dias": meta["max_age_days"]}, ONE)


def evaluate_reserve(rule: dict, snapshot: dict | None, *, last_signal_date: str | None) -> Trigger | None:
    if not snapshot:
        return None
    essential = to_decimal(snapshot["essential_expenses"])
    if essential <= 0:
        return None
    months = to_decimal(snapshot["liquid_reserve"]) / essential
    minimum = to_decimal(rule["params"]["meses_minimos"])
    if months >= minimum or not _rearmed(last_signal_date, snapshot["as_of"], rule["params"].get("rearme_dias", 30)):
        return None
    return Trigger(snapshot["as_of"], None,
                   f"reserva cobre {months.quantize(Decimal('0.1'))} meses de despesas essenciais (mínimo {minimum})",
                   {"meses": str(months.quantize(Decimal("0.01"))), "minimo": str(minimum),
                    "reserva": snapshot["liquid_reserve"], "despesas_essenciais": snapshot["essential_expenses"],
                    "retrato_id": snapshot["id"]},
                   min((minimum - months) / minimum, ONE))
