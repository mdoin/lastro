// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Conselho do Lastro como reunião: a sala (pergunta, etapas e lugares), o painel do participante e o veredito do
 * Bento com menções clicáveis. Tudo é derivado de lib/council.ts (estado real); nenhum raciocínio privado aparece,
 * só estados, pareceres publicados e resumos para a pessoa.
 */
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import type { Agent, OpinionExcerpt, Stance, TeamMessage, Verdict, VerdictSegment } from "../api/types";
import { phases, SEAT_LABEL, seats, type RoomInput, type Seat } from "../lib/council";
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
const nameOf = (agents: AgentMap, id: string) => (id === "auditor" ? agents[id]?.name ?? "Cora" : agents[id]?.name ?? "Agente");
const roleOf = (agents: AgentMap, id: string) => (agents[id]?.title ?? (id === "auditor" ? "Auditora · verificação independente" : "")).split(" · ")[0];

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

// ---------------------------------------------------------------- sala

export function CouncilRoom({ input, question, agents, selected, onSelect, masked }: {
  input: RoomInput; question?: TeamMessage; agents: AgentMap; selected?: string | null; onSelect: (agent: string) => void; masked: boolean;
}) {
  const list = seats(input);
  const steps = phases(input);
  const running = list.filter((s) => s.active).map((s) => nameOf(agents, s.agent));
  return (
    <section className="council-room" aria-label="Sala do Conselho" data-run={input.run.status}>
      <header className="council-head">
        <span className="eyebrow">Conselho do Lastro</span>
        <span className="tag plain">{RUN_LABEL[input.run.status] ?? input.run.status}</span>
      </header>
      {question && <p className="council-question">{maybeMask(question.content.replace(/^\s*\/(conselho|reuni[aã]o)\b[:\s]*/i, ""), masked)}</p>}

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
              aria-label={`${nameOf(agents, s.agent)}, ${roleOf(agents, s.agent)}: ${SEAT_LABEL[s.state]}${s.act ? ` (${s.act})` : ""}. Abrir detalhes`}>
              <AgentAvatar id={s.agent} size={52} decorative state={s.active ? (s.state === "analyzing" ? "speaking" : "thinking") : "idle"} />
              <span className="council-seat-name">{nameOf(agents, s.agent)}</span>
              <span className="council-seat-role">{roleOf(agents, s.agent)}</span>
              <span key={s.state} className="council-seat-state" data-state={s.state}>
                {s.active && <span className="council-pulse" aria-hidden="true" />}
                {SEAT_LABEL[s.state]}
              </span>
              {s.act && s.agent === "mentor" && <span className="council-seat-act">{s.act}</span>}
              {s.stance && <span className="council-seat-stance" data-stance={s.stance}>{STANCE_LABEL[s.stance]}</span>}
            </button>
          </li>
        ))}
      </ul>
      <p className="visually-hidden" role="status" aria-live="polite">
        {running.length ? `Trabalhando agora: ${running.join(", ")}.` : ""}
      </p>
    </section>
  );
}

// ---------------------------------------------------------------- painel do participante

const EXCERPT_ORDER: [OpinionExcerpt, string][] = [
  ["tese", "Resumo da posição"], ["evidencia", "Principais argumentos"], ["risco", "Riscos e ressalvas"],
  ["lacuna", "O que falta saber"], ["fonte", "Evidências e fontes"], ["nao agir", "Se não fizer nada"],
];

export function AgentPanel({ seat, seats: all, agents, onClose, onSelect, onReply, auditBadge, masked }: {
  seat: Seat; seats: Seat[]; agents: AgentMap; onClose: () => void; onSelect: (agent: string) => void;
  onReply?: (m: TeamMessage) => void; auditBadge: (m: TeamMessage) => ReactNode; masked: boolean;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [seat.agent]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const m = seat.message;
  const excerpts = seat.agent === "mentor" || seat.agent === "auditor" ? undefined : m?.meta?.opinion?.excerpts;
  const name = nameOf(agents, seat.agent);
  const reply = seat.agent === "mentor" ? m : seat.agent === "auditor" ? undefined : m;
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
              {seat.stance && <span className="council-seat-stance" data-stance={seat.stance}>Posição: {STANCE_LABEL[seat.stance]}</span>}
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

        {seat.agent === "auditor" ? (
          m?.audit ? <div className="council-panel-block"><h3 className="eyebrow">Resultado da auditoria</h3>{auditBadge(m)}</div>
            : <p className="small muted">A auditoria aparece quando a síntese do Bento estiver pronta.</p>
        ) : !m ? (
          <p className="small muted">{seat.state === "failed" ? `${name} não conseguiu concluir. As demais análises seguem valendo.`
            : seat.agent === "mentor" && seat.framing ? "O enquadramento está abaixo; a síntese vem depois dos pareceres."
            : `${name} ainda não publicou o parecer.`}</p>
        ) : excerpts && Object.keys(excerpts).length ? (
          EXCERPT_ORDER.filter(([k]) => excerpts[k]).map(([k, label]) => (
            <div key={k} className="council-panel-block">
              <h3 className="eyebrow">{label}</h3>
              <p>{maybeMask(excerpts[k]!, masked)}</p>
              {k === "fonte" && m.sources.length > 0 && (
                <ul className="bullets small">{m.sources.map((s, i) => <li key={i}>{s.label}{s.reference_date ? ` · ref. ${s.reference_date}` : ""}</li>)}</ul>
              )}
            </div>
          ))
        ) : null}

        {seat.contest && (
          <details className="council-panel-block">
            <summary className="eyebrow">Resposta na contestação</summary>
            <Markdown text={maybeMask(seat.contest.content, masked)} />
          </details>
        )}
        {seat.framing && (
          <details className="council-panel-block">
            <summary className="eyebrow">Enquadramento da reunião</summary>
            <Markdown text={maybeMask(seat.framing.content, masked)} />
          </details>
        )}
        {m && seat.agent !== "auditor" && (
          <>
            {m.audit && <div className="council-panel-block"><h3 className="eyebrow">Auditoria</h3>{auditBadge(m)}</div>}
            <details className="council-panel-block">
              <summary className="eyebrow">{seat.agent === "mentor" ? "Síntese completa" : "Parecer completo"}</summary>
              <Markdown text={maybeMask(m.content, masked)} />
            </details>
          </>
        )}
        {reply && onReply && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => onReply(reply)}>
            <Icon name="arrow" /> Responder a {name}
          </button>
        )}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------- veredito do Bento

const SECTION_ICON: Record<Verdict["sections"][number]["key"], IconName> = {
  conclusao: "spark", concordancia: "check", diverg: "flow", risco: "alert", informac: "search", proxim: "arrow",
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
            <h3><Icon name={SECTION_ICON[s.key]} /> {s.title}</h3>
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
