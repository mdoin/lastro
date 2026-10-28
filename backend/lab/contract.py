# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registro estruturado de uma análise do Laboratório: a MESMA instrução vai para o Bento sozinho e para a síntese do
Conselho, e o mesmo leitor determinístico confere os dois. Nada obriga a inventar previsão: "dados insuficientes" e
"sem hipótese testável" são respostas válidas e ficam registradas como tais."""

import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app import convictions

CONTRACT_VERSION = "lab-registro-1"
MAX_HYPOTHESES = 4
MAX_ITEMS = 12
BLOCK = re.compile(r"```(?:json|registro-lastro)[ \t]*\n(.*?)```", re.DOTALL)
CONFIDENCE = ("baixa", "media", "alta")

SUFFIX = """

[Registro do Laboratório — obrigatório no FIM da resposta, depois do texto: um bloco ```json com este formato.
O Lastro lê o bloco, confere e acompanha. Não invente previsões: se não houver hipótese testável, deixe "hipoteses"
vazio e explique em "sem_hipotese_motivo"; se os dados não bastam, diga isso em "conclusao" e marque
"dados_insuficientes": true.]
```json
{"cenario": "uma frase", "horizonte_dias": 90, "hipotese": "a hipótese central, ou null",
 "resultado_esperado": "o que se espera observar, ou null", "metricas_observaveis": ["..."],
 "riscos_identificados": ["..."], "premissas": ["..."], "fontes": ["dossiê do Laboratório", "..."],
 "nivel_confianca": "baixa|media|alta ou null", "condicoes_invalidacao": ["..."], "conclusao": "...",
 "dados_insuficientes": false, "sem_hipotese_motivo": null,
 "hipoteses": [{"afirmacao": "A meta da Selic estará abaixo de 14% ao ano.", "probabilidade": 0.6,
                "data": "AAAA-MM-DD", "condicao": "selic_meta < 14"}]}
```
Em "hipoteses" (até 4): "probabilidade" de 0.01 a 0.99 de a afirmação ser verdadeira NA data, ou null se você não
quiser quantificar; "data" entre amanhã e 5 anos; "condicao" que o Lastro confere sozinho (selic_meta, cdi, cdi_diario,
ipca_mensal, ipca_sidra, ipca_12m, dolar_ptax, fed_funds, treasury_10y com <, <=, > ou >= e um número; ou cripto:BTC…)
ou "manual" quando só a pessoa pode conferir."""


def _text(value, limit: int = 600) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None


def _items(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [t for t in (_text(v, 300) for v in value[:MAX_ITEMS]) if t]


def parse(text: str, today: date) -> tuple[dict | None, str, list[str]]:
    """(registro normalizado | None, 'ok' | 'ausente' | 'invalido', problemas). Hipótese inválida é recusada com o
    motivo, sem derrubar o resto do registro."""
    blocks = BLOCK.findall(text or "")
    if not blocks:
        return None, "ausente", ["A análise não trouxe o registro estruturado."]
    try:
        raw = json.loads(blocks[-1])
    except json.JSONDecodeError as exc:
        return None, "invalido", [f"Registro estruturado ilegível (JSON inválido: {exc.msg})."]
    if not isinstance(raw, dict):
        return None, "invalido", ["Registro estruturado não é um objeto."]
    problems: list[str] = []
    horizon = raw.get("horizonte_dias")
    if horizon is not None:
        try:
            horizon = int(horizon)
            if not 1 <= horizon <= 1825:
                raise ValueError
        except (TypeError, ValueError):
            problems.append("horizonte_dias fora de 1 a 1825; ignorado.")
            horizon = None
    confidence = _text(raw.get("nivel_confianca"), 20)
    if confidence is not None:
        confidence = confidence.lower().replace("é", "e")
        if confidence not in CONFIDENCE:
            problems.append(f"nivel_confianca não reconhecido ({confidence}); ignorado.")
            confidence = None
    record = {
        "cenario": _text(raw.get("cenario"), 300), "horizonte_dias": horizon,
        "hipotese": _text(raw.get("hipotese")), "resultado_esperado": _text(raw.get("resultado_esperado")),
        "metricas_observaveis": _items(raw.get("metricas_observaveis")),
        "riscos_identificados": _items(raw.get("riscos_identificados")), "premissas": _items(raw.get("premissas")),
        "fontes": _items(raw.get("fontes")), "nivel_confianca": confidence,
        "condicoes_invalidacao": _items(raw.get("condicoes_invalidacao")),
        "conclusao": _text(raw.get("conclusao"), 1500), "dados_insuficientes": raw.get("dados_insuficientes") is True,
        "sem_hipotese_motivo": _text(raw.get("sem_hipotese_motivo"), 400), "hipoteses": [],
    }
    if not record["conclusao"]:
        problems.append("Registro sem conclusão.")
    for i, h in enumerate((raw.get("hipoteses") or [])[:MAX_HYPOTHESES] if isinstance(raw.get("hipoteses"), list) else []):
        parsed, why = hypothesis(h, today)
        if why:
            problems.append(f"Hipótese {i + 1} recusada: {why}.")
        else:
            record["hipoteses"].append(parsed)
    if not record["hipoteses"] and not record["sem_hipotese_motivo"] and not record["dados_insuficientes"]:
        problems.append("Nenhuma hipótese testável e nenhum motivo registrado.")
    return record, ("ok" if record["conclusao"] else "invalido"), problems


def hypothesis(h, today: date) -> tuple[dict | None, str | None]:
    if not isinstance(h, dict):
        return None, "formato inválido"
    statement = _text(h.get("afirmacao"), 300)
    if not statement or len(statement) < 10:
        return None, "afirmação curta ou ausente"
    try:
        due = date.fromisoformat(str(h.get("data", ""))[:10])
    except ValueError:
        return None, "data inválida"
    if not today < due <= today + timedelta(days=365 * convictions.MAX_YEARS):
        return None, f"data fora do intervalo (amanhã a {convictions.MAX_YEARS} anos)"
    probability = h.get("probabilidade")
    if probability is not None:
        try:
            probability = Decimal(str(probability)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None, "probabilidade inválida"
        if not Decimal("0.01") <= probability <= Decimal("0.99"):
            return None, "probabilidade fora de 0,01–0,99"
    cond = _text(h.get("condicao"), 60) or "manual"
    check, why = convictions._check(cond)
    if why:
        return None, why
    return {"afirmacao": statement, "probabilidade": None if probability is None else str(probability),
            "data": due.isoformat(), "check": check}, None


def strip(text: str) -> str:
    """Texto da análise sem o bloco do registro (o bloco é mostrado já interpretado)."""
    return BLOCK.sub("", text or "").strip()
