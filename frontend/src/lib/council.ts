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

/** Passo de pesquisa na internet (sessão isolada do agente): o texto dele é material interno, não fala. */
export const isResearch = (key: string) => key.includes(">pesquisa#");

const RESEARCH_TOOL: Record<string, string> = {
  web_search: "pesquisando na internet", web_open: "lendo uma fonte", ler_pagina_oficial: "lendo uma fonte oficial",
  web_find: "conferindo um dado na fonte", web_extract: "extraindo dados da fonte",
  navegador_abrir: "navegando", navegador_clicar: "navegando", navegador_digitar: "pesquisando num site",
  navegador_rolar: "lendo a página", navegador_voltar: "navegando", navegador_ler: "lendo a página",
};

/** O que mostrar enquanto um agente pesquisa, a partir da ferramenta que de fato está rodando. */
export function researchLabel(key: string, step: LiveStep): string | null {
  if (!isResearch(key) && step.kind !== "research") return null;
  return (step.tool && RESEARCH_TOOL[step.tool]) || "consultando fontes";
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
const DEBATE = /^conselho:debate:([^:]+):([a-z]+)(:|>|$)/;

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
  const starts = (k: string) => key === k || key.startsWith(`${k}:`) || key.startsWith(`${k}#`) || key.startsWith(`${k}>`);
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
  if (isResearch(key)) return "Pesquisando fontes";
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
        : isResearch(key) || (step.tool && !step.text) ? "consulting"
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

// ---------------------------------------------------------------- palco, narrativa e replay

/** As duas primeiras linhas de uma fala ("**Posição:**", "**Reação:**") viram selos; o resto é o texto. */
export const speech = (text: string) => text.replace(/^\s*\**\s*(posi[cç][aã]o|rea[cç][aã]o)\s*:?\**\s*:?[^\n]*\n/gim, "").trim();

/** Primeira frase de um texto (sem marcação), para citações curtas. */
export function firstSentence(text: string, max = 220): string {
  const plain = speech(text).replace(/[*_#>`]/g, "").replace(/\s+/g, " ").trim();
  const cut = /^(.+?[.!?])(\s|$)/.exec(plain)?.[1] ?? plain;
  return cut.length > max ? `${cut.slice(0, max).replace(/\s+\S*$/, "")}…` : cut;
}

const isInitial = (key: string) => /^conselho:[a-z]+$/.test(key) && !RESERVED.has(key.slice(9));
const isTurn = (key: string) => DEBATE.test(key) || key.startsWith("conselho:contestacao:");

/** Tipo da contribuição, só pelo que foi registrado (passo e metadados), nunca por palavras do texto. */
export function contributionType(m: TeamMessage): { label: string; key: string; fromReaction: boolean } {
  const key = m.step_key ?? "";
  const t = (label: string, k: string, fromReaction = false) => ({ label, key: k, fromReaction });
  if (m.role === "user") return t("Você", "pessoa");
  if (key === "conselho:enquadramento") return t("Abertura", "abertura");
  if (key.startsWith("conselho:pauta")) return t("Pauta", "pauta");
  if (key.startsWith("conselho:sintese")) return t("Conclusão", "conclusao");
  if (key.startsWith("conselho:auditoria") || key.startsWith("conselho:devolucao")) return t("Auditoria", "auditoria");
  if (isInitial(key)) return t("Análise inicial", "inicial");
  const d = m.meta?.deliberation ?? {};
  if (d.revised) return t("Revisão de posição", "revisao");
  if (d.kind === "contestacao" || key.startsWith("conselho:contestacao:")) return t("Contestação", "contestacao");
  if (d.kind === "pergunta") return t("Pergunta", "pergunta");
  if (d.reaction === "concorda") return t("Concordância", "concordancia", true);
  if (d.reaction === "discorda") return t("Discordância", "discordancia", true);
  if (d.reaction === "pergunta") return t("Pergunta", "pergunta", true);
  return t(KIND_LABEL[d.kind ?? ""] ?? "Fala", d.kind ?? "fala");
}

export type StepState = "done" | "active" | "pending" | "skipped";
export interface NarrativeStep { key: string; text: string; state: StepState }

/** Etapas narradas, na ordem real. Etapas condicionais (divergências, discussão, revisão, redação) só entram quando
 * aconteceram; nenhuma aparece concluída antes do registro correspondente. */
export function narrative(input: RoomInput, mentor = "Bento"): NarrativeStep[] {
  const { run, steps, live, messages } = input;
  const liveKeys = Object.keys(live);
  const ended = !ACTIVE_RUN.includes(run.status);
  const mode = run.route.mode ?? "completo";
  const has = (p: (k: string) => boolean) => messages.some((m) => p(m.step_key ?? ""));
  const isLive = (p: (k: string) => boolean) => liveKeys.some(p);
  const st = (done: boolean, active: boolean): StepState => (done ? "done" : active ? "active" : ended ? "skipped" : "pending");
  const synthesis = byKey(messages, "conselho:sintese");
  const synthStarted = isLive((k) => k.startsWith("conselho:sintese")) || steps.some((s) => s.step_key === "conselho:sintese");
  const auditing = isLive((k) => k.startsWith("conselho:auditoria") || k.startsWith("conselho:devolucao"))
    || (steps.some((s) => s.step_key === "conselho:sintese" && s.status === "succeeded") && !synthesis);
  const audited = !!synthesis?.audit || has((k) => k === "conselho:auditoria");
  const out: NarrativeStep[] = [{ key: "convocado", text: run.route.origin ? "Reunião extraordinária convocada" : "O Conselho foi convocado", state: "done" }];

  if (mode !== "revisao" && mode !== "rodada") {
    const specialists = lineup(run, steps).filter((a) => a !== "mentor" && a !== "auditor");
    const published = specialists.filter((a) => has((k) => k === `conselho:${a}`)).length;
    const later = has((k) => k.startsWith("conselho:pauta") || isTurn(k) || k === "conselho:posicoes" || k === "conselho:sintese") || synthStarted;
    const done = (specialists.length > 0 && published === specialists.length) || later;
    const active = published > 0 || isLive((k) => specialists.some((a) => k === `conselho:${a}` || k.startsWith(`conselho:${a}:`)));
    out.push({ key: "analise", text: done ? "Os especialistas analisaram" : "Os especialistas estão analisando", state: st(done, active) });
  }
  const diverged = messages.some((m) => (m.meta?.deliberation?.plan?.divergences?.length ?? 0) > 0
    || (isTurn(m.step_key ?? "") && (m.meta?.deliberation?.reaction === "discorda" || m.meta?.deliberation?.kind === "contestacao")));
  if (diverged) out.push({ key: "divergencias", text: "Surgiram divergências", state: "done" });
  const debating = isLive(isTurn) || isLive((k) => k.startsWith("conselho:pauta"));
  if (debating || has(isTurn)) {
    out.push({ key: "discussao", text: debating ? "Os participantes estão discutindo" : "Os participantes discutiram", state: debating ? "active" : "done" });
  }
  if (messages.some((m) => m.meta?.deliberation?.revised)) out.push({ key: "revisao", text: "As hipóteses foram revisadas", state: "done" });
  if (synthStarted || synthesis) {
    const drafting = isLive((k) => k.startsWith("conselho:sintese"));
    out.push({ key: "redacao", text: drafting ? `O ${mentor} está redigindo o veredito` : `O ${mentor} redigiu o veredito`, state: drafting ? "active" : "done" });
  }
  out.push({ key: "auditoria", text: audited ? "A auditoria avaliou o veredito" : "A auditoria está avaliando", state: st(audited, auditing) });
  out.push({ key: "conclusao", text: `O ${mentor} apresentou uma conclusão`, state: st(synthesis?.status === "ok", false) });
  return out;
}

export interface Spotlight { speaker: string; target: string | null; toPerson: boolean; label: string; text: string; live: boolean; message?: TeamMessage }

const excerptOf = (m: TeamMessage) => (isInitial(m.step_key ?? "") ? m.meta?.opinion?.excerpts?.tese ?? firstSentence(m.content) : firstSentence(m.content));

/** Quem está no centro agora: a fala em curso (com o alvo que a pauta pediu) ou a última contribuição publicada. */
export function spotlight(input: RoomInput): Spotlight | null {
  const talking = Object.entries(input.live).filter(([k, s]) => isTurn(k) && (s.status === "running" || s.status === "retrying"));
  if (talking.length) {
    const [key, s] = talking[talking.length - 1]!;
    const turn = plannedTurn(input.messages, key);
    return { speaker: s.agent_id, target: turn?.target ?? null, toPerson: false, label: KIND_LABEL[turn?.kind ?? ""] ?? "Fala",
      text: s.text ? firstSentence(s.text) : "", live: true };
  }
  const m = [...input.messages].reverse().find((x) => x.role === "assistant" && x.status === "ok" && !!x.agent_id
    && (isTurn(x.step_key ?? "") || isInitial(x.step_key ?? "") || x.step_key === "conselho:sintese" || !!x.step_key?.startsWith("conselho:devolucao")));
  if (!m) return null;
  const responds = m.meta?.deliberation?.responds_to;
  return { speaker: m.agent_id!, target: responds?.agent ?? null, toPerson: !!responds?.person, label: contributionType(m).label,
    text: excerptOf(m), live: false, message: m };
}

/** A mensagem a que uma fala responde (o argumento contestado) e o trecho dela que cabe numa citação. */
export function quoted(m: TeamMessage, messages: TeamMessage[]): { message: TeamMessage; excerpt: string; contested: boolean } | null {
  const d = m.meta?.deliberation;
  const id = d?.responds_to?.message_id ?? m.reply_to_id;
  const before = messages.slice(0, Math.max(0, messages.indexOf(m)));
  const who = d?.responds_to?.agent;
  const target = (id ? messages.find((x) => x.id === id) : undefined)
    ?? (who ? [...before].reverse().find((x) => x.agent_id === who && x.status === "ok" && x.role === "assistant") : undefined);
  if (!target) return null;
  return { message: target, excerpt: excerptOf(target), contested: d?.reaction === "discorda" || d?.kind === "contestacao" };
}

export interface PositionChange { message: TeamMessage; from: Stance | null; to: Stance | null; after: string | null }
export interface Track { agent: string; initial: Stance | null; current: Stance | null; thesis?: string; now?: string; changes: PositionChange[] }

/** Posição de cada especialista: a inicial (análise independente), a atual e cada mudança com quem a provocou. */
export function tracks(messages: TeamMessage[], agents: string[]): Track[] {
  return agents.filter((a) => a !== "mentor" && a !== "auditor").map((agent) => {
    const first = messages.find((m) => m.step_key === `conselho:${agent}` && m.status === "ok");
    const initial = first?.meta?.opinion?.stance ?? null;
    const changes: PositionChange[] = [];
    let current = initial;
    let now: string | undefined;
    for (const m of messages) {
      if (m.agent_id !== agent || m.status !== "ok" || !isTurn(m.step_key ?? "")) continue;
      const d = m.meta?.deliberation ?? {};
      const stance = (d.stance as Stance | undefined) ?? current;
      if (d.revised || stance !== current) {
        changes.push({ message: m, from: current, to: stance, after: d.responds_to?.agent ?? null });
        now = firstSentence(m.content);
      }
      current = stance;
    }
    return { agent, initial, current, thesis: first?.meta?.opinion?.excerpts?.tese, now, changes };
  });
}

/** Hipótese e evidências que o Radar mandou no contexto da convocação automática, linha a linha. */
export function convocation(text: string | undefined): { hypothesis?: string; evidence: string[] } {
  const lines = (text ?? "").split("\n");
  const hypothesis = lines.find((l) => l.startsWith("Hipótese a investigar:"))?.slice("Hipótese a investigar:".length).trim();
  const at = lines.findIndex((l) => l.trim() === "Evidências:");
  const evidence: string[] = [];
  if (at >= 0) for (const l of lines.slice(at + 1)) { if (!l.startsWith("- ")) break; evidence.push(l.slice(2).trim()); }
  return { hypothesis, evidence };
}

export interface Chapter { key: string; label: string; index: number }

/** Onde cada etapa começa na sequência publicada (para o replay pular direto). */
export function chapters(messages: TeamMessage[]): Chapter[] {
  const at = (p: (m: TeamMessage) => boolean) => messages.findIndex(p);
  const list: Chapter[] = [
    { key: "abertura", label: "Abertura", index: at((m) => m.step_key === "conselho:enquadramento") },
    { key: "analise", label: "Análises independentes", index: at((m) => isInitial(m.step_key ?? "")) },
    { key: "divergencias", label: "Divergências", index: at((m) => (m.meta?.deliberation?.plan?.divergences?.length ?? 0) > 0) },
    { key: "discussao", label: "Discussão", index: at((m) => isTurn(m.step_key ?? "")) },
    { key: "revisao", label: "Revisões de posição", index: at((m) => !!m.meta?.deliberation?.revised) },
    { key: "auditoria", label: "Auditoria", index: at((m) => !!m.step_key && (m.step_key.startsWith("conselho:devolucao") || m.step_key === "conselho:auditoria")) },
    { key: "conclusao", label: "Veredito", index: at((m) => m.step_key === "conselho:sintese") },
  ];
  return list.filter((c) => c.index >= 0).sort((a, b) => a.index - b.index);
}

/** A sala no quadro `n` do replay: só o que estava publicado até ali, com a reunião "em curso" até o último quadro. */
export function replayInput(input: RoomInput, n: number): RoomInput {
  const messages = input.messages.slice(0, n + 1);
  if (n >= input.messages.length - 1) return { ...input, live: {} };
  const keys = new Set(messages.map((m) => m.step_key));
  return { run: { ...input.run, status: "running" }, steps: input.steps.filter((s) => keys.has(s.step_key)), live: {}, messages };
}
