# SPDX-License-Identifier: AGPL-3.0-or-later
"""Montagem da sessão de um papel, independente do provedor de IA.

O papel define instruções (`prompts/`), teto de passos e ferramentas (`ROLE_CAPABILITIES`): navegador e dados
do dono só convivem no chat, com o navegador restrito a hosts exatos e sem query string; a pesquisa do painel
não vê dados do dono. O provedor (providers/) só recebe o `SessionSpec` pronto e não amplia a concessão.
"""

from pathlib import Path

from providers.base import SessionSpec
from team.agents import AGENTS, MODES

from .tools import RESEARCH_CAPS, ROLE_CAPABILITIES, TOOL_NAMES, tools_for

PROMPTS = Path(__file__).resolve().parent / "prompts"
# Teto de idas e voltas do agente por turno (ferramenta → resposta): um loop induzido por página não segura o slot.
MAX_TURNS = {"coordenador": 25, "pesquisa": 8, "rotina": 12, "sintese": 4,
             **{a.id: a.max_turns for a in AGENTS.values()}}
DEFAULT_MAX_TURNS = 8
RESEARCH_TURNS = 16  # busca → abrir → localizar → conferir outra fonte: precisa de mais idas e voltas
CHAT_MODES = ("direto", "grupo", "conversa")  # conversa com a pessoa (não reunião, auditoria ou rotina)
ROLES = ("coordenador", "diagnostico", "simulacao", "educacao", "pesquisa", "sintese", "rotina", *AGENTS)


def load_prompt(role: str, mode: str | None = None) -> str:
    if role not in ROLES:
        raise ValueError(f"Papel desconhecido: {role}")
    if mode is not None and mode not in MODES:
        raise ValueError(f"Modo desconhecido: {mode}")
    spec = AGENTS.get(role)
    file = spec.prompt if spec else f"{role}.md"
    if spec and spec.chat_prompt and (mode in CHAT_MODES or mode == "pesquisa_web"):
        file = spec.chat_prompt
    parts = [PROMPTS / "_base.md", PROMPTS / file] + ([PROMPTS / "modos" / f"{mode}.md"] if mode else [])
    texts = [p.read_text(encoding="utf-8") for p in parts]
    texts.insert(1, team_roster(role))
    return "\n\n".join(texts)


def team_roster(role: str) -> str:
    """Nomes de exibição vêm do registro (um lugar só): trocar um nome não exige reescrever instruções."""
    lines = [f"- {a.name} (@{a.handle}): {a.title}" for a in AGENTS.values() if a.kind != "internal"]
    spec = AGENTS.get(role)
    me = f"Seu nome é {spec.name}. " if spec else ""
    if spec and spec.persona:
        me += (f"Seu jeito: {spec.persona}. Isso muda o estilo, nunca os fatos; varie as palavras e não transforme "
               "o jeito em bordão. ")
    return f"{me}Equipe:\n" + "\n".join(lines)


def session_spec(*, role: str = "coordenador", workdir: Path, session_id: str | None = None,
                 resume: str | None = None, model: str | None = None, effort: str = "high",
                 ephemeral: bool = False, browser=None, frame_sink=None, mode: str | None = None,
                 research=None) -> SessionSpec:
    # Pesquisa: mesma persona, mas só as ferramentas de internet (sem dados do dono, sem delegar, sem memória).
    caps = RESEARCH_CAPS if mode == "pesquisa_web" else ROLE_CAPABILITIES[role]
    return SessionSpec(role=role, system_prompt=load_prompt(role, mode),
                       tools=tools_for(caps, browser, frame_sink, research), workdir=workdir, model=model,
                       max_turns=RESEARCH_TURNS if mode == "pesquisa_web" else MAX_TURNS.get(role, DEFAULT_MAX_TURNS),
                       effort=effort, ephemeral=ephemeral,
                       session_id=session_id, resume=resume)


def mentor_options(**kwargs):
    """Opções do Claude Code para um papel (compatibilidade e testes de isolamento)."""
    from providers.claude_code import claude_options

    return claude_options(session_spec(**kwargs))


def __getattr__(name):
    if name == "only_mentor_tools":  # barreira com todas as ferramentas do Lastro (precisa do extra claude-code)
        from providers.claude_code import tool_gate

        return tool_gate(set(TOOL_NAMES))
    raise AttributeError(name)
