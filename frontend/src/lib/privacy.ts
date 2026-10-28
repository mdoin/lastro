// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Máscara do modo apresentação: esconde valores em reais na TELA (prints e demonstrações). Não altera nada que
 * está guardado; desligar o modo mostra os valores de novo.
 */

export const MASK = "R$ •••";

// "R$ 1.234,56", "R$1234", "R$ 50 mil", "R$ 2,5 milhões", "-R$ 38,00"
const MONEY = /-?R\$\s?-?\d[\d.]*(?:,\d+)?(?:\s?(?:mil|milh(?:ão|ões|ao|oes)|bi(?:lhão|lhões)?))?\b/gi;
// "1.234,56 reais", "38 reais"
const REAIS = /\b\d[\d.]*(?:,\d+)?\s?(?:mil\s)?reais\b/gi;

export function maskMoney(text: string): string {
  return text.replace(MONEY, MASK).replace(REAIS, MASK);
}

export function maybeMask(text: string, on: boolean): string {
  return on ? maskMoney(text) : text;
}
