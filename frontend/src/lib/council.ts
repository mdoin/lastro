// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Sala do Conselho: estado de cada participante, etapas e fio da discussão, derivados SÓ do que o backend registrou
 * (passos da execução, eventos ao vivo e mensagens publicadas). Nada aqui inventa atividade: um agente só aparece
 * "falando" se há texto chegando de um passo dele, "questionando" se a pauta pediu uma pergunta e o passo está
 * rodando, "consultando informações" se o passo chamou uma ferramenta.
 */
import type { RunStep, Stance, TeamMessage, TeamRun } from "../api/types";

export type SeatState =
  | "waiting" | "analyzing" | "consulting" | "speaking" | "responding" | "questioning" | "revising" | "available"
  | "done" | "unavailable";

export const SEAT_LABEL: Record<SeatState, string> = {
  waiting: "Aguardando",
  analyzing: "Analisando",
  consulting: "Consultando informações",
  speaking: "Falando",
  responding: "Respondendo",
  questioning: "Questionando",
  revising: "Revisando uma posição",
  available: "Parecer disponível",
  done: "Concluído",
  unavailable: "Indisponível",
};

export const MODE_LABEL: Record<string, string> = {
  rapida: "Consulta rápida", completo: "Conselho completo", debate: "Debate", rodada: "Nova rodada", revisao: "Revisão do veredito",
};

export interface LiveStep {
  agent_id: string;
  status?: string;
  kind?: string;
  text?: string;
  tool?: string;
  wait?: string;
}

export interface Seat {
  agent: string;
  state: SeatState;
  active: boolean;
  /** Atuação em curso ou registrada (o Bento enquadra, organiza a pauta e sintetiza; especialistas discutem). */
  act?: string;
  stance?: Stance | null;
  initialStance?: Stance | null;
  /** Parecer inicial (especialista) ou veredito (Bento e Cora). */
  message?: TeamMessage;
  framing?: TeamMessage;
  /** Tudo o que o participante disse nesta reunião, em ordem. */
  history: TeamMessage[];
  changed: boolean;
}

export type PhaseKey = "enquadramento" | "pareceres" | "discussao" | "sintese" | "auditoria";
export interface Phase {
  key: PhaseKey;
  label: string;
  state: "pending" | "active" | "done" | "failed";
}

const DEFAULT_SPECIALISTS = ["planejador", "analista", "economista", "riscos", "comportamental"];
const RESERVED = new Set(["enquadramento", "sintese", "auditoria", "posicoes", "pauta", "devolucao"]);
const ACTIVE_RUN: TeamRun["status"][] = ["queued", "running"];
const DEBATE = /^conselho:debate:([^:]+):([a-z]+)(:|$)/;

/** Quem foi convocado: o backend grava a escalação na execução; execuções antigas são deduzidas dos passos. */
export function lineup(run: TeamRun, steps: RunStep[]): string[] {
  if (run.route.lineup?.length) return run.route.lineup;
  const found = steps
    .map((s) => /^conselho:([a-z]+)$/.exec(s.step_key)?.[1])
    .filter((a): a is string => !!a && !RESERVED.has(a));
  const specialists = found.length ? [...new Set(found)] : DEFAULT_SPECIALISTS;
  return ["mentor", ...specialists, "auditor"];
}

export function belongs(key: string, agent: string): boolean {
  const starts = (k: string) => key === k || key.startsWith(`${k}:`) || key.startsWith(`${k}#`);
  if (agent === "mentor") return ["conselho:enquadramento", "conselho:sintese", "conselho:pauta"].some(starts);
  if (agent === "auditor") return ["conselho:auditoria", "conselho:devolucao"].some(starts);
  return starts(`conselho:${agent}`) || starts(`conselho:contestacao:${agent}`) || DEBATE.exec(key)?.[2] === agent;
}

interface PlannedTurn { quem?: string; speaker?: string; target?: string | null; kind?: string }

/** O que a pauta da rodada pediu para esta fala (tipo e alvo), para mostrar "questionando"/"respondendo". */
function plannedTurn(messages: TeamMessage[], key: string): PlannedTurn | undefined {
  const m = DEBATE.exec(key);
  if (!m) return undefined;
  const [, label, agent] = m;
  if (label!.startsWith("auditoria")) return { speaker: agent, target: null, kind: "evidencia" };
  const pauta = messages.find((x) => x.step_key === `conselho:pauta:${label}`);
  const turns = (pauta?.meta?.deliberation?.plan?.turns ?? []) as PlannedTurn[];
  return turns.find((t) => t.speaker === agent);
}

function actOf(key: string, messages: TeamMessage[]): string | undefined {
  if (key.startsWith("conselho:enquadramento")) return "Enquadramento";
  if (key.startsWith("conselho:pauta")) return "Organizando a pauta";
  if (key.startsWith("conselho:sintese")) return "Veredito";
  if (key.startsWith("conselho:auditoria") || key.startsWith("conselho:devolucao")) return "Auditoria";
  const turn = plannedTurn(messages, key);
  if (turn) return turn.kind ? KIND_LABEL[turn.kind] ?? "Discussão" : "Discussão";
  return undefined;
}

export interface RoomInput {
  run: TeamRun;
  steps: RunStep[];
  live: Record<string, LiveStep>;
  /** Mensagens desta execução (run_id igual) e intervenções da pessoa nela, na ordem em que foram publicadas. */
  messages: TeamMessage[];
}

const byKey = (messages: TeamMessage[], key: string) => messages.find((m) => m.step_key === key);

export function seats(input: RoomInput): Seat[] {
  const { run, steps, live, messages } = input;
  const runActive = ACTIVE_RUN.includes(run.status);
  const synthesis = byKey(messages, "conselho:sintese");
  const framing = byKey(messages, "conselho:enquadramento");
  const synthesisStep = steps.find((s) => s.step_key === "conselho:sintese");
  const positions = byKey(messages, "conselho:posicoes")?.meta?.positions ?? {};

  return lineup(run, steps).map((agent): Seat => {
    const running = Object.entries(live).filter(([k, s]) => belongs(k, agent) && (s.status === "running" || s.status === "retrying"));
    const own = steps.filter((s) => belongs(s.step_key, agent));
    const history = messages.filter((m) => m.step_key && belongs(m.step_key, agent) && m.agent_id === agent);
    const main = agent === "mentor" || agent === "auditor" ? synthesis : byKey(messages, `conselho:${agent}`);
    const turns = history.filter((m) => m.step_key?.startsWith("conselho:debate:"));
    const latest = [...turns].reverse().find((m) => m.meta?.deliberation?.stance);
    const initialStance = main?.meta?.opinion?.stance ?? positions[agent]?.initial ?? null;
    const stance = (latest?.meta?.deliberation?.stance as Stance | undefined) ?? positions[agent]?.final ?? initialStance;
    const base: Seat = {
      agent, state: "waiting", active: false, message: main, framing: agent === "mentor" ? framing : undefined,
      stance, initialStance, history, changed: !!initialStance && !!stance && initialStance !== stance,
    };

    if (running.length) {
      const [key, step] = running[running.length - 1]!;
      if (step.wait?.includes("limite")) return { ...base, state: "unavailable", act: "aguardando o limite do provedor" };
      const turn = plannedTurn(messages, key);
      const state: SeatState = key.endsWith(":correcao") ? "revising"
        : turn?.kind === "pergunta" ? "questioning"
        : turn && (turn.target || turn.kind === "resposta") ? "responding"
        : step.tool && !step.text ? "consulting"
        : step.text ? "speaking" : "analyzing";
      return { ...base, state, active: true, act: actOf(key, messages) };
    }
    if (main?.status === "error" || (own.some((s) => s.status === "failed") && !history.some((m) => m.status === "ok"))) {
      return { ...base, state: "unavailable", act: "não concluiu" };
    }
    if (runActive) {
      if (agent === "mentor") {
        if (synthesisStep?.status === "succeeded" && !synthesis) return { ...base, act: "Veredito com a Cora" };
        const pautas = messages.filter((m) => m.step_key?.startsWith("conselho:pauta:"));
        if (pautas.length) return { ...base, act: "Pauta organizada" };
        if (framing) return { ...base, act: "Enquadramento feito" };
        return base;
      }
      if (agent === "auditor") return base;
      return main ? { ...base, state: "available", act: turns.length ? `${turns.length} fala(s)` : undefined } : base;
    }
    if (agent === "auditor") return { ...base, state: synthesis?.audit ? "done" : "unavailable", act: "Auditoria" };
    if (history.some((m) => m.status === "ok") || (agent === "mentor" && synthesis?.status === "ok")) {
      return { ...base, state: "done", act: agent === "mentor" ? "Veredito" : turns.length ? `${turns.length} fala(s)` : undefined };
    }
    return { ...base, state: "unavailable" };
  });
}

export function phases(input: RoomInput): Phase[] {
  const { run, steps, live, messages } = input;
  const liveKeys = Object.keys(live);
  const stepKeys = steps.map((s) => s.step_key);
  const has = (key: string) => !!byKey(messages, key);
  const isLive = (pred: (k: string) => boolean) => liveKeys.some(pred);
  const specialists = lineup(run, steps).filter((a) => a !== "mentor" && a !== "auditor");
  const discussed = [...stepKeys, ...liveKeys].some((k) => k.startsWith("conselho:pauta") || DEBATE.test(k) || k.startsWith("conselho:contestacao"));
  const synthesis = byKey(messages, "conselho:sintese");
  const ended = !ACTIVE_RUN.includes(run.status);
  const mode = run.route.mode ?? "completo";

  const state = (done: boolean, active: boolean): Phase["state"] =>
    done ? "done" : active ? "active" : ended && run.status !== "succeeded" ? "failed" : "pending";

  const list: Phase[] = [];
  if (mode !== "rapida" && mode !== "revisao" && mode !== "rodada") {
    list.push({ key: "enquadramento", label: "Enquadramento", state: state(has("conselho:enquadramento"), isLive((k) => k.startsWith("conselho:enquadramento"))) });
  }
  if (mode !== "revisao" && mode !== "rodada") {
    list.push({
      key: "pareceres", label: mode === "rapida" ? "Consulta" : "Análises independentes",
      state: state(specialists.every((a) => has(`conselho:${a}`)) || has("conselho:posicoes"),
        specialists.some((a) => has(`conselho:${a}`) || isLive((k) => k === `conselho:${a}` || k.startsWith(`conselho:${a}:`)))),
    });
  }
  if (discussed || (mode !== "rapida" && mode !== "revisao" && !ended)) {
    list.push({ key: "discussao", label: "Discussão", state: state(has("conselho:posicoes"), isLive((k) => k.startsWith("conselho:pauta") || DEBATE.test(k))) });
  }
  const synthesisDone = stepKeys.includes("conselho:sintese") && steps.some((s) => s.step_key === "conselho:sintese" && s.status === "succeeded") || !!synthesis;
  list.push(
    { key: "sintese", label: "Veredito", state: state(synthesisDone, isLive((k) => k.startsWith("conselho:sintese"))) },
    { key: "auditoria", label: "Auditoria", state: state(!!synthesis?.audit, isLive((k) => k.startsWith("conselho:auditoria")) || (synthesisDone && !synthesis)) },
  );
  return list;
}

// ---------------------------------------------------------------- fio da discussão

export const KIND_LABEL: Record<string, string> = {
  pergunta: "Pergunta", contestacao: "Contestação", resposta: "Resposta", complemento: "Complemento", evidencia: "Evidência",
};
export const REACTION_LABEL: Record<string, string> = {
  concorda: "concorda", discorda: "discorda", pergunta: "pergunta", complementa: "complementa", reconhece: "reconhece",
  revisa: "revisa a posição",
};

export type FeedItem =
  | { type: "abertura"; message: TeamMessage }
  | { type: "iniciais"; messages: TeamMessage[] }
  | { type: "pauta"; message: TeamMessage }
  | { type: "fala"; message: TeamMessage; label: string; target: string | null; toPerson: boolean; reaction: string | null; revised: boolean }
  | { type: "devolucao"; message: TeamMessage }
  | { type: "pessoa"; message: TeamMessage };

/** Reunião como conversa organizada: abertura, posições iniciais (lado a lado), pauta, falas, devolução, intervenções.
 * Mapa de posições, auditoria e veredito ficam fora (aparecem na sala e no veredito). */
export function feed(messages: TeamMessage[]): FeedItem[] {
  const out: FeedItem[] = [];
  let initials: TeamMessage[] | null = null;
  for (const m of messages) {
    const key = m.step_key ?? "";
    if (m.role === "user") { out.push({ type: "pessoa", message: m }); continue; }
    if (key === "conselho:enquadramento") { out.push({ type: "abertura", message: m }); continue; }
    if (/^conselho:[a-z]+$/.test(key) && !RESERVED.has(key.slice(9))) {
      if (!initials) { initials = []; out.push({ type: "iniciais", messages: initials }); }
      initials.push(m);
      continue;
    }
    if (key.startsWith("conselho:pauta:")) { out.push({ type: "pauta", message: m }); continue; }
    if (key.startsWith("conselho:devolucao")) { out.push({ type: "devolucao", message: m }); continue; }
    if (DEBATE.test(key) || key.startsWith("conselho:contestacao:")) {
      const d = m.meta?.deliberation ?? {};
      const responds = d.responds_to ?? null;
      out.push({
        type: "fala", message: m,
        label: d.revised ? "Revisão" : KIND_LABEL[d.kind ?? ""] ?? "Fala",
        target: responds?.agent ?? null, toPerson: !!responds?.person,
        reaction: d.reaction ?? null, revised: !!d.revised,
      });
    }
  }
  return out;
}

/** Agrupa a conversa: cada reunião do Conselho vira um bloco (pergunta, sala, discussão, veredito); o resto segue. */
export type ThreadBlock =
  | { kind: "message"; message: TeamMessage }
  | { kind: "council"; run: TeamRun; question?: TeamMessage; messages: TeamMessage[] };

export function threadBlocks(messages: TeamMessage[], runs: TeamRun[]): ThreadBlock[] {
  // Análises do Radar também são "council", mas têm outro roteiro (radar:*) e seguem como mensagens.
  const councils = new Map(runs.filter((r) => r.kind === "council" && !r.route.radar).map((r) => [r.id, r]));
  const byQuestion = new Map([...councils.values()].map((r) => [r.message_id, r]));
  const ownerOf = (m: TeamMessage) => {
    const intervention = m.meta?.intervention_for;
    return byQuestion.get(m.id) ?? (m.run_id ? councils.get(m.run_id) : undefined) ?? (intervention ? councils.get(intervention) : undefined);
  };
  const blocks: ThreadBlock[] = [];
  const seen = new Set<string>();
  for (const m of messages) {
    const run = ownerOf(m);
    if (!run) { blocks.push({ kind: "message", message: m }); continue; }
    if (seen.has(run.id)) continue;
    seen.add(run.id);
    blocks.push({
      kind: "council", run,
      question: messages.find((x) => x.id === run.message_id),
      messages: messages.filter((x) => x.id !== run.message_id && ownerOf(x)?.id === run.id),
    });
  }
  return blocks;
}
