// SPDX-License-Identifier: AGPL-3.0-or-later
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Agent, TeamMessage, TeamRun } from "../api/types";
import { seats } from "../lib/council";
import { AgentPanel, CouncilRoom, VerdictView } from "./Council";

const agent = (id: string, name: string, title: string): Agent => ({
  id: id as Agent["id"], name, handle: name.toLowerCase(), title, kind: "specialist", icon: "chat", color: `var(--agent-${id})`,
  summary: "", examples: [], tools: [], version: "t",
});
const AGENTS = Object.fromEntries([
  agent("mentor", "Bento", "Mentor · coordenação e síntese"), agent("riscos", "Rui", "Gestor de riscos · perdas"),
  agent("planejador", "Lia", "Planejadora · orçamento"), agent("auditor", "Cora", "Auditora · verificação"),
].map((a) => [a.id, a]));
const run: TeamRun = { id: "r1", conversation_id: "c1", message_id: "q1", kind: "council", status: "running",
  route: { lineup: ["mentor", "planejador", "riscos", "auditor"] }, error: null, created_at: "2026-10-28T10:00:00Z" };
const parecer: TeamMessage = {
  id: "m1", role: "assistant", content: "**Posição:** contrária\n\n## Tese\nNão agora.", status: "ok", tools: [],
  audit: { verdict: "PASSA COM RESSALVAS", reasons: ["Números sem origem"], checked_numbers: 1 }, created_at: "2026-10-28T10:02:00Z",
  agent_id: "riscos", run_id: "r1", step_key: "conselho:riscos", client_id: null, reply_to_id: "q1", mentions: [], kind: "analysis",
  sources: [{ kind: "dados", label: "Seu retrato financeiro de 2026-10-20" }],
  meta: { opinion: { stance: "contraria", sections: ["tese", "risco"], excerpts: { tese: "Não agora: a reserva cobre R$ 9.000,00.", risco: "Concentração em um ativo." } } },
};
const noop = () => undefined;

describe("componentes do Conselho", () => {
  it("cada participante é um botão com nome, cargo e estado real", () => {
    const html = renderToStaticMarkup(
      <CouncilRoom input={{ run, steps: [], live: { "conselho:planejador": { agent_id: "planejador", status: "running", tool: "metas" } }, messages: [parecer] }}
        agents={AGENTS} onSelect={noop} masked={false} />,
    );
    expect(html).toContain('aria-label="Lia, Planejadora: Consultando informações. Abrir detalhes"');
    expect(html).toContain('aria-label="Rui, Gestor de riscos: Parecer disponível. Abrir detalhes"');
    expect(html).toContain('aria-label="Bento, Mentor: Na fila. Abrir detalhes"');
    expect(html).toContain("Trabalhando agora: Lia.");
    expect(html).toContain("contrária");
  });

  it("painel mostra resumo, riscos, fontes, auditoria e o botão de responder; com máscara, sem valores", () => {
    const seat = seats({ run, steps: [], live: {}, messages: [parecer] }).find((s) => s.agent === "riscos")!;
    const props = { seat, seats: [seat], agents: AGENTS, onClose: noop, onSelect: noop, onReply: noop,
      auditBadge: (m: TeamMessage) => <span>Auditoria: {m.audit?.verdict}</span> };
    const html = renderToStaticMarkup(<AgentPanel {...props} masked={false} />);
    for (const text of ["Resumo da posição", "Não agora: a reserva cobre R$ 9.000,00.", "Riscos e ressalvas", "Auditoria: PASSA COM RESSALVAS",
      "Parecer completo", "Responder a Rui", 'aria-labelledby="council-panel-title"']) expect(html).toContain(text);
    const masked = renderToStaticMarkup(<AgentPanel {...props} masked />);
    expect(masked).not.toContain("9.000,00");
    expect(masked).toContain("R$ •••");
  });

  it("menções do veredito são botões acessíveis na cor do agente; texto nunca vira HTML", () => {
    const synthesis = { ...parecer, id: "s1", agent_id: "mentor", step_key: "conselho:sintese", kind: "message" as const };
    const html = renderToStaticMarkup(
      <VerdictView message={synthesis} agents={AGENTS} onOpen={noop} masked={false} verdict={{
        mentioned: ["riscos"],
        sections: [
          { key: "conclusao", title: "Conclusão", items: [[{ t: "Ainda não. " }, { t: "<img src=x onerror=alert(1)>" }]] },
          { key: "risco", title: "Riscos", items: [[{ agent: "riscos" }, { t: " apontou concentração." }]] },
        ],
      }} />,
    );
    expect(html).toContain('aria-label="Rui: abrir parecer"');
    expect(html).toContain("--agent:var(--agent-riscos)");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img src=x");
  });
});
