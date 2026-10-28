// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Sala do Conselho: estado de cada participante e de cada etapa, derivado SÓ do que o backend registrou
 * (passos da execução, eventos ao vivo e mensagens publicadas). Nada aqui inventa atividade: um agente só aparece
 * "analisando" se há um passo dele em andamento, e "consultando informações" se esse passo chamou uma ferramenta.
 */
import type { RunStep, Stance, TeamMessage, TeamRun } from "../api/types";

export type SeatState = "queued" | "consulting" | "analyzing" | "available" | "review" | "done" | "failed" | "skipped";

export const SEAT_LABEL: Record<SeatState, string> = {
  queued: "Na fila",
  consulting: "Consultando informações",
  analyzing: "Analisando",
  available: "Parecer disponível",
  review: "Aguardando revisão",
  done: "Concluído",
  failed: "Falhou",
  skipped: "Não executado",
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
  /** Atuação em curso ou registrada (o Bento enquadra e sintetiza; especialistas podem contestar). */
  act?: string;
  stance?: Stance | null;
  /** Parecer (especialista), síntese (Bento) ou a síntese auditada (Cora). */
  message?: TeamMessage;
  contest?: TeamMessage;
  framing?: TeamMessage;
}

export type PhaseKey = "enquadramento" | "pareceres" | "contestacao" | "sintese" | "auditoria";
export interface Phase {
  key: PhaseKey;
  label: string;
  state: "pending" | "active" | "done" | "failed";
}

const DEFAULT_SPECIALISTS = ["planejador", "analista", "economista", "riscos", "comportamental"];
const MENTOR_KEYS = ["conselho:enquadramento", "conselho:sintese"];
const RESERVED = new Set(["enquadramento", "sintese", "auditoria", "posicoes"]);
const ACTIVE_RUN: TeamRun["status"][] = ["queued", "running"];

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
  if (agent === "mentor") return MENTOR_KEYS.some((k) => key === k || key.startsWith(`${k}:`));
  if (agent === "auditor") return key.startsWith("conselho:auditoria");
  return [`conselho:${agent}`, `conselho:contestacao:${agent}`].some((k) => key === k || key.startsWith(`${k}:`));
}

function actOf(key: string): string | undefined {
  if (key.startsWith("conselho:enquadramento")) return "Enquadramento";
  if (key.startsWith("conselho:sintese")) return "Síntese";
  if (key.startsWith("conselho:contestacao")) return "Contestação";
  if (key.startsWith("conselho:auditoria")) return "Auditoria";
  return undefined;
}

export interface RoomInput {
  run: TeamRun;
  steps: RunStep[];
  live: Record<string, LiveStep>;
  /** Mensagens desta execução (run_id igual), na ordem em que foram publicadas. */
  messages: TeamMessage[];
}

const byKey = (messages: TeamMessage[], key: string) => messages.find((m) => m.step_key === key);

export function seats(input: RoomInput): Seat[] {
  const { run, steps, live, messages } = input;
  const runActive = ACTIVE_RUN.includes(run.status);
  const synthesis = byKey(messages, "conselho:sintese");
  const framing = byKey(messages, "conselho:enquadramento");
  const synthesisStep = steps.find((s) => s.step_key === "conselho:sintese");

  return lineup(run, steps).map((agent): Seat => {
    const running = Object.entries(live).filter(([k, s]) => belongs(k, agent) && (s.status === "running" || s.status === "retrying"));
    const own = steps.filter((s) => belongs(s.step_key, agent));
    const main = agent === "mentor" ? synthesis : agent === "auditor" ? synthesis : byKey(messages, `conselho:${agent}`);
    const contest = agent === "mentor" || agent === "auditor" ? undefined : byKey(messages, `conselho:contestacao:${agent}`);
    const base: Seat = {
      agent, state: "queued", active: false, message: main, contest,
      framing: agent === "mentor" ? framing : undefined,
      stance: contest?.meta?.opinion?.stance ?? main?.meta?.opinion?.stance ?? null,
    };

    if (running.length) {
      const [key, step] = running[running.length - 1]!;
      const state: SeatState = key.endsWith(":correcao") ? "review" : step.tool ? "consulting" : "analyzing";
      return { ...base, state, active: true, act: actOf(key) };
    }
    if (main?.status === "error" || (own.some((s) => s.status === "failed") && !main)) {
      return { ...base, state: "failed", act: agent === "mentor" ? "Síntese" : undefined };
    }
    if (runActive) {
      if (agent === "mentor") {
        if (synthesisStep?.status === "succeeded" && !synthesis) return { ...base, state: "review", act: "Síntese" };
        // enquadramento feito: o Bento espera os pareceres para sintetizar (não é um parecer dele)
        if (framing) return { ...base, state: "queued", act: "Enquadramento feito" };
        return base;
      }
      if (agent === "auditor") return base;
      return main ? { ...base, state: "available", act: contest ? "Contestação" : undefined } : base;
    }
    // execução encerrada
    if (agent === "auditor") return { ...base, state: synthesis?.audit ? "done" : "skipped", act: "Auditoria" };
    if (main && main.status === "ok") return { ...base, state: "done", act: agent === "mentor" ? "Síntese" : contest ? "Contestação" : undefined };
    return { ...base, state: run.status === "failed" ? "failed" : "skipped" };
  });
}

export function phases(input: RoomInput): Phase[] {
  const { run, steps, live, messages } = input;
  const liveKeys = Object.keys(live);
  const stepKeys = steps.map((s) => s.step_key);
  const has = (key: string) => !!byKey(messages, key);
  const isLive = (pred: (k: string) => boolean) => liveKeys.some(pred);
  const specialists = lineup(run, steps).filter((a) => a !== "mentor" && a !== "auditor");
  const contestKeys = [...stepKeys, ...liveKeys].filter((k) => k.startsWith("conselho:contestacao:"));
  const synthesis = byKey(messages, "conselho:sintese");
  const ended = !ACTIVE_RUN.includes(run.status);

  const state = (done: boolean, active: boolean): Phase["state"] =>
    done ? "done" : active ? "active" : ended && run.status !== "succeeded" ? "failed" : "pending";

  const list: Phase[] = [
    { key: "enquadramento", label: "Enquadramento", state: state(has("conselho:enquadramento"), isLive((k) => k.startsWith("conselho:enquadramento"))) },
    {
      key: "pareceres", label: "Pareceres",
      state: state(specialists.every((a) => has(`conselho:${a}`)) || has("conselho:posicoes"),
        specialists.some((a) => has(`conselho:${a}`) || isLive((k) => k === `conselho:${a}` || k.startsWith(`conselho:${a}:`)))),
    },
  ];
  if (contestKeys.length) {
    list.push({ key: "contestacao", label: "Contestação", state: state(has("conselho:posicoes"), isLive((k) => k.startsWith("conselho:contestacao:"))) });
  }
  const synthesisDone = steps.some((s) => s.step_key === "conselho:sintese" && s.status === "succeeded") || !!synthesis;
  list.push(
    { key: "sintese", label: "Síntese", state: state(synthesisDone, isLive((k) => k.startsWith("conselho:sintese"))) },
    { key: "auditoria", label: "Auditoria", state: state(!!synthesis?.audit, synthesisDone && !synthesis) },
  );
  return list;
}

/** Agrupa a conversa: cada reunião do Conselho vira um bloco (pergunta, sala, veredito); o resto segue como antes. */
export type ThreadBlock =
  | { kind: "message"; message: TeamMessage }
  | { kind: "council"; run: TeamRun; question?: TeamMessage; messages: TeamMessage[] };

export function threadBlocks(messages: TeamMessage[], runs: TeamRun[]): ThreadBlock[] {
  // Análises do Radar também são "council", mas têm outro roteiro (radar:*) e seguem como mensagens.
  const councils = new Map(runs.filter((r) => r.kind === "council" && !r.route.radar).map((r) => [r.id, r]));
  const byQuestion = new Map([...councils.values()].map((r) => [r.message_id, r]));
  const blocks: ThreadBlock[] = [];
  const seen = new Set<string>();
  for (const m of messages) {
    const run = byQuestion.get(m.id) ?? (m.run_id ? councils.get(m.run_id) : undefined);
    if (!run) { blocks.push({ kind: "message", message: m }); continue; }
    if (seen.has(run.id)) continue;
    seen.add(run.id);
    blocks.push({
      kind: "council", run,
      question: messages.find((x) => x.id === run.message_id),
      messages: messages.filter((x) => x.run_id === run.id),
    });
  }
  return blocks;
}
