# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registro versionado dos agentes do Lastro.

Um agente "persistente" não é um processo vivo: é esta configuração (identidade, instruções, ferramentas,
limites) mais o que o banco guarda dele (conversas, memória individual). O worker instancia uma sessão do
Claude só quando há trabalho e a descarta ao final.

Capacidades são aplicadas em código: o servidor MCP de cada sessão só registra as ferramentas permitidas e
`can_use_tool` recusa qualquer outra (ver mentor/session.py). O prompt descreve; não isola.
"""

from dataclasses import dataclass, field

REGISTRY_VERSION = "2026-10-28.2"


@dataclass(frozen=True)
class Capabilities:
    """O que um agente enxerga. Navegador livre e dados do dono nunca convivem na mesma sessão."""
    data: bool = True                 # ferramentas /v1/me/* (retratos, diagnóstico, metas, decisões)
    browser: str | None = None        # None | "owner" (hosts exatos, sem query) | "research" (allowlist inteira)
    quiet: bool = False               # sem_novidade (só rotinas)
    facts: bool = False               # memória financeira confirmada (leitura)
    market: bool = False              # séries de dados externos já coletadas (leitura)
    calc: bool = False                # calculadora determinística
    delegate: bool = False            # pedir análise a outro especialista (via orquestrador)
    memory: bool = False              # anotar memória individual / propor fato financeiro (o dono confirma)
    journal: bool = False             # Diário de Oportunidades do Radar (leitura; contém decisões do dono)
    diary: bool = False               # propor rascunho ao Diário de Decisões (só a pessoa confirma)
    ledger: bool = False              # livro de movimentações e caixa de documentos (leitura)


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str                         # nome exibido
    handle: str                       # @menção canônica
    title: str                        # especialidade, uma linha
    kind: str                         # coordinator | specialist | auditor
    prompt: str                       # arquivo em mentor/prompts/
    caps: Capabilities
    aliases: tuple = ()
    icon: str = "chat"
    color: str = "var(--agent-coordenador)"
    max_turns: int = 12
    effort: str = "medium"
    can_delegate_to: tuple = ()
    version: str = REGISTRY_VERSION
    summary: str = ""
    examples: tuple = field(default_factory=tuple)

    @property
    def chat_enabled(self) -> bool:
        return self.kind in ("coordinator", "specialist")

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "handle": self.handle, "title": self.title, "kind": self.kind,
                "icon": self.icon, "color": self.color, "summary": self.summary, "examples": list(self.examples),
                "version": self.version,
                "tools": sorted(n for n, on in (("dados do seu retrato", self.caps.data),
                                                ("memória financeira", self.caps.facts),
                                                ("dados de mercado", self.caps.market),
                                                ("motor financeiro", self.caps.calc),
                                                ("consulta a especialistas", self.caps.delegate),
                                                ("Diário de Oportunidades", self.caps.journal),
                                                ("rascunhos do Diário de Decisões", self.caps.diary),
                                                ("movimentações e documentos", self.caps.ledger),
                                                ("leitura de fontes oficiais", bool(self.caps.browser))) if on)}


SPECIALISTS = ("planejador", "analista", "economista", "riscos", "comportamental", "cripto", "mila")

AGENTS: dict[str, AgentSpec] = {a.id: a for a in (
    AgentSpec(
        id="mentor", name="Bento", handle="bento", title="Mentor · coordenação e síntese", kind="coordinator",
        prompt="mentor.md", icon="layers", color="var(--agent-coordenador)", max_turns=25, effort="high",
        aliases=("mentor", "coordenador", "lastro"),
        caps=Capabilities(data=True, browser="owner", facts=True, market=True, calc=True, delegate=True, memory=True,
                          journal=True, diary=True, ledger=True),
        can_delegate_to=SPECIALISTS,
        summary="Entende o que você precisa, chama os especialistas certos e junta tudo numa resposta clara.",
        examples=("O que faço com o dinheiro disponível este mês?", "Me ajuda a organizar minhas prioridades.")),
    AgentSpec(
        id="planejador", name="Lia", handle="lia", title="Planejadora · orçamento, reserva e metas",
        kind="specialist", prompt="planejador.md", icon="wallet", color="var(--agent-diagnostico)",
        aliases=("planejador", "planejamento", "planejadora", "orcamento"),
        caps=Capabilities(data=True, facts=True, calc=True, delegate=True, memory=True, journal=True, ledger=True),
        can_delegate_to=("analista", "economista", "riscos", "comportamental", "mila"),
        summary="Orçamento, reserva, dívidas, metas e capacidade de poupança, antes de qualquer produto.",
        examples=("Quanto devo ter de reserva?", "Quito o cartão ou começo a investir?")),
    AgentSpec(
        id="analista", name="Caio", handle="caio", title="Analista · pesquisa e avaliação de investimentos",
        kind="specialist", prompt="analista.md", icon="bars", color="var(--agent-simulacao)",
        aliases=("analista", "investimentos", "analista-de-investimentos", "analise"),
        caps=Capabilities(data=True, facts=True, market=True, calc=True, delegate=True, memory=True, journal=True),
        can_delegate_to=("planejador", "economista", "riscos", "comportamental", "cripto"),
        summary="Renda fixa, ações, ETFs, FIIs e fundos: retorno líquido, custos, liquidez e adequação ao prazo.",
        examples=("Quais categorias fazem sentido para 10 anos?", "Compare CDB e Tesouro Selic para minha reserva.")),
    AgentSpec(
        id="economista", name="Vera", handle="vera", title="Economista · macroeconomia e cenários",
        kind="specialist", prompt="economista.md", icon="globe", color="var(--agent-pesquisa)",
        aliases=("economista", "economia", "macro"),
        # Pode ler a web (allowlist oficial), por isso NÃO vê os dados do dono: texto injetado numa página
        # nunca está na mesma sessão que conhece o patrimônio da pessoa.
        caps=Capabilities(data=False, browser="research", facts=False, market=True, calc=True, delegate=True,
                          memory=True),
        can_delegate_to=("analista", "riscos"),
        summary="Selic, CDI, IPCA, câmbio e ciclos: dados oficiais com data de referência e cenários, nunca certezas.",
        examples=("Como está o cenário de juros?", "O que a inflação acumulada significa para mim?")),
    AgentSpec(
        id="riscos", name="Rui", handle="rui", title="Gestor de riscos · perdas, liquidez e concentração",
        kind="specialist", prompt="riscos.md", icon="alert", color="var(--agent-riscos)",
        aliases=("riscos", "risco", "gestor", "gestor-de-riscos"),
        caps=Capabilities(data=True, facts=True, market=True, calc=True, delegate=True, memory=True, journal=True),
        can_delegate_to=("planejador", "analista", "economista", "cripto"),
        summary="O contraponto crítico: o que pode dar errado, quanto se perderia e que premissas precisam valer.",
        examples=("Minha carteira está concentrada?", "Quanto eu perderia num cenário ruim?")),
    AgentSpec(
        id="comportamental", name="Nina", handle="nina", title="Conselheira · comportamento e decisões",
        kind="specialist", prompt="comportamental.md", icon="spark", color="var(--agent-educacao)",
        aliases=("conselheiro", "comportamental", "comportamento", "conselheira"),
        caps=Capabilities(data=True, facts=True, calc=False, delegate=True, memory=True),
        can_delegate_to=("planejador", "riscos"),
        summary="Ajuda a perceber FOMO, aversão à perda e impulsos; disciplina sem culpa. Não faz diagnóstico.",
        examples=("Estou com vontade de vender tudo, é impulso?", "Como manter os aportes todo mês?")),
    AgentSpec(
        id="cripto", name="Téo", handle="teo", title="Analista de ativos digitais · cripto e custódia",
        kind="specialist", prompt="cripto.md", icon="coins", color="var(--agent-cripto)",
        aliases=("cripto", "ativos-digitais", "criptoativos", "bitcoin"),
        caps=Capabilities(data=True, facts=True, market=True, calc=True, delegate=True, memory=True, journal=True),
        can_delegate_to=("analista", "economista", "riscos"),
        summary="Cripto, stablecoins e tokens: custódia, liquidez, risco operacional e de contraparte, sem euforia.",
        examples=("Faz sentido ter bitcoin na minha carteira?", "Stablecoin é igual a dólar guardado?")),
    AgentSpec(
        id="mila", name="Mila", handle="mila", title="Organizadora financeira · documentos e conciliação",
        kind="specialist", prompt="mila.md", icon="inbox", color="var(--agent-mila)",
        aliases=("organizadora", "documentos", "caixa"),
        # Só leitura: o registro de movimentações é feito pelo backend (caixa de entrada e confirmações da pessoa).
        caps=Capabilities(data=True, facts=True, calc=True, delegate=True, memory=True, ledger=True),
        can_delegate_to=("planejador",),
        summary="Lê extratos, faturas e comprovantes, concilia lançamentos e aponta duplicatas e pendências.",
        examples=("O que ficou pendente na minha caixa de entrada?", "Quanto gastei com transporte este mês?")),
    AgentSpec(
        id="extrator", name="Mila", handle="extrator", title="Leitura de documento (interna)", kind="internal",
        prompt="extrator.md", icon="inbox", color="var(--agent-mila)", max_turns=1, effort="low",
        # Sem nenhuma ferramenta: o texto de um documento é dado não confiável e esta sessão só devolve JSON.
        caps=Capabilities(data=False),
        summary="Sessão interna da caixa de entrada para ler texto de documento quando a pessoa pede."),
    AgentSpec(
        id="auditor", name="Cora", handle="cora", title="Auditora · verificação independente", kind="auditor",
        prompt="auditor.md", icon="shieldCheck", color="var(--agent-auditor)", max_turns=6,
        caps=Capabilities(data=True, facts=True, market=True, calc=True, journal=True),
        summary="Confere números, fontes, datas, riscos e promessas antes de a resposta chegar a você."),
)}


# Modos de trabalho: complementos de instrução por situação (mentor/prompts/modos/<modo>.md).
MODES = ("direto", "grupo", "delegado", "integracao", "conselho_enquadramento", "conselho_parecer",
         "conselho_sintese", "conselho_contestacao", "correcao", "radar_parecer", "radar_sintese",
         "extracao_documento", "conselho_pauta", "conselho_debate")


def get(agent_id: str) -> AgentSpec:
    try:
        return AGENTS[agent_id]
    except KeyError:
        raise ValueError(f"Agente desconhecido: {str(agent_id)[:40]}") from None


def chat_agents() -> list[AgentSpec]:
    return [a for a in AGENTS.values() if a.chat_enabled]


