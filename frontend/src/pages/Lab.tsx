// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Laboratório do Conselho: o Bento sozinho e o Conselho completo analisam o MESMO dossiê, em conversas separadas, e
 * o Lastro mede depois quem acertou, com que confiança e a que custo (backend/lab/, docs/LAB.md).
 * Nada aqui é estimado na tela: contagens, Brier e testes vêm do backend; sem amostra, sem porcentagem nem vencedor.
 */
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { createManualDecision, getAgents } from "../api/endpoints";
import {
  cancelExperiment, createExperiment, CRITERIA, getExperiment, getLab, judgeExperiment, linkDecision, putLabSettings,
  refuseExperiment, resolveHypothesis, reviewExperiment, RISK_LABELS, startExperiment,
  type Criterion, type LabAnalysis, type LabDashboard, type LabExperimentDetail, type LabExperimentSummary,
  type LabHypothesis, type LabMode, type LabPair, type LabSettings, type ModeMetrics, type Verdict,
} from "../api/lab";
import type { Agent } from "../api/types";
import { AgentAvatar } from "../components/AgentAvatar";
import { Legend, LineChart } from "../components/LineChart";
import { Markdown } from "../components/Markdown";
import { Badge, Card, EmptyState, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
import { formatDate, formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/lab.css";

type AgentMap = Record<string, Agent>;
type Tone = "good" | "critical" | "neutral" | "warning";

const STATUS: Record<LabExperimentSummary["status"], { label: string; tone: Tone }> = {
  proposto: { label: "proposto", tone: "warning" }, executando: { label: "em execução", tone: "neutral" },
  concluido: { label: "concluído", tone: "good" }, incompleto: { label: "incompleto", tone: "critical" },
  cancelado: { label: "cancelado", tone: "neutral" }, recusado: { label: "recusado", tone: "neutral" },
};
const OUTCOME: Record<LabPair["calibracao"], string> = {
  conselho: "Conselho mais calibrado", individual: "Bento sozinho mais calibrado", empate: "empate",
  sem_avaliacao: "aguardando resultado", nao_comparavel: "não comparável",
};
const HYP: Record<LabHypothesis["status"], { label: string; tone: Tone }> = {
  aberta: { label: "em aberto", tone: "neutral" }, aconteceu: { label: "aconteceu", tone: "good" },
  nao_aconteceu: { label: "não aconteceu", tone: "critical" }, indeterminada: { label: "sem dado", tone: "warning" },
};
const MODE_NAME: Record<LabMode, string> = { individual: "Bento sozinho", conselho: "Conselho completo" };
const PERIODS: Record<string, number | null> = { "30 dias": 30, "90 dias": 90, "1 ano": 365, "Tudo": null };
const num = (v: string | number | null | undefined, digits = 3) =>
  v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: digits });
const pct = (v: string | null) => (v == null ? "—" : `${Math.round(Number(v) * 100)}%`);
const errorText = (e: unknown) => (e instanceof ApiError ? e.detail : "Não foi possível concluir.");
const newId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
const isoDaysAgo = (d: number) => new Date(Date.now() - d * 86400000).toISOString().slice(0, 10);

export function LabPage() {
  const { experimentId } = useParams();
  const agentsQ = useAsync(getAgents, []);
  const agents: AgentMap = Object.fromEntries((agentsQ.data ?? []).map((a) => [a.id, a]));
  return experimentId ? <ExperimentView id={experimentId} agents={agents} /> : <LabHome agents={agents} />;
}

// ---------------------------------------------------------------- tela principal

function LabHome({ agents }: { agents: AgentMap }) {
  const [period, setPeriod] = useState("Tudo");
  const [category, setCategory] = useState("");
  const [creating, setCreating] = useState(false);
  const since = PERIODS[period] ? isoDaysAgo(PERIODS[period] as number) : undefined;
  const q = useAsync(() => getLab({ category, since }), [category, since]);
  const data = q.data;
  const running = data?.experiments.some((e) => e.status === "executando");
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => void q.reload(), 8000);
    return () => window.clearInterval(t);
  }, [running, q]);

  return (
    <div className="stack-lg lab">
      <PageHeader eyebrow="Mentor" title="Laboratório do Conselho"
        lede="O Bento analisa sozinho; o Conselho analisa em reunião. Os dois recebem o mesmo dossiê, sem ver um ao outro, e o Lastro mede depois quem acertou, com que confiança e a que custo. Qualquer resultado vale, inclusive empate."
        actions={<button type="button" className="btn btn-primary" onClick={() => setCreating((v) => !v)}
          aria-expanded={creating}>{creating ? "Fechar" : "Novo experimento"}</button>} />
      {creating && data && <NewExperimentForm categories={data.categories} defaults={data.settings} />}
      {q.loading && !data && <Loading />}
      <ErrorNotice error={q.error} onRetry={q.reload} />
      {data && (
        <>
          <div className="lab-filters" role="group" aria-label="Filtros">
            <div className="lab-segmented" role="radiogroup" aria-label="Período">
              {Object.keys(PERIODS).map((p) => (
                <button key={p} type="button" role="radio" aria-checked={period === p}
                  className={period === p ? "is-on" : ""} onClick={() => setPeriod(p)}>{p}</button>
              ))}
            </div>
            <label className="visually-hidden" htmlFor="lab-cat">Categoria</label>
            <select id="lab-cat" className="select lab-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">Todas as categorias</option>
              {Object.entries(data.categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <Evidence board={data.dashboard} agents={agents} categories={data.categories} />
          <History experiments={data.experiments} categories={data.categories} />
          <Automation settings={data.settings} onSaved={q.reload} />
        </>
      )}
    </div>
  );
}

function Evidence({ board, agents, categories }: { board: LabDashboard; agents: AgentMap; categories: Record<string, string> }) {
  const lineup = ["planejador", "analista", "economista", "riscos", "comportamental"];
  return (
    <section className="stack" aria-labelledby="lab-evidence">
      <h2 id="lab-evidence" className="eyebrow">O que as evidências dizem até agora</h2>
      <VerdictBanner v={board.calibracao} title="Calibração das previsões (Brier)" />
      <div className="lab-tiles">
        <Tile label="Experimentos" value={board.experimentos} sub={`${board.concluidos} concluído(s) · ${board.em_execucao} em execução`} />
        <Tile label="Já avaliáveis" value={board.avaliaveis} sub="com hipótese conferida nos dois modos" />
        <Tile label="Hipóteses pendentes" value={board.pendentes} sub="aguardando a data ou o dado" />
        <Tile label="Não comparáveis" value={board.nao_comparaveis} sub="data simulada: fora da calibração" />
      </div>
      <div className="lab-duel">
        <ModeColumn mode="individual" m={board.por_modo.individual} heads={<AgentAvatar id="mentor" size={44} decorative />} agents={agents} />
        <div className="lab-versus" aria-hidden="true">×</div>
        <ModeColumn mode="conselho" m={board.por_modo.conselho} agents={agents}
          heads={<span className="lab-heads">{lineup.map((a) => <AgentAvatar key={a} id={a} size={30} decorative />)}</span>} />
      </div>
      <div className="grid-2">
        <Card title="Utilidade" eyebrow="Avaliações registradas">
          <div className="stack-sm">
            <VerdictBanner v={board.utilidade.ia} title="IA às cegas" compact />
            <VerdictBanner v={board.utilidade.pessoa} title="Você" compact />
            <p className="tiny muted">A avaliação por IA é uma opinião a mais, não a verdade: notas sem trecho literal conferido são descartadas.</p>
          </div>
        </Card>
        <Card title="O que o debate trouxe" eyebrow={`${board.debate.reunioes} reunião(ões) do Laboratório`}>
          <dl className="kv small">
            <dt>Com mudança de posição justificada</dt><dd>{board.debate.com_mudanca_de_posicao}</dd>
            <dt>Com correção depois do Auditor</dt><dd>{board.debate.com_correcao_apos_auditor}</dd>
            <dt>Com divergência preservada no veredito</dt><dd>{board.debate.com_divergencia_preservada}</dd>
            <dt>Falas repetitivas (sem informação nova)</dt><dd>{board.debate.falas_repetitivas}</dd>
          </dl>
        </Card>
      </div>
      <Evolution board={board} />
      {Object.keys(board.por_categoria).length > 0 && (
        <Card title="Onde cada um foi melhor" eyebrow="Por categoria, comparações de calibração">
          <ul className="lab-cats">
            {Object.entries(board.por_categoria).map(([k, c]) => (
              <li key={k}>
                <span className="lab-cat-name">{categories[k] ?? k}</span>
                <span className="small">Conselho <strong className="num">{c.conselho}</strong></span>
                <span className="small">Bento sozinho <strong className="num">{c.individual}</strong></span>
                <span className="small muted">empates {c.empate} · aguardando {c.sem_avaliacao}</span>
              </li>
            ))}
          </ul>
          <p className="tiny muted">Contagens por repetição. Poucos casos por categoria não sustentam conclusão.</p>
        </Card>
      )}
    </section>
  );
}

function VerdictBanner({ v, title, compact }: { v: Verdict; title: string; compact?: boolean }) {
  const icon = v.vencedor ? (v.vencedor === "conselho" ? "Conselho" : "Bento sozinho") : "Sem vencedor declarado";
  return (
    <div className={`lab-verdict${compact ? " is-compact" : ""}${v.vencedor ? " has-winner" : ""}`} role="status">
      <div className="lab-verdict-head">
        <span className="eyebrow">{title}</span>
        <strong>{icon}</strong>
      </div>
      <p className={compact ? "small" : ""}>{v.texto}</p>
      {!compact && <p className="tiny muted">Conselho {v.conselho} × {v.individual} Bento sozinho · {v.empates} empate(s){v.p_valor != null ? ` · p = ${num(v.p_valor)}` : ""}</p>}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <div className="lab-tile">
      <div className="stat-label">{label}</div>
      <div className="stat-value num">{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
  );
}

function proportionText(p: ModeMetrics["factual_sem_ressalva"]) {
  if (!p.n) return "sem amostra";
  if (p.pct == null) return `${p.k} de ${p.n} (amostra pequena)`;
  return `${num(p.pct, 1)}% (IC95% ${num(p.ic95?.[0], 1)}–${num(p.ic95?.[1], 1)}%, n=${p.n})`;
}

function ModeColumn({ mode, m, heads }: { mode: LabMode; m: ModeMetrics; heads: ReactNode; agents: AgentMap }) {
  const b = m.calibracao;
  return (
    <article className={`lab-mode is-${mode}`} aria-labelledby={`lab-mode-${mode}`}>
      <header className="lab-mode-head">
        {heads}
        <div>
          <h3 id={`lab-mode-${mode}`}>{MODE_NAME[mode]}</h3>
          <p className="tiny muted">{m.analises} análise(s) concluída(s) · {m.hipoteses} hipótese(s)</p>
        </div>
      </header>
      <dl className="lab-metrics">
        <dt>Calibração (Brier)</dt>
        <dd>{b.n ? <>{num(b.brier)} <span className="muted">n={b.n}{b.ic95 && !b.amostra_pequena ? ` · IC95% ${num(b.ic95[0])}–${num(b.ic95[1])}` : ""}{b.amostra_pequena ? " · amostra pequena" : ""}</span></> : <span className="muted">nenhuma hipótese conferida</span>}</dd>
        <dt>Sem ressalva do Auditor</dt><dd>{proportionText(m.factual_sem_ressalva)}</dd>
        <dt>Registro estruturado válido</dt><dd>{proportionText(m.registro_valido)}</dd>
        <dt>Categorias de risco por análise</dt><dd>{m.categorias_de_risco_media ?? "—"}</dd>
        <dt>Problemas de consistência</dt><dd>{m.problemas_de_consistencia} · apontados pelo Auditor {m.erros_apontados_pelo_auditor}</dd>
        <dt>Consumo médio</dt><dd>{m.tokens_medio != null ? `${num(m.tokens_medio, 0)} tokens (n=${m.tokens_amostra})` : "não informado pelo provedor"}</dd>
        <dt>Tempo médio</dt><dd>{m.segundos_medio != null ? `${num(m.segundos_medio, 1)} s` : "—"}</dd>
      </dl>
      <p className="tiny muted">Brier: 0 é perfeito; {num(b.referencia_50pct)} é dizer sempre 50%.</p>
    </article>
  );
}

function Evolution({ board }: { board: LabDashboard }) {
  const ev = board.evolucao;
  if (ev.length < 2) {
    return (
      <Card title="Evolução da calibração" eyebrow="Brier acumulado por modo">
        <p className="small muted">O gráfico aparece quando houver pelo menos duas hipóteses conferidas em experimentos comparáveis.</p>
      </Card>
    );
  }
  const series = (["individual", "conselho"] as const).map((mode, i) => ({
    key: mode, label: MODE_NAME[mode], color: `var(--series-${i + 1})`,
    points: ev.map((p, idx) => ({ x: idx + 1, y: Number(p[mode] ?? NaN), raw: p[mode] ?? "" })).filter((p) => p.raw !== ""),
  }));
  return (
    <Card title="Evolução da calibração" eyebrow="Brier acumulado por modo (menor é melhor)"
      aside={<Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />}>
      <LineChart ariaLabel="Brier acumulado do Bento sozinho e do Conselho à medida que as hipóteses são conferidas"
        series={series} height={220} formatX={(x) => `${Math.round(x)}ª conferida`} formatTick={(y) => num(y, 2)}
        formatValue={(raw) => num(raw)} />
      <details className="small">
        <summary>Ver como tabela</summary>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Conferida em</th><th>Modo</th><th className="num">Bento sozinho</th><th className="num">Conselho</th></tr></thead>
            <tbody>
              {ev.map((p, i) => (
                <tr key={i}><td>{formatDate(p.data)}</td><td>{MODE_NAME[p.modo]}</td>
                  <td className="num">{num(p.individual)} (n={p.n_individual})</td><td className="num">{num(p.conselho)} (n={p.n_conselho})</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}

function History({ experiments, categories }: { experiments: LabExperimentSummary[]; categories: Record<string, string> }) {
  if (!experiments.length) {
    return (
      <EmptyState title="Nenhum experimento ainda" icon="layers">
        Comece com uma pergunta real sobre o seu dinheiro. O painel só mostra resultados de experimentos de verdade.
      </EmptyState>
    );
  }
  return (
    <section className="stack" aria-labelledby="lab-history">
      <h2 id="lab-history" className="eyebrow">Histórico ({experiments.length})</h2>
      <ul className="lab-list">
        {experiments.map((e) => {
          const s = STATUS[e.status];
          const open = e.hypotheses.aberta ?? 0;
          const done = (e.hypotheses.aconteceu ?? 0) + (e.hypotheses.nao_aconteceu ?? 0);
          return (
            <li key={e.id}>
              <Link to={`/laboratorio/${e.id}`} className="lab-item">
                <div className="lab-item-main">
                  <p className="lab-question">{e.question}</p>
                  <p className="tiny muted">
                    {formatDate(e.created_at.slice(0, 10))} · {categories[e.category] ?? e.category}
                    {e.origin === "radar" && " · sugerido pelo Radar"}
                    {e.simulated && ` · data simulada ${formatDate(e.as_of)}`}
                    {` · ${e.repetitions} repetição(ões)`}
                  </p>
                </div>
                <div className="lab-item-side">
                  <Badge tone={s.tone}>{s.label}</Badge>
                  <span className="tiny muted">{done} conferida(s) · {open} em aberto</span>
                  <span className="lab-outcomes">
                    {e.pairs.map((p) => <span key={p.repeticao} className={`lab-dot is-${p.calibracao}`} title={OUTCOME[p.calibracao]} aria-label={`Repetição ${p.repeticao}: ${OUTCOME[p.calibracao]}`} />)}
                  </span>
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function NewExperimentForm({ categories, defaults }: { categories: Record<string, string>; defaults: LabSettings }) {
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  const [category, setCategory] = useState("renda_fixa");
  const [repetitions, setRepetitions] = useState(defaults.repetitions);
  const [research, setResearch] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [followups, setFollowups] = useState<number[]>([30, 90, 180]);
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clientId] = useState(newId);

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    const days = [...followups, ...(custom ? [Number(custom)] : [])].filter((d) => d > 0);
    try {
      const exp = await createExperiment({ question, category, repetitions, research: research && !asOf,
        as_of: asOf || null, followups: days, client_id: clientId });
      navigate(`/laboratorio/${exp.id}`);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }
  const toggle = (d: number) => setFollowups((f) => (f.includes(d) ? f.filter((x) => x !== d) : [...f, d]));
  return (
    <Card title="Novo experimento" eyebrow="Mesmo problema, duas análises independentes">
      <form className="form-grid" onSubmit={(e) => void submit(e)}>
        <Field label="Pergunta" htmlFor="lab-q" help="Uma decisão ou dúvida real. Os dois modos recebem exatamente este texto e o mesmo dossiê.">
          <textarea id="lab-q" className="textarea" rows={3} required minLength={10} maxLength={2000} value={question}
            onChange={(e) => setQuestion(e.target.value)} placeholder="Ex.: Com a Selic alta, vale alongar a renda fixa agora?" />
        </Field>
        <div className="row">
          <Field label="Categoria" htmlFor="lab-nc">
            <select id="lab-nc" className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
              {Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="Repetições por modo" htmlFor="lab-rep" help="O modelo varia entre execuções; mais repetições, conclusão mais firme (e mais consumo).">
            <select id="lab-rep" className="select" value={repetitions} onChange={(e) => setRepetitions(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </Field>
        </div>
        <fieldset className="lab-fieldset">
          <legend>Reavaliações</legend>
          {[30, 90, 180].map((d) => (
            <label key={d} className="lab-check"><input type="checkbox" checked={followups.includes(d)} onChange={() => toggle(d)} /> {d} dias</label>
          ))}
          <label className="lab-check">Outro prazo (dias):
            <input className="input lab-days" type="number" min={1} max={1825} value={custom} onChange={(e) => setCustom(e.target.value)} />
          </label>
        </fieldset>
        <details className="small">
          <summary>Opções avançadas</summary>
          <div className="stack-sm lab-advanced">
            <label className="lab-check"><input type="checkbox" checked={research && !asOf} disabled={!!asOf}
              onChange={(e) => setResearch(e.target.checked)} /> Permitir pesquisa na internet (para os dois modos)</label>
            <p className="tiny muted">Desligada, os dois só usam o dossiê: comparação mais limpa. Ligada, os resultados de busca podem diferir entre as execuções.</p>
            <Field label="Data simulada (opcional)" htmlFor="lab-asof" help="Corta tudo depois desta data. O modelo pode conhecer o período pelo treinamento, então o experimento fica fora da calibração.">
              <input id="lab-asof" type="date" className="input" value={asOf} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setAsOf(e.target.value)} />
            </Field>
          </div>
        </details>
        {error && <Notice tone="warning" title="Não deu.">{error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={busy || question.trim().length < 10}>
            {busy ? "Preparando o dossiê…" : "Rodar as duas análises"}
          </button>
          <span className="tiny muted">Consome a sua cota do provedor de IA. Nenhuma operação financeira é executada.</span>
        </div>
      </form>
    </Card>
  );
}

function Automation({ settings, onSaved }: { settings: LabSettings; onSaved: () => Promise<void> }) {
  const [s, setS] = useState(settings);
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    try {
      await putLabSettings(s);
      setMsg("Salvo.");
      await onSaved();
    } catch (e) {
      setMsg(errorText(e));
    }
  }
  return (
    <details className="lab-auto">
      <summary className="eyebrow">Experimentos sugeridos pelo Radar</summary>
      <div className="form-grid">
        <p className="small">Quando o Radar vê um sinal relevante (por exemplo, uma mudança de juros), o Laboratório pode montar um experimento com ele.</p>
        <Field label="Automação" htmlFor="lab-auto">
          <select id="lab-auto" className="select" value={s.automation} onChange={(e) => setS({ ...s, automation: e.target.value as LabSettings["automation"] })}>
            <option value="desligada">Desligada</option>
            <option value="propor">Propor (eu aprovo antes de rodar)</option>
            <option value="executar">Executar sozinho, dentro dos limites</option>
          </select>
        </Field>
        <div className="row">
          <Field label="Máximo por semana" htmlFor="lab-week">
            <input id="lab-week" className="input" type="number" min={0} max={14} value={s.max_per_week} onChange={(e) => setS({ ...s, max_per_week: Number(e.target.value) })} />
          </Field>
          <Field label="Teto mensal de tokens (0 = sem teto)" htmlFor="lab-budget">
            <input id="lab-budget" className="input" type="number" min={0} value={s.monthly_token_budget} onChange={(e) => setS({ ...s, monthly_token_budget: Number(e.target.value) })} />
          </Field>
        </div>
        <div className="row">
          <button type="button" className="btn btn-secondary" onClick={() => void save()}>Salvar</button>
          {msg && <span className="small muted" role="status">{msg}</span>}
        </div>
      </div>
    </details>
  );
}

// ---------------------------------------------------------------- um experimento

function ExperimentView({ id, agents }: { id: string; agents: AgentMap }) {
  const q = useAsync(() => getExperiment(id), [id]);
  const [rep, setRep] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const exp = q.data;
  const running = exp?.status === "executando";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => void q.reload(), 6000);
    return () => window.clearInterval(t);
  }, [running, q]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await q.reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (!exp) return <div className="stack-lg">{q.loading ? <Loading /> : <ErrorNotice error={q.error} onRetry={q.reload} />}</div>;
  const s = STATUS[exp.status];
  const pair = exp.pairs.find((p) => p.repeticao === rep);
  const byMode = (m: LabMode) => exp.analyses.find((a) => a.mode === m && a.repetition === rep);
  const hyps = (m: LabMode) => exp.hypotheses.filter((h) => h.mode === m && h.repetition === rep);
  const lineup = exp.snapshot.agentes.conselho.filter((a) => a !== "mentor" && a !== "auditor");

  return (
    <div className="stack-lg lab">
      <PageHeader eyebrow="Laboratório do Conselho" title={exp.question}
        lede={<>Criado em {formatDateTime(exp.created_at)} · dados até {formatDate(exp.as_of)}{exp.simulated ? " (simulado)" : ""} · {exp.repetitions} repetição(ões) por modo</>}
        actions={<>
          <Badge tone={s.tone}>{s.label}</Badge>
          {exp.status === "proposto" && <>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void act(() => startExperiment(exp.id))}>Rodar agora</button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void act(() => refuseExperiment(exp.id))}>Recusar</button>
          </>}
          {running && <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void act(() => cancelExperiment(exp.id))}>Cancelar</button>}
        </>} />
      <p><Link to="/laboratorio" className="small">← Voltar ao Laboratório</Link></p>
      {error && <Notice tone="warning" title="Atenção.">{error}</Notice>}
      {!exp.comparable && (
        <Notice tone="warning" title="Experimento não comparável para previsões.">
          {exp.snapshot.comparabilidade.motivos.join(" ")}
        </Notice>
      )}
      {exp.origin === "radar" && <p className="small muted">Sugerido pelo Radar a partir de um sinal registrado.</p>}

      {exp.repetitions > 1 && (
        <div className="lab-segmented" role="radiogroup" aria-label="Repetição">
          {Array.from({ length: exp.repetitions }, (_, i) => i + 1).map((r) => (
            <button key={r} type="button" role="radio" aria-checked={rep === r} className={rep === r ? "is-on" : ""} onClick={() => setRep(r)}>Repetição {r}</button>
          ))}
        </div>
      )}

      {pair && exp.status !== "proposto" && (
        <div className={`lab-result is-${pair.calibracao}`} role="status">
          <span className="eyebrow">Resultado observado</span>
          <strong>{OUTCOME[pair.calibracao]}</strong>
          <span className="small muted">
            Brier: Bento sozinho {num(pair.brier.individual.brier)} (n={pair.brier.individual.n}) · Conselho {num(pair.brier.conselho.brier)} (n={pair.brier.conselho.n})
            {pair.utilidade_ia && ` · utilidade (IA às cegas): ${pair.utilidade_ia === "empate" ? "empate" : MODE_NAME[pair.utilidade_ia]}`}
            {pair.utilidade_pessoa && ` · utilidade (você): ${pair.utilidade_pessoa === "empate" ? "empate" : MODE_NAME[pair.utilidade_pessoa]}`}
          </span>
        </div>
      )}

      <div className="lab-compare">
        <AnalysisColumn mode="individual" a={byMode("individual")} hyps={hyps("individual")} agents={agents} onChange={q.reload}
          heads={<AgentAvatar id="mentor" size={48} state={running ? "thinking" : "idle"} decorative />} />
        <AnalysisColumn mode="conselho" a={byMode("conselho")} hyps={hyps("conselho")} agents={agents} onChange={q.reload}
          heads={<span className="lab-heads">{["mentor", ...lineup, "auditor"].map((a) => <AgentAvatar key={a} id={a} size={34} state={running ? "thinking" : "idle"} decorative />)}</span>} />
      </div>

      {exp.status === "concluido" && (
        <Utility exp={exp} rep={rep} busy={busy} act={act} />
      )}
      <FollowUp exp={exp} />
      <Decision exp={exp} act={act} busy={busy} />
      <Controls exp={exp} />
    </div>
  );
}

function AnalysisColumn({ mode, a, hyps, heads, agents, onChange }: {
  mode: LabMode; a: LabAnalysis | undefined; hyps: LabHypothesis[]; heads: ReactNode; agents: AgentMap; onChange: () => Promise<void>;
}) {
  const ev = a?.evaluation;
  const r = a?.record;
  return (
    <article className={`lab-analysis is-${mode}`} aria-labelledby={`lab-a-${mode}`}>
      <header className="lab-mode-head">
        {heads}
        <div>
          <h2 id={`lab-a-${mode}`}>{MODE_NAME[mode]}</h2>
          <p className="tiny muted">{a ? ({ na_fila: "na fila", executando: "analisando…", concluida: "concluída", falhou: "falhou", cancelada: "cancelada" })[a.status] : "—"}
            {a?.usage?.segundos != null && ` · ${num(a.usage.segundos, 0)} s`}
            {a?.usage?.chamadas != null && ` · ${a.usage.chamadas} chamada(s)`}
            {a?.usage?.tokens ? ` · ${num(a.usage.tokens, 0)} tokens` : ""}</p>
        </div>
      </header>
      {!a || a.status === "na_fila" || a.status === "executando" ? <p className="small muted">A análise aparece aqui quando terminar.</p> : null}
      {a?.status === "falhou" && <Notice tone="warning" title="Esta análise falhou.">O experimento fica incompleto e não entra nas métricas.</Notice>}
      {a?.status === "concluida" && (
        <>
          <section className="lab-block">
            <h3 className="eyebrow">Conclusão</h3>
            <p className="lab-conclusion">{r?.conclusao ?? "Sem registro estruturado."}</p>
            {r && <p className="tiny muted">Confiança declarada: {r.nivel_confianca ?? "não declarada"}{r.dados_insuficientes ? " · disse que os dados não bastam" : ""}{r.horizonte_dias ? ` · horizonte ${r.horizonte_dias} dias` : ""}</p>}
          </section>
          <section className="lab-block">
            <h3 className="eyebrow">Riscos encontrados</h3>
            <div className="lab-chips">
              {(ev?.riscos.categorias ?? []).map((c) => <span key={c} className="chip">{RISK_LABELS[c] ?? c}</span>)}
              {!ev?.riscos.categorias.length && <span className="small muted">Nenhuma categoria reconhecida.</span>}
            </div>
            {r && r.riscos_identificados.length > 0 && <ul className="small lab-ul">{r.riscos_identificados.map((x, i) => <li key={i}>{x}</li>)}</ul>}
          </section>
          <section className="lab-block">
            <h3 className="eyebrow">Hipóteses ({hyps.length})</h3>
            {hyps.length ? <ul className="lab-hyps">{hyps.map((h) => <HypothesisItem key={h.id} h={h} onChange={onChange} />)}</ul>
              : <p className="small muted">{r?.sem_hipotese_motivo ? `Sem hipótese testável: ${r.sem_hipotese_motivo}` : "Nenhuma hipótese registrada."}</p>}
          </section>
          <section className="lab-block">
            <h3 className="eyebrow">Verificações</h3>
            <ul className="small lab-ul">
              <li>Auditor: <strong>{ev?.factual.veredito ?? "—"}</strong>{ev?.factual.numeros_conferidos ? ` · ${ev.factual.numeros_conferidos} número(s) conferido(s)` : ""}</li>
              <li>Registro estruturado: {a.record_status}</li>
              {(ev?.consistencia.problemas ?? []).map((p, i) => <li key={i} className="lab-problem">{p}</li>)}
              {(ev?.factual.ressalvas ?? []).map((p, i) => <li key={`r${i}`} className="muted">{p}</li>)}
            </ul>
          </section>
          {ev?.debate && (
            <section className="lab-block">
              <h3 className="eyebrow">Contribuição do debate</h3>
              <dl className="kv small">
                <dt>Falas na discussão</dt><dd>{ev.debate.falas}</dd>
                <dt>Contestações e perguntas</dt><dd>{ev.debate.contestacoes}</dd>
                <dt>Mudaram de posição</dt><dd>{ev.debate.mudancas_de_posicao.length ? ev.debate.mudancas_de_posicao.map((x) => agents[x]?.name ?? x).join(", ") : "ninguém"}</dd>
                <dt>Correções depois do Auditor</dt><dd>{ev.debate.correcoes_apos_auditor}</dd>
                <dt>Divergências no veredito</dt><dd>{ev.debate.divergencias_finais.length || "nenhuma"}</dd>
                <dt>Falas repetitivas</dt><dd>{ev.debate.falas_repetitivas}</dd>
              </dl>
            </section>
          )}
          {ev && ev.fontes.length > 0 && (
            <section className="lab-block">
              <h3 className="eyebrow">Evidências consultadas</h3>
              <ul className="small lab-ul">{ev.fontes.slice(0, 8).map((f, i) => <li key={i}>{f.url ? <a href={f.url} target="_blank" rel="noreferrer noopener">{f.label ?? f.url}</a> : f.label ?? f.kind}</li>)}</ul>
            </section>
          )}
          <details className="lab-block">
            <summary className="small">Ler a análise completa</summary>
            {a.text && <Markdown text={a.text} />}
            <p className="tiny"><Link to={`/mentor/${a.conversation_id}`}>Abrir a conversa do experimento</Link></p>
          </details>
        </>
      )}
    </article>
  );
}

function HypothesisItem({ h, onChange }: { h: LabHypothesis; onChange: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const due = h.due_on <= new Date().toISOString().slice(0, 10);
  const st = HYP[h.status];
  async function resolve(outcome: "aconteceu" | "nao_aconteceu" | "indeterminada") {
    setBusy(true);
    try {
      await resolveHypothesis(h.id, outcome);
      await onChange();
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className="lab-hyp">
      <span className="lab-prob">{h.probability ? pct(h.probability) : "—"}</span>
      <div>
        <p className="small">{h.statement}</p>
        <p className="tiny muted">até {formatDate(h.due_on)} · {h.check ? `confere sozinho: ${h.check.series_id ?? h.check.symbol} ${h.check.op} ${h.check.value.replace(".", ",")}` : "você confere"}
          {" · "}<Badge tone={st.tone}>{st.label}</Badge>{h.brier && ` · Brier ${num(h.brier)}`}</p>
        {h.observed && <p className="tiny muted">{h.observed.label}: {h.observed.value.replace(".", ",")} {h.observed.unit} em {formatDate(h.observed.reference_date.slice(0, 10))}</p>}
        {h.status === "aberta" && !h.check && due && (
          <div className="row" role="group" aria-label="O que aconteceu?">
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void resolve("aconteceu")}>Aconteceu</button>
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void resolve("nao_aconteceu")}>Não aconteceu</button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void resolve("indeterminada")}>Não dá para saber</button>
          </div>
        )}
      </div>
    </li>
  );
}

function Utility({ exp, rep, busy, act }: { exp: LabExperimentDetail; rep: number; busy: boolean; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const reviews = exp.reviews.filter((r) => r.repetition === rep);
  const [scores, setScores] = useState<Record<LabMode, Partial<Record<Criterion, number>>>>({ individual: {}, conselho: {} });
  const set = (m: LabMode, c: Criterion, v: number) => setScores((s) => ({ ...s, [m]: { ...s[m], [c]: v } }));
  return (
    <Card title="Utilidade para você" eyebrow="Avaliação explícita, por critério">
      <div className="stack">
        <div className="row">
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void act(() => judgeExperiment(exp.id, rep))}>Pedir avaliação às cegas (IA)</button>
          <span className="tiny muted">As análises vão como "A" e "B", em ordem sorteada. Cada nota precisa citar um trecho literal; nota sem trecho conferido é descartada.</span>
        </div>
        {reviews.map((r) => (
          <div key={r.id} className="lab-review">
            <p className="small"><strong>{r.reviewer === "ia" ? "IA às cegas" : "Você"}</strong> · {formatDateTime(r.created_at)}{r.blind ? ` · A = ${MODE_NAME[r.blind.A]}, B = ${MODE_NAME[r.blind.B]}` : ""}</p>
            <div className="lab-review-grid">
              {(["individual", "conselho"] as const).map((m) => {
                const sc = r.scores.por_modo[m];
                return (
                  <div key={m}>
                    <p className="tiny muted">{MODE_NAME[m]}: <strong>{sc?.total ?? 0}</strong> de {sc?.max ?? 0}</p>
                    <ul className="tiny lab-ul">
                      {Object.entries(sc?.criterios ?? {}).map(([c, v]) => <li key={c}>{CRITERIA[c as Criterion]}: {v?.nota}{v?.trecho ? ` — “${v.trecho}”` : ""}</li>)}
                      {(sc?.descartados ?? []).map((c) => <li key={c} className="muted">{CRITERIA[c]}: descartada (sem trecho conferido)</li>)}
                    </ul>
                  </div>
                );
              })}
            </div>
            {r.scores.observacao && <p className="tiny muted">{r.scores.observacao}</p>}
          </div>
        ))}
        <details>
          <summary className="small">Dar a sua avaliação</summary>
          <div className="lab-review-grid">
            {(["individual", "conselho"] as const).map((m) => (
              <fieldset key={m} className="lab-fieldset">
                <legend>{MODE_NAME[m]}</legend>
                {(Object.keys(CRITERIA) as Criterion[]).map((c) => (
                  <label key={c} className="lab-score">{CRITERIA[c]}
                    <select className="select" value={scores[m][c] ?? ""} onChange={(e) => set(m, c, Number(e.target.value))}>
                      <option value="">—</option><option value={0}>0</option><option value={1}>1</option><option value={2}>2</option>
                    </select>
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void act(() => reviewExperiment(exp.id, rep, scores))}>Registrar minha avaliação</button>
        </details>
      </div>
    </Card>
  );
}

function FollowUp({ exp }: { exp: LabExperimentDetail }) {
  return (
    <Card title="Acompanhamento" eyebrow="Reavaliações agendadas">
      <ol className="lab-timeline">
        {exp.checkpoints.map((c) => (
          <li key={c.id} className={`is-${c.status}`}>
            <strong>{c.days} dias</strong> <span className="small muted">{formatDate(c.due_on)}</span>
            <Badge tone={c.status === "feita" ? "good" : c.status === "pendente" ? "warning" : "neutral"}>
              {c.status === "feita" ? "feita" : c.status === "pendente" ? "aguardando dados" : "agendada"}
            </Badge>
          </li>
        ))}
      </ol>
      {exp.journal.length > 0 && (
        <details className="small">
          <summary>Diário do Laboratório ({exp.journal.length} registro(s), encadeados)</summary>
          <ul className="lab-ul">
            {exp.journal.map((j) => (
              <li key={j.id}>{formatDateTime(j.created_at)} · {j.kind === "analise_ia" ? "análise de IA" : j.kind === "resultado_observado" ? "resultado observado" : "decisão vinculada"} · <span className="tiny muted">{j.payload.aviso}</span></li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function Decision({ exp, act, busy }: { exp: LabExperimentDetail; act: (fn: () => Promise<unknown>) => Promise<void>; busy: boolean }) {
  const [choice, setChoice] = useState("");
  const [clientId] = useState(newId);
  const linked = exp.journal.some((j) => j.kind === "decisao_vinculada");
  if (exp.status !== "concluido" && exp.status !== "incompleto") return null;
  return (
    <Card title="E você, o que decidiu?" eyebrow="Diário de Decisões">
      <p className="small">As análises acima são da IA. Uma recomendação não é uma decisão sua, e uma decisão não é uma operação feita. Se quiser, registre a sua escolha no Diário; ela fica ligada a este experimento.</p>
      {linked ? <p className="small"><Badge tone="good">decisão registrada</Badge> <Link to="/diario">ver no Diário</Link></p> : (
        <div className="row">
          <label className="visually-hidden" htmlFor="lab-choice">Minha escolha</label>
          <input id="lab-choice" className="input lab-choice" maxLength={500} placeholder="Ex.: mantive no pós-fixado por enquanto" value={choice} onChange={(e) => setChoice(e.target.value)} />
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy || !choice.trim()} onClick={() => void act(async () => {
            const d = await createManualDecision({ titulo: exp.question.slice(0, 200), escolha: choice, client_id: clientId,
              informacoes: `Experimento do Laboratório do Conselho ${exp.id}.` });
            await linkDecision(exp.id, d.id);
          })}>Registrar no Diário</button>
        </div>
      )}
    </Card>
  );
}

function Controls({ exp }: { exp: LabExperimentDetail }) {
  const s = exp.snapshot;
  return (
    <details className="lab-controls">
      <summary className="eyebrow">Controle experimental</summary>
      <dl className="kv small">
        <dt>Dossiê (SHA-256)</dt><dd className="lab-hash">{s.dossie_sha256}</dd>
        <dt>Registro completo (SHA-256)</dt><dd className="lab-hash">{exp.snapshot_sha256}</dd>
        <dt>Versão dos prompts</dt><dd className="lab-hash">{s.prompts_sha256.slice(0, 16)}</dd>
        <dt>Data de corte</dt><dd>{formatDate(s.data_de_corte)}{s.simulado ? " (simulada)" : ""}</dd>
        <dt>Ferramentas (iguais nos dois modos)</dt><dd>{s.ferramentas.todos_os_agentes.join(", ")} · leitura ao vivo {s.ferramentas.leitura_ao_vivo}</dd>
        <dt>Conselho convocado</dt><dd>{s.agentes.conselho.join(", ")}</dd>
        <dt>Modelos</dt><dd>{Object.entries(s.modelos).map(([a, m]) => `${a}: ${Object.values(m).join(" ") || "padrão"}`).join(" · ")}</dd>
        <dt>Motor financeiro</dt><dd>{s.motor_financeiro} · Lastro {s.versao_lastro}</dd>
        <dt>Amostragem</dt><dd>{s.amostragem}</dd>
        <dt>Fontes do dossiê</dt><dd>{s.fontes.map((f) => `${f.serie} (ref. ${formatDate(f.data_referencia)}, coletado ${formatDateTime(f.coletado_em)})`).join(" · ") || "nenhuma"}</dd>
        {s.avisos.length > 0 && <><dt>Avisos</dt><dd>{s.avisos.join(" ")}</dd></>}
      </dl>
    </details>
  );
}
