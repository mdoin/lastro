// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import type { RunStep, TeamMessage, TeamRun } from "../api/types";
import { lineup, phases, seats, threadBlocks, type LiveStep } from "./council";
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
const LINEUP = ["mentor", "planejador", "riscos", "auditor"];
const stateOf = (list: ReturnType<typeof seats>, agent: string) => list.find((s) => s.agent === agent)!;

describe("sala do Conselho", () => {
  it("usa a escalação gravada e, em execuções antigas, a deduzida dos passos", () => {
    expect(lineup(run("queued", { lineup: LINEUP }), [])).toEqual(LINEUP);
    expect(lineup(run("succeeded"), [step("conselho:enquadramento", "mentor", "succeeded"), step("conselho:cripto", "cripto", "succeeded"),
      step("conselho:contestacao:cripto", "cripto", "succeeded")])).toEqual(["mentor", "cripto", "auditor"]);
  });

  it("na fila, ninguém aparece trabalhando", () => {
    const list = seats({ run: run("queued", { lineup: LINEUP }), steps: [], live: {}, messages: [] });
    expect(list.map((s) => s.state)).toEqual(["queued", "queued", "queued", "queued"]);
    expect(list.some((s) => s.active)).toBe(false);
  });

  it("reflete o passo real: ferramenta = consultando; sem ferramenta = analisando; parecer publicado = disponível", () => {
    const live: Record<string, LiveStep> = {
      "conselho:planejador": { agent_id: "planejador", status: "running", tool: "situacao_atual" },
      "conselho:riscos": { agent_id: "riscos", status: "running" },
    };
    const list = seats({ run: run("running", { lineup: LINEUP }), steps: [], live, messages: [msg("conselho:enquadramento", "mentor")] });
    expect(stateOf(list, "planejador")).toMatchObject({ state: "consulting", active: true });
    expect(stateOf(list, "riscos")).toMatchObject({ state: "analyzing", active: true });
    expect(stateOf(list, "mentor")).toMatchObject({ state: "queued", act: "Enquadramento feito", active: false });

    const after = seats({ run: run("running", { lineup: LINEUP }), steps: [], live: {},
      messages: [msg("conselho:planejador", "planejador", { meta: { opinion: { stance: "contraria", sections: [] } } })] });
    expect(stateOf(after, "planejador")).toMatchObject({ state: "available", stance: "contraria" });
  });

  it("correção do parecer e síntese à espera do Auditor aparecem como aguardando revisão", () => {
    const list = seats({
      run: run("running", { lineup: LINEUP }),
      steps: [step("conselho:sintese", "mentor", "succeeded")],
      live: { "conselho:riscos:correcao": { agent_id: "riscos", status: "running" } },
      messages: [],
    });
    expect(stateOf(list, "riscos").state).toBe("review");
    expect(stateOf(list, "mentor")).toMatchObject({ state: "review", act: "Síntese" });
  });

  it("falha e retomada: passo que falhou mostra Falhou; os demais concluem", () => {
    const messages = [msg("conselho:planejador", "planejador", { status: "error" }), msg("conselho:riscos", "riscos"),
      msg("conselho:sintese", "mentor", { kind: "message", audit: { verdict: "PASSA", reasons: [], checked_numbers: 0 } })];
    const list = seats({ run: run("partial", { lineup: LINEUP }), steps: [step("conselho:planejador", "planejador", "failed")], live: {}, messages });
    expect(list.map((s) => s.state)).toEqual(["done", "failed", "done", "done"]);
    // retomada: depois do reinício o passo volta a rodar e o estado acompanha
    const resumed = seats({ run: run("running", { lineup: LINEUP }), steps: [step("conselho:planejador", "planejador", "failed")],
      live: { "conselho:planejador": { agent_id: "planejador", status: "retrying" } }, messages: [] });
    expect(stateOf(resumed, "planejador")).toMatchObject({ state: "analyzing", active: true });
  });

  it("etapas: contestação só aparece quando existiu", () => {
    const base = { run: run("running", { lineup: LINEUP }), steps: [] as RunStep[], live: {}, messages: [msg("conselho:enquadramento", "mentor")] };
    expect(phases(base).map((p) => p.key)).toEqual(["enquadramento", "pareceres", "sintese", "auditoria"]);
    const contested = phases({ ...base, live: { "conselho:contestacao:riscos": { agent_id: "riscos", status: "running" } } });
    expect(contested.find((p) => p.key === "contestacao")?.state).toBe("active");
    expect(contested[0]!.state).toBe("done");
  });

  it("agrupa cada reunião em um bloco e deixa análises do Radar como mensagens", () => {
    const q = { ...msg("q1", "lastro"), id: "q1", role: "user" as const, run_id: null, step_key: null, kind: "message" as const };
    const other = { ...msg("x", "mentor"), id: "x", run_id: "r9", step_key: "resposta:mentor" };
    const blocks = threadBlocks([q, msg("conselho:riscos", "riscos"), other], [run("succeeded"), { ...run("succeeded", { radar: "o1" }), id: "r9" }]);
    expect(blocks.map((b) => b.kind)).toEqual(["council", "message"]);
    expect(blocks[0]).toMatchObject({ kind: "council", question: { id: "q1" } });
  });
});

describe("máscara do modo apresentação", () => {
  it("esconde valores em reais sem tocar no resto", () => {
    expect(maskMoney("Gastei R$ 1.234,56 e R$38 hoje; meta de R$ 50 mil e 2,5 milhões de pessoas."))
      .toBe(`Gastei ${MASK} e ${MASK} hoje; meta de ${MASK} e 2,5 milhões de pessoas.`);
    expect(maskMoney("Sobram 400 reais. Selic de 10,5% a.a.")).toBe(`Sobram ${MASK}. Selic de 10,5% a.a.`);
  });
});
