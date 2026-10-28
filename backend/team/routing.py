# SPDX-License-Identifier: AGPL-3.0-or-later
"""Roteamento de mensagens: @menções, respostas a agentes, comando de reunião e o Mentor como roteador.

Regras (determinísticas, testadas):
- conversa individual: sempre o agente da conversa;
- conversa do Conselho: toda mensagem abre uma reunião;
- `/conselho …` (ou `/reuniao`, `/reunião`): reunião estruturada, no Mentor ou em grupos;
- grupo com @menções: só os mencionados que participam do grupo, na ordem em que aparecem;
- grupo sem menção, respondendo a mensagem de um agente: o autor daquela mensagem;
- grupo sem menção: o Mentor, que responde ou delega.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from .agents import AGENTS, get

COUNCIL_COMMAND = re.compile(r"^\s*/(conselho|reuniao|reunião)\b[:\s]*", re.IGNORECASE)
MENTION = re.compile(r"(?<![\w@])@([\wÀ-ÿ][\wÀ-ÿ-]{1,40})")
COUNCIL_FIRST = ("planejador", "analista", "economista")   # pareceres independentes, em paralelo
COUNCIL_SECOND = ("riscos", "comportamental")              # leem os anteriores: contraponto e comportamento
CRYPTO = re.compile(r"\b(cripto\w*|bitcoin|btc|ethereum|ether|eth|stablecoins?|usdt|usdc|tokens?|blockchain|defi|"
                    r"altcoins?|solana|nfts?|memecoins?|ativos?\s+digita\w*)\b")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _handles() -> dict[str, str]:
    table = {}
    for agent in AGENTS.values():
        if not agent.chat_enabled:
            continue
        for name in (agent.handle, agent.id, *agent.aliases, agent.name.replace(" ", "-")):
            table[_fold(name)] = agent.id
    return table


def resolve_handle(handle: str) -> str | None:
    folded = _fold(handle).rstrip("-")
    table = _handles()
    if folded in table:
        return table[folded]
    # "@Riscos," / "@Economista." já saem sem pontuação; aceita plural simples ("@analistas").
    return table.get(folded.rstrip("s"))


def parse_mentions(text: str) -> tuple[list[str], list[str]]:
    """Agentes mencionados (ordem de aparição, sem repetição) e menções que não são de agente."""
    found, unknown = [], []
    for match in MENTION.finditer(text or ""):
        agent_id = resolve_handle(match.group(1))
        if agent_id is None:
            unknown.append(match.group(1))
        elif agent_id not in found:
            found.append(agent_id)
    return found, unknown


def council_agents(question: str) -> tuple[tuple, tuple]:
    """Especialistas convocados para a reunião. O de ativos digitais só entra quando o tema é cripto."""
    extra = ("cripto",) if CRYPTO.search(_fold(question or "")) else ()
    return COUNCIL_FIRST + extra, COUNCIL_SECOND


def strip_council_command(text: str) -> tuple[bool, str]:
    match = COUNCIL_COMMAND.match(text or "")
    if not match:
        return False, text
    return True, text[match.end():].strip()


@dataclass
class Route:
    kind: str                       # "agents" | "council" | "rejected"
    agents: list[str] = field(default_factory=list)
    via_router: bool = False        # o Mentor decide (mensagem sem menção num grupo)
    reason: str = ""
    notices: list[str] = field(default_factory=list)


def route_message(conversation: dict, participants: list[str], text: str, reply_to: dict | None = None) -> Route:
    channel = conversation["channel"]
    is_council, _rest = strip_council_command(text)
    if channel == "council":
        return Route("council", reason="conversa do Conselho")
    if channel == "direct":
        agent_id = conversation.get("agent_id") or "mentor"
        if is_council:
            if agent_id == "mentor":
                return Route("council", reason="comando de reunião na conversa com o Mentor")
            return Route("rejected", reason="O Conselho é convocado pelo Mentor ou num grupo, não numa conversa "
                                            f"individual com {get(agent_id).name}.")
        return Route("agents", [agent_id], reason="conversa individual")
    if channel != "group":
        return Route("rejected", reason="Esta conversa não aceita mensagens.")

    if is_council:
        return Route("council", reason="comando de reunião no grupo")
    mentioned, unknown = parse_mentions(text)
    notices = [f"@{u} não é um agente do Lastro." for u in unknown]
    if mentioned:
        present = [a for a in mentioned if a in participants]
        absent = [a for a in mentioned if a not in participants]
        notices += [f"{get(a).name} não participa deste grupo; adicione-o para que responda." for a in absent]
        if present:
            return Route("agents", present, reason="menção", notices=notices)
        return Route("rejected", reason="Nenhum agente mencionado participa deste grupo.", notices=notices)
    if reply_to and reply_to.get("agent_id") in participants:
        return Route("agents", [reply_to["agent_id"]], reason="resposta a mensagem do agente", notices=notices)
    return Route("agents", ["mentor"], via_router=True, reason="sem menção: Mentor decide", notices=notices)


# ---------- delegação ----------

MAX_DELEGATION_DEPTH = 2
MAX_DELEGATIONS_PER_RUN = 6


@dataclass
class DelegationDecision:
    accepted: bool
    reason: str = ""


def _norm_question(text: str) -> str:
    return re.sub(r"\s+", " ", _fold(text or "")).strip()[:300]


def check_delegation(*, requester: str, target: str, question: str, chain: tuple, depth: int, used: int,
                     seen: set, allowed_targets: set | None, max_depth: int = MAX_DELEGATION_DEPTH,
                     max_calls: int = MAX_DELEGATIONS_PER_RUN) -> DelegationDecision:
    """Aplica os limites antes de qualquer delegação: alvo válido, profundidade, total, ciclo e duplicata."""
    if target not in AGENTS or not AGENTS[target].chat_enabled or target == "mentor":
        return DelegationDecision(False, f"alvo inválido: {target[:40]}")
    if target not in get(requester).can_delegate_to:
        return DelegationDecision(False, f"{get(requester).name} não pode consultar {get(target).name}")
    if allowed_targets is not None and target not in allowed_targets:
        return DelegationDecision(False, f"{get(target).name} não participa desta conversa")
    if not question or not question.strip():
        return DelegationDecision(False, "pedido sem pergunta")
    if depth > max_depth:
        return DelegationDecision(False, f"profundidade máxima ({max_depth}) atingida")
    if used >= max_calls:
        return DelegationDecision(False, f"limite de {max_calls} consultas por execução atingido")
    if target in chain or target == requester:
        return DelegationDecision(False, "ciclo de delegação: " + " → ".join((*chain, requester, target)))
    key = (target, _norm_question(question))
    if key in seen:
        return DelegationDecision(False, "pedido duplicado nesta execução")
    return DelegationDecision(True)


def dedup_key(target: str, question: str) -> tuple:
    return target, _norm_question(question)
