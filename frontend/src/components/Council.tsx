// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Conselho do Lastro como reunião: a sala (pergunta, etapas e lugares), o fio da discussão (posições iniciais,
 * pauta, falas que respondem a falas, intervenções), o painel do participante e o veredito do Bento com menções
 * clicáveis. Tudo vem de lib/council.ts (estado real); nenhum raciocínio privado aparece, só estados, pareceres,
 * falas publicadas e resumos para a pessoa.
 */
import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import type { Agent, OpinionExcerpt, Stance, TeamMessage, Verdict, VerdictKey, VerdictSegment } from "../api/types";
import { feed, MODE_LABEL, phases, REACTION_LABEL, SEAT_LABEL, seats, type FeedItem, type LiveStep, type RoomInput, type Seat } from "../lib/council";
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

const tone = (agents: AgentMap, id: string): CSSProperties => ({ ["--agent" as string]: agents[id]?.color ?? "var(--agent-coordenador)" });
export const nameOf = (agents: AgentMap, id: string) => agents[id]?.name ?? (id === "lastro" ? "Lastro" : "Agente");
const roleOf = (agents: AgentMap, id: string) => (agents[id]?.title ?? "").split(" · ")[0];
/** As duas primeiras linhas de uma fala ("**Posição:**", "**Reação:**") viram selos; o resto é o texto. */
const speech = (text: string) => text.replace(/^\s*\**\s*(posi[cç][aã]o|rea[cç][aã]o)\s*:?\**\s*:?[^\n]*\n/gim, "").trim();

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
function Expandable({ text, masked, limit = 520 }: { text: string; masked: boolean; limit?: number }) {
  const [open, setOpen] = useState(false);
  const shown = maybeMask(text, masked);
  if (shown.length <= limit) return <Markdown text={shown} />;
  return (
    <div>
      <Markdown text={open ? shown : `${shown.slice(0, limit).replace(/\s+\S*$/, "")}…`} />
      <button type="button" className="link-btn small" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Mostrar menos" : "Ler tudo"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- sala

export function CouncilRoom({ input, question, agents, selected, onSelect, masked }: {
  input: RoomInput; question?: TeamMessage; agents: AgentMap; selected?: string | null; onSelect: (agent: string) => void; masked: boolean;
}) {
  const list = seats(input);
  const steps = phases(input);
  const running = list.filter((s) => s.active).map((s) => `${nameOf(agents, s.agent)} (${SEAT_LABEL[s.state].toLowerCase()})`);
  const origin = input.run.route.origin;
  const mode = input.run.route.mode ?? "completo";
  const text = origin ? origin.summary ?? question?.content ?? "" : question?.content.replace(/^\s*\/[a-zçãáâéêíóôõú]+\b[:\s]*/i, "") ?? "";
  return (
    <section className="council-room" aria-label="Sala do Conselho" data-run={input.run.status} data-auto={origin ? "1" : undefined}>
      {origin && (
        <p className="council-auto" role="note">
          <Icon name="pulse" /> <strong>Conselho convocado automaticamente</strong>
          {origin.asset && <span className="tag plain">{origin.asset}</span>}
          {origin.severity && <span className="tag plain">{origin.severity}</span>}
        </p>
      )}
      <header className="council-head">
        <span className="eyebrow">Conselho do Lastro · {MODE_LABEL[mode] ?? mode}</span>
        <span className="tag plain">{RUN_LABEL[input.run.status] ?? input.run.status}</span>
      </header>
      {text && <p className="council-question">{maybeMask(text, masked)}</p>}

      <ol className="council-phases" aria-label="Etapas da reunião">
        {steps.map((p) => (
          <li key={p.key} data-state={p.state}>
            <span className="council-phase-dot" aria-hidden="true">{p.state === "done" ? <Icon name="check" /> : null}</span>
            <span>{p.label}</span>
            <span className="visually-hidden">: {{ pending: "aguardando", active: "em andamento", done: "concluída", failed: "não concluída" }[p.state]}</span>
          </li>
        ))}
      </ol>

      <ul className="council-seats" aria-label="Participantes">
        {list.map((s) => (
          <li key={s.agent}>
            <button type="button" className="council-seat" style={tone(agents, s.agent)} data-state={s.state}
              data-active={s.active || undefined} aria-pressed={selected === s.agent} onClick={() => onSelect(s.agent)}
              aria-label={`${nameOf(agents, s.agent)}, ${roleOf(agents, s.agent)}: ${SEAT_LABEL[s.state]}${s.act ? ` (${s.act})` : ""}${s.stance ? `, posição ${STANCE_LABEL[s.stance]}` : ""}${s.changed ? ", mudou de posição" : ""}. Abrir detalhes`}>
              <AgentAvatar id={s.agent} size={52} decorative
                state={s.active ? (s.state === "speaking" || s.state === "responding" || s.state === "questioning" ? "speaking" : "thinking") : "idle"} />
              <span className="council-seat-name">{nameOf(agents, s.agent)}</span>
              <span className="council-seat-role">{roleOf(agents, s.agent)}</span>
              <span key={s.state} className="council-seat-state" data-state={s.state}>
                {s.active && <span className="council-pulse" aria-hidden="true" />}
                {SEAT_LABEL[s.state]}
              </span>
              {s.act && <span className="council-seat-act">{s.act}</span>}
              {s.stance && (
                <span className="council-seat-stance" data-stance={s.stance}>
                  {s.changed && <Icon name="refresh" />}{STANCE_LABEL[s.stance]}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
      <p className="visually-hidden" role="status" aria-live="polite">
        {running.length ? `Agora: ${running.join(", ")}.` : ""}
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- discussão

export function CouncilDiscussion({ messages, live, agents, onOpen, masked }: {
  messages: TeamMessage[]; live: Record<string, LiveStep>; agents: AgentMap; onOpen: (agent: string) => void; masked: boolean;
}) {
  const items = feed(messages);
  const talking = Object.entries(live).filter(([k, s]) => k.startsWith("conselho:debate:") && s.text);
  if (!items.length && !talking.length) return null;
  return (
    <section className="council-feed" aria-label="Discussão do Conselho">
      {items.map((it, i) => <FeedEntry key={i} item={it} agents={agents} onOpen={onOpen} masked={masked} />)}
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

function FeedEntry({ item, agents, onOpen, masked }: { item: FeedItem; agents: AgentMap; onOpen: (agent: string) => void; masked: boolean }) {
  if (item.type === "pessoa") {
    return (
      <article className="council-bubble is-person" aria-label="Sua mensagem na reunião">
        <div className="council-bubble-body"><p className="council-bubble-who"><strong>Você</strong></p>
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
              <li key={m.id}>
                <button type="button" className="council-initial" style={tone(agents, id)} onClick={() => onOpen(id)}
                  aria-label={`Parecer inicial de ${nameOf(agents, id)}${st ? `: ${STANCE_LABEL[st]}` : ""}. Abrir`}>
                  <span className="row" style={{ gap: 8 }}><AgentAvatar id={id} size={28} decorative /><strong>{nameOf(agents, id)}</strong>
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
      <article className={`council-note is-${item.type}`} style={tone(agents, id)} aria-label={`${title}, por ${nameOf(agents, id)}`}>
        <p className="council-bubble-who"><AgentAvatar id={id} size={24} decorative /> <strong>{nameOf(agents, id)}</strong> <span className="tag plain">{title}</span></p>
        <Expandable text={m.content} masked={masked} limit={420} />
      </article>
    );
  }
  const stance = m.meta?.deliberation?.stance;
  return (
    <article className={`council-bubble${item.revised ? " is-revised" : ""}`} style={tone(agents, id)} data-reaction={item.reaction ?? undefined}
      aria-label={`${item.label} de ${nameOf(agents, id)}${item.target ? ` para ${nameOf(agents, item.target)}` : item.toPerson ? " para você" : ""}`}>
      <button type="button" className="council-bubble-avatar" onClick={() => onOpen(id)} aria-label={`Abrir ${nameOf(agents, id)}`}>
        <AgentAvatar id={id} size={36} decorative />
      </button>
      <div className="council-bubble-body">
        <p className="council-bubble-who">
          <strong>{nameOf(agents, id)}</strong> <span className="tiny muted">{roleOf(agents, id)}</span>
          <span className="council-kind" data-kind={item.revised ? "revisao" : item.label}>{item.label}</span>
          {item.reaction && <span className="council-reaction" data-reaction={item.reaction}>{REACTION_LABEL[item.reaction] ?? item.reaction}</span>}
          {stance && <span className="council-seat-stance" data-stance={stance}>{item.revised ? "agora " : ""}{STANCE_LABEL[stance]}</span>}
        </p>
        {(item.target || item.toPerson) && (
          <p className="council-replying tiny">↳ respondendo a {item.target ? <MentionChip id={item.target} agents={agents} onOpen={onOpen} /> : <strong>você</strong>}</p>
        )}
        {m.status === "error" ? <p className="small muted">Não conseguiu concluir esta fala.</p> : <Expandable text={speech(m.content)} masked={masked} />}
        {m.sources.length > 0 && <p className="tiny muted">{m.sources.length} fonte(s): {m.sources.map((s) => s.label).join(" · ")}</p>}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------- painel do participante

const EXCERPT_ORDER: [OpinionExcerpt, string][] = [
  ["tese", "Resumo da posição"], ["evidencia", "Principais argumentos"], ["risco", "Riscos e ressalvas"],
  ["lacuna", "O que falta saber"], ["fonte", "Evidências e fontes"], ["nao agir", "Se não fizer nada"],
];

export function AgentPanel({ seat, seats: all, agents, onClose, onSelect, onReply, onAsk, auditBadge, masked }: {
  seat: Seat; seats: Seat[]; agents: AgentMap; onClose: () => void; onSelect: (agent: string) => void;
  onReply?: (m: TeamMessage) => void; onAsk?: (agent: string, text: string) => Promise<void>;
  auditBadge: (m: TeamMessage) => ReactNode; masked: boolean;
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
          <AgentAvatar id={seat.agent} size={64} decorative />
          <div>
            <h2 id="council-panel-title" ref={heading} tabIndex={-1}>{name}</h2>
            <p className="small muted">{agents[seat.agent]?.title ?? roleOf(agents, seat.agent)}</p>
            <p className="council-panel-tags">
              <span className="council-seat-state" data-state={seat.state}>{SEAT_LABEL[seat.state]}</span>
              {seat.stance && <span className="council-seat-stance" data-stance={seat.stance}>Posição atual: {STANCE_LABEL[seat.stance]}</span>}
            </p>
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

        {contributions.length > 0 && (
          <div className="council-panel-block">
            <h3 className="eyebrow">Participação na reunião ({contributions.length})</h3>
            <ol className="council-history">
              {contributions.map((h) => {
                const d = h.meta?.deliberation;
                const label = h.step_key === "conselho:enquadramento" ? "Abertura" : h.step_key?.startsWith("conselho:pauta") ? "Pauta"
                  : h.step_key?.startsWith("conselho:debate") ? (d?.revised ? "Revisão" : { pergunta: "Pergunta", contestacao: "Contestação", resposta: "Resposta", complemento: "Complemento", evidencia: "Evidência" }[d?.kind ?? ""] ?? "Fala")
                  : h.step_key?.startsWith("conselho:devolucao") ? "Devolução" : h.step_key === "conselho:auditoria" ? "Auditoria" : "Parecer inicial";
                return (
                  <li key={h.id}>
                    <details>
                      <summary><span className="tag plain">{label}</span>{d?.responds_to?.agent && <> para {nameOf(agents, d.responds_to.agent)}</>}{d?.responds_to?.person && <> para você</>}</summary>
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
            <label htmlFor="council-ask" className="small"><strong>Perguntar a {name}</strong></label>
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

export function VerdictView({ message, verdict, agents, onOpen, masked, footer }: {
  message: TeamMessage; verdict: Verdict; agents: AgentMap; onOpen: (id: string) => void; masked: boolean; footer?: ReactNode;
}) {
  const conclusion = verdict.sections.find((s) => s.key === "conclusao");
  const rest = verdict.sections.filter((s) => s.key !== "conclusao");
  return (
    <article className="council-verdict" aria-label={`Veredito de ${nameOf(agents, "mentor")}`}>
      <header className="council-verdict-head">
        <AgentAvatar id="mentor" size={40} decorative />
        <div>
          <span className="eyebrow">Veredito do {nameOf(agents, "mentor")}</span>
          {conclusion && conclusion.items.map((item, i) => (
            <p key={i} className="council-conclusion"><Segments items={item} agents={agents} onOpen={onOpen} masked={masked} /></p>
          ))}
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
