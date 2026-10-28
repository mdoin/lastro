# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conselho deliberativo: regras determinísticas em volta das falas dos agentes (docs/COUNCIL.md).

O que é decidido aqui, sem modelo: quem é convocado (por tema, menções ou escolha da pessoa), os modos, os limites
de custo e de tempo, a validação da pauta proposta pelo Bento (só participantes reais, sem ciclos, número de falas
limitado) e a leitura da posição e da reação declaradas em cada fala. O que os agentes dizem vem das execuções reais;
nada aqui escreve fala de agente.
"""

import json
import os
import re
from dataclasses import asdict, dataclass, field

from .agents import AGENTS, get
from .auditor import fold
from .routing import CRYPTO, MENTION, resolve_handle

MODES = {"rapida": "Consulta rápida", "completo": "Conselho completo", "debate": "Debate",
         "rodada": "Nova rodada", "revisao": "Revisão do veredito"}
COMMAND = re.compile(r"^\s*/(rapida|rápida|conselho|reuniao|reunião|debate|rodada|revisar|encerrar)\b[:\s]*",
                     re.IGNORECASE)
_COMMANDS = {"rapida": "rapida", "rápida": "rapida", "conselho": "completo", "reuniao": "completo",
             "reunião": "completo", "debate": "debate", "rodada": "rodada", "revisar": "revisao",
             "encerrar": "encerrar"}
COUNCIL_SPECIALISTS = ("planejador", "analista", "economista", "riscos", "comportamental", "cripto", "mila")

# Temas que justificam convocar cada especialista (texto sem acento). Cripto usa o padrão do roteamento.
TOPICS = {
    "planejador": r"reserva|orcament|meta|divida|gasto|despesa|renda|salario|aposent|poupar|emergencia|financia|"
                  r"compra|carro|casa|imovel|quitar|parcela|planej|mes|mensal",
    "analista": r"invest|aplic|acao|acoes|fii|etf|cdb|lci|lca|tesouro|renda fixa|carteira|fundo|rentab|bolsa|ativo",
    "economista": r"selic|juro|inflacao|ipca|cambio|dolar|cenario|economia|recessao|macro|cdi|banco central",
    "riscos": r"risco|perd|volatil|concentr|seguro|garantia|alavanc|tudo|toda|inteir",
    "comportamental": r"impuls|ansie|medo|fomo|agora|urgente|emocao|vontade|arrepend|tudo|toda|todos|pressa|culpa",
    "mila": r"extrato|fatura|lancament|gastei|gastos do mes|comprovante|conciliar|categoria",
}


@dataclass
class Limits:
    """Tetos por reunião. Atingir um deles encerra a discussão e leva à síntese com aviso — nunca ao silêncio."""
    max_rounds: int = 2
    max_messages: int = 16          # falas publicadas na discussão (sem contar pareceres iniciais e síntese)
    max_calls: int = 40             # chamadas ao modelo nesta execução
    max_seconds: int = 1500
    max_tokens: int = 0             # 0 = sem teto (só conta quando o provedor informa o consumo)
    max_participants: int = 5
    max_parallel: int = 3
    max_returns: int = 1            # quantas vezes a Cora pode devolver questões ao Conselho
    max_turns_per_round: int = 6

    @classmethod
    def from_env(cls) -> "Limits":
        out = cls()
        for name in out.__dataclass_fields__:
            raw = os.environ.get(f"LASTRO_COUNCIL_{name.upper()}")
            if raw and raw.isdigit():
                setattr(out, name, int(raw))
        return out


def parse_command(text: str) -> tuple[str | None, str]:
    match = COMMAND.match(text or "")
    if not match:
        return None, text
    return _COMMANDS[match.group(1).lower()], text[match.end():].strip()


def addressed(text: str) -> list[str]:
    """Agentes a quem a pessoa se dirige. Com @menção, só os mencionados ("@rui, por que discorda do Caio?" é para
    o Rui); sem @, nomes de exibição ("Bento, quero ouvir a Nina")."""
    found = [a for a in (resolve_handle(m.group(1)) for m in MENTION.finditer(text or "")) if a]
    if found:
        return list(dict.fromkeys(found))
    folded = fold(text or "")
    for spec in AGENTS.values():
        if spec.chat_enabled and re.search(rf"(?<![\w@]){re.escape(fold(spec.name))}(?!\w)", folded):
            found.append(spec.id)
    return list(dict.fromkeys(found))


def select(question: str, mode: str, requested: list[str] | None = None, limits: Limits | None = None) -> list[str]:
    """Especialistas convocados, em ordem de relevância. Pedido explícito da pessoa vale primeiro."""
    limits = limits or Limits()
    chosen = [a for a in (requested or []) if a in COUNCIL_SPECIALISTS]
    folded = fold(question or "")
    scores = {a: len(re.findall(p, folded)) for a, p in TOPICS.items()}
    scores["cripto"] = 3 * len(CRYPTO.findall(folded))
    ranked = [a for a, s in sorted(scores.items(), key=lambda kv: (-kv[1], COUNCIL_SPECIALISTS.index(kv[0]))) if s > 0]
    if mode == "rapida":
        picks = chosen or ranked[:2] or ["planejador"]
        return picks[:2]
    if mode == "debate" and len(chosen) >= 2:
        return chosen[:limits.max_participants]
    picks = list(dict.fromkeys([*chosen, "planejador", *ranked, "riscos"]))
    for default in ("analista", "comportamental"):  # reunião completa tem ao menos três vozes
        if len(picks) < 3 and default not in picks:
            picks.append(default)
    if "riscos" in picks and len(picks) > limits.max_participants:  # o contraponto de riscos nunca é cortado
        picks.remove("riscos")
        picks = picks[:limits.max_participants - 1] + ["riscos"]
    return picks[:limits.max_participants]


def debate_roles(participants: list[str]) -> dict[str, str]:
    """Papéis de análise no Debate (não crenças): metade examina o que sustenta a hipótese, metade o que a contraria."""
    return {a: ("favor" if i % 2 == 0 else "contra") for i, a in enumerate(participants)}


# ---------- pauta do coordenador ----------

TURN_KINDS = ("pergunta", "contestacao", "resposta", "complemento", "evidencia")


@dataclass
class Turn:
    speaker: str
    target: str | None
    kind: str
    prompt: str


@dataclass
class Plan:
    agreements: list = field(default_factory=list)
    divergences: list = field(default_factory=list)
    contradictions: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    turns: list = field(default_factory=list)
    ask_user: str = ""
    close: bool = False
    source: str = "coordenador"     # "coordenador" (pauta do Bento) | "regra" (sem pauta válida)

    def public(self) -> dict:
        return asdict(self)


def _strings(value, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v)[:400] for v in value if isinstance(v, str | int | float) and str(v).strip()][:limit]


def _agent(value) -> str | None:
    if not isinstance(value, str):
        return None
    return resolve_handle(value.lstrip("@")) or (value if value in AGENTS else None)


def parse_plan(text: str, participants: list[str], limits: Limits) -> Plan | None:
    """Lê o JSON da pauta. Fala de quem não está na reunião, para si mesmo ou repetida é descartada."""
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(text[start:end + 1])
    except (ValueError, RecursionError):
        return None
    if not isinstance(raw, dict):
        return None
    turns, seen = [], set()
    for t in raw.get("falas", []) if isinstance(raw.get("falas"), list) else []:
        if not isinstance(t, dict):
            continue
        speaker, target = _agent(t.get("quem")), _agent(t.get("para")) if t.get("para") not in (None, "", "pessoa") else None
        kind = str(t.get("tipo", "resposta")).lower()
        if speaker not in participants or (target and target not in participants) or target == speaker:
            continue
        if speaker in seen:  # uma fala por agente por rodada; pedidos extras viram contexto da mesma fala
            continue
        seen.add(speaker)
        turns.append(Turn(speaker, target, kind if kind in TURN_KINDS else "resposta",
                          str(t.get("pedido", ""))[:500]))
    return Plan(agreements=_strings(raw.get("concordancias")), divergences=_strings(raw.get("divergencias")),
                contradictions=_strings(raw.get("contradicoes")), hypotheses=_strings(raw.get("hipoteses")),
                missing=_strings(raw.get("lacunas")), turns=turns[:limits.max_turns_per_round],
                ask_user=str(raw.get("perguntar_pessoa") or "")[:400], close=bool(raw.get("encerrar")))


def fallback_plan(stances: dict[str, str | None], first_round: bool) -> Plan:
    """Sem pauta válida: só há discussão se há divergência material, e só entre os lados opostos (1ª rodada)."""
    favor = [a for a, s in stances.items() if s == "favoravel"]
    contra = [a for a, s in stances.items() if s == "contraria"]
    if not first_round or not favor or not contra:
        return Plan(close=True, source="regra")
    turns = [Turn(a, contra[i % len(contra)], "contestacao", "Responda aos argumentos de quem discorda de você.")
             for i, a in enumerate(favor)]
    turns += [Turn(a, favor[i % len(favor)], "contestacao", "Responda aos argumentos de quem discorda de você.")
              for i, a in enumerate(contra)]
    return Plan(divergences=["Há posições favoráveis e contrárias à proposta."], turns=turns, source="regra")


def plan_markdown(plan: Plan) -> str:
    """Texto da pauta para a pessoa (gerado do JSON validado, nunca o JSON cru do modelo)."""
    name = lambda a: f"@{get(a).handle}" if a else "a pessoa"  # noqa: E731
    parts = []
    for title, items in (("Concordâncias", plan.agreements), ("Divergências", plan.divergences),
                         ("Contradições a esclarecer", plan.contradictions), ("Hipóteses a testar", plan.hypotheses),
                         ("O que falta saber", plan.missing)):
        if items:
            parts.append(f"## {title}\n" + "\n".join(f"- {i}" for i in items))
    if plan.turns:
        parts.append("## Próximas falas\n" + "\n".join(
            f"- @{get(t.speaker).handle} → {name(t.target)}: {t.kind}" + (f" — {t.prompt}" if t.prompt else "")
            for t in plan.turns))
    if plan.ask_user:
        parts.append(f"## Pergunta para você\n{plan.ask_user}")
    if plan.close and not plan.turns:
        parts.append("Informação suficiente: a discussão termina aqui.")
    return "\n\n".join(parts) or "Sem pontos novos para discutir."


# ---------- leitura de uma fala ----------

REACTIONS = {"concordo": "concorda", "discordo": "discorda", "pergunto": "pergunta", "complemento": "complementa",
             "reconheco": "reconhece", "reviso": "revisa"}
_REACTION = re.compile(r"^\W*reacao\W*:?\W*(concordo|discordo|pergunto|complemento|reconheco|reviso)", re.MULTILINE)
_REVISED = re.compile(r"^\W*posicao\W*:?[^\n]*\b(revista|revisada|mudei|reviso)\b", re.MULTILINE)


def read_turn(text: str) -> dict:
    folded = fold(text or "")
    m = _REACTION.search(folded)
    return {"reaction": REACTIONS[m.group(1)] if m else None, "revised": bool(_REVISED.search(folded))}


# ---------- registro da reunião ----------

def record(*, question: str, mode: str, participants: list[str], initial: dict, final: dict, excerpts: dict,
           turns: list[dict], verdict: dict | None, audit: dict | None, plan_notes: list[str],
           limits_hit: list[str]) -> dict:
    """Registro estruturado (tema, participantes, evidências, posições, mudanças, divergências, conclusão, revisão).
    É histórico da deliberação, NÃO decisão da pessoa."""
    section = lambda key: next((s for s in (verdict or {}).get("sections", []) if s["key"] == key), None)  # noqa: E731
    flat = lambda s: ["".join(seg["t"] if "t" in seg else f"@{get(seg['agent']).handle}" for seg in item)  # noqa: E731
                      for item in (s or {}).get("items", [])]
    return {
        "tema": question[:500], "modo": mode, "participantes": participants,
        "posicoes_iniciais": {a: initial.get(a) for a in participants},
        "posicoes_finais": {a: final.get(a) for a in participants},
        "mudancas": [a for a in participants if initial.get(a) and final.get(a) and initial[a] != final[a]],
        "evidencias": {a: (excerpts.get(a) or {}).get("evidencia", "") for a in participants},
        "falas": turns, "pauta": plan_notes,
        "conclusao": flat(section("conclusao")), "divergencias": flat(section("diverg")),
        "condicoes_de_revisao": flat(section("condicoes")), "riscos": flat(section("risco")),
        "auditoria": audit, "limites_atingidos": limits_hit,
        "aviso": "Registro da deliberação do Conselho. Não é uma decisão sua: decisões só existem quando você as "
                 "confirma no Diário.",
    }


_RETURN = re.compile(r"^\s*DEVOLVER\s*:\s*@?([\wÀ-ÿ-]+)\s*[—–:-]+\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def parse_returns(text: str, participants: list[str]) -> list[Turn]:
    """Questões que a Cora devolve ao Conselho ("DEVOLVER: @rui — …"); só para quem participou, no máximo 3."""
    out, seen = [], set()
    for m in _RETURN.finditer(text or ""):
        agent = resolve_handle(m.group(1))
        if agent in participants and agent not in seen:
            seen.add(agent)
            out.append(Turn(agent, None, "evidencia", m.group(2).strip()[:400]))
    return out[:3]
