// SPDX-License-Identifier: AGPL-3.0-or-later
/** Peças do módulo Carreira reaproveitadas entre as telas. */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { AgentInfo, ApplicationStatus, CareerEvent, Stage } from "../api/carreira";
import { AGENT_STATE, ORIGIN, RUN_KIND, STAGE, STATUS, eventText, eventTone } from "../lib/career";
import { formatDateTime } from "../lib/dates";
import { Badge } from "./ui";

/** Bloco cinza no lugar do conteúdo enquanto carrega (sem texto falso). */
export function Skeleton({ rows = 3, height = 18 }: { rows?: number; height?: number }) {
  return (
    <div className="skeleton-stack" role="status" aria-label="Carregando…">
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="skeleton" style={{ height, width: `${92 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

/** Estado do envio e, separado, a etapa da empresa. */
export function ApplicationBadges({ status, etapa }: { status: ApplicationStatus; etapa: Stage | null }) {
  return (
    <span className="row career-badges">
      {!(status === "candidatada" && etapa) && <Badge tone={STATUS[status].tone}>{STATUS[status].label}</Badge>}
      {etapa && <Badge tone={STAGE[etapa].tone}>{STAGE[etapa].label}</Badge>}
    </span>
  );
}

export function Metric({ label, value, sub, to, tone }: {
  label: string; value: ReactNode; sub?: ReactNode; to?: string; tone?: "warning" | "critical";
}) {
  const body = (
    <>
      <span className="career-metric-label">{label}</span>
      <span className={`career-metric-value num ${tone ?? ""}`}>{value}</span>
      {sub && <span className="career-metric-sub">{sub}</span>}
    </>
  );
  return to ? <Link to={to} className="career-metric">{body}</Link> : <div className="career-metric">{body}</div>;
}

/** Histórico imutável: cada linha diz o que aconteceu, quem fez e quando. */
export function Timeline({ events, empty = "Nenhum evento registrado." }: { events: CareerEvent[]; empty?: string }) {
  if (!events.length) return <p className="small muted">{empty}</p>;
  return (
    <ol className="career-timeline">
      {events.map((e) => (
        <li key={e.id} data-tone={eventTone(e.tipo)}>
          <span className="career-timeline-dot" aria-hidden="true" />
          <div>
            <div className="career-timeline-text">{eventText(e)}</div>
            {typeof e.detalhe.motivo === "string" && e.detalhe.motivo && (
              <div className="small muted">{e.detalhe.motivo}</div>
            )}
            {typeof e.detalhe.resumo === "string" && e.detalhe.resumo && e.tipo === "resposta" && (
              <div className="small muted">{e.detalhe.resumo}</div>
            )}
            <div className="tiny muted">
              {formatDateTime(e.created_at)} · {ORIGIN[e.origem] ?? e.origem}
              {e.detalhe.reconstruido ? " · reconstruído do registro anterior" : ""}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Estado do agente em uma linha, com o indicador vivo só quando há execução real em andamento. */
export function AgentStatusLine({ agent }: { agent: AgentInfo }) {
  const s = AGENT_STATE[agent.estado];
  const run = agent.atual;
  return (
    <div className="career-agent-line" role="status">
      <span className={`status-dot ${s.live ? "running" : s.tone === "neutral" ? "" : s.tone}`} aria-hidden="true" />
      <strong>{s.label}</strong>
      {run && (
        <span className="muted small">
          {RUN_KIND[run.tipo]}
          {run.title ? ` · ${run.title}${run.company ? ` — ${run.company}` : ""}` : ""} · desde {formatDateTime(run.started_at)}
        </span>
      )}
    </div>
  );
}
