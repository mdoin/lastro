// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Conselho do Lastro como reunião viva: o palco (personagens com postura derivada dos fatos, quem fala com quem,
 * etapas narradas na ordem real), o fio da discussão (falas que respondem a falas, argumento contestado, revisões de
 * posição), o painel do participante, o veredito do Bento e o replay de reuniões encerradas. Tudo vem de
 * lib/council.ts e lib/expressions.ts (estado registrado); nenhum raciocínio privado aparece e nada é encenado.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import type { Agent, OpinionExcerpt, Stance, TeamMessage, TeamRun, Verdict, VerdictKey, VerdictSegment } from "../api/types";
import {
  chapters, contributionType, convocation, feed, firstSentence, lineup, MODE_LABEL, narrative, quoted, REACTION_LABEL, replayInput,
  isResearch, SEAT_LABEL, seats, speech, spotlight, tracks, type FeedItem, type LiveStep, type RoomInput, type Seat,
} from "../lib/council";
import { EXPRESSION_LABEL, messageExpression, posture } from "../lib/expressions";
import { maybeMask } from "../lib/privacy";
import { AgentAvatar } from "./AgentAvatar";
import { Icon, type IconName } from "./Icon";
import { Markdown } from "./Markdown";

type AgentMap = Record<string, Agent>;

export const STANCE_LABEL: Record<Stance, string> = {
  favoravel: "favorável", contraria: "contrária", condicional: "condicional", insuficiente: "sem base suficiente",
};

const RUN_LABEL: Record<string, string> = {
  queued: "na fila", running: "em reunião", succeeded: "concluída", partial: "concluída com falhas", failed: "falhou", cancelled: "interrompida",
};
const ACTIVE: TeamRun["status"][] = ["queued", "running"];

const tone = (agents: AgentMap, id: string): CSSProperties => ({ ["--agent" as string]: agents[id]?.color ?? "var(--agent-coordenador)" });
export const nameOf = (agents: AgentMap, id: string) => agents[id]?.name ?? (id === "lastro" ? "Lastro" : "Agente");
const roleOf = (agents: AgentMap, id: string) => (agents[id]?.title ?? "").split(" · ")[0];
const clock = (iso: string) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Leva até uma fala do fio (ou ao veredito) e marca por um instante onde ela está. */
export function goTo(id: string, flash = true) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" });
  if (!flash) return;
  el.setAttribute("data-flash", "");
  el.focus({ preventScroll: true });
  window.setTimeout(() => el.removeAttribute("data-flash"), 1600);
}

/** "@Rui" e "@rui" no texto viram links internos que o Markdown desenha como menção (só agentes do registro). */
function linkMentions(text: string, agents: AgentMap): string {
  const byWord = new Map<string, string>();
  for (const a of Object.values(agents)) { byWord.set(a.name.toLowerCase(), a.id); byWord.set(a.handle.toLowerCase(), a.id); }
  return text.replace(/(^|[\s(“"'])@([\p{L}][\p{L}\d_-]*)/gu, (all, pre: string, word: string) => {
    const id = byWord.get(word.toLowerCase());
    return id ? `${pre}[@${word}](#agente:${id})` : all;
  });
}

// ---------------------------------------------------------------- menção

export function MentionChip({ id, agents, onOpen }: { id: string; agents: AgentMap; onOpen?: (id: string) => void }) {
  const name = nameOf(agents, id);
  return (
    <button type="button" className="mention-chip" style={tone(agents, id)} onClick={() => onOpen?.(id)}
      aria-label={`${name}: abrir parecer`} disabled={!onOpen}>
      <span aria-hidden="true">@</span>{name}
    </button>
  );
}

/** Texto de um agente com @menções clicáveis e coloridas. */
function Said({ text, agents, onOpen }: { text: string; agents: AgentMap; onOpen?: (id: string) => void }) {
  return <Markdown text={linkMentions(text, agents)} mention={(id) => <MentionChip id={id} agents={agents} onOpen={onOpen} />} />;
}

function Segments({ items, agents, onOpen, masked }: { items: VerdictSegment[]; agents: AgentMap; onOpen?: (id: string) => void; masked: boolean }) {
  return (
    <>
      {items.map((s, i) => ("agent" in s
        ? <MentionChip key={i} id={s.agent} agents={agents} onOpen={onOpen} />
        : <span key={i}>{maybeMask(s.t, masked)}</span>))}
    </>
  );
}

/** Texto longo recolhido: o resumo vem primeiro, o resto sob demanda. */
function Expandable({ text, masked, limit = 520, agents, onOpen }: { text: string; masked: boolean; limit?: number; agents?: AgentMap; onOpen?: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const shown = maybeMask(text, masked);
  const body = (t: string) => (agents ? <Said text={t} agents={agents} onOpen={onOpen} /> : <Markdown text={t} />);
  if (shown.length <= limit) return body(shown);
  return (
    <div>
      {body(open ? shown : `${shown.slice(0, limit).replace(/\s+\S*$/, "")}…`)}
      <button type="button" className="link-btn small" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Mostrar menos" : "Ler tudo"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- sala (palco)

export function CouncilRoom({ input, question, agents, selected, onSelect, masked, replaying = false }: {
  input: RoomInput; question?: TeamMessage; agents: AgentMap; selected?: string | null; onSelect: (agent: string) => void; masked: boolean;
  replaying?: boolean;
}) {
  const list = seats(input);
  const steps = narrative(input, nameOf(agents, "mentor"));
  const running = list.filter((s) => s.active).map((s) => `${nameOf(agents, s.agent)} (${SEAT_LABEL[s.state].toLowerCase()})`);
  const origin = input.run.route.origin;
  const mode = input.run.route.mode ?? "completo";
  const live = ACTIVE.includes(input.run.status);
  const spot = live || replaying ? spotlight(input) : null;
  const name = (id: string) => nameOf(agents, id);
  const text = origin ? "" : question?.content.replace(/^\s*\/[a-zçãáâéêíóôõú]+\b[:\s]*/i, "") ?? "";
  const call = origin ? convocation(question?.content) : null;
  const lineupIds = lineup(input.run, input.steps);
  const positions = tracks(input.messages, lineupIds).filter((t) => t.current);
  const pauta = [...input.messages].reverse().find((m) => m.step_key?.startsWith("conselho:pauta:"));
  const divergences = pauta?.meta?.deliberation?.plan?.divergences ?? [];
  const sides = (["favoravel", "condicional", "contraria", "insuficiente"] as Stance[])
    .map((st) => ({ st, who: positions.filter((t) => t.current === st) })).filter((g) => g.who.length);

  return (
    <section className="council-room" aria-label="Sala do Conselho" data-run={input.run.status} data-auto={origin ? "1" : undefined}>
      {origin ? (
        <div className="council-opening" role="note">
          <span className="eyebrow"><Icon name="pulse" /> Reunião extraordinária · convocada pelo Radar às {clock(input.run.created_at)}</span>
          {origin.summary && <p className="council-opening-title">{maybeMask(origin.summary, masked)}</p>}
          <p className="council-opening-tags">
            {origin.asset && <span className="tag plain">{origin.asset}</span>}
            {origin.severity && <span className="tag plain">gravidade: {origin.severity}</span>}
            <span className="tag plain">{MODE_LABEL[mode] ?? mode}</span>
          </p>
          {call?.hypothesis && <p className="small"><strong>Hipótese a investigar:</strong> {maybeMask(call.hypothesis, masked)}</p>}
          {call && call.evidence.length > 0 && (
            <ul className="council-opening-evidence small">{call.evidence.slice(0, 3).map((e, i) => <li key={i}>{maybeMask(e, masked)}</li>)}</ul>
          )}
          {call && call.evidence.length > 3 && (
            <details className="small">
              <summary>Mais {call.evidence.length - 3} evidência(s) do Radar</summary>
              <ul className="council-opening-evidence">{call.evidence.slice(3).map((e, i) => <li key={i}>{maybeMask(e, masked)}</li>)}</ul>
            </details>
          )}
          <p className="council-opening-who small">
            <span className="muted">Convocados:</span>
            {lineupIds.map((a) => <span key={a} className="row" style={{ gap: 4 }}><AgentAvatar id={a} size={20} decorative />{name(a)}</span>)}
          </p>
        </div>
      ) : (
        <>
          <header className="council-head">
            <span className="eyebrow">Conselho do Lastro · {MODE_LABEL[mode] ?? mode}</span>
            <span className="tag plain">{replaying ? "replay" : RUN_LABEL[input.run.status] ?? input.run.status}</span>
          </header>
          {text && <p className="council-question">{maybeMask(text, masked)}</p>}
        </>
      )}

      <ol className="council-story" aria-label="Etapas da reunião">
        {steps.map((p) => (
          <li key={p.key} data-state={p.state}>
            <span className="council-phase-dot" aria-hidden="true">{p.state === "done" ? <Icon name="check" /> : null}</span>
            <span>{p.text}</span>
            <span className="visually-hidden">: {{ pending: "ainda não aconteceu", active: "em andamento", done: "concluída", skipped: "não aconteceu" }[p.state]}</span>
          </li>
        ))}
      </ol>

      <ul className="council-seats" aria-label="Participantes" data-spot={spot ? "1" : undefined}>
        {list.map((s) => {
          const p = posture(s, input.messages, name);
          const role = spot?.speaker === s.agent ? "speaker" : spot?.target === s.agent ? "target" : undefined;
          return (
            <li key={s.agent}>
              <button type="button" className="council-seat" style={tone(agents, s.agent)} data-state={s.state} data-role={role}
                data-dim={spot && !role && !s.active ? "1" : undefined}
                data-active={s.active || undefined} aria-pressed={selected === s.agent} onClick={() => onSelect(s.agent)}
                aria-label={`${name(s.agent)}, ${roleOf(agents, s.agent)}: ${SEAT_LABEL[s.state]}${s.act ? ` (${s.act})` : ""}${s.stance ? `, posição ${STANCE_LABEL[s.stance]}` : ""}${s.changed ? ", mudou de posição" : ""}; postura: ${EXPRESSION_LABEL[p.expression]}, ${p.reason}. Abrir detalhes`}>
                <AgentAvatar key={p.expression} id={s.agent} size={56} decorative expression={p.expression}
                  state={s.active ? (s.state === "speaking" || s.state === "responding" || s.state === "questioning" ? "speaking" : "thinking") : "idle"} />
                <span className="council-seat-name">{name(s.agent)}</span>
                <span className="council-seat-role">{roleOf(agents, s.agent)}</span>
                <span key={s.state} className="council-seat-state" data-state={s.state}>
                  {s.active && <span className="council-pulse" aria-hidden="true" />}
                  {SEAT_LABEL[s.state]}
                </span>
                <span className="council-seat-posture">{p.reason}</span>
                {s.stance && (
                  <span className="council-seat-stance" data-stance={s.stance}>
                    {s.changed && <Icon name="refresh" />}{STANCE_LABEL[s.stance]}
                  </span>
                )}
                {role === "speaker" && spot?.target && <span className="council-seat-arrow" aria-hidden="true">fala com {name(spot.target)} →</span>}
                {role === "target" && <span className="council-seat-arrow" aria-hidden="true">← ouve {name(spot!.speaker)}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      {spot && (
        <div className="council-spotlight" style={tone(agents, spot.speaker)} data-live={spot.live || undefined}>
          <p className="council-spotlight-who">
            <strong>{name(spot.speaker)}</strong>
            {spot.target && <><span aria-hidden="true"> → </span><span className="visually-hidden"> para </span><MentionChip id={spot.target} agents={agents} onOpen={onSelect} /></>}
            {spot.toPerson && <> → <strong>você</strong></>}
            <span className="council-kind">{spot.label}</span>
            {spot.live && <span className="tiny muted">falando agora</span>}
          </p>
          {spot.text && <p className="council-spotlight-text">“{maybeMask(spot.text, masked)}”</p>}
          {spot.message && (
            <button type="button" className="link-btn small" onClick={() => goTo(`fala-${spot.message!.id}`)}>Ver na conversa</button>
          )}
        </div>
      )}

      {sides.length > 0 && (
        <div className="council-sides" aria-label="Posições agora">
          {sides.map(({ st, who }) => (
            <div key={st} className="council-side" data-stance={st}>
              <span className="council-seat-stance" data-stance={st}>{STANCE_LABEL[st]}</span>
              <ul>
                {who.map((t) => (
                  <li key={t.agent}>
                    <button type="button" className="council-side-who" style={tone(agents, t.agent)} onClick={() => onSelect(t.agent)}
                      aria-label={`${name(t.agent)}: ${t.initial && t.initial !== t.current ? `começou ${STANCE_LABEL[t.initial]}, agora ` : ""}${STANCE_LABEL[st]}. Abrir`}>
                      <AgentAvatar id={t.agent} size={20} decorative />{name(t.agent)}
                      {t.initial && t.initial !== t.current && <span className="tiny muted"> (era {STANCE_LABEL[t.initial]})</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {divergences.length > 0 && (
            <div className="council-side is-open">
              <span className="eyebrow">Divergências na pauta</span>
              <ul className="small">{divergences.map((d, i) => <li key={i}>{maybeMask(d, masked)}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      <p className="visually-hidden" role="status" aria-live="polite">
        {running.length ? `Agora: ${running.join(", ")}.` : ""}
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- discussão

export function CouncilDiscussion({ messages, live, agents, onOpen, masked, presenting = false }: {
  messages: TeamMessage[]; live: Record<string, LiveStep>; agents: AgentMap; onOpen: (agent: string) => void; masked: boolean; presenting?: boolean;
}) {
  const items = feed(messages);
  const [focus, setFocus] = useState<string | null>(null);
  const related = useMemo(() => {
    if (!focus) return null;
    const m = messages.find((x) => x.id === focus);
    const ids = new Set([focus]);
    if (m) { const q = quoted(m, messages); if (q) ids.add(q.message.id); }
    for (const x of messages) if (quoted(x, messages)?.message.id === focus) ids.add(x.id);
    return ids;
  }, [focus, messages]);
  useEffect(() => {
    if (!focus) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setFocus(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focus]);
  const talking = Object.entries(live).filter(([k, s]) => k.startsWith("conselho:debate:") && !isResearch(k) && s.text);
  if (!items.length && !talking.length) return null;
  const ctx = { agents, onOpen, masked, messages, related, onFocus: presenting ? setFocus : undefined };
  return (
    <section className="council-feed" aria-label="Discussão do Conselho" data-focus={related ? "1" : undefined}>
      {related && (
        <p className="council-focus-bar small" role="status">
          Foco numa troca de falas. <button type="button" className="link-btn small" onClick={() => setFocus(null)}>Mostrar toda a conversa</button>
        </p>
      )}
      {items.map((it, i) => <FeedEntry key={i} item={it} {...ctx} />)}
      {talking.map(([key, s]) => (
        <article key={key} className="council-bubble is-live" style={tone(agents, s.agent_id)} aria-label={`${nameOf(agents, s.agent_id)} está falando`}>
          <AgentAvatar id={s.agent_id} size={36} decorative state="speaking" />
          <div className="council-bubble-body">
            <p className="council-bubble-who"><strong>{nameOf(agents, s.agent_id)}</strong> <span className="tiny muted">falando…</span></p>
            <Markdown text={maybeMask(speech(s.text ?? ""), masked)} />
          </div>
        </article>
      ))}
    </section>
  );
}

interface EntryCtx {
  agents: AgentMap; onOpen: (agent: string) => void; masked: boolean; messages: TeamMessage[]; related: Set<string> | null;
  onFocus?: (id: string) => void;
}

function FeedEntry({ item, agents, onOpen, masked, messages, related, onFocus }: { item: FeedItem } & EntryCtx) {
  const dim = (id: string) => (related && !related.has(id) ? "1" : undefined);
  const order = (m: TeamMessage) => <span className="council-order tiny muted">nº {messages.indexOf(m) + 1} · {clock(m.created_at)}</span>;
  if (item.type === "pessoa") {
    return (
      <article id={`fala-${item.message.id}`} tabIndex={-1} className="council-bubble is-person" aria-label="Sua mensagem na reunião" data-dim={dim(item.message.id)}>
        <div className="council-bubble-body"><p className="council-bubble-who"><strong>Você</strong> {order(item.message)}</p>
          <p className="council-person-text">{maybeMask(item.message.content, masked)}</p></div>
      </article>
    );
  }
  if (item.type === "iniciais") {
    return (
      <div className="council-initials">
        <h3 className="eyebrow">Posições iniciais (análises independentes)</h3>
        <ul>
          {item.messages.map((m) => {
            const id = m.agent_id ?? "";
            const st = m.meta?.opinion?.stance;
            return (
              <li key={m.id} id={`fala-${m.id}`} tabIndex={-1} data-dim={dim(m.id)}>
                <button type="button" className="council-initial" style={tone(agents, id)} onClick={() => onOpen(id)}
                  aria-label={`Parecer inicial de ${nameOf(agents, id)}${st ? `: ${STANCE_LABEL[st]}` : ""}. Abrir`}>
                  <span className="row" style={{ gap: 8 }}><AgentAvatar id={id} size={28} decorative expression={messageExpression(m)} /><strong>{nameOf(agents, id)}</strong>
                    {st && <span className="council-seat-stance" data-stance={st}>{STANCE_LABEL[st]}</span>}
                    {m.meta?.deliberation?.role && <span className="tag plain">{m.meta.deliberation.role === "favor" ? "examina o a favor" : "examina o contra"}</span>}</span>
                  <span className="council-initial-thesis">{maybeMask(m.meta?.opinion?.excerpts?.tese ?? (m.status === "error" ? "Não concluiu." : speech(m.content).slice(0, 220)), masked)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }
  const m = item.message;
  const id = m.agent_id ?? "mentor";
  if (item.type === "abertura" || item.type === "pauta" || item.type === "devolucao") {
    const title = item.type === "abertura" ? "Abertura da reunião" : item.type === "pauta" ? `Pauta${m.meta?.deliberation?.round ? ` · rodada ${m.meta.deliberation.round}` : ""}` : "A auditoria devolveu questões";
    return (
      <article id={`fala-${m.id}`} tabIndex={-1} className={`council-note is-${item.type}`} style={tone(agents, id)} data-dim={dim(m.id)}
        aria-label={`${title}, por ${nameOf(agents, id)}`}>
        <p className="council-bubble-who"><AgentAvatar id={id} size={24} decorative /> <strong>{nameOf(agents, id)}</strong> <span className="tag plain">{title}</span> {order(m)}</p>
        <Expandable text={m.content} masked={masked} limit={420} agents={agents} onOpen={onOpen} />
      </article>
    );
  }
  const type = contributionType(m);
  const stance = m.meta?.deliberation?.stance;
  const q = quoted(m, messages);
  const change = item.revised ? tracks(messages, [id]).at(0) : undefined;
  const step = change?.changes.find((c) => c.message.id === m.id);
  return (
    <article id={`fala-${m.id}`} tabIndex={-1} className={`council-bubble${item.revised ? " is-revised" : ""}`} style={tone(agents, id)}
      data-reaction={item.reaction ?? undefined} data-dim={dim(m.id)}
      aria-label={`${type.label} de ${nameOf(agents, id)}${item.target ? ` para ${nameOf(agents, item.target)}` : item.toPerson ? " para você" : ""}`}>
      <button type="button" className="council-bubble-avatar" onClick={() => onOpen(id)} aria-label={`Abrir ${nameOf(agents, id)}`}>
        <AgentAvatar id={id} size={40} decorative expression={messageExpression(m)} />
      </button>
      <div className="council-bubble-body">
        <p className="council-bubble-who">
          <strong>{nameOf(agents, id)}</strong> <span className="tiny muted">{roleOf(agents, id)}</span>
          {(item.target || item.toPerson) && (
            <span className="council-to tiny"><span aria-hidden="true">→</span> {item.target ? <MentionChip id={item.target} agents={agents} onOpen={onOpen} /> : <strong>você</strong>}</span>
          )}
          <span className="council-kind" data-kind={type.key}>{type.label}</span>
          {item.reaction && !type.fromReaction && !item.revised && (REACTION_LABEL[item.reaction] ?? item.reaction).toLowerCase() !== type.label.toLowerCase() && (
            <span className="council-reaction" data-reaction={item.reaction}>{REACTION_LABEL[item.reaction] ?? item.reaction}</span>
          )}
          {stance && !item.revised && <span className="council-seat-stance" data-stance={stance}>{STANCE_LABEL[stance]}</span>}
          {order(m)}
        </p>
        {(item.target || item.toPerson) && <p className="visually-hidden">↳ respondendo a {item.target ? nameOf(agents, item.target) : "você"}</p>}
        {q && !item.revised && (
          <button type="button" className="council-quote" data-contested={q.contested || undefined} style={tone(agents, q.message.agent_id ?? "lastro")}
            onClick={() => goTo(`fala-${q.message.id}`)} aria-label={`${q.contested ? "Argumento contestado" : "Em resposta a"}: ${q.message.role === "user" ? "você" : nameOf(agents, q.message.agent_id ?? "")}. Ir para a fala`}>
            <span className="tiny">{q.contested ? "Argumento contestado" : "Em resposta a"} · {q.message.role === "user" ? "você" : nameOf(agents, q.message.agent_id ?? "")}</span>
            <span className="council-quote-text">“{maybeMask(q.excerpt, masked)}”</span>
          </button>
        )}
        {item.revised && step && (
          <div className="council-revision" role="note" aria-label="Posição reconsiderada">
            <div>
              <span className="eyebrow">Posição inicial</span>
              {step.from && <span className="council-seat-stance" data-stance={step.from}>{STANCE_LABEL[step.from]}</span>}
              {change?.thesis && <p className="small">{maybeMask(change.thesis, masked)}</p>}
            </div>
            <Icon name="arrow" />
            <div>
              <span className="eyebrow">Posição atual</span>
              {step.to && <span className="council-seat-stance" data-stance={step.to}>{STANCE_LABEL[step.to]}</span>}
              <p className="small">{maybeMask(firstSentence(m.content), masked)}</p>
            </div>
            {step.after && (
              <p className="council-revision-why small">
                <strong>Motivo:</strong> depois de ouvir <MentionChip id={step.after} agents={agents} onOpen={onOpen} />
                {q && <> — <button type="button" className="link-btn small" onClick={() => goTo(`fala-${q.message.id}`)}>“{maybeMask(q.excerpt, masked)}”</button></>}
              </p>
            )}
          </div>
        )}
        {m.status === "error" ? <p className="small muted">Não conseguiu concluir esta fala.</p> : <Expandable text={speech(m.content)} masked={masked} agents={agents} onOpen={onOpen} />}
        {m.sources.length > 0 && (
          <p className="council-evidence tiny"><Icon name="search" /> {m.sources.length} fonte(s): {m.sources.map((s) => s.label).join(" · ")}</p>
        )}
        {onFocus && <button type="button" className="link-btn tiny council-focus-btn" onClick={() => onFocus(m.id)}>Focar nesta troca</button>}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------- painel do participante

const EXCERPT_ORDER: [OpinionExcerpt, string][] = [
  ["tese", "Resumo da posição"], ["evidencia", "Principais argumentos"], ["risco", "Riscos e ressalvas"],
  ["lacuna", "O que falta saber"], ["fonte", "Evidências e fontes"], ["nao agir", "Se não fizer nada"],
];

export function AgentPanel({ seat, seats: all, agents, onClose, onSelect, onReply, onAsk, auditBadge, masked, messages = [] }: {
  seat: Seat; seats: Seat[]; agents: AgentMap; onClose: () => void; onSelect: (agent: string) => void;
  onReply?: (m: TeamMessage) => void; onAsk?: (agent: string, text: string) => Promise<void>;
  auditBadge: (m: TeamMessage) => ReactNode; masked: boolean; messages?: TeamMessage[];
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [ask, setAsk] = useState("");
  const [sending, setSending] = useState(false);
  useEffect(() => { heading.current?.focus(); setAsk(""); }, [seat.agent]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const m = seat.message;
  const specialist = seat.agent !== "mentor" && seat.agent !== "auditor";
  const excerpts = specialist ? m?.meta?.opinion?.excerpts : undefined;
  const name = nameOf(agents, seat.agent);
  const contributions = seat.history.filter((h) => h.step_key !== "conselho:sintese" && h.status === "ok");
  const p = posture(seat, messages, (id) => nameOf(agents, id));
  const track = specialist ? tracks(messages, [seat.agent])[0] : undefined;
  const turns = messages.filter((x) => x.status === "ok" && x.step_key?.startsWith("conselho:debate:"));
  const disagreements = turns.filter((x) => x.meta?.deliberation?.reaction === "discorda"
    && (x.agent_id === seat.agent || x.meta?.deliberation?.responds_to?.agent === seat.agent));
  const role = (m?.meta?.deliberation?.role ? (m.meta.deliberation.role === "favor" ? "Examina o lado a favor" : "Examina o lado contra")
    : seat.agent === "mentor" ? "Conduz a reunião e dá o veredito" : seat.agent === "auditor" ? "Audita o veredito" : "Especialista convocado");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ask.trim() || !onAsk) return;
    setSending(true);
    try { await onAsk(seat.agent, ask.trim()); setAsk(""); } finally { setSending(false); }
  }

  return (
    <>
      <button type="button" className="scrim council-scrim" aria-label="Fechar" onClick={onClose} />
      <aside className="council-panel" role="dialog" aria-modal="false" aria-labelledby="council-panel-title" style={tone(agents, seat.agent)}>
        <div className="council-panel-head">
          <AgentAvatar id={seat.agent} size={64} decorative expression={p.expression} />
          <div>
            <h2 id="council-panel-title" ref={heading} tabIndex={-1}>{name}</h2>
            <p className="small muted">{agents[seat.agent]?.title ?? roleOf(agents, seat.agent)}</p>
            <p className="council-panel-tags">
              <span className="council-seat-state" data-state={seat.state}>{SEAT_LABEL[seat.state]}</span>
              {seat.stance && <span className="council-seat-stance" data-stance={seat.stance}>Posição atual: {STANCE_LABEL[seat.stance]}</span>}
            </p>
            <p className="tiny muted">Postura: <strong>{EXPRESSION_LABEL[p.expression]}</strong> — {p.reason} · Papel: {role}</p>
          </div>
          <button type="button" className="icon-btn" aria-label="Fechar painel" onClick={onClose}><Icon name="x" /></button>
        </div>

        <nav className="council-panel-switch" aria-label="Outros participantes">
          {all.map((s) => (
            <button key={s.agent} type="button" aria-current={s.agent === seat.agent ? "true" : undefined}
              aria-label={nameOf(agents, s.agent)} title={nameOf(agents, s.agent)} onClick={() => onSelect(s.agent)}>
              <AgentAvatar id={s.agent} size={28} decorative />
            </button>
          ))}
        </nav>

        {seat.changed && seat.initialStance && seat.stance && (
          <p className="council-change" role="note"><Icon name="refresh" /> Mudou de posição na discussão: <strong>{STANCE_LABEL[seat.initialStance]}</strong> → <strong>{STANCE_LABEL[seat.stance]}</strong></p>
        )}
        {track && track.now && (
          <div className="council-panel-block council-panel-positions">
            <div><h3 className="eyebrow">Posição inicial</h3><p className="small">{maybeMask(track.thesis ?? "—", masked)}</p></div>
            <div><h3 className="eyebrow">Posição atual</h3><p className="small">{maybeMask(track.now, masked)}</p></div>
          </div>
        )}

        {seat.agent === "auditor" ? (
          m?.audit ? <div className="council-panel-block"><h3 className="eyebrow">Resultado da auditoria</h3>{auditBadge(m)}</div>
            : <p className="small muted">A auditoria aparece quando o veredito do Bento estiver pronto.</p>
        ) : !m && specialist ? (
          <p className="small muted">{seat.state === "unavailable" ? `${name} não conseguiu concluir. As demais análises seguem valendo.` : `${name} ainda não publicou o parecer.`}</p>
        ) : excerpts && Object.keys(excerpts).length ? (
          EXCERPT_ORDER.filter(([k]) => excerpts[k]).map(([k, label]) => (
            <div key={k} className="council-panel-block">
              <h3 className="eyebrow">{label}</h3>
              <p>{maybeMask(excerpts[k]!, masked)}</p>
              {k === "fonte" && m!.sources.length > 0 && (
                <ul className="bullets small">{m!.sources.map((s, i) => <li key={i}>{s.label}{s.reference_date ? ` · ref. ${s.reference_date}` : ""}</li>)}</ul>
              )}
            </div>
          ))
        ) : null}

        {disagreements.length > 0 && (
          <div className="council-panel-block">
            <h3 className="eyebrow">Divergências ({disagreements.length})</h3>
            <ul className="bullets small">
              {disagreements.map((x) => {
                const other = x.agent_id === seat.agent ? x.meta?.deliberation?.responds_to?.agent : x.agent_id;
                return (
                  <li key={x.id}>
                    <button type="button" className="link-btn small" onClick={() => { onClose(); goTo(`fala-${x.id}`); }}>
                      {x.agent_id === seat.agent ? `Discordou de ${nameOf(agents, other ?? "")}` : `${nameOf(agents, other ?? "")} discordou`}
                    </button>: {maybeMask(firstSentence(x.content, 140), masked)}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {track && track.changes.length > 0 && (
          <div className="council-panel-block">
            <h3 className="eyebrow">Mudanças de posição</h3>
            <ol className="bullets small">
              {track.changes.map((c) => (
                <li key={c.message.id}>
                  {c.from ? STANCE_LABEL[c.from] : "sem posição"} → <strong>{c.to ? STANCE_LABEL[c.to] : "sem posição"}</strong>
                  {c.after && <> depois de ouvir {nameOf(agents, c.after)}</>} · {clock(c.message.created_at)}
                </li>
              ))}
            </ol>
          </div>
        )}

        {contributions.length > 0 && (
          <div className="council-panel-block">
            <h3 className="eyebrow">Participação na reunião ({contributions.length})</h3>
            <ol className="council-history">
              {contributions.map((h) => {
                const d = h.meta?.deliberation;
                const label = contributionType(h).label === "Análise inicial" ? "Parecer inicial" : contributionType(h).label;
                return (
                  <li key={h.id}>
                    <details>
                      <summary><span className="tag plain">{label}</span>{d?.responds_to?.agent && <> para {nameOf(agents, d.responds_to.agent)}</>}{d?.responds_to?.person && <> para você</>} <span className="tiny muted">{clock(h.created_at)}</span></summary>
                      <Markdown text={maybeMask(speech(h.content), masked)} />
                    </details>
                  </li>
                );
              })}
            </ol>
          </div>
        )}

        {m && seat.agent === "mentor" && (
          <details className="council-panel-block">
            <summary className="eyebrow">Veredito completo</summary>
            <Markdown text={maybeMask(m.content, masked)} />
          </details>
        )}
        {m && specialist && (
          <>
            {m.audit && <div className="council-panel-block"><h3 className="eyebrow">Auditoria do parecer</h3>{auditBadge(m)}</div>}
            <details className="council-panel-block">
              <summary className="eyebrow">Parecer completo</summary>
              <Markdown text={maybeMask(m.content, masked)} />
            </details>
          </>
        )}
        {onAsk && seat.agent !== "auditor" && (
          <form className="council-ask" onSubmit={(e) => void submit(e)}>
            <label htmlFor="council-ask" className="small"><strong>Perguntar a {name}</strong> <span className="tiny muted">(a resposta aparece na conversa)</span></label>
            <textarea id="council-ask" className="textarea" rows={2} value={ask} maxLength={2000} onChange={(e) => setAsk(e.target.value)}
              placeholder={seat.agent === "mentor" ? "Ex.: quero ouvir a Nina antes da decisão" : `Ex.: por que você pensa assim, ${name}?`} />
            <button type="submit" className="btn btn-primary btn-sm" disabled={!ask.trim() || sending}><Icon name="arrowUp" /> Enviar</button>
          </form>
        )}
        {m && onReply && seat.agent !== "auditor" && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onReply(m)}>
            <Icon name="arrow" /> Responder a esta mensagem de {name}
          </button>
        )}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------- veredito do Bento

const SECTION_ICON: Record<VerdictKey, IconName> = {
  conclusao: "spark", fundamentos: "bars", participacao: "layers", concordancia: "check", reconsideradas: "refresh",
  diverg: "flow", risco: "alert", informac: "search", condicoes: "sliders", proxim: "arrow",
};

export function VerdictView({ message, verdict, agents, onOpen, masked, footer, participants = [] }: {
  message: TeamMessage; verdict: Verdict; agents: AgentMap; onOpen: (id: string) => void; masked: boolean; footer?: ReactNode; participants?: string[];
}) {
  const conclusion = verdict.sections.find((s) => s.key === "conclusao");
  const rest = verdict.sections.filter((s) => s.key !== "conclusao");
  const specialists = participants.filter((a) => a !== "mentor" && a !== "auditor");
  return (
    <article id={`veredito-${message.id}`} tabIndex={-1} className="council-verdict" aria-label={`Veredito de ${nameOf(agents, "mentor")}`}>
      <header className="council-verdict-head">
        <AgentAvatar id="mentor" size={56} decorative expression={message.status === "ok" ? "confiante" : "neutro"} />
        <div>
          <span className="eyebrow">O veredito do {nameOf(agents, "mentor")} · {clock(message.created_at)}</span>
          {conclusion && conclusion.items.map((item, i) => (
            <p key={i} className="council-conclusion"><Segments items={item} agents={agents} onOpen={onOpen} masked={masked} /></p>
          ))}
          {specialists.length > 0 && (
            <p className="council-verdict-who small">
              <span className="muted">Especialistas envolvidos:</span>
              {specialists.map((a) => (
                <button key={a} type="button" className="council-side-who" style={tone(agents, a)} onClick={() => onOpen(a)} aria-label={`${nameOf(agents, a)}: abrir`}>
                  <AgentAvatar id={a} size={20} decorative />{nameOf(agents, a)}
                </button>
              ))}
            </p>
          )}
        </div>
      </header>
      <div className="council-verdict-grid">
        {rest.map((s) => (
          <section key={s.key} className="council-verdict-section" data-key={s.key}>
            <h3><Icon name={SECTION_ICON[s.key] ?? "info"} /> {s.title}</h3>
            <ul>
              {s.items.map((item, i) => <li key={i}><Segments items={item} agents={agents} onOpen={onOpen} masked={masked} /></li>)}
            </ul>
          </section>
        ))}
      </div>
      {footer && <footer className="council-verdict-foot">{footer}</footer>}
      <p className="visually-hidden">Publicado em {message.created_at}</p>
    </article>
  );
}

// ---------------------------------------------------------------- reunião completa (palco, fio, veredito e replay)

const SPEEDS = [1, 2, 4];
const FRAME_MS = 2600;
/** Quadros do replay: o que alguém disse (agentes e a pessoa). Mapa de posições e avisos do Lastro não contam. */
const isFrame = (m: TeamMessage) => m.role === "user" || (!!m.agent_id && m.agent_id !== "lastro");

export function CouncilMeeting({ run, question, messages, live, agents, masked, presenting, selected, onOpen, renderVerdict }: {
  run: TeamRun; question?: TeamMessage; messages: TeamMessage[]; live: Record<string, LiveStep>; agents: AgentMap; masked: boolean;
  presenting: boolean; selected: string | null; onOpen: (agent: string) => void; renderVerdict: (synthesis: TeamMessage, participants: string[]) => ReactNode;
}) {
  const full: RoomInput = { run, steps: run.steps ?? [], live, messages };
  const frames = useMemo(() => messages.flatMap((m, i) => (isFrame(m) ? [i] : [])), [messages]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const ended = !ACTIVE.includes(run.status);
  const replaying = cursor !== null && ended;
  const index = replaying ? frames[Math.min(cursor, frames.length - 1)]! : messages.length - 1;
  const input = replaying ? replayInput(full, index) : full;
  const current = replaying ? messages[index] : undefined;
  const synthesis = input.messages.find((m) => m.step_key === "conselho:sintese");
  const participants = lineup(run, run.steps ?? []);
  const marks = chapters(messages);

  useEffect(() => {
    if (!playing || cursor === null) return;
    if (cursor >= frames.length - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setCursor((c) => (c ?? 0) + 1), FRAME_MS / speed);
    return () => window.clearTimeout(t);
  }, [playing, cursor, speed, frames.length]);
  useEffect(() => {
    if (current) requestAnimationFrame(() => document.getElementById(`fala-${current.id}`)?.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" }));
  }, [current]);

  const jump = (messageIndex: number) => { setPlaying(false); setCursor(Math.max(0, frames.findIndex((i) => i >= messageIndex))); };
  const nextOf = (agent: string) => {
    const at = frames.findIndex((i, k) => k > (cursor ?? -1) && messages[i]!.agent_id === agent);
    const first = frames.findIndex((i) => messages[i]!.agent_id === agent);
    if (at >= 0 || first >= 0) { setPlaying(false); setCursor(at >= 0 ? at : first); }
  };
  const toVerdict = () => {
    setPlaying(false);
    setCursor(frames.length - 1);
    const s = messages.find((m) => m.step_key === "conselho:sintese");
    if (s) window.setTimeout(() => goTo(`veredito-${s.id}`), 60);
  };
  const describe = (m?: TeamMessage) => {
    if (!m) return "";
    const d = m.meta?.deliberation?.responds_to;
    const who = m.role === "user" ? "Você" : nameOf(agents, m.agent_id ?? "");
    return `${who} · ${contributionType(m).label}${d?.agent ? ` para ${nameOf(agents, d.agent)}` : d?.person ? " para você" : ""}`;
  };

  return (
    <>
      <CouncilRoom input={input} question={question} agents={agents} masked={masked} onSelect={onOpen} selected={selected} replaying={replaying} />
      {ended && frames.length > 1 && (
        <div className="council-replay" role="group" aria-label="Replay da reunião">
          {!replaying ? (
            <>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setCursor(0); setPlaying(true); }}>
                <Icon name="play" /> Rever a reunião
              </button>
              <span className="tiny muted">{frames.length} contribuições, a partir do que ficou registrado (nenhuma nova chamada à IA).</span>
            </>
          ) : (
            <>
              <div className="council-replay-buttons">
                <button type="button" className="icon-btn" aria-label="Contribuição anterior" disabled={cursor === 0}
                  onClick={() => { setPlaying(false); setCursor((c) => Math.max(0, (c ?? 0) - 1)); }}><Icon name="chevronRight" style={{ transform: "rotate(180deg)" }} /></button>
                <button type="button" className="icon-btn" aria-label={playing ? "Pausar" : "Reproduzir"} aria-pressed={playing}
                  onClick={() => { if (cursor >= frames.length - 1) setCursor(0); setPlaying((v) => !v); }}><Icon name={playing ? "pause" : "play"} /></button>
                <button type="button" className="icon-btn" aria-label="Próxima contribuição" disabled={cursor >= frames.length - 1}
                  onClick={() => { setPlaying(false); setCursor((c) => Math.min(frames.length - 1, (c ?? 0) + 1)); }}><Icon name="chevronRight" /></button>
                <label className="tiny">Velocidade{" "}
                  <select className="select select-sm" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                    {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
                  </select>
                </label>
                <label className="tiny">Etapa{" "}
                  <select className="select select-sm" value="" onChange={(e) => e.target.value && jump(Number(e.target.value))}>
                    <option value="">Ir para…</option>
                    {marks.map((c) => <option key={c.key} value={c.index}>{c.label}</option>)}
                  </select>
                </label>
                <label className="tiny">Participante{" "}
                  <select className="select select-sm" value="" onChange={(e) => e.target.value && nextOf(e.target.value)}>
                    <option value="">Próxima fala de…</option>
                    {participants.map((a) => <option key={a} value={a}>{nameOf(agents, a)}</option>)}
                  </select>
                </label>
                {messages.some((m) => m.step_key === "conselho:sintese") && <button type="button" className="btn btn-ghost btn-sm" onClick={toVerdict}>Ir ao veredito</button>}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setPlaying(false); setCursor(null); }}><Icon name="x" /> Sair do replay</button>
              </div>
              <progress className="council-replay-progress" max={frames.length} value={cursor + 1} aria-hidden="true" />
              <p className="tiny" role="status" aria-live="polite">
                Contribuição {cursor + 1} de {frames.length}: {describe(current)}
              </p>
            </>
          )}
        </div>
      )}
      <CouncilDiscussion messages={input.messages} live={input.live} agents={agents} onOpen={onOpen} masked={masked} presenting={presenting} />
      {synthesis && renderVerdict(synthesis, participants)}
    </>
  );
}
