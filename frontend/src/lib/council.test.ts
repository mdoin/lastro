// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import type { RunStep, TeamMessage, TeamRun } from "../api/types";
import { feed, lineup, phases, seats, threadBlocks, type LiveStep } from "./council";
import { MASK, maskMoney } from "./privacy";

const run = (status: TeamRun["status"], route: TeamRun["route"] = {}): TeamRun => ({
  id: "r1", conversation_id: "c1", message_id: "q1", kind: "council", status, route, error: null, created_at: "2026-10-28T10:00:00Z",
});
const step = (step_key: string, agent_id: string, status: RunStep["status"]): RunStep => ({
  step_key, agent_id, status, kind: "council", parent_key: null, depth: 0, error: null,
});
const msg = (step_key: string, agent_id: string, extra: Partial<TeamMessage> = {}): TeamMessage => ({
  id: step_key, role: "assistant", content: `texto ${step_key}`, status: "ok", tools: [], audit: null, created_at: "2026-10-28T10:01:00Z",
  agent_id, run_id: "r1", step_key, client_id: null, reply_to_id: "q1", mentions: [], sources: [], kind: "analysis", ...extra,
});
const LINEUP = ["mentor", "planejador", "riscos", "analista", "auditor"];
const stateOf = (list: ReturnType<typeof seats>, agent: string) => list.find((s) => s.agent === agent)!;
const pauta = msg("conselho:pauta:1", "mentor", {
  meta: { deliberation: { phase: "pauta", plan: { turns: [
    { speaker: "riscos", target: "analista", kind: "contestacao", prompt: "" },
    { speaker: "planejador", target: null, kind: "pergunta", prompt: "" },
  ] } } },
});

describe("sala do Conselho", () => {
  it("usa a escalação gravada e, em execuções antigas, a deduzida dos passos", () => {
    expect(lineup(run("queued", { lineup: LINEUP }), [])).toEqual(LINEUP);
    expect(lineup(run("succeeded"), [step("conselho:enquadramento", "mentor", "succeeded"), step("conselho:cripto", "cripto", "succeeded"),
      step("conselho:debate:1:cripto", "cripto", "succeeded"), step("conselho:pauta:1", "mentor", "succeeded")])).toEqual(["mentor", "cripto", "auditor"]);
  });

  it("antes de começar, todos aguardam e ninguém aparece trabalhando", () => {
    const list = seats({ run: run("queued", { lineup: LINEUP }), steps: [], live: {}, messages: [] });
    expect(list.every((s) => s.state === "waiting" && !s.active)).toBe(true);
  });

  it("análise: ferramenta = consultando; texto chegando = falando; parecer publicado = disponível", () => {
    const live: Record<string, LiveStep> = {
      "conselho:planejador": { agent_id: "planejador", status: "running", tool: "situacao_atual" },
      "conselho:riscos": { agent_id: "riscos", status: "running", text: "A reserva" },
      "conselho:analista": { agent_id: "analista", status: "running" },
    };
    const list = seats({ run: run("running", { lineup: LINEUP }), steps: [], live, messages: [msg("conselho:enquadramento", "mentor")] });
    expect(stateOf(list, "planejador")).toMatchObject({ state: "consulting", active: true });
    expect(stateOf(list, "riscos")).toMatchObject({ state: "speaking", active: true });
    expect(stateOf(list, "analista")).toMatchObject({ state: "analyzing", active: true });
    expect(stateOf(list, "mentor")).toMatchObject({ state: "waiting", act: "Enquadramento feito", active: false });
  });

  it("discussão: estados vêm da pauta real e do passo em curso", () => {
    const live: Record<string, LiveStep> = {
      "conselho:debate:1:riscos": { agent_id: "riscos", status: "running" },
      "conselho:debate:1:planejador": { agent_id: "planejador", status: "running" },
      "conselho:analista:correcao": { agent_id: "analista", status: "running" },
    };
    const list = seats({ run: run("running", { lineup: LINEUP }), steps: [], live, messages: [pauta] });
    expect(stateOf(list, "riscos")).toMatchObject({ state: "responding", act: "Contestação" });
    expect(stateOf(list, "planejador")).toMatchObject({ state: "questioning", act: "Pergunta" });
    expect(stateOf(list, "analista").state).toBe("revising");
    const waitingLimit = seats({ run: run("running", { lineup: LINEUP }), steps: [], messages: [],
      live: { "conselho:riscos": { agent_id: "riscos", status: "running", wait: "Aguardando limite de uso." } } });
    expect(stateOf(waitingLimit, "riscos").state).toBe("unavailable");
  });

  it("mudança de posição aparece no lugar do participante", () => {
    const parecer = msg("conselho:analista", "analista", { meta: { opinion: { stance: "favoravel", sections: [] } } });
    const turn = msg("conselho:debate:1:analista", "analista", { meta: { deliberation: { phase: "debate", stance: "contraria", revised: true } } });
    const list = seats({ run: run("succeeded", { lineup: LINEUP }), steps: [], live: {}, messages: [parecer, turn] });
    expect(stateOf(list, "analista")).toMatchObject({ initialStance: "favoravel", stance: "contraria", changed: true, state: "done" });
    expect(stateOf(list, "analista").history.map((m) => m.step_key)).toEqual(["conselho:analista", "conselho:debate:1:analista"]);
  });

  it("falha e retomada: passo que falhou deixa o participante indisponível; os demais concluem", () => {
    const messages = [msg("conselho:planejador", "planejador", { status: "error" }), msg("conselho:riscos", "riscos"),
      msg("conselho:analista", "analista"), msg("conselho:sintese", "mentor", { kind: "message", audit: { verdict: "PASSA", reasons: [], checked_numbers: 0 } })];
    const list = seats({ run: run("partial", { lineup: LINEUP }), steps: [step("conselho:planejador", "planejador", "failed")], live: {}, messages });
    expect(list.map((s) => s.state)).toEqual(["done", "unavailable", "done", "done", "done"]);
    const resumed = seats({ run: run("running", { lineup: LINEUP }), steps: [step("conselho:planejador", "planejador", "failed")],
      live: { "conselho:planejador": { agent_id: "planejador", status: "retrying" } }, messages: [] });
    expect(stateOf(resumed, "planejador")).toMatchObject({ state: "analyzing", active: true });
  });

  it("etapas: discussão aparece em reunião completa; consulta rápida não tem enquadramento", () => {
    const full = phases({ run: run("running", { lineup: LINEUP, mode: "completo" }), steps: [], live: {}, messages: [msg("conselho:enquadramento", "mentor")] });
    expect(full.map((p) => p.key)).toEqual(["enquadramento", "pareceres", "discussao", "sintese", "auditoria"]);
    expect(full[0]!.state).toBe("done");
    const quick = phases({ run: run("succeeded", { lineup: ["mentor", "planejador", "auditor"], mode: "rapida" }), steps: [], live: {}, messages: [] });
    expect(quick.map((p) => p.key)).toEqual(["pareceres", "sintese", "auditoria"]);
  });

  it("fio da discussão: posições iniciais juntas, pauta, falas com resposta e intervenção da pessoa", () => {
    const person = { ...msg("u1", "lastro"), id: "u1", role: "user" as const, run_id: null, step_key: null, kind: "message" as const,
      content: "@rui, por que discorda?", meta: { intervention_for: "r1" } };
    const turn = msg("conselho:debate:1:riscos", "riscos", { meta: { deliberation: { kind: "contestacao", reaction: "discorda",
      responds_to: { agent: "analista", message_id: "conselho:analista" } } } });
    const answer = msg("conselho:debate:2:riscos", "riscos", { meta: { deliberation: { kind: "resposta", responds_to: { person: true, message_id: "u1" } } } });
    const items = feed([msg("conselho:enquadramento", "mentor"), msg("conselho:planejador", "planejador"), msg("conselho:riscos", "riscos"),
      pauta, turn, person, answer, msg("conselho:posicoes", "lastro"), msg("conselho:sintese", "mentor")]);
    expect(items.map((i) => i.type)).toEqual(["abertura", "iniciais", "pauta", "fala", "pessoa", "fala"]);
    expect(items[1]).toMatchObject({ type: "iniciais" });
    expect(items[3]).toMatchObject({ label: "Contestação", target: "analista", reaction: "discorda" });
    expect(items[5]).toMatchObject({ toPerson: true, label: "Resposta" });
  });

  it("agrupa cada reunião (com as intervenções) em um bloco e deixa análises do Radar como mensagens", () => {
    const q = { ...msg("q1", "lastro"), id: "q1", role: "user" as const, run_id: null, step_key: null, kind: "message" as const };
    const inter = { ...q, id: "u9", meta: { intervention_for: "r1" } };
    const other = { ...msg("x", "mentor"), id: "x", run_id: "r9", step_key: "resposta:mentor" };
    const blocks = threadBlocks([q, msg("conselho:riscos", "riscos"), inter, other], [run("succeeded"), { ...run("succeeded", { radar: "o1" }), id: "r9" }]);
    expect(blocks.map((b) => b.kind)).toEqual(["council", "message"]);
    expect(blocks[0]).toMatchObject({ kind: "council", question: { id: "q1" } });
    expect((blocks[0] as { messages: TeamMessage[] }).messages.map((m) => m.id)).toEqual(["conselho:riscos", "u9"]);
  });
});

describe("máscara do modo apresentação", () => {
  it("esconde valores em reais sem tocar no resto", () => {
    expect(maskMoney("Gastei R$ 1.234,56 e R$38 hoje; meta de R$ 50 mil e 2,5 milhões de pessoas."))
      .toBe(`Gastei ${MASK} e ${MASK} hoje; meta de ${MASK} e 2,5 milhões de pessoas.`);
    expect(maskMoney("Sobram 400 reais. Selic de 10,5% a.a.")).toBe(`Sobram ${MASK}. Selic de 10,5% a.a.`);
  });
});
