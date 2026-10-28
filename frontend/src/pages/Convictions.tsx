// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Convicções: o que cada especialista previu no Conselho (com probabilidade e data), o que aconteceu e quão bem
 * calibrado ele é. Tudo vem do registro (app/convictions.py): previsão gravada como foi dita, conferida pelos dados
 * coletados ou por você quando não há condição automática. Nenhum número é estimado na tela.
 */
import { useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { getConvictions, resolvePrediction, type Calibration, type Prediction } from "../api/convictions";
import { getAgents } from "../api/endpoints";
import type { Agent } from "../api/types";
import { AgentAvatar } from "../components/AgentAvatar";
import { Badge, EmptyState, ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";
import { formatDate } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/convictions.css";

type AgentMap = Record<string, Agent>;
const pct = (v: string | null) => (v == null ? "—" : `${Math.round(Number(v) * 100)}%`);
const num = (v: string | null) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 3 }));
const tone = (agents: AgentMap, id: string): CSSProperties => ({ ["--agent" as string]: agents[id]?.color ?? "var(--agent-coordenador)" });

const RESULT: Record<Prediction["status"], { label: string; tone: "good" | "critical" | "neutral" | "warning" }> = {
  aberta: { label: "em aberto", tone: "neutral" },
  aconteceu: { label: "aconteceu", tone: "good" },
  nao_aconteceu: { label: "não aconteceu", tone: "critical" },
  anulada: { label: "anulada", tone: "neutral" },
  indeterminada: { label: "sem dado para conferir", tone: "warning" },
};

function condition(p: Prediction): string {
  if (!p.check) return "você confere";
  const what = p.check.kind === "serie" ? p.check.series_id : `${p.check.symbol} em USDT`;
  return `confere sozinho: ${what} ${p.check.op} ${p.check.value.replace(".", ",")}`;
}

export function ConvictionsPage() {
  const q = useAsync(getConvictions, []);
  const agentsQ = useAsync(getAgents, []);
  const agents: AgentMap = Object.fromEntries((agentsQ.data ?? []).map((a) => [a.id, a]));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const data = q.data;
  const preds = data?.predictions ?? [];
  const awaiting = preds.filter((p) => p.status === "aberta" && !p.check && p.due_on <= (data?.today ?? ""));
  const open = preds.filter((p) => p.status === "aberta" && !awaiting.includes(p));
  const closed = preds.filter((p) => p.status !== "aberta").sort((a, b) => (b.resolved_at ?? "").localeCompare(a.resolved_at ?? ""));

  async function resolve(p: Prediction, outcome: "aconteceu" | "nao_aconteceu" | "anulada") {
    setBusy(p.id);
    setError(null);
    try {
      await resolvePrediction(p.id, outcome);
      await q.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Não foi possível registrar.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Mentor" title="Convicções"
        lede="O que cada especialista previu no Conselho, com a probabilidade que deu, e o que aconteceu depois. A previsão fica gravada como foi dita; quem acerta com a confiança certa ganha credibilidade." />
      {q.loading && !data && <Loading />}
      <ErrorNotice error={q.error} onRetry={q.reload} />
      {error && <Notice tone="warning" title="Atenção.">{error}</Notice>}

      {data && !preds.length && (
        <EmptyState title="Nenhuma previsão ainda" icon="target">
          Elas aparecem quando um especialista do Conselho declara uma expectativa concreta, com data e probabilidade.
        </EmptyState>
      )}

      {awaiting.length > 0 && (
        <section className="conv-section" aria-labelledby="conv-awaiting">
          <h2 id="conv-awaiting" className="eyebrow">Para você conferir ({awaiting.length})</h2>
          <p className="small muted">A data chegou e só você sabe se aconteceu.</p>
          <ul className="conv-list">
            {awaiting.map((p) => (
              <PredictionItem key={p.id} p={p} agents={agents}>
                <div className="conv-actions" role="group" aria-label="O que aconteceu?">
                  <button type="button" className="btn btn-secondary btn-sm" disabled={busy === p.id} onClick={() => void resolve(p, "aconteceu")}>Aconteceu</button>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={busy === p.id} onClick={() => void resolve(p, "nao_aconteceu")}>Não aconteceu</button>
                  <button type="button" className="btn btn-ghost btn-sm" disabled={busy === p.id} onClick={() => void resolve(p, "anulada")}>Anular</button>
                </div>
              </PredictionItem>
            ))}
          </ul>
        </section>
      )}

      {data && Object.keys(data.agents).length > 0 && (
        <section className="conv-section" aria-labelledby="conv-calibration">
          <h2 id="conv-calibration" className="eyebrow">Calibração por especialista</h2>
          <p className="small muted">Brier: 0 é perfeito; 0,25 é o mesmo que dizer sempre 50%. Quanto mais perto da diagonal, mais a confiança declarada bate com o que acontece.</p>
          <div className="conv-agents">
            {Object.entries(data.agents).map(([id, c]) => <AgentCalibration key={id} id={id} c={c} agents={agents} />)}
          </div>
        </section>
      )}

      {open.length > 0 && (
        <section className="conv-section" aria-labelledby="conv-open">
          <h2 id="conv-open" className="eyebrow">Em aberto ({open.length})</h2>
          <ul className="conv-list">
            {open.map((p) => (
              <PredictionItem key={p.id} p={p} agents={agents}>
                <div className="conv-actions">
                  <button type="button" className="btn btn-ghost btn-sm" disabled={busy === p.id} onClick={() => void resolve(p, "anulada")}>Anular</button>
                </div>
              </PredictionItem>
            ))}
          </ul>
        </section>
      )}

      {closed.length > 0 && (
        <section className="conv-section" aria-labelledby="conv-closed">
          <h2 id="conv-closed" className="eyebrow">Conferidas ({closed.length})</h2>
          <ul className="conv-list">
            {closed.map((p) => <PredictionItem key={p.id} p={p} agents={agents} />)}
          </ul>
        </section>
      )}
    </div>
  );
}

function PredictionItem({ p, agents, children }: { p: Prediction; agents: AgentMap; children?: React.ReactNode }) {
  const name = agents[p.agent_id]?.name ?? "Agente";
  const result = RESULT[p.status];
  return (
    <li className="conv-item" style={tone(agents, p.agent_id)}>
      <span className="conv-prob" aria-label={`Probabilidade ${pct(p.probability)}`}>{pct(p.probability)}</span>
      <div className="conv-main">
        <p className="conv-statement">{p.statement}</p>
        <p className="tiny muted conv-meta">
          <span className="conv-who"><AgentAvatar id={p.agent_id} size={20} decorative /> {name}</span>
          <span>até {formatDate(p.due_on)}</span>
          <span>{condition(p)}</span>
          {p.conversation_id && <Link to={`/mentor/${p.conversation_id}`}>ver a reunião</Link>}
        </p>
        {p.status !== "aberta" && (
          <p className="small conv-result">
            <Badge tone={result.tone}>{result.label}</Badge>
            {p.observed && <span> {p.observed.label}: {p.observed.value.replace(".", ",")} {p.observed.unit} em {formatDate(p.observed.reference_date.slice(0, 10))} ({p.observed.source})</span>}
            {p.resolved_by === "pessoa" && <span className="muted"> · conferida por você</span>}
            {p.brier && <span className="muted"> · Brier {num(p.brier)}</span>}
            {p.note && <span className="muted"> · {p.note}</span>}
          </p>
        )}
        {children}
      </div>
    </li>
  );
}

/** Diagrama de confiabilidade: probabilidade declarada (x) contra frequência observada (y), uma bolinha por faixa. */
function AgentCalibration({ id, c, agents }: { id: string; c: Calibration; agents: AgentMap }) {
  const name = agents[id]?.name ?? "Agente";
  const better = c.brier != null && Number(c.brier) < Number(c.baseline);
  const S = 132, P = 14, W = S - 2 * P;
  return (
    <article className="conv-agent" style={tone(agents, id)} aria-labelledby={`conv-agent-${id}`}>
      <header className="conv-agent-head">
        <AgentAvatar id={id} size={36} decorative />
        <div>
          <h3 id={`conv-agent-${id}`}>{name}</h3>
          <p className="tiny muted">{c.resolved} conferida(s) · {c.open} em aberto{c.indeterminate ? ` · ${c.indeterminate} sem dado` : ""}</p>
        </div>
      </header>
      {c.resolved ? (
        <div className="conv-agent-body">
          <div>
            <p className="conv-brier"><span className="eyebrow">Brier</span><strong>{num(c.brier)}</strong></p>
            <p className="small">{better ? "Melhor que dizer sempre 50%." : "Não melhor que dizer sempre 50%."}</p>
            <p className="tiny muted">Confiança média {pct(c.mean_probability)} · aconteceu {pct(c.observed_rate)} · {c.hits} de {c.resolved} do lado certo</p>
            {c.small_sample && <p className="tiny conv-small">Amostra pequena: ainda não diz muito.</p>}
          </div>
          <svg className="conv-chart" viewBox={`0 0 ${S} ${S}`} width={S} height={S} role="img"
            aria-label={`Calibração de ${name}: ${c.buckets.map((b) => `faixa ${b.from}–${b.to}%, ${b.n} previsão(ões), aconteceu ${pct(b.observed_rate)}`).join("; ")}`}>
            <rect x={P} y={P} width={W} height={W} className="conv-chart-frame" />
            <line x1={P} y1={P + W} x2={P + W} y2={P} className="conv-chart-diagonal" />
            {c.buckets.map((b) => {
              const x = P + Number(b.mean_probability) * W, y = P + (1 - Number(b.observed_rate)) * W;
              return (
                <circle key={b.from} cx={x} cy={y} r={Math.min(4 + b.n, 9)} className="conv-chart-dot">
                  <title>{`Declarou ${pct(b.mean_probability)} em média; aconteceu ${pct(b.observed_rate)} (${b.n} previsão(ões))`}</title>
                </circle>
              );
            })}
            <text x={P} y={S - 2} className="conv-chart-label">0%</text>
            <text x={S - P} y={S - 2} textAnchor="end" className="conv-chart-label">100%</text>
          </svg>
        </div>
      ) : <p className="small muted">Nenhuma previsão conferida ainda.</p>}
    </article>
  );
}
