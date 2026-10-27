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
