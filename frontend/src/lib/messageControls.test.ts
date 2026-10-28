// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import type { TeamMessage } from "../api/types";
import { canRecord, visibleAudit } from "./messageControls";

const msg = (over: Partial<TeamMessage> = {}): TeamMessage => ({
  id: "m", role: "assistant", content: "Oi!", status: "ok", tools: [], audit: { verdict: "PASSA", reasons: [], checked_numbers: 0 },
  created_at: "2026-10-27T10:00:00Z", agent_id: "riscos", run_id: "r", step_key: "resposta:riscos", client_id: null,
  reply_to_id: null, mentions: [], sources: [], kind: "message", ...over,
});

describe("controles da mensagem conforme o conteúdo", () => {
  it("papo e pergunta sem números não ganham selo nem Registrar no Diário", () => {
    for (const m of [msg(), msg({ meta: { chat: { style: "conversa", intent: "conversa" } } })]) {
      expect(visibleAudit(m)).toBeNull();
      expect(canRecord(m)).toBe(false);
    }
  });

  it("resposta com números conferidos ou fontes mantém o selo e o registro", () => {
    const numbers = msg({ audit: { verdict: "PASSA", reasons: [], checked_numbers: 3 } });
    const sourced = msg({ sources: [{ kind: "mercado", label: "Selic" }] });
    for (const m of [numbers, sourced]) {
      expect(visibleAudit(m)?.verdict).toBe("PASSA");
      expect(canRecord(m)).toBe(true);
    }
    expect(canRecord(msg({ meta: { chat: { intent: "decisao" } } }))).toBe(true);
  });

  it("ressalva e reprovação aparecem até no papo", () => {
    const chat = { meta: { chat: { style: "conversa" } } };
    expect(visibleAudit(msg({ ...chat, audit: { verdict: "REPROVA", reasons: ["x"] } }))?.verdict).toBe("REPROVA");
    expect(visibleAudit(msg({ ...chat, audit: { verdict: "PASSA COM RESSALVAS", reasons: ["y"] } }))?.verdict).toBe("PASSA COM RESSALVAS");
  });
});
