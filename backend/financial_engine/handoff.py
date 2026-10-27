"""Validação do formato obrigatório de handoff entre agentes (seção 4 do plano)."""

import re
import uuid

AGENT_IDS = {f"AG-0{i}" for i in range(7)}
STATUSES = {"complete", "needs_review", "blocked"}
LIST_FIELDS = ("facts", "sources", "assumptions", "missing_information", "uncertainties", "conclusions")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def validate_handoff(data: dict) -> list:
    """Retorna a lista de problemas encontrados; lista vazia significa handoff válido."""
    problems = []
    if not isinstance(data, dict):
        return ["Handoff precisa ser um objeto JSON."]

    try:
        uuid.UUID(str(data.get("task_id", "")))
    except ValueError:
        problems.append("task_id precisa ser UUID.")
    if data.get("agent") not in AGENT_IDS:
        problems.append("agent desconhecido.")
    if not _ISO_DATE.match(str(data.get("as_of", ""))):
        problems.append("as_of precisa ser data ISO (AAAA-MM-DD).")
    if not str(data.get("question", "")).strip():
        problems.append("question vazia.")
    if data.get("status") not in STATUSES:
        problems.append(f"status precisa ser um de {sorted(STATUSES)}.")
    for name in LIST_FIELDS:
        if not isinstance(data.get(name), list):
            problems.append(f"{name} precisa ser lista.")

    sources = data.get("sources") if isinstance(data.get("sources"), list) else []
    for i, src in enumerate(sources):
        if not isinstance(src, dict) or not all(str(src.get(k, "")).strip() for k in ("title", "url", "accessed_at")):
            problems.append(f"sources[{i}] precisa de title, url e accessed_at.")

    if data.get("facts") and not sources:
        problems.append("Fatos sem fonte: rotule como hipótese ou inclua a fonte.")
    if data.get("status") == "complete" and data.get("missing_information"):
        problems.append("status complete com informação faltante: use needs_review.")
    return problems
