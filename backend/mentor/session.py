"""Configuração do Claude Code (assinatura do usuário) para o mentor.

Barreiras técnicas, independentes do prompt:
- `tools=[]`: nenhuma ferramenta nativa (sem terminal, arquivos, web, agendamento);
- `strict_mcp_config` + `setting_sources=[]`: ignora configurações e MCPs do disco;
- sem `allowed_tools`: toda chamada passa por `can_use_tool`, que só libera as ferramentas do papel;
- capacidades por papel (`ROLE_CAPABILITIES`): navegador e dados do dono só convivem no chat, com o
  navegador restrito a hosts exatos e sem query string; a pesquisa do painel não vê dados do dono;
- diretório de trabalho vazio e dedicado.
"""

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, PermissionResultAllow, PermissionResultDeny

from .tools import ROLE_CAPABILITIES, SERVER_NAME, TOOL_NAMES, build_server, tool_names

PROMPTS = Path(__file__).resolve().parent / "prompts"
# Teto de idas e voltas do agente por turno (ferramenta → resposta): um loop induzido por página não segura o slot.
MAX_TURNS = {"coordenador": 25, "pesquisa": 8, "rotina": 12, "sintese": 4, "auditor": 4}
DEFAULT_MAX_TURNS = 8
ROLES = ("coordenador", "diagnostico", "simulacao", "riscos", "educacao", "pesquisa", "sintese", "auditor", "rotina")


def load_prompt(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Papel desconhecido: {role}")
    base = (PROMPTS / "_base.md").read_text(encoding="utf-8")
    return base + "\n\n" + (PROMPTS / f"{role}.md").read_text(encoding="utf-8")


def tool_gate(allowed: set[str]):
    async def gate(tool_name: str, _input: dict, _context) -> PermissionResultAllow | PermissionResultDeny:
        if tool_name in allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message="Ferramenta indisponível: o mentor só tem ferramentas de leitura.")
    return gate


only_mentor_tools = tool_gate(set(TOOL_NAMES))


def mentor_options(*, role: str = "coordenador", workdir: Path, session_id: str | None = None,
                   resume: str | None = None, model: str | None = None, effort: str = "high",
                   ephemeral: bool = False, browser=None, frame_sink=None) -> ClaudeAgentOptions:
    extra_args = {"no-session-persistence": None} if ephemeral else {}
    caps = ROLE_CAPABILITIES[role]
    return ClaudeAgentOptions(
        tools=[],
        mcp_servers={SERVER_NAME: build_server(browser, frame_sink, caps)},
        strict_mcp_config=True,
        setting_sources=[],
        can_use_tool=tool_gate(tool_names(caps, browser)),
        permission_mode="default",
        system_prompt=load_prompt(role),
        cwd=str(workdir),
        session_id=session_id,
        resume=resume,
        model=model,
        effort=effort,
        max_turns=MAX_TURNS.get(role, DEFAULT_MAX_TURNS),
        include_partial_messages=True,
        extra_args=extra_args,
        env={"DISABLE_AUTOUPDATER": "1"},
    )
