// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import type { TeamMessage } from "../api/types";
import type { Seat } from "./council";
import { overlay, posture } from "./expressions";

const name = (id: string) => ({ caio: "Caio", rui: "Rui" }[id] ?? id);
const seat = (agent: string, extra: Partial<Seat> = {}): Seat => ({ agent, state: "available", active: false, history: [], changed: false, ...extra });
let t = 0;
const turn = (agent: string, d: Record<string, unknown>): TeamMessage => ({
  id: `m${++t}`, conversation_id: "c", role: "assistant", content: "x", status: "ok", agent_id: agent, run_id: "r",
  step_key: `conselho:debate:1:${agent}`, client_id: null, reply_to_id: null, mentions: [], sources: [], kind: "message",
  created_at: `2026-01-01T00:00:${String(t).padStart(2, "0")}`, meta: { deliberation: d },
} as unknown as TeamMessage);

describe("posture", () => {
  it("vem do estado em curso", () => {
    expect(posture(seat("caio", { active: true, state: "questioning" }), [], name).expression).toBe("desconfiado");
    expect(posture(seat("caio", { active: true, state: "consulting" }), [], name).expression).toBe("pensativo");
  });

  it("vem da última fala registrada, com o motivo em texto", () => {
    const p = posture(seat("rui"), [turn("rui", { reaction: "discorda", responds_to: { agent: "caio" } })], name);
    expect(p).toEqual({ expression: "discordando", reason: "discordou de @Caio" });
    const again = posture(seat("rui"), [
      turn("rui", { reaction: "discorda", responds_to: { agent: "caio" } }),
      turn("rui", { reaction: "discorda", responds_to: { agent: "caio" } }),
    ], name);
    expect(again.expression).toBe("irritado");
    expect(posture(seat("caio"), [turn("caio", { revised: true, responds_to: { agent: "rui" } })], name).expression).toBe("surpreso");
  });

  it("contestado e sem resposta fica pensativo; sem fala, vale a posição declarada", () => {
    expect(posture(seat("caio", { stance: "favoravel" }), [turn("rui", { reaction: "discorda", responds_to: { agent: "caio" } })], name).expression).toBe("pensativo");
    expect(posture(seat("caio", { stance: "favoravel" }), [], name).expression).toBe("entusiasmado");
    expect(posture(seat("caio"), [], name).expression).toBe("neutro");
  });

  it("nunca atribui 'debochado' (nenhum evento o justifica)", () => {
    const reactions = ["concorda", "discorda", "pergunta", "complementa", "reconhece", "revisa", null];
    const stances = ["favoravel", "contraria", "condicional", "insuficiente", null] as const;
    for (const r of reactions) for (const s of stances) {
      expect(posture(seat("caio", { stance: s }), [turn("caio", { reaction: r })], name).expression).not.toBe("debochado");
    }
  });
});

describe("overlay", () => {
  it("neutro não altera o desenho; as outras expressões ficam dentro do corpo", () => {
    expect(overlay("analista", "neutro")).toEqual([]);
    const px = overlay("analista", "irritado");
    expect(px.length).toBeGreaterThan(0);
    expect(px.every((p) => p.x >= 0 && p.x < 16 && p.y >= 0 && p.y < 16)).toBe(true);
  });
});
