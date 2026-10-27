// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import {
  NBSP,
  addDecimals,
  compareDecimals,
  decimalToInputBRL,
  formatBRL,
  formatNumberBR,
  formatPct,
  formatPercentPoints,
  fractionToPercentInput,
  parseBRL,
  parsePercent,
  ratioDecimal,
  roundDecimal,
  subtractDecimals,
} from "./money";

const brl = (s: string) => s.replace(/ /g, NBSP);

describe("parseBRL (espelha backend parse_brl)", () => {
  it.each([
    ["R$ 1.234,56", "1234.56"],
    ["150", "150"],
    ["150,00", "150.00"],
    ["0,5", "0.5"],
    ["1.000", "1000"],
    ["1.234.567,89", "1234567.89"],
    ["-R$ 10,00", "-10.00"],
    ["(10,00)", "-10.00"],
    ["R$ 10,00", "10.00"],
    ["  R$ 1.234,56 ", "1234.56"],
    [",5", "0.5"],
    ["007", "7"],
    ["-0", "0"],
  ])("aceita %j → %s", (text, expected) => {
    expect(parseBRL(text)).toEqual({ ok: true, value: expected });
  });

  it.each(["10.50", "0.5", "1,234,56", "12.34,5", "abc", "", "1.2345", "10,", "1e3", "R$", "--5", "1,5,0"])(
    "recusa %j",
    (text) => {
      const r = parseBRL(text);
      expect(r.ok).toBe(false);
    },
  );

  it("explica a ambiguidade de 10.50", () => {
    const r = parseBRL("10.50");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/vírgula para centavos/);
  });
});

describe("parsePercent", () => {
  it.each([
    ["12", "0.12"],
    ["12%", "0.12"],
    ["2,5", "0.025"],
    ["0,8 %", "0.008"],
    ["100", "1.00"],
    ["-1,5", "-0.015"],
  ])("%j → %s", (text, expected) => {
    expect(parsePercent(text)).toEqual({ ok: true, value: expected });
  });

  it("recusa 2.5 (ambíguo)", () => {
    expect(parsePercent("2.5").ok).toBe(false);
  });
});

describe("formatBRL / formatPct sem float", () => {
  it("formata como o backend", () => {
    expect(formatBRL("1234567.891")).toBe(brl("R$ 1.234.567,89"));
    expect(formatBRL("-0.5")).toBe(brl("-R$ 0,50"));
    expect(formatBRL("1234.56")).toBe(brl("R$ 1.234,56"));
    expect(formatBRL("0")).toBe(brl("R$ 0,00"));
    expect(formatBRL("-0.001")).toBe(brl("R$ 0,00"));
  });

  it("arredonda meio para cima (ROUND_HALF_UP)", () => {
    expect(formatBRL("0.005")).toBe(brl("R$ 0,01"));
    expect(formatBRL("-0.005")).toBe(brl("-R$ 0,01"));
    expect(formatBRL("2.675")).toBe(brl("R$ 2,68")); // float daria 2,67
    expect(formatBRL("999.995")).toBe(brl("R$ 1.000,00"));
  });

  it("preserva precisão acima do float", () => {
    expect(formatBRL("12345678901234567890.12")).toBe(brl("R$ 12.345.678.901.234.567.890,12"));
    expect(formatBRL("0.1")).toBe(brl("R$ 0,10"));
  });

  it("aceita notação exponencial do Decimal do Python", () => {
    expect(formatBRL("1E+3")).toBe(brl("R$ 1.000,00"));
    expect(formatBRL("0E-10")).toBe(brl("R$ 0,00"));
  });

  it("valores ausentes ou inválidos", () => {
    expect(formatBRL(null)).toBe("—");
    expect(formatBRL(undefined)).toBe("—");
    expect(formatBRL("abc")).toBe("—");
    expect(formatBRL("1,5")).toBe("—");
  });

  it("percentuais", () => {
    expect(formatPct("0.12")).toBe("12,00%");
    expect(formatPct("0.1786")).toBe("17,86%");
    expect(formatPct("0.017864")).toBe("1,79%");
    expect(formatPct("0.00125", 3)).toBe("0,125%");
    expect(formatPct("-0.05")).toBe("-5,00%");
    expect(formatPct("12.5")).toBe("1.250,00%");
    expect(formatPct(null)).toBe("—");
  });

  it("número genérico", () => {
    expect(formatNumberBR("2.5", 1)).toBe("2,5");
    expect(formatNumberBR("1234", 0)).toBe("1.234");
  });
});

describe("conversões para campos", () => {
  it("decimal → campo de dinheiro", () => {
    expect(decimalToInputBRL("1234.5")).toBe("1.234,50");
    expect(decimalToInputBRL(null)).toBe("");
  });
  it("fração → campo percentual", () => {
    expect(fractionToPercentInput("0.025")).toBe("2,5");
    expect(fractionToPercentInput("0.12")).toBe("12");
    expect(fractionToPercentInput("0.1200")).toBe("12");
    expect(fractionToPercentInput("0")).toBe("0");
    expect(fractionToPercentInput("0.0005")).toBe("0,05");
  });
  it("ida e volta percentual", () => {
    for (const v of ["0.025", "0.12", "0.0005", "1.5"]) {
      const r = parsePercent(fractionToPercentInput(v));
      expect(r.ok).toBe(true);
      if (r.ok) expect(compareDecimals(r.value, v)).toBe(0);
    }
  });
});

describe("aritmética exata", () => {
  it("soma e subtrai sem erro de float", () => {
    expect(addDecimals("0.1", "0.2")).toBe("0.3");
    expect(subtractDecimals("1000.00", "8400.00")).toBe("-7400.00");
    expect(subtractDecimals("0.3", "0.1")).toBe("0.2");
    expect(addDecimals("1", "x")).toBeNull();
  });
  it("compara", () => {
    expect(compareDecimals("10.0", "10")).toBe(0);
    expect(compareDecimals("-1", "0")).toBe(-1);
    expect(compareDecimals("2.01", "2.001")).toBe(1);
  });
  it("arredonda", () => {
    expect(roundDecimal("1.005")).toBe("1.01");
    expect(roundDecimal("-2.5", 0)).toBe("-3");
  });
});

describe("formatPercentPoints", () => {
  it("não multiplica por 100 valores que já são pontos percentuais", () => {
    expect(formatPercentPoints("100.0")).toBe("100,0%");
    expect(formatPercentPoints("33.3")).toBe("33,3%");
    expect(formatPercentPoints(null)).toBe("—");
  });
});

describe("ratioDecimal", () => {
  it("divide sem float, com arredondamento meio-para-cima", () => {
    expect(ratioDecimal("50", "200")).toBe("0.2500");
    expect(ratioDecimal("1", "3")).toBe("0.3333");
    expect(ratioDecimal("2", "3")).toBe("0.6667");
    expect(ratioDecimal("1", "8", 2)).toBe("0.13");
    expect(ratioDecimal("0.1", "0.3", 6)).toBe("0.333333");
  });
  it("mantém o sinal e recusa divisor zero ou texto inválido", () => {
    expect(ratioDecimal("-300", "5250", 4)).toBe("-0.0571");
    expect(ratioDecimal("300", "-1", 0)).toBe("-300");
    expect(ratioDecimal("0", "-5")).toBe("0.0000");
    expect(ratioDecimal("5", "0")).toBeNull();
    expect(ratioDecimal("x", "1")).toBeNull();
  });
  it("combina com formatPct", () => {
    expect(formatPct(ratioDecimal("500", "5250"), 1)).toBe("9,5%");
  });
});
