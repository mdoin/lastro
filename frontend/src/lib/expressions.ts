// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Expressões dos mascotes na Sala do Conselho.
 *
 * São representações narrativas da postura de cada participante, não emoções dos modelos. Cada expressão sai de um
 * fato registrado na reunião (passo em andamento, reação e posição declaradas pelo próprio agente, veredito da
 * auditoria) e vem acompanhada do motivo, em texto. Nada é sorteado e nenhuma palavra solta do texto decide a cara
 * de ninguém. "debochado" existe no desenho, mas nenhum evento do Lastro o justifica hoje, então nunca é atribuído.
 */
import type { TeamMessage } from "../api/types";
import type { Seat } from "./council";
import { EYE_CHARS, MASCOTS } from "../components/mascots";

export type Expression =
  | "neutro" | "pensativo" | "preocupado" | "desconfiado" | "irritado" | "debochado" | "surpreso" | "entusiasmado"
  | "confiante" | "concordando" | "discordando" | "satisfeito";

export const EXPRESSION_LABEL: Record<Expression, string> = {
  neutro: "neutro", pensativo: "pensativo", preocupado: "preocupado", desconfiado: "desconfiado", irritado: "irritado",
  debochado: "debochado", surpreso: "surpreso", entusiasmado: "entusiasmado", confiante: "confiante",
  concordando: "concordando", discordando: "discordando", satisfeito: "satisfeito",
};

export interface Posture {
  expression: Expression;
  /** Por que essa postura, em uma frase curta (também é o texto acessível). */
  reason: string;
}

type Names = (id: string) => string;

const turnsOf = (messages: TeamMessage[], agent: string) =>
  messages.filter((m) => m.agent_id === agent && m.status === "ok" && m.step_key?.startsWith("conselho:debate:"));

/** Postura de um participante a partir do lugar dele (estado real) e das mensagens publicadas até agora. */
export function posture(seat: Seat, messages: TeamMessage[], name: Names): Posture {
  const at = (id?: string | null) => (id ? `@${name(id)}` : "a pessoa");
  if (seat.active) {
    if (seat.state === "consulting") return { expression: "pensativo", reason: "consultando dados" };
    if (seat.state === "revising") return { expression: "pensativo", reason: "revendo o próprio parecer" };
    if (seat.state === "questioning") return { expression: "desconfiado", reason: "preparando uma pergunta" };
    if (seat.state === "responding") return { expression: "confiante", reason: "respondendo na discussão" };
    if (seat.state === "speaking") return { expression: "confiante", reason: "apresentando o argumento" };
    return { expression: "pensativo", reason: "analisando" };
  }
  if (seat.state === "unavailable") return { expression: "neutro", reason: "não concluiu a participação" };

  if (seat.agent === "auditor") {
    const back = messages.some((m) => m.step_key?.startsWith("conselho:devolucao"));
    const verdict = seat.message?.audit?.verdict;
    if (verdict === "REPROVA") return { expression: "preocupado", reason: "reprovou a primeira versão do veredito" };
    if (back && !seat.message) return { expression: "preocupado", reason: "devolveu questões ao Conselho" };
    if (verdict === "PASSA COM RESSALVAS") return { expression: "desconfiado", reason: "aprovou com ressalvas" };
    if (verdict === "PASSA") return { expression: "satisfeito", reason: "auditoria sem achados relevantes" };
    return { expression: "neutro", reason: "aguardando o veredito para auditar" };
  }
  if (seat.agent === "mentor") {
    if (seat.message?.status === "ok") return { expression: "confiante", reason: "apresentou o veredito" };
    const pauta = [...messages].reverse().find((m) => m.step_key?.startsWith("conselho:pauta:"));
    const divergences = pauta?.meta?.deliberation?.plan?.divergences?.length ?? 0;
    if (divergences) return { expression: "pensativo", reason: "organizando as divergências" };
    if (pauta) return { expression: "neutro", reason: "conduzindo a pauta" };
    return { expression: "neutro", reason: seat.framing ? "abriu a reunião" : "aguardando" };
  }

  const mine = turnsOf(messages, seat.agent);
  const last = mine[mine.length - 1];
  if (last) {
    const d = last.meta?.deliberation ?? {};
    const target = d.responds_to?.agent ?? null;
    if (d.revised) return { expression: "surpreso", reason: `revisou a posição depois de ouvir ${at(target)}` };
    if (d.reaction === "discorda") {
      const before = mine.slice(0, -1).some((m) => m.meta?.deliberation?.reaction === "discorda"
        && m.meta?.deliberation?.responds_to?.agent === target && !!target);
      return before ? { expression: "irritado", reason: `voltou a discordar de ${at(target)}` }
        : { expression: "discordando", reason: `discordou de ${at(target)}` };
    }
    if (d.reaction === "concorda") return { expression: "concordando", reason: `concordou com ${at(target)}` };
    if (d.reaction === "reconhece") return { expression: "satisfeito", reason: `reconheceu o ponto de ${at(target)}` };
    if (d.reaction === "pergunta" || d.kind === "pergunta") return { expression: "desconfiado", reason: `questionou ${at(target)}` };
    if (d.reaction === "complementa") return { expression: "confiante", reason: `complementou ${at(target)}` };
  }
  // contestado por alguém e ainda sem resposta: pensativo
  const contested = [...messages].reverse().find((m) => m.agent_id !== seat.agent && m.step_key?.startsWith("conselho:debate:")
    && m.meta?.deliberation?.responds_to?.agent === seat.agent && m.meta?.deliberation?.reaction === "discorda");
  if (contested && (!last || last.created_at < contested.created_at)) {
    return { expression: "pensativo", reason: `${at(contested.agent_id)} contestou o argumento` };
  }
  switch (seat.stance) {
    case "favoravel": return { expression: "entusiasmado", reason: "parecer favorável à proposta" };
    case "contraria": return { expression: "preocupado", reason: "parecer contrário: vê riscos" };
    case "condicional": return { expression: "pensativo", reason: "favorável só sob condições" };
    case "insuficiente": return { expression: "desconfiado", reason: "sem base suficiente para opinar" };
    default: return { expression: "neutro", reason: seat.state === "waiting" ? "aguardando a vez" : "presente" };
  }
}

// ---------------------------------------------------------------- desenho (sobreposição no pixel art)

export interface Px { x: number; y: number; c: "k" | "b" }

interface Face { eyes: { x0: number; x1: number }[]; eyeTop: number; mouth: { x: number; y: number }[]; mx: number; my: number }

const FACES: Record<string, Face | null> = {};

/** Olhos e boca de um mascote, achados no próprio desenho (vale para qualquer mascote novo). */
export function face(id: string): Face | null {
  if (id in FACES) return FACES[id]!;
  const m = MASCOTS[id];
  if (!m) return (FACES[id] = null);
  const eyeCells: { x: number; y: number }[] = [];
  m.rows.forEach((row, y) => [...row].forEach((ch, x) => { if (EYE_CHARS.has(ch)) eyeCells.push({ x, y }); }));
  if (!eyeCells.length) return (FACES[id] = null);
  const eyeTop = Math.min(...eyeCells.map((c) => c.y));
  const eyeBottom = Math.max(...eyeCells.map((c) => c.y));
  const mid = 7.5;
  const left = eyeCells.filter((c) => c.x < mid), right = eyeCells.filter((c) => c.x >= mid);
  const span = (cells: typeof eyeCells) => ({ x0: Math.min(...cells.map((c) => c.x)), x1: Math.max(...cells.map((c) => c.x)) });
  const mouth: { x: number; y: number }[] = [];
  m.rows.forEach((row, y) => [...row].forEach((ch, x) => { if (ch === "k" && y > eyeBottom) mouth.push({ x, y }); }));
  const mouthRow = mouth.length ? Math.min(...mouth.map((c) => c.y)) : eyeBottom + 2;
  const atRow = mouth.filter((c) => c.y === mouthRow);
  const mx = atRow.length ? Math.round(atRow.reduce((s, c) => s + c.x, 0) / atRow.length) : 7;
  return (FACES[id] = { eyes: [left, right].filter((e) => e.length).map(span), eyeTop, mouth: atRow, mx, my: mouthRow });
}

// bocas: modelos de 4 colunas (linha 0 é a linha da boca; -1 fica acima)
const MOUTHS: Partial<Record<Expression, { dy: number; row: string }[]>> = {
  satisfeito: [{ dy: -1, row: "k..k" }, { dy: 0, row: ".kk." }],
  concordando: [{ dy: -1, row: "k..k" }, { dy: 0, row: ".kk." }],
  entusiasmado: [{ dy: -1, row: "k..k" }, { dy: 0, row: ".kk." }, { dy: 1, row: ".kk." }],
  confiante: [{ dy: 0, row: "kkk." }, { dy: -1, row: "...k" }],
  preocupado: [{ dy: 0, row: ".kk." }, { dy: 1, row: "k..k" }],
  discordando: [{ dy: 0, row: ".kk." }, { dy: 1, row: "k..k" }],
  irritado: [{ dy: 0, row: "kkkk" }],
  desconfiado: [{ dy: 0, row: ".kkk" }],
  pensativo: [{ dy: 0, row: "..kk" }],
  surpreso: [{ dy: 0, row: ".kk." }, { dy: 1, row: ".kk." }],
  debochado: [{ dy: 0, row: "kkk." }, { dy: -1, row: "...k" }, { dy: -1, row: "k..." }],
};

/** Pixels a sobrepor: cobre a boca original (cor da base) e desenha sobrancelhas e a boca da expressão. */
export function overlay(id: string, expression: Expression): Px[] {
  const f = face(id);
  if (!f || expression === "neutro") return [];
  const out: Px[] = [];
  const mouth = MOUTHS[expression];
  if (mouth) {
    f.mouth.forEach((c) => out.push({ x: c.x, y: c.y, c: "b" }));
    const x0 = f.mx - 2;
    for (const { dy, row } of mouth) [...row].forEach((ch, i) => { if (ch === "k") out.push({ x: x0 + i, y: f.my + dy, c: "k" }); });
  }
  const up = f.eyeTop - 2, low = f.eyeTop - 1;
  const brow = (inner: number, outer: number) => f.eyes.forEach((e, i) => {
    const innerX = i === 0 ? e.x1 : e.x0, outerX = i === 0 ? e.x0 : e.x1;
    out.push({ x: innerX, y: inner, c: "k" }, { x: outerX, y: outer, c: "k" });
  });
  if (["irritado", "discordando"].includes(expression)) brow(low, up);          // franzido: ponta interna desce
  else if (expression === "preocupado") brow(up, low);                           // aflito: ponta interna sobe
  else if (expression === "surpreso") brow(up, up);
  else if (["desconfiado", "pensativo", "debochado"].includes(expression)) {      // uma sobrancelha erguida
    f.eyes.forEach((e, i) => { const y = i === 1 ? up : low; out.push({ x: e.x0, y, c: "k" }, { x: e.x1, y, c: "k" }); });
  }
  const rows = MASCOTS[id]!.rows;
  // só sobre o corpo do mascote: sobrancelha nunca fica "flutuando" fora da cabeça
  return out.filter((p) => p.x >= 0 && p.x < 16 && p.y >= 0 && p.y < 16 && rows[p.y]![p.x] !== ".");
}

/** Cor do traço da expressão: escuro no corpo claro, claro no corpo escuro (o Bento é grafite). */
export function strokeColor(id: string): string {
  const m = MASCOTS[id];
  if (!m) return "#15151a";
  const hex = m.palette.b!.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return (0.299 * r! + 0.587 * g! + 0.114 * b!) / 255 < 0.38 ? "#ece7da" : m.palette.k!;
}
