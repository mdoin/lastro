/**
 * Dinheiro e taxas no frontend.
 *
 * Regra: valores vindos da API são strings decimais com ponto ("1234.56", "0.12").
 * Nunca passam por float para exibição ou envio — toda formatação e conversão aqui
 * é feita por manipulação de string / BigInt. `toChartNumber` é a única saída para
 * float e existe só para geometria de gráficos.
 *
 * `parseBRL` espelha `backend/financial_engine/money.py::parse_brl`:
 * ponto separa milhar, vírgula separa centavos e entradas ambíguas ("10.50") são recusadas.
 */

/** Espaço não separável entre "R$" e o número: evita quebra de linha no meio do valor. */
export const NBSP = " ";

interface Dec {
  neg: boolean;
  /** Dígitos sem sinal e sem ponto, sem zeros à esquerda (exceto "0"). */
  digits: string;
  /** Quantidade de dígitos depois do ponto decimal. */
  scale: number;
}

const DECIMAL_RE = /^([+-])?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/;

/** Lê uma string decimal da API (aceita também notação exponencial do `str(Decimal)` do Python). */
function readDecimal(input: string): Dec | null {
  const s = input.trim();
  const m = DECIMAL_RE.exec(s);
  if (!m) return null;
  const intPart = m[2] ?? "";
  const fracPart = m[3] ?? "";
  if (intPart === "" && fracPart === "") return null;
  let digits = intPart + fracPart;
  let scale = fracPart.length;
  const exp = m[4] ? Number.parseInt(m[4], 10) : 0;
  if (!Number.isSafeInteger(exp) || Math.abs(exp) > 400) return null;
  scale -= exp;
  if (scale < 0) {
    digits = digits + "0".repeat(-scale);
    scale = 0;
  }
  digits = digits.replace(/^0+(?=\d)/, "");
  if (digits === "") digits = "0";
  const neg = m[1] === "-" && /[1-9]/.test(digits);
  return { neg, digits, scale };
}

export function isDecimalString(value: unknown): value is string {
  return typeof value === "string" && readDecimal(value) !== null;
}

/** Inteiro escalado (BigInt) com arredondamento meio-para-cima (afastando de zero), como ROUND_HALF_UP. */
function toScaled(d: Dec, places: number): bigint {
  let mag: bigint;
  if (d.scale <= places) {
    mag = BigInt(d.digits + "0".repeat(places - d.scale));
  } else {
    const cut = d.scale - places;
    const padded = d.digits.padStart(cut + 1, "0");
    const keep = padded.slice(0, padded.length - cut);
    const dropped = padded.slice(padded.length - cut);
    mag = BigInt(keep);
    if ((dropped[0] ?? "0") >= "5") mag += 1n;
  }
  return d.neg ? -mag : mag;
}

function scaledToPlain(value: bigint, places: number): { neg: boolean; int: string; frac: string } {
  const neg = value < 0n;
  const abs = (neg ? -value : value).toString().padStart(places + 1, "0");
  const int = abs.slice(0, abs.length - places);
  const frac = places > 0 ? abs.slice(abs.length - places) : "";
  return { neg: neg && /[1-9]/.test(int + frac), int, frac };
}

function groupThousands(int: string): string {
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/** Arredonda (ROUND_HALF_UP) e devolve string decimal com ponto. */
export function roundDecimal(value: string, places = 2): string {
  const d = readDecimal(value);
  if (!d) throw new Error(`Número inválido: ${value}`);
  const p = scaledToPlain(toScaled(d, places), places);
  return `${p.neg ? "-" : ""}${p.int}${places > 0 ? "." + p.frac : ""}`;
}

/** Número no padrão brasileiro sem símbolo: "1.234,56". */
export function formatNumberBR(value: string, places = 2): string {
  const d = readDecimal(value);
  if (!d) return "—";
  const p = scaledToPlain(toScaled(d, places), places);
  return `${p.neg ? "-" : ""}${groupThousands(p.int)}${places > 0 ? "," + p.frac : ""}`;
}

/** "R$ 1.234,56" / "-R$ 10,00". `null`/`undefined`/inválido → "—". */
export function formatBRL(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const d = readDecimal(value);
  if (!d) return "—";
  const p = scaledToPlain(toScaled(d, 2), 2);
  return `${p.neg ? "-" : ""}R$${NBSP}${groupThousands(p.int)},${p.frac}`;
}

/** Desloca a vírgula decimal `shift` casas (positivo = multiplica por 10^shift). Sem float. */
function shiftDecimal(d: Dec, shift: number): Dec {
  let { digits, scale } = d;
  scale -= shift;
  if (scale < 0) {
    digits = digits + "0".repeat(-scale);
    scale = 0;
  }
  digits = digits.replace(/^0+(?=\d)/, "");
  return { neg: d.neg, digits, scale };
}

/** Fração → percentual: "0.12" → "12,00%". */
export function formatPct(rate: string | null | undefined, places = 2): string {
  if (rate === null || rate === undefined) return "—";
  const d = readDecimal(rate);
  if (!d) return "—";
  const p = scaledToPlain(toScaled(shiftDecimal(d, 2), places), places);
  return `${p.neg ? "-" : ""}${groupThousands(p.int)}${places > 0 ? "," + p.frac : ""}%`;
}

/** Pontos percentuais já calculados pela API → texto: "100.0" → "100,0%" (sem multiplicar por 100). */
export function formatPercentPoints(points: string | null | undefined, places = 1): string {
  if (points === null || points === undefined) return "—";
  const d = readDecimal(points);
  if (!d) return "—";
  const p = scaledToPlain(toScaled(d, places), places);
  return `${p.neg ? "-" : ""}${groupThousands(p.int)}${places > 0 ? "," + p.frac : ""}%`;
}

/** Valor decimal da API → texto para preencher um campo de dinheiro ("1234.5" → "1.234,50"). */
export function decimalToInputBRL(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  return formatNumberBR(value, 2);
}

/** Fração da API → texto para campo percentual ("0.025" → "2,5"; "0.12" → "12"). */
export function fractionToPercentInput(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const d = readDecimal(value);
  if (!d) return "";
  const s = shiftDecimal(d, 2);
  const int = s.scale > 0 ? s.digits.padStart(s.scale + 1, "0").slice(0, -s.scale) : s.digits;
  const frac = s.scale > 0 ? s.digits.padStart(s.scale + 1, "0").slice(-s.scale).replace(/0+$/, "") : "";
  const intClean = int.replace(/^0+(?=\d)/, "");
  return `${s.neg ? "-" : ""}${groupThousands(intClean)}${frac ? "," + frac : ""}`;
}

// ---------------------------------------------------------------------------
// Entrada digitada pelo usuário
// ---------------------------------------------------------------------------

export type ParseResult = { ok: true; value: string } | { ok: false; error: string };

const BR_THOUSANDS = /^\d{1,3}(\.\d{3})+$/;
const PLAIN_NUMBER = /^\d+(\.\d+)?$/;
const ONLY_DIGITS = /^\d+$/;

/**
 * Converte texto no padrão brasileiro ("R$ 1.234,56", "150", "0,5") em string decimal com ponto
 * ("1234.56"). Mesmas regras de `parse_brl` no backend.
 */
export function parseBRL(text: string): ParseResult {
  let s = text.trim().replace(/R\$/g, "").replace(/[\s  ]/g, "");
  let negative = false;
  if (s.startsWith("(") && s.endsWith(")")) {
    negative = true;
    s = s.slice(1, -1);
  }
  if (s.startsWith("-")) {
    negative = true;
    s = s.slice(1);
  }
  if (!s) return { ok: false, error: "Valor vazio." };

  let number: string;
  if (s.includes(",")) {
    const idx = s.lastIndexOf(",");
    const integer = s.slice(0, idx);
    const frac = s.slice(idx + 1);
    if (integer.includes(",") || !ONLY_DIGITS.test(frac)) {
      return { ok: false, error: `Valor inválido: "${text}". Exemplo válido: 1.234,56` };
    }
    if (integer.includes(".") && !BR_THOUSANDS.test(integer)) {
      return { ok: false, error: `Separador de milhar inválido em "${text}". Use ponto a cada 3 dígitos (ex.: 1.234,56).` };
    }
    number = `${integer.replace(/\./g, "") || "0"}.${frac}`;
  } else if (s.includes(".")) {
    if (!BR_THOUSANDS.test(s)) {
      return {
        ok: false,
        error: `Valor ambíguo "${text}": use vírgula para centavos (ex.: 10,50) e ponto apenas para milhar (ex.: 1.000).`,
      };
    }
    number = s.replace(/\./g, "");
  } else {
    number = s;
  }

  if (!PLAIN_NUMBER.test(number)) {
    return { ok: false, error: `Valor inválido: "${text}". Use apenas números, ponto de milhar e vírgula de centavos.` };
  }
  const [i = "0", f] = number.split(".");
  const intClean = i.replace(/^0+(?=\d)/, "");
  const canonical = f !== undefined ? `${intClean}.${f}` : intClean;
  const isZero = !/[1-9]/.test(canonical);
  return { ok: true, value: negative && !isZero ? `-${canonical}` : canonical };
}

/** Percentual digitado ("2,5", "12%", "0,8") → fração decimal ("0.025", "0.12", "0.008"). */
export function parsePercent(text: string): ParseResult {
  const cleaned = text.replace(/%/g, "");
  const r = parseBRL(cleaned);
  if (!r.ok) return { ok: false, error: r.error.replace("Valor", "Percentual") };
  const d = readDecimal(r.value);
  if (!d) return { ok: false, error: `Percentual inválido: "${text}".` };
  const s = shiftDecimal(d, -2);
  const padded = s.digits.padStart(s.scale + 1, "0");
  const int = s.scale > 0 ? padded.slice(0, -s.scale) : padded;
  const frac = s.scale > 0 ? padded.slice(-s.scale) : "";
  return { ok: true, value: `${s.neg ? "-" : ""}${int}${frac ? "." + frac : ""}` };
}

// ---------------------------------------------------------------------------
// Aritmética exata (para somas exibidas, como "reserva − dívidas")
// ---------------------------------------------------------------------------

function commonScaled(values: string[]): { scaled: bigint[]; places: number } | null {
  const decs = values.map(readDecimal);
  if (decs.some((d) => d === null)) return null;
  const places = Math.max(0, ...decs.map((d) => (d as Dec).scale));
  return { scaled: decs.map((d) => toScaled(d as Dec, places)), places };
}

function scaledToDecimal(v: bigint, places: number): string {
  const p = scaledToPlain(v, places);
  return `${p.neg ? "-" : ""}${p.int}${places > 0 ? "." + p.frac : ""}`;
}

export function addDecimals(...values: string[]): string | null {
  const c = commonScaled(values);
  if (!c) return null;
  return scaledToDecimal(c.scaled.reduce((a, b) => a + b, 0n), c.places);
}

export function subtractDecimals(a: string, b: string): string | null {
  const c = commonScaled([a, b]);
  if (!c) return null;
  return scaledToDecimal((c.scaled[0] ?? 0n) - (c.scaled[1] ?? 0n), c.places);
}

/** -1, 0 ou 1. Strings inválidas → null. */
export function compareDecimals(a: string, b: string): -1 | 0 | 1 | null {
  const c = commonScaled([a, b]);
  if (!c) return null;
  const [x = 0n, y = 0n] = c.scaled;
  return x < y ? -1 : x > y ? 1 : 0;
}

/**
 * Razão a ÷ b como fração decimal, arredondada meio-para-cima (afastando de zero), sem float:
 * ratioDecimal("50", "200") → "0.2500". Divisor zero ou entrada inválida → null.
 */
export function ratioDecimal(a: string, b: string, places = 4): string | null {
  const c = commonScaled([a, b]);
  if (!c) return null;
  const [x = 0n, y = 0n] = c.scaled;
  if (y === 0n) return null;
  const ax = x < 0n ? -x : x;
  const ay = y < 0n ? -y : y;
  const scaledNum = ax * 10n ** BigInt(places);
  let q = scaledNum / ay;
  if ((scaledNum % ay) * 2n >= ay) q += 1n;
  return scaledToDecimal(x < 0n !== y < 0n ? -q : q, places);
}

export function isNegative(value: string | null | undefined): boolean {
  if (!value) return false;
  const d = readDecimal(value);
  return !!d && d.neg;
}

export function isZero(value: string | null | undefined): boolean {
  if (!value) return false;
  const d = readDecimal(value);
  return !!d && !/[1-9]/.test(d.digits);
}

/** ÚNICA ponte para float: só para geometria de gráficos e medidores. Nunca reenviar à API. */
export function toChartNumber(value: string | null | undefined): number {
  if (value === null || value === undefined) return Number.NaN;
  return Number(value);
}
