// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import type { RunStep, TeamMessage, TeamRun } from "../api/types";
import { chapters, contributionType, convocation, feed, lineup, narrative, phases, quoted, replayInput, seats, spotlight, threadBlocks, tracks, type LiveStep } from "./council";
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

describe("palco, narrativa e replay", () => {
  const opinion = (agent: string, stance: "favoravel" | "contraria", tese: string) =>
    msg(`conselho:${agent}`, agent, { meta: { opinion: { stance, sections: [], excerpts: { tese } } } });
  const caio = opinion("analista", "favoravel", "O preço subiu com volume alto.");
  const rui = opinion("riscos", "contraria", "A reserva não cobre seis meses.");
  const lia = opinion("planejador", "favoravel", "Cabe no orçamento.");
  const contest = msg("conselho:debate:1:riscos", "riscos", { id: "t1", content: "**Posição:** contrária\nVolume alto não prova nada. Veja o resto.",
    meta: { deliberation: { kind: "contestacao", reaction: "discorda", stance: "contraria", responds_to: { agent: "analista", message_id: "conselho:analista" } } } });
  const revise = msg("conselho:debate:2:analista", "analista", { id: "t2", content: "Rui tem razão sobre a reserva. Mudo para contrária.",
    meta: { deliberation: { kind: "resposta", reaction: "reconhece", revised: true, stance: "contraria", responds_to: { agent: "riscos", message_id: "t1" } } } });
  const synth = msg("conselho:sintese", "mentor", { audit: { verdict: "PASSA", reasons: [], checked_numbers: 0 } });
  const all = [msg("conselho:enquadramento", "mentor"), lia, rui, caio, pauta, contest, revise, synth];
  const ended = { run: run("succeeded", { lineup: LINEUP }), steps: [], live: {}, messages: all };

  it("tipo da contribuição vem dos metadados", () => {
    expect([caio, contest, revise, synth].map((m) => contributionType(m).label)).toEqual(["Análise inicial", "Contestação", "Revisão de posição", "Conclusão"]);
    const agrees = msg("conselho:debate:1:planejador", "planejador", { meta: { deliberation: { reaction: "concorda" } } });
    expect(contributionType(agrees)).toMatchObject({ label: "Concordância", fromReaction: true });
  });

  it("narrativa: nada concluído antes da hora; etapas condicionais só quando aconteceram", () => {
    const start = narrative({ run: run("running", { lineup: LINEUP }), steps: [], live: {}, messages: [] });
    expect(start.map((s) => [s.key, s.state])).toEqual([["convocado", "done"], ["analise", "pending"], ["auditoria", "pending"], ["conclusao", "pending"]]);
    const half = narrative({ run: run("running", { lineup: LINEUP }), steps: [], live: {}, messages: [lia] });
    expect(half.find((s) => s.key === "analise")).toMatchObject({ state: "active", text: "Os especialistas estão analisando" });
    const live = narrative({ run: run("running", { lineup: LINEUP }), steps: [], messages: [lia, rui, caio, pauta, contest],
      live: { "conselho:debate:2:analista": { agent_id: "analista", status: "running" } } });
    expect(live.map((s) => s.key)).toEqual(["convocado", "analise", "divergencias", "discussao", "auditoria", "conclusao"]);
    expect(live.find((s) => s.key === "discussao")!.state).toBe("active");
    expect(live.find((s) => s.key === "conclusao")!.state).toBe("pending");
    const done = narrative(ended, "Bento");
    expect(done.map((s) => s.key)).toEqual(["convocado", "analise", "divergencias", "discussao", "revisao", "redacao", "auditoria", "conclusao"]);
    expect(done.every((s) => s.state === "done")).toBe(true);
    const failed = narrative({ run: run("failed", { lineup: LINEUP }), steps: [], live: {}, messages: [lia] });
    expect(failed.find((s) => s.key === "conclusao")!.state).toBe("skipped");
  });

  it("holofote: fala em curso com o alvo da pauta; senão a última contribuição", () => {
    const live = spotlight({ run: run("running", { lineup: LINEUP }), steps: [], messages: [pauta],
      live: { "conselho:debate:1:riscos": { agent_id: "riscos", status: "running", text: "Não concordo. Mais texto" } } });
    expect(live).toMatchObject({ speaker: "riscos", target: "analista", label: "Contestação", text: "Não concordo.", live: true });
    expect(spotlight(ended)).toMatchObject({ speaker: "mentor", label: "Conclusão" });
    expect(spotlight({ ...ended, messages: all.slice(0, 6) })).toMatchObject({ speaker: "riscos", target: "analista", text: "Volume alto não prova nada." });
  });

  it("argumento contestado e revisão de posição vêm do registro", () => {
    expect(quoted(contest, all)).toMatchObject({ message: { id: "conselho:analista" }, excerpt: "O preço subiu com volume alto.", contested: true });
    expect(quoted(revise, all)).toMatchObject({ message: { id: "t1" }, excerpt: "Volume alto não prova nada.", contested: false });
    const [, analista, planejador] = tracks(all, ["mentor", "riscos", "analista", "planejador", "auditor"]);
    expect(analista).toMatchObject({ initial: "favoravel", current: "contraria", thesis: "O preço subiu com volume alto.", now: "Rui tem razão sobre a reserva." });
    expect(analista!.changes).toHaveLength(1);
    expect(analista!.changes[0]).toMatchObject({ from: "favoravel", to: "contraria", after: "riscos" });
    expect(planejador).toMatchObject({ initial: "favoravel", current: "favoravel", changes: [] });
  });

  it("convocação automática: hipótese e evidências do contexto do Radar", () => {
    const text = "Evento detectado\nHipótese a investigar: queda com volume\nEvidências:\n- BTC -8% em 4 h\n- volume 3x\nFontes: Binance";
    expect(convocation(text)).toEqual({ hypothesis: "queda com volume", evidence: ["BTC -8% em 4 h", "volume 3x"] });
    expect(convocation(undefined)).toEqual({ hypothesis: undefined, evidence: [] });
  });

  it("replay: capítulos na ordem publicada e sala só com o que já existia", () => {
    expect(chapters(all).map((c) => [c.key, c.index])).toEqual([["abertura", 0], ["analise", 1], ["discussao", 5], ["revisao", 6], ["conclusao", 7]]);
    const frame = replayInput(ended, 2);
    expect(frame.messages.map((m) => m.id)).toEqual(["conselho:enquadramento", "conselho:planejador", "conselho:riscos"]);
    expect(frame.run.status).toBe("running");
    expect(narrative(frame).find((s) => s.key === "conclusao")!.state).toBe("pending");
    expect(replayInput(ended, all.length - 1).run.status).toBe("succeeded");
  });
});
