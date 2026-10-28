// SPDX-License-Identifier: AGPL-3.0-or-later
/** @menções no campo de mensagem: o que está sendo digitado e como completar. */

export interface MentionQuery {
  start: number; // posição do "@"
  query: string; // texto depois do "@" até o cursor
}

/** Menção em edição na posição do cursor, ou null. Só conta "@" no início ou depois de espaço/pontuação. */
export function mentionAt(text: string, caret: number): MentionQuery | null {
  const before = text.slice(0, caret);
  const match = /(^|[\s(,;])@([\p{L}\d-]{0,40})$/u.exec(before);
  const query = match?.[2];
  if (query === undefined) return null;
  return { start: caret - query.length - 1, query };
}

const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Candidatos cujo handle ou nome começa com o que foi digitado (sem acento, sem caixa). */
export function filterCandidates<T extends { handle: string; name: string }>(items: T[], query: string): T[] {
  const q = fold(query);
  return items.filter((a) => fold(a.handle).startsWith(q) || fold(a.name).startsWith(q));
}

/** Troca a menção em edição pelo handle escolhido; devolve o texto e a nova posição do cursor. */
export function applyMention(text: string, at: MentionQuery, handle: string): { text: string; caret: number } {
  const end = at.start + 1 + at.query.length;
  const insert = `@${handle} `;
  return { text: text.slice(0, at.start) + insert + text.slice(end).replace(/^\s/, ""), caret: at.start + insert.length };
}

type Named = { id: string; handle: string; name: string };
const MENTION = /(^|[^\p{L}\d@])@([\p{L}\d][\p{L}\d-]{0,40})/gu;

/** Agente citado por "@handle", "@id" ou "@Nome" (sem acento, sem caixa); undefined se não for da equipe. */
export function resolveMention<T extends Named>(items: T[], word: string): T | undefined {
  const w = fold(word);
  return items.find((a) => fold(a.handle) === w || a.id === w || fold(a.name) === w);
}

/** Texto em pedaços: texto puro e menções a agentes reais (as outras "@palavras" seguem como texto). */
export function splitMentions<T extends Named>(text: string, items: T[]): (string | T)[] {
  const out: (string | T)[] = [];
  let last = 0;
  for (const m of text.matchAll(MENTION)) {
    const agent = resolveMention(items, m[2]!);
    if (!agent) continue;
    const at = m.index! + m[1]!.length;
    out.push(text.slice(last, at), agent);
    last = at + 1 + m[2]!.length;
  }
  out.push(text.slice(last));
  return out.filter((p) => p !== "");
}

/** Markdown com as menções viradas em links internos "#agente-<id>" (a tela os mostra como menção clicável). */
export function linkMentions<T extends Named>(text: string, items: T[]): string {
  return splitMentions(text, items).map((p) => (typeof p === "string" ? p : `[@${p.name}](#agente-${p.id})`)).join("");
}
