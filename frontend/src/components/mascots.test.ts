// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { EYE_CHARS, GRID, MASCOTS, runs } from "./mascots";

describe("mascotes", () => {
  const all = Object.values(MASCOTS);

  it("tem os nove agentes, cada um numa grade 16×16 com só cores da paleta", () => {
    expect(Object.keys(MASCOTS).sort()).toEqual(
      ["analista", "auditor", "comportamental", "cripto", "economista", "mentor", "mila", "planejador", "riscos"],
    );
    for (const m of all) {
      expect(m.rows).toHaveLength(GRID);
      for (const row of m.rows) {
        expect(row).toHaveLength(GRID);
        for (const ch of row) if (ch !== ".") expect(m.palette[ch], `${m.id}: ${ch}`).toBeDefined();
      }
    }
  });

  it("todos têm olhos (que piscam) e texto alternativo", () => {
    for (const m of all) {
      expect(runs(m.rows).some((r) => EYE_CHARS.has(r.ch)), m.id).toBe(true);
      expect(m.alt.length).toBeGreaterThan(10);
    }
  });

  it("nenhum é recolorido de outro: silhuetas diferentes", () => {
    const shape = (rows: string[]) => rows.map((r) => r.replace(/[^.]/g, "#")).join("\n");
    const shapes = new Set(all.map((m) => shape(m.rows)));
    expect(shapes.size).toBe(all.length);
  });

  it("junta pixels vizinhos sem perder nenhum", () => {
    for (const m of all) {
      const painted = m.rows.join("").replace(/\./g, "").length;
      expect(runs(m.rows).reduce((n, r) => n + r.w, 0)).toBe(painted);
    }
  });
});
