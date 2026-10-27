// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { safeNext } from "./safeNext";

describe("safeNext", () => {
  beforeEach(() => {
    (globalThis as { window?: unknown }).window = { location: { origin: "https://lastro.example" } };
  });
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  it("mantém caminhos internos", () => {
    expect(safeNext("/mentor?c=1#fim")).toBe("/mentor?c=1#fim");
  });

  it("recusa destinos de outro site e o próprio login", () => {
    for (const raw of [null, "", "https://evil.example", "//evil.example", "/\\evil.example", "/\t/evil.example",
      "/\n/evil.example", "/login?next=/x"]) {
      expect(safeNext(raw)).toBe("/");
    }
  });
});
