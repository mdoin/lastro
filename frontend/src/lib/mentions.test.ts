// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { applyMention, filterCandidates, linkMentions, mentionAt, resolveMention, splitMentions } from "./mentions";

const agents = [
  { handle: "economista", name: "Economista" },
  { handle: "riscos", name: "Gestor de Riscos" },
  { handle: "conselheiro", name: "Conselheiro" },
];

describe("menções", () => {
  it("detecta a menção em edição só no início ou após espaço", () => {
    expect(mentionAt("Oi @eco", 7)).toEqual({ start: 3, query: "eco" });
    expect(mentionAt("@", 1)).toEqual({ start: 0, query: "" });
    expect(mentionAt("email@eco", 9)).toBeNull();
    expect(mentionAt("@eco fala", 9)).toBeNull();
  });

  it("filtra por handle ou nome, sem acento", () => {
    expect(filterCandidates(agents, "co").map((a) => a.handle)).toEqual(["conselheiro"]);
    expect(filterCandidates(agents, "GES").map((a) => a.handle)).toEqual(["riscos"]);
  });

  it("completa e posiciona o cursor depois do handle", () => {
    const at = mentionAt("Pergunta para @ec agora", 17)!;
    expect(applyMention("Pergunta para @ec agora", at, "economista")).toEqual({
      text: "Pergunta para @economista agora",
      caret: 26,
    });
  });
});

describe("menções no texto", () => {
  const team = [{ id: "riscos", handle: "rui", name: "Rui" }, { id: "comportamental", handle: "nina", name: "Nina" }];
  it("só agentes reais viram menção; e-mail e @desconhecido seguem texto", () => {
    expect(splitMentions("Concordo com o @rui e a @Nina. @fulano, a@b.com", team)).toEqual(
      ["Concordo com o ", team[0], " e a ", team[1], ". @fulano, a@b.com"]);
    expect(linkMentions("@RUI, e aí?", team)).toBe("[@Rui](#agente-riscos), e aí?");
    expect(resolveMention(team, "riscos")?.name).toBe("Rui");
  });
});
