// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  addDecision,
  addOperation,
  CATEGORY,
  DECISION_LABEL,
  discuss,
  getJournal,
  getMetrics,
  getOpportunity,
  getRules,
  STATE,
  VERDICT,
  type Block,
  type Decision,
  type JournalFilters,
  type OpportunityDetail,
  type Outcome,
  type Rate,
  type Verdict,
} from "../api/radar";
import { AgentAvatar } from "../components/AgentAvatar";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { Badge, Card, EmptyState, ErrorNotice, Field, Loading, Notice, PageHeader, Segmented, Tag } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDate, formatDateTime } from "../lib/dates";
import { formatNumberBR } from "../lib/money";
import { errorMessage, useAsync } from "../lib/useAsync";
import "../styles/radar.css";
import { AgentStack, PriorityBadge } from "./Radar";
import { DateInput } from "../components/DateInput";

const AGENT_NAMES: Record<string, string> = {
  mentor: "Mentor",
  planejador: "Planejador",
  analista: "Analista",
  economista: "Economista",
  riscos: "Gestor de Riscos",
  comportamental: "Conselheiro",
  cripto: "Analista de Ativos Digitais",
  auditor: "Auditor",
};

const RUN_LABEL: Record<string, string> = {
  succeeded: "concluída",
  partial: "parcial (algum especialista falhou)",
  failed: "falhou",
  cancelled: "cancelada",
  tempo_esgotado: "tempo esgotado",
  indisponivel: "indisponível",
};

function VerdictBadge({ v }: { v: Verdict | null }) {
  if (!v) return <Badge tone="neutral" icon="clock">pendente</Badge>;
  return <Badge tone={VERDICT[v].tone}>{VERDICT[v].label}</Badge>;
}

function pct(r: Rate): ReactNode {
  if (r.valor === null) return <span className="muted">—</span>;
  return (
    <>
      {formatNumberBR(String(Number(r.valor) * 100), 0)}%{" "}
      <span className={`tiny ${r.confiavel ? "muted" : "radar-small-sample"}`}>
        n={r.n}
        {!r.confiavel && " · amostra pequena"}
      </span>
    </>
  );
}

// ---------------------------------------------------------------- Diário (lista + métricas)

export function OpportunitiesPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("aba") === "historico" ? "historico" : "visao";
  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Diário de oportunidades"
        title="O que o Lastro viu, e o que aconteceu depois"
        lede="Cada sinal avaliado fica registrado como era conhecido no dia, inclusive os que não viraram alerta. Depois, o Lastro volta a eles nos horizontes combinados e mede, com o critério escrito antes, se a hipótese se confirmou."
        actions={
          <Link className="btn btn-ghost btn-sm" to="/radar">
            <Icon name="pulse" />
            Radar
          </Link>
        }
      />
      <Segmented
        label="Seção do Diário"
        variant="mono"
        options={[
          { value: "visao", label: "Métricas" },
          { value: "historico", label: "Histórico" },
        ]}
        value={tab}
        onChange={(v) => setParams(v === "historico" ? { aba: v } : {})}
      />
      {tab === "visao" ? <MetricsView /> : <History />}
    </div>
  );
}

function MetricsView() {
  const [days, setDays] = useState("365");
  const [horizon, setHorizon] = useState("90");
  const m = useAsync(() => getMetrics(Number(days), Number(horizon)), [days, horizon]);
  const d = m.data;
  return (
    <div className="stack-lg">
      <div className="row">
        <Segmented
          label="Período"
          options={[
            { value: "30", label: "30 dias" },
            { value: "90", label: "90 dias" },
            { value: "365", label: "12 meses" },
          ]}
          value={days}
          onChange={setDays}
        />
        <Segmented
          label="Horizonte avaliado"
          options={["7", "30", "90", "180", "365"].map((h) => ({ value: h, label: `${h} d` }))}
          value={horizon}
          onChange={setHorizon}
        />
      </div>
      {m.loading && !d && <Loading />}
      <ErrorNotice error={m.error} onRetry={m.reload} />
      {d && (
        <>
          <div className="grid">
            <Stat label="Sinais detectados" value={d.totais.sinais} />
            <Stat label="Alertas emitidos" value={d.totais.alertas} />
            <Stat label="Em acompanhamento" value={d.totais.estados.em_acompanhamento ?? 0} />
            <Stat label="Encerradas" value={d.totais.estados.encerrada ?? 0} />
            <Stat label="Invalidadas" value={d.totais.estados.invalidada ?? 0} />
            <Stat label="Inconclusivas" value={d.totais.estados.inconclusiva ?? 0} />
          </div>
          <Card title={`Qualidade do Radar · horizonte de ${d.horizonte_dias} dias`} eyebrow="Métricas"
            footer={<ul className="bullets tiny muted">{d.limitacoes.map((l) => <li key={l}>{l}</li>)}</ul>}>
            <BlockTable rows={[{ name: "Geral", b: d.geral }, ...Object.entries(d.por_categoria).map(([k, b]) => ({ name: CATEGORY[k as keyof typeof CATEGORY] ?? k, b }))]} />
          </Card>
          <Card title="Por regra" eyebrow="Onde está o ruído">
            {Object.keys(d.por_regra).length === 0 ? (
              <p className="muted small">Sem sinais no período.</p>
            ) : (
              <BlockTable rows={Object.values(d.por_regra).map((b) => ({ name: b.nome, b }))} />
            )}
          </Card>
          <Card title="Evolução mês a mês" eyebrow="O Radar está melhorando?">
            {d.tendencia_mensal.length < 3 && (
              <Notice tone="info">Com menos de três meses de histórico não dá para falar em tendência.</Notice>
            )}
            <BlockTable rows={d.tendencia_mensal.map((b) => ({ name: b.mes, b }))} />
          </Card>
          <Card title="Latência" eyebrow="Tempo">
            <dl className="kv">
              <dt>Do dado à detecção (mediana)</dt>
              <dd>{d.latencia.evento_ate_deteccao_dias_mediana ?? "—"} dias</dd>
              <dt>Da detecção ao alerta (mediana)</dt>
              <dd>{d.latencia.deteccao_ate_alerta_horas_mediana ?? "—"} h</dd>
            </dl>
            <p className="tiny muted">{String(d.latencia.nota)}</p>
          </Card>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="card stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value num">{value}</div>
    </div>
  );
}

function BlockTable({ rows }: { rows: { name: string; b: Block }[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th></th>
            <th className="num">Sinais</th>
            <th className="num">Hipóteses confirmadas</th>
            <th className="num">Invalidados</th>
            <th className="num">Dados insuficientes</th>
            <th className="num">Repetidos</th>
            <th className="num">Úteis (sua avaliação)</th>
            <th className="num">Excesso médio vs CDI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ name, b }) => (
            <tr key={name}>
              <td>{name}</td>
              <td className="num">{b.sinais}</td>
              <td className="num">{pct(b.precisao)}</td>
              <td className="num">{pct(b.invalidados)}</td>
              <td className="num">{pct(b.dados_insuficientes)}</td>
              <td className="num">{pct(b.redundantes)}</td>
              <td className="num">{pct(b.utilidade_informada)}</td>
              <td className="num">
                {b.excesso_medio_vs_cdi_pp === null ? "—" : `${formatNumberBR(b.excesso_medio_vs_cdi_pp)} p.p.`}
                {b.n_excesso > 0 && <span className="tiny muted"> n={b.n_excesso}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function History() {
  const id = useId();
  const [f, setF] = useState<JournalFilters>({});
  const [applied, setApplied] = useState<JournalFilters>({});
  const list = useAsync(() => getJournal(applied), [JSON.stringify(applied)]);
  const rules = useAsync(getRules, []);
  const set = (k: keyof JournalFilters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="stack">
      <form
        className="card form-grid radar-filters"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(f);
        }}
      >
        <Field label="Ativo" htmlFor={`${id}-a`}>
          <input id={`${id}-a`} className="input" value={f.asset ?? ""} onChange={set("asset")} placeholder="IPCA+ 2035" />
        </Field>
        <Field label="Categoria" htmlFor={`${id}-c`}>
          <select id={`${id}-c`} className="select" value={f.category ?? ""} onChange={set("category")}>
            <option value="">Todas</option>
            {Object.entries(CATEGORY).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="Regra" htmlFor={`${id}-r`}>
          <select id={`${id}-r`} className="select" value={f.rule_id ?? ""} onChange={set("rule_id")}>
            <option value="">Todas</option>
            {rules.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </Field>
        <Field label="Estado" htmlFor={`${id}-s`}>
          <select id={`${id}-s`} className="select" value={f.state ?? ""} onChange={set("state")}>
            <option value="">Todos</option>
            {Object.entries(STATE).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="Prioridade mínima" htmlFor={`${id}-p`}>
          <select id={`${id}-p`} className="select" value={f.min_class ?? ""} onChange={set("min_class")}>
            <option value="">Qualquer</option>
            {[2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </Field>
        <Field label="Resultado" htmlFor={`${id}-v`}>
          <select id={`${id}-v`} className="select" value={f.verdict ?? ""} onChange={set("verdict")}>
            <option value="">Qualquer</option>
            {Object.entries(VERDICT).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </Field>
        <Field label="Especialista" htmlFor={`${id}-e`}>
          <select id={`${id}-e`} className="select" value={f.agent ?? ""} onChange={set("agent")}>
            <option value="">Qualquer</option>
            {Object.entries(AGENT_NAMES).filter(([k]) => k !== "auditor").map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="De" htmlFor={`${id}-d1`}>
          <DateInput id={`${id}-d1`} value={f.since ?? ""} onChange={(e) => setF({ ...f, since: e.target.value })} />
        </Field>
        <Field label="Até" htmlFor={`${id}-d2`}>
          <DateInput id={`${id}-d2`} value={f.until ?? ""} onChange={(e) => setF({ ...f, until: e.target.value })} />
        </Field>
        <div className="row" style={{ alignSelf: "end" }}>
          <button type="submit" className="btn btn-primary btn-sm">Filtrar</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setF({}); setApplied({}); }}>Limpar</button>
        </div>
      </form>
      {list.loading && !list.data && <Loading />}
      <ErrorNotice error={list.error} onRetry={list.reload} />
      {list.data?.length === 0 && (
        <EmptyState title="Nenhum registro" icon="book">
          Quando o Radar detectar um sinal, ele entra aqui, com o que se sabia naquele momento.
        </EmptyState>
      )}
      {!!list.data?.length && (
        <div className="table-wrap">
          <table className="table radar-journal">
            <thead>
              <tr>
                <th>Detectada</th>
                <th>Ativo e condição</th>
                <th>Classificação</th>
                <th>Estado</th>
                <th>Avaliações</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((o) => (
                <tr key={o.id}>
                  <td className="nowrap">{formatDate(o.created_at)}</td>
                  <td>
                    <Link to={`/oportunidades/${o.id}`}>{o.asset_label}</Link>
                    <div className="tiny muted">{o.condition_text}</div>
                    <div className="row tiny">
                      {o.agents.length > 0 && o.agents.map((id) => <AgentAvatar key={id} id={id} size={20} />)}
                      <Tag>{CATEGORY[o.category]}</Tag>
                      {o.alert_id ? <Tag>alerta</Tag> : <Tag>sem alerta</Tag>}
                      {o.redundant_of && <Tag>repetido</Tag>}
                    </div>
                  </td>
                  <td><PriorityBadge level={o.classification} /></td>
                  <td>{STATE[o.state]}</td>
                  <td>
                    <div className="row">
                      {o.verdicts.map((v) => (
                        <span key={`${v.horizon_days}`} className="radar-verdict-chip" title={v.verdict ? VERDICT[v.verdict].label : "pendente"}>
                          <span className="mono tiny">{v.horizon_days}d</span> <VerdictBadge v={v.verdict} />
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Detalhe

/** Painel do que se sabia na data da detecção (registro imutável) ou do que veio depois. */
function Era({ known, at, title, children }: { known: boolean; at?: string; title: string; children: ReactNode }) {
  return (
    <section className={known ? "radar-known" : "radar-later"} aria-label={title}>
      <div className="radar-era">
        <Icon name={known ? "lock" : "clock"} />
        {known ? `Conhecido em ${at ? formatDateTime(at) : "—"} · registro original` : "Descoberto depois"}
      </div>
      <h2 className="radar-section-title">{title}</h2>
      {children}
    </section>
  );
}

export function OpportunityPage() {
  const { opportunityId = "" } = useParams();
  const app = useApp();
  const navigate = useNavigate();
  const q = useAsync(() => getOpportunity(opportunityId), [opportunityId]);
  const [busy, setBusy] = useState(false);
  if (q.loading && !q.data) return <Loading />;
  if (!q.data) return <ErrorNotice error={q.error} onRetry={q.reload} />;
  const d = q.data;
  const det = d.snapshots.find((s) => s.kind === "deteccao");
  const analysis = d.snapshots.find((s) => s.kind === "analise");
  const corrections = d.snapshots.filter((s) => s.kind === "correcao");
  const p = det?.payload ?? {};

  async function talk(target: "mentor" | "conselho") {
    setBusy(true);
    try {
      const conv = await discuss(d.opportunity.id, target);
      navigate(`/mentor/${conv.id}`);
    } catch (e) {
      app.toast(errorMessage(e), "error");
      setBusy(false);
    }
  }

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow={`Diário de oportunidades · ${CATEGORY[d.opportunity.category]}`}
        title={d.opportunity.asset_label}
        lede={d.signal.condition_text}
        actions={
          <>
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => talk("mentor")}>
              <Icon name="chat" />
              Discutir com o Mentor
            </button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => talk("conselho")}>
              <Icon name="layers" />
              Convocar o Conselho
            </button>
          </>
        }
      />
      <div className="row">
        <PriorityBadge level={d.opportunity.classification} />
        <Badge tone="neutral" icon="info">{STATE[d.opportunity.state]}</Badge>
        <Badge tone={d.chain.ok ? "good" : "critical"} icon={d.chain.ok ? "shieldCheck" : "alert"}>
          {d.chain.ok ? `Registro íntegro (${d.chain.registros} registro(s) encadeados)` : `Cadeia quebrada nos registros ${d.chain.falhas.join(", ")}`}
        </Badge>
      </div>

      <Era known at={det?.created_at} title="1. Situação original">
        <dl className="kv">
          <dt>Regra</dt>
          <dd>{p.regra?.name} (versão {p.regra?.version})</dd>
          <dt>Data de referência do dado</dt>
          <dd>{formatDate(p.sinal?.reference_date)}</dd>
          <dt>Valor observado</dt>
          <dd>{p.sinal?.valor_observado} {p.serie?.unit ?? ""}</dd>
          <dt>Fonte</dt>
          <dd>{p.serie?.fonte ?? "Seu retrato financeiro"}</dd>
          <dt>Score (critérios ponderados, não é probabilidade)</dt>
          <dd>{p.classificacao?.score}</dd>
          {Object.entries(p.contexto ?? {})
            .filter(([k]) => k in CONTEXT_LABEL)
            .map(([k, v]) => (
              <FragmentKV key={k} k={CONTEXT_LABEL[k]!} v={formatContext(k, String(v))} />
            ))}
        </dl>
        <ul className="bullets small">
          {(p.classificacao?.reasons ?? []).map((r: string) => <li key={r}>{r}</li>)}
        </ul>
      </Era>

      <Era known at={det?.created_at} title="2. Dados disponíveis na detecção">
        <div className="grid-2">
          <div>
            <h3 className="small">Qualidade</h3>
            <p className="small">
              {p.qualidade?.status} · revisão {p.qualidade?.revision ?? "—"} · coletado em {formatDateTime(p.qualidade?.fetched_at)}
            </p>
            <ul className="bullets small">{(p.qualidade?.issues ?? []).map((i: string) => <li key={i}>{i}</li>)}</ul>
            {p.dados?.macro && (
              <>
                <h3 className="small">Contexto macro</h3>
                <dl className="kv small">
                  {Object.values(p.dados.macro).filter(Boolean).map((m: any) => (
                    <FragmentKV key={m.series_id} k={`${m.label} (${formatDate(m.reference_date)})`} v={`${m.value} ${m.unit} · ${m.validity}`} />
                  ))}
                </dl>
              </>
            )}
          </div>
          <div>
            <h3 className="small">Adequação ao seu momento</h3>
            <p className="small">{p.adequacao?.status?.replaceAll("_", " ")}</p>
            <ul className="bullets small">{(p.adequacao?.reasons ?? []).map((r: string) => <li key={r}>{r}</li>)}</ul>
            <h3 className="small">Custos e impostos considerados</h3>
            <ul className="bullets small">{(p.custos?.premissas ?? []).map((r: string) => <li key={r}>{r}</li>)}</ul>
          </div>
        </div>
        <h3 className="small">Limitações dos dados</h3>
        <ul className="bullets small">{(p.limitacoes ?? []).map((l: string) => <li key={l}>{l}</li>)}</ul>
      </Era>

      <Era known at={analysis?.created_at ?? det?.created_at} title="3. Hipótese e análise original">
        <blockquote className="radar-hypothesis">{p.hipotese?.texto}</blockquote>
        <p className="tiny muted">
          Método de avaliação: {p.hipotese?.metodo} · referência: {p.hipotese?.benchmark ?? "—"} · horizontes:{" "}
          {(p.horizontes ?? []).join(", ")} dias
        </p>
        {analysis && analysis.payload.pareceres?.length > 0 && (
          <AgentStack ids={analysis.payload.pareceres.filter((o: { status: string }) => o.status === "ok").map((o: { agent_id: string }) => o.agent_id)} />
        )}
        {!analysis && (
          <p className="small muted">
            {d.opportunity.state === "em_analise" || d.opportunity.state === "detectada"
              ? "Análise do Conselho em andamento."
              : `Conselho não acionado: ${notAnalyzedReason(d, p)}`}
          </p>
        )}
        {analysis && (
          <div className="stack">
            {analysis.payload.mentor && (
              <div className="radar-opinion">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="row">
                    <AgentAvatar id="mentor" size={32} decorative />
                    <strong>Parecer do Mentor</strong>
                  </span>
                  {analysis.payload.mentor.auditoria && (
                    <Badge tone={analysis.payload.mentor.auditoria.verdict === "PASSA" ? "good" : analysis.payload.mentor.auditoria.verdict === "REPROVA" ? "critical" : "warning"} icon="shieldCheck">
                      Auditoria: {analysis.payload.mentor.auditoria.verdict}
                    </Badge>
                  )}
                </div>
                <Markdown text={analysis.payload.mentor.texto} />
                {analysis.payload.mentor.auditoria?.reasons?.length > 0 && (
                  <ul className="bullets tiny muted">{analysis.payload.mentor.auditoria.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>
                )}
              </div>
            )}
            {(analysis.payload.pareceres ?? []).map((o: any) => (
              <details key={o.agent_id} className="radar-opinion">
                <summary className="radar-opinion-head">
                  <AgentAvatar id={o.agent_id} size={28} decorative />
                  <strong>{AGENT_NAMES[o.agent_id] ?? o.agent_id}</strong>{" "}
                  {o.auditoria && <span className="tiny muted">· auditoria {o.auditoria.verdict}</span>}
                </summary>
                <Markdown text={o.texto} />
              </details>
            ))}
            <p className="tiny muted">Execução: {RUN_LABEL[analysis.payload.run_status] ?? analysis.payload.run_status}.</p>
          </div>
        )}
      </Era>

      <Era known at={det?.created_at} title="4. Alertas e riscos registrados">
        {d.alert ? (
          <>
            <p className="small">{d.alert.title}</p>
            <ul className="list tiny">
              {d.alert.deliveries.map((x, i) => (
                <li key={i}>
                  {formatDateTime(x.at)} · {x.channel} · <strong>{x.status}</strong> {x.reason && `(${x.reason})`}
                </li>
              ))}
            </ul>
          </>
        ) : d.opportunity.redundant_of ? (
          <p className="small">
            Agrupado com um alerta semelhante recente, sem nova notificação.{" "}
            <Link to={`/oportunidades/${d.opportunity.redundant_of}`}>Ver o registro que gerou o alerta</Link>
          </p>
        ) : (
          <p className="small muted">Não virou alerta (registrado mesmo assim, para medir também o que foi descartado).</p>
        )}
      </Era>

      <Era known={false} title="5. Linha do tempo">
        <ol className="timeline">
          {d.timeline.map((t, i) => (
            <li key={i} className="timeline-item">
              <span className="mono tiny">{formatDateTime(t.at)}</span> {t.kind.replaceAll("_", " ")}
            </li>
          ))}
        </ol>
      </Era>

      <Era known={false} title="6. Evolução do ativo depois da detecção">
        {d.evolution.length < 2 ? (
          <p className="small muted">Ainda sem dados posteriores.</p>
        ) : (
          <p className="small">
            De {d.evolution[0]!.value} em {formatDate(d.evolution[0]!.reference_date)} para{" "}
            <strong>{d.evolution.at(-1)!.value}</strong> em {formatDate(d.evolution.at(-1)!.reference_date)} ({d.evolution.length} observações).
          </p>
        )}
      </Era>

      <Era known={false} title="7–8. Avaliações posteriores e comparação com a referência">
        <OutcomesTable outcomes={d.outcomes} />
      </Era>

      <Era known={false} title="9. Conclusão retrospectiva">
        <Retrospective outcomes={d.outcomes} />
        {corrections.length > 0 && (
          <>
            <h3 className="small">Correções versionadas</h3>
            <ul className="list small">
              {corrections.map((c) => (
                <li key={c.id}>
                  {formatDateTime(c.created_at)} — {c.reason}
                </li>
              ))}
            </ul>
          </>
        )}
      </Era>

      <YourSide d={d} onSaved={q.reload} />
    </div>
  );
}

const CONTEXT_LABEL: Record<string, string> = {
  vencimento: "Vencimento",
  anos_ate_vencimento: "Anos até o vencimento",
  retorno_contratado: "Retorno contratado",
  taxa_real_contratada: "Taxa real contratada",
  taxa_real_aproximada: "Taxa real aproximada",
  nota_taxa_real: "Sobre a taxa real",
};

function formatContext(key: string, value: string): string {
  if (key === "vencimento") return formatDate(value);
  if (key.startsWith("taxa_real")) return `${formatNumberBR(String(Number(value) * 100))}% a.a.`;
  if (key === "anos_ate_vencimento") return formatNumberBR(value, 1);
  return value;
}

function notAnalyzedReason(d: OpportunityDetail, p: Record<string, any>): string {
  const evaluated = d.timeline.find((t) => t.kind === "avaliada");
  return String(evaluated?.detail.motivo ?? p.analise_multiagente?.motivo ?? "não informado");
}

function FragmentKV({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt>{k.replaceAll("_", " ")}</dt>
      <dd>{v}</dd>
    </>
  );
}

function OutcomesTable({ outcomes }: { outcomes: Outcome[] }) {
  if (!outcomes.length) return <p className="small muted">Nenhuma avaliação agendada.</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Horizonte</th>
            <th>Resultado</th>
            <th className="num">Retorno</th>
            <th className="num">Referência (CDI)</th>
            <th className="num">Diferença</th>
            <th className="num">Maior queda</th>
            <th>Notas</th>
          </tr>
        </thead>
        <tbody>
          {outcomes.map((o) => {
            const r = o.result;
            const ret = r.retorno_liquido_pct ?? r.retorno_total_pct ?? (r.variacao !== undefined ? `Δ ${r.variacao}` : null);
            return (
              <tr key={o.id}>
                <td className="nowrap">
                  {o.horizon_days} dias
                  <div className="tiny muted">vence {formatDate(o.due_date)} · método v{o.method_version}</div>
                </td>
                <td><VerdictBadge v={o.verdict} /></td>
                <td className="num">{ret === null ? "—" : String(ret).startsWith("Δ") ? ret : `${formatNumberBR(ret)}%`}</td>
                <td className="num">{r.cdi_liquido_pct ?? r.cdi_bruto_pct ? `${formatNumberBR(r.cdi_liquido_pct ?? r.cdi_bruto_pct)}%` : "—"}</td>
                <td className="num">{r.excesso_vs_cdi_pp ? `${formatNumberBR(r.excesso_vs_cdi_pp)} p.p.` : "—"}</td>
                <td className="num">{r.maior_queda ? `${formatNumberBR(String(Number(r.maior_queda) * 100))}%` : "—"}</td>
                <td className="tiny muted">
                  {o.status === "pendente" ? o.last_error ?? "aguardando a data" : r.motivo ?? (r.variacao_taxa_pp ? `taxa: ${r.variacao_taxa_pp} p.p.` : "")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Retrospective({ outcomes }: { outcomes: Outcome[] }) {
  const done = outcomes.filter((o) => o.status !== "pendente");
  if (!done.length) return <p className="small muted">Nenhum horizonte venceu ainda. A conclusão é calculada, não escrita depois.</p>;
  const count = (v: Verdict) => done.filter((o) => o.verdict === v).length;
  return (
    <p className="small">
      {done.length} de {outcomes.length} horizonte(s) avaliados: {count("confirmada")} confirmado(s),{" "}
      {count("nao_confirmada")} não confirmado(s), {count("favoravel_por_outro_motivo")} favorável(is) por outro motivo,{" "}
      {count("inconclusivo") + count("dados_insuficientes")} sem conclusão, {count("invalidada")} invalidado(s). Critério: o
      registrado na detecção.
    </p>
  );
}

function YourSide({ d, onSaved }: { d: OpportunityDetail; onSaved: () => void }) {
  const app = useApp();
  const id = useId();
  const [decision, setDecision] = useState<Decision>("analisei");
  const [note, setNote] = useState("");
  const [op, setOp] = useState({ operation_date: "", direction: "entrada" as "entrada" | "saida", amount: "", unit_price: "" });
  async function run(fn: () => Promise<unknown>, msg: string) {
    try {
      await fn();
      app.toast(msg);
      onSaved();
    } catch (e) {
      app.toast(errorMessage(e), "error");
    }
  }
  return (
    <Card title="Sua decisão" eyebrow="Separado do desempenho hipotético">
      <p className="tiny muted">
        O Lastro não presume que um alerta virou compra e não executa operações. O que você registrar aqui fica à parte do
        resultado hipotético da oportunidade.
      </p>
      {d.decisions.length > 0 && (
        <ul className="list small">
          {d.decisions.map((x) => (
            <li key={x.id}>
              {formatDateTime(x.created_at)} — <strong>{DECISION_LABEL[x.decision]}</strong> {x.note && `· ${x.note}`}
            </li>
          ))}
        </ul>
      )}
      <form
        className="form-grid"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void run(() => addDecision(d.opportunity.id, decision, note), "Decisão registrada.");
          setNote("");
        }}
      >
        <Field label="Decisão" htmlFor={`${id}-d`}>
          <select id={`${id}-d`} className="select" value={decision} onChange={(e) => setDecision(e.target.value as Decision)}>
            {Object.entries(DECISION_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="Nota (opcional)" htmlFor={`${id}-n`}>
          <input id={`${id}-n`} className="input" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="row" style={{ alignSelf: "end" }}>
          <button type="submit" className="btn btn-secondary btn-sm">Registrar decisão</button>
        </div>
      </form>
      <details>
        <summary className="small">Informar uma operação que você fez por conta própria</summary>
        {d.operations.length > 0 && (
          <ul className="list small">
            {d.operations.map((o) => (
              <li key={o.id}>
                {formatDate(o.operation_date)} · {o.direction} · R$ {formatNumberBR(o.amount)} {o.unit_price && `a ${formatNumberBR(o.unit_price)}`}
              </li>
            ))}
          </ul>
        )}
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => addOperation(d.opportunity.id, { ...op, amount: op.amount.replace(",", "."), unit_price: op.unit_price.replace(",", ".") || undefined }), "Operação registrada.");
          }}
        >
          <Field label="Data" htmlFor={`${id}-od`}>
            <DateInput id={`${id}-od`} required value={op.operation_date} onChange={(e) => setOp({ ...op, operation_date: e.target.value })} />
          </Field>
          <Field label="Sentido" htmlFor={`${id}-os`}>
            <select id={`${id}-os`} className="select" value={op.direction} onChange={(e) => setOp({ ...op, direction: e.target.value as "entrada" | "saida" })}>
              <option value="entrada">Apliquei</option>
              <option value="saida">Resgatei</option>
            </select>
          </Field>
          <Field label="Valor (R$)" htmlFor={`${id}-ov`}>
            <input id={`${id}-ov`} className="input" inputMode="decimal" required value={op.amount} onChange={(e) => setOp({ ...op, amount: e.target.value })} />
          </Field>
          <Field label="Preço unitário (opcional)" htmlFor={`${id}-op`}>
            <input id={`${id}-op`} className="input" inputMode="decimal" value={op.unit_price} onChange={(e) => setOp({ ...op, unit_price: e.target.value })} />
          </Field>
          <div className="row" style={{ alignSelf: "end" }}>
            <button type="submit" className="btn btn-ghost btn-sm">Registrar operação</button>
          </div>
        </form>
      </details>
      {d.links.length > 0 && (
        <>
          <div className="divider" />
          <h3 className="small">Conversas ligadas a esta oportunidade</h3>
          <ul className="list small">
            {d.links.map((l) => (
              <li key={l.conversation_id}>
                <Link to={`/mentor/${l.conversation_id}`}>{l.title}</Link> <span className="tiny muted">· {l.purpose} · {formatDateTime(l.created_at)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
