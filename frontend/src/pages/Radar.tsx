import { useId, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  addAsset,
  addAssetObservation,
  addCorporateEvent,
  backtestRule,
  CATEGORY,
  createRule,
  decideProposal,
  getAlerts,
  getOverview,
  getProposals,
  getRules,
  getSeries,
  KIND_LABEL,
  muteAlert,
  PRIORITY,
  runTick,
  savePrefs,
  setAlertFeedback,
  setAlertStatus,
  setChannel,
  setRuleStatus,
  type Alert,
  type BacktestResult,
  type Category,
  type Rule,
  type RuleInput,
  type RuleKind,
  type SeriesItem,
} from "../api/radar";
import { AgentAvatar } from "../components/AgentAvatar";
import { Icon } from "../components/Icon";
import { Badge, Card, EmptyState, ErrorNotice, Field, Loading, Notice, PageHeader, Segmented, Tag } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDate, formatDateTime } from "../lib/dates";
import { formatNumberBR } from "../lib/money";
import { errorMessage, useAsync } from "../lib/useAsync";
import "../styles/radar.css";
import { DateInput } from "../components/DateInput";

type Tab = "monitoramento" | "alertas" | "regras" | "ativos";
const TABS: { value: Tab; label: string }[] = [
  { value: "monitoramento", label: "Monitoramento" },
  { value: "alertas", label: "Alertas" },
  { value: "regras", label: "Regras" },
  { value: "ativos", label: "Ativos" },
];

export function RadarPage() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.value === params.get("aba"))?.value ?? "monitoramento") as Tab;
  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Lastro Radar"
        title="O que mudou no mercado, e se importa para você"
        lede="Regras determinísticas observam fontes oficiais; o Conselho só é chamado quando a análise acrescenta algo. Cada sinal é uma hipótese registrada no Diário, nunca uma ordem."
        actions={
          <Link className="btn btn-ghost btn-sm" to="/oportunidades">
            <Icon name="book" />
            Diário de oportunidades
          </Link>
        }
      />
      <Segmented label="Seção do Radar" variant="mono" options={TABS} value={tab} onChange={(v) => setParams({ aba: v })} />
      {tab === "monitoramento" && <Monitoring />}
      {tab === "alertas" && <Alerts />}
      {tab === "regras" && <Rules />}
      {tab === "ativos" && <Assets />}
    </div>
  );
}

// ---------------------------------------------------------------- Monitoramento

function Monitoring() {
  const app = useApp();
  const ov = useAsync(getOverview, []);
  const [busy, setBusy] = useState(false);
  const o = ov.data;
  if (ov.loading && !o) return <Loading />;
  if (!o) return <ErrorNotice error={ov.error} onRetry={ov.reload} />;
  const sourceRows = Object.entries(o.series_by_source).map(([source, count]) => {
    const file = o.sources.find((s) => s.source === source);
    const per = o.series_status.filter((s) => s.source === source);
    const failing = per.filter((s) => !s.ok);
    return { source, count, file, per, failing };
  });

  async function tick() {
    setBusy(true);
    try {
      const r = await runTick();
      app.toast(`Verificação feita: ${String(r.sinais ?? 0)} sinal(is) novo(s).`);
      await ov.reload();
    } catch (e) {
      app.toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack-lg">
      <Notice tone="info" title="Sem cotação em tempo real.">
        Os dados vêm de fontes públicas com atraso de publicação (Tesouro: uma vez por dia; Banco Central e IBGE: conforme
        divulgação). O Radar nunca apresenta esses valores como tempo real.
      </Notice>
      <div className="grid">
        <div className="card stat-card">
          <div className="stat-label">Alertas novos</div>
          <div className="stat-value num">{o.unread_alerts}</div>
          <div className="stat-sub">
            <Link to="/radar?aba=alertas">Ver alertas</Link>
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Regras ativas</div>
          <div className="stat-value num">{o.rules}</div>
          <div className="stat-sub">
            <Link to="/radar?aba=regras">Ver e criar regras</Link>
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Séries observadas</div>
          <div className="stat-value num">{Object.values(o.series_by_source).reduce((a, b) => a + b, 0)}</div>
          <div className="stat-sub">{Object.keys(o.series_by_source).length} fonte(s)</div>
        </div>
      </div>

      <Card
        title="Fontes"
        eyebrow="Coleta"
        aside={
          <button type="button" className="btn btn-secondary btn-sm" onClick={tick} disabled={busy}>
            <Icon name="refresh" />
            {busy ? "Verificando…" : "Verificar regras agora"}
          </button>
        }
        footer={
          <span className="tiny muted">
            Não conectadas (exigem licença ou credencial, nunca simuladas): {o.not_connected.join(" · ")}
          </span>
        }
      >
        {sourceRows.length === 0 ? (
          <EmptyState title="Nenhuma coleta ainda" icon="pulse">
            O serviço lastro-coletor ainda não gravou dados. Depois da primeira coleta, as fontes aparecem aqui.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Fonte</th>
                  <th className="num">Séries</th>
                  <th>Última verificação</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {sourceRows.map((r) => {
                  const checked = r.file?.checked_at ?? r.per.map((p) => p.checked_at).sort().at(-1);
                  const error = r.file && !r.file.ok ? r.file.error : r.failing.length ? `${r.failing.length} série(s) com falha` : null;
                  return (
                    <tr key={r.source}>
                      <td>{o.source_names[r.source] ?? r.source}</td>
                      <td className="num">{r.count}</td>
                      <td>{checked ? formatDateTime(checked) : "—"}</td>
                      <td>
                        {error ? <Badge tone="warning">{error}</Badge> : <Badge tone="good">ok</Badge>}
                        {r.file?.next_at && <div className="tiny muted">próxima: {formatDateTime(r.file.next_at)}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <PrefsCard prefs={o.prefs} channels={o.channels} onSaved={ov.reload} />
    </div>
  );
}

function PrefsCard({ prefs, channels, onSaved }: { prefs: import("../api/radar").Prefs; channels: import("../api/radar").Channel[]; onSaved: () => void }) {
  const app = useApp();
  const id = useId();
  const [p, setP] = useState(prefs);
  const [saving, setSaving] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await savePrefs(p);
      app.toast("Preferências salvas.");
      onSaved();
    } catch (err) {
      app.toast(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }
  async function toggle(channel: string, enabled: boolean) {
    const consent = enabled
      ? window.confirm(
          "Ativar este canal autoriza o Lastro a enviar resumos dos alertas para fora do aplicativo quando o transporte estiver configurado. Confirma?",
        )
      : false;
    if (enabled && !consent) return;
    try {
      await setChannel(channel, enabled, consent);
      onSaved();
    } catch (err) {
      app.toast(errorMessage(err), "error");
    }
  }
  const num = (k: keyof typeof p) => (e: React.ChangeEvent<HTMLInputElement>) => setP({ ...p, [k]: Number(e.target.value) });
  return (
    <Card title="Notificações" eyebrow="Preferências">
      <form className="stack" onSubmit={save}>
        <div className="form-grid">
          <Field label="Alertar a partir de" htmlFor={`${id}-min`} help="Alertas de risco (5) sempre aparecem.">
            <select id={`${id}-min`} className="select" value={p.min_priority} onChange={(e) => setP({ ...p, min_priority: Number(e.target.value) })}>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} — {PRIORITY[n]?.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Máximo de notificações por dia" htmlFor={`${id}-max`}>
            <input id={`${id}-max`} className="input" type="number" min={0} max={100} value={p.max_per_day} onChange={num("max_per_day")} />
          </Field>
          <Field label="Intervalo para agrupar alertas iguais (horas)" htmlFor={`${id}-cd`}>
            <input id={`${id}-cd`} className="input" type="number" min={0} max={1440} value={p.cooldown_hours} onChange={num("cooldown_hours")} />
          </Field>
          <Field label="Análises do Conselho por dia" htmlFor={`${id}-an`} help="Limita o uso do modelo.">
            <input id={`${id}-an`} className="input" type="number" min={0} max={50} value={p.max_analyses_per_day} onChange={num("max_analyses_per_day")} />
          </Field>
          <Field label="Silêncio a partir de" htmlFor={`${id}-qs`}>
            <input id={`${id}-qs`} className="input" type="time" value={p.quiet_start} onChange={(e) => setP({ ...p, quiet_start: e.target.value })} />
          </Field>
          <Field label="Silêncio até" htmlFor={`${id}-qe`}>
            <input id={`${id}-qe`} className="input" type="time" value={p.quiet_end} onChange={(e) => setP({ ...p, quiet_end: e.target.value })} />
          </Field>
        </div>
        <div className="row">
          <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
            Salvar preferências
          </button>
        </div>
      </form>
      <div className="divider" />
      <h3 className="small">Canais fora do Lastro</h3>
      <p className="tiny muted">
        Os alertas sempre ficam aqui no Lastro. Canais externos exigem seu consentimento e um transporte configurado no
        servidor; enquanto não houver, a entrega fica registrada como “não configurado”, nunca como enviada.
      </p>
      <ul className="list">
        {channels.map((c) => (
          <li key={c.channel} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {{ email: "E-mail", telegram: "Telegram", webpush: "Notificação push (PWA)" }[c.channel]}{" "}
              {!c.transport_ready && <Tag>transporte não configurado</Tag>}
              {c.consent_at && <span className="tiny muted"> · consentimento em {formatDateTime(c.consent_at)}</span>}
            </span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => toggle(c.channel, !c.enabled)} aria-pressed={c.enabled}>
              {c.enabled ? "Desativar" : "Ativar"}
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ---------------------------------------------------------------- Alertas

export function PriorityBadge({ level }: { level: number }) {
  const p = PRIORITY[level] ?? { label: "Informativo", tone: "neutral" as const };
  return (
    <Badge tone={p.tone} icon={level === 5 ? "alert" : level >= 3 ? "pulse" : "info"}>
      {level} · {p.label}
    </Badge>
  );
}

function Alerts() {
  const app = useApp();
  const [filter, setFilter] = useState<"" | "novo" | "analisado">("");
  const list = useAsync(() => getAlerts(filter || undefined), [filter]);

  async function act(fn: () => Promise<unknown>, msg: string) {
    try {
      await fn();
      app.toast(msg);
      await list.reload();
    } catch (e) {
      app.toast(errorMessage(e), "error");
    }
  }

  return (
    <div className="stack">
      <Segmented
        label="Filtrar alertas"
        options={[
          { value: "", label: "Todos" },
          { value: "novo", label: "Novos" },
          { value: "analisado", label: "Analisados" },
        ]}
        value={filter}
        onChange={setFilter}
      />
      {list.loading && !list.data && <Loading />}
      <ErrorNotice error={list.error} onRetry={list.reload} />
      {list.data?.length === 0 && (
        <EmptyState title="Nenhum alerta" icon="pulse">
          Quando uma regra encontrar algo relevante, o alerta aparece aqui com a fundamentação, os riscos e o parecer do
          Conselho.
        </EmptyState>
      )}
      {list.data?.map((a) => <AlertCard key={a.id} alert={a} act={act} />)}
    </div>
  );
}

function AlertCard({ alert: a, act }: { alert: Alert; act: (fn: () => Promise<unknown>, msg: string) => void }) {
  return (
    <article className={`card radar-alert p${a.priority} ${a.status === "novo" ? "is-new" : ""}`}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <PriorityBadge level={a.priority} />
          <Tag>{CATEGORY[a.category]}</Tag>
          {a.occurrences > 1 && <Tag>{a.occurrences} ocorrências</Tag>}
          {a.status === "novo" && <span className="unread-dot" role="img" aria-label="novo" />}
        </div>
        <span className="tiny muted">{formatDateTime(a.created_at)}</span>
      </div>
      <h3 className="radar-alert-title">
        <Link to={`/oportunidades/${a.opportunity_id}`}>{a.asset_label}</Link>
      </h3>
      <p className="small">{a.condition_text}</p>
      <p className="tiny muted">Dado de referência: {formatDate(a.reference_date)} · estado: {a.state.replaceAll("_", " ")}</p>
      {a.agents.length > 0 && <AgentStack ids={a.agents} />}
      <div className="row">
        <Link className="btn btn-primary btn-sm" to={`/oportunidades/${a.opportunity_id}`}>
          Abrir análise
        </Link>
        {a.status !== "analisado" && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(() => setAlertStatus(a.id, "analisado"), "Marcado como analisado.")}>
            <Icon name="check" />
            Marcar como analisado
          </button>
        )}
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          aria-pressed={a.feedback === "util"}
          onClick={() => act(() => setAlertFeedback(a.id, "util"), "Obrigado: conta para as métricas.")}
        >
          Útil
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          aria-pressed={a.feedback === "irrelevante"}
          onClick={() => act(() => setAlertFeedback(a.id, "irrelevante"), "Anotado como irrelevante.")}
        >
          Irrelevante
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => act(() => muteAlert(a.id, 30), "Semelhantes silenciados por 30 dias.")}>
          <Icon name="ban" />
          Silenciar semelhantes
        </button>
      </div>
    </article>
  );
}

/** Quem do Conselho analisou: mascotes lado a lado, com os nomes para leitores de tela. */
export function AgentStack({ ids, size = 24 }: { ids: string[]; size?: number }) {
  return (
    <span className="radar-agents">
      <span className="tiny muted">Analisado por</span>
      {ids.map((id) => (
        <AgentAvatar key={id} id={id} size={size} />
      ))}
      <span className="mascot-mentor-tail">
        <AgentAvatar id="mentor" size={size} />
        <AgentAvatar id="auditor" size={size} />
      </span>
    </span>
  );
}

// ---------------------------------------------------------------- Regras

function describe(r: Rule): string {
  const p = r.params;
  switch (r.kind) {
    case "limite":
      return `${p.operador} ${formatNumberBR(String(p.valor))}`;
    case "variacao":
      return `${p.direcao === "alta" ? "alta" : p.direcao === "baixa" ? "queda" : "variação"} ≥ ${formatNumberBR(String(p.minimo))} ${
        p.unidade === "pp" ? "p.p." : "%"
      } em ${p.janela_dias} dias`;
    case "queda":
      return `queda ≥ ${formatNumberBR(String(p.queda_minima_pct))}% em ${p.janela_dias} dias`;
    case "reserva":
      return `abaixo de ${formatNumberBR(String(p.meses_minimos), 1)} meses`;
    default:
      return "série sem dado recente";
  }
}

function Rules() {
  const app = useApp();
  const rules = useAsync(getRules, []);
  const proposals = useAsync(getProposals, []);
  const [creating, setCreating] = useState(false);
  const [bt, setBt] = useState<Record<string, BacktestResult | "loading" | string>>({});

  async function status(r: Rule, s: Rule["status"]) {
    try {
      await setRuleStatus(r.id, s);
      await rules.reload();
    } catch (e) {
      app.toast(errorMessage(e), "error");
    }
  }
  async function test(r: Rule) {
    setBt((b) => ({ ...b, [r.id]: "loading" }));
    try {
      const res = await backtestRule(r.id);
      setBt((b) => ({ ...b, [r.id]: res }));
    } catch (e) {
      setBt((b) => ({ ...b, [r.id]: errorMessage(e) }));
    }
  }

  return (
    <div className="stack-lg">
      {(proposals.data ?? []).filter((p) => p.status === "pendente").length > 0 && (
        <Card title="Propostas de ajuste" eyebrow="Aprendizado controlado">
          <p className="tiny muted">Geradas a partir dos resultados com amostra mínima. Nada muda sem a sua aprovação.</p>
          <ul className="list">
            {proposals.data!
              .filter((p) => p.status === "pendente")
              .map((p) => (
                <li key={p.id} className="stack">
                  <div>
                    <strong>{rules.data?.find((r) => r.id === p.rule_id)?.name ?? p.rule_id}</strong>: {p.rationale.motivo}
                  </div>
                  <code className="tiny">{JSON.stringify(p.change)}</code>
                  <div className="row">
                    <button type="button" className="btn btn-primary btn-sm" onClick={async () => { await decideProposal(p.id, "approve"); await Promise.all([proposals.reload(), rules.reload()]); }}>
                      Aprovar (nova versão da regra)
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={async () => { await decideProposal(p.id, "reject"); await proposals.reload(); }}>
                      Recusar
                    </button>
                  </div>
                </li>
              ))}
          </ul>
        </Card>
      )}
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="small muted" style={{ margin: 0 }}>
          Cada alteração cria uma nova versão; o sinal guarda a versão que o disparou.
        </p>
        {!creating && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
            <Icon name="plus" />
            Nova regra
          </button>
        )}
      </div>
      {creating && (
        <RuleForm
          onCancel={() => setCreating(false)}
          onSaved={async () => {
            setCreating(false);
            await rules.reload();
          }}
        />
      )}
      {rules.loading && !rules.data && <Loading />}
      <ErrorNotice error={rules.error} onRetry={rules.reload} />
      <div className="stack">
        {rules.data?.map((r) => {
          const res = bt[r.id];
          return (
            <article key={r.id} className={`card radar-rule ${r.status !== "ativa" ? "is-off" : ""}`}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="row">
                  <PriorityBadge level={r.priority} />
                  <Tag>{CATEGORY[r.category]}</Tag>
                  <Tag>
                    v{r.version} · {r.origin}
                  </Tag>
                </div>
                <Badge tone={r.status === "ativa" ? "good" : "neutral"} icon={r.status === "ativa" ? "check" : "pause"}>
                  {r.status}
                </Badge>
              </div>
              <h3 className="radar-alert-title">{r.name}</h3>
              <p className="small">
                {KIND_LABEL[r.kind]}: {describe(r)}
                {r.series_pattern && (
                  <>
                    {" "}
                    · <span className="mono tiny">{r.series_pattern}</span>
                  </>
                )}
              </p>
              <p className="tiny muted">
                A cada {r.interval_minutes >= 60 ? `${r.interval_minutes / 60} h` : `${r.interval_minutes} min`} · horizontes{" "}
                {r.horizons.join(", ")} dias
                {r.state?.last_evaluated_at && ` · última avaliação ${formatDateTime(r.state.last_evaluated_at)} (${r.state.last_result})`}
              </p>
              <div className="row">
                {r.status === "ativa" ? (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => status(r, "pausada")}>
                    <Icon name="pause" />
                    Pausar
                  </button>
                ) : (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => status(r, "ativa")}>
                    <Icon name="play" />
                    Ativar
                  </button>
                )}
                {["limite", "variacao", "queda"].includes(r.kind) && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => test(r)} disabled={res === "loading"}>
                    <Icon name="clock" />
                    {res === "loading" ? "Testando…" : "Testar no histórico"}
                  </button>
                )}
              </div>
              {typeof res === "string" && res !== "loading" && <Notice tone="error">{res}</Notice>}
              {res && typeof res === "object" && <BacktestView r={res} />}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function rate(v: string | null) {
  return v === null ? "—" : `${formatNumberBR(String(Number(v) * 100), 0)}%`;
}

function BacktestView({ r }: { r: BacktestResult }) {
  return (
    <div className="radar-later stack">
      <div className="eyebrow">Resultado simulado · não é desempenho real</div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Trecho</th>
              <th className="num">Sinais</th>
              <th className="num">Avaliáveis</th>
              <th className="num">Confirmação</th>
              <th className="num">Excesso médio vs CDI</th>
            </tr>
          </thead>
          <tbody>
            {[
              { k: `Dentro da amostra (até ${formatDate(r.dentro_da_amostra.ate)})`, b: r.dentro_da_amostra },
              { k: `Fora da amostra (depois de ${formatDate(r.fora_da_amostra.de)})`, b: r.fora_da_amostra },
              ...r.segmentos.map((s) => ({ k: `${formatDate(s.de)} – ${formatDate(s.ate)}`, b: s })),
            ].map(({ k, b }) => (
              <tr key={k}>
                <td>{k}</td>
                <td className="num">{b.sinais}</td>
                <td className="num">{b.avaliaveis}</td>
                <td className="num">{rate(b.taxa_confirmacao)}</td>
                <td className="num">{b.excesso_medio_vs_cdi_pp === null ? "—" : `${formatNumberBR(b.excesso_medio_vs_cdi_pp)} p.p.`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="bullets tiny muted">
        {r.limitacoes.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  );
}

const KIND_DEFAULT: Record<RuleKind, Record<string, string>> = {
  limite: { operador: ">=", valor: "", tolerancia: "0.5" },
  variacao: { janela_dias: "30", minimo: "", unidade: "pp", direcao: "qualquer" },
  queda: { janela_dias: "60", queda_minima_pct: "" },
  reserva: { meses_minimos: "3" },
  dado_desatualizado: {},
};

function RuleForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => void }) {
  const app = useApp();
  const id = useId();
  const series = useAsync(() => getSeries(), []);
  const [draft, setDraft] = useState<RuleInput>({
    name: "",
    kind: "limite",
    category: "renda_fixa",
    series_pattern: "",
    params: { ...KIND_DEFAULT.limite },
    priority: 3,
    interval_minutes: 360,
    horizons: [7, 30, 90, 180, 365],
    status: "ativa",
    note: "",
  });
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<RuleInput>) => setDraft((d) => ({ ...d, ...patch }));
  const param = (k: string, v: string) => setDraft((d) => ({ ...d, params: { ...d.params, [k]: v } }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createRule({ ...draft, params: Object.fromEntries(Object.entries(draft.params).map(([k, v]) => [k, String(v).replace(",", ".")])) });
      app.toast("Regra criada.");
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Card title="Nova regra" eyebrow="Radar">
      <form className="stack" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Nome" htmlFor={`${id}-n`}>
            <input id={`${id}-n`} className="input" required minLength={3} maxLength={120} value={draft.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label="Tipo" htmlFor={`${id}-k`}>
            <select
              id={`${id}-k`}
              className="select"
              value={draft.kind}
              onChange={(e) => {
                const kind = e.target.value as RuleKind;
                set({ kind, params: { ...KIND_DEFAULT[kind] }, category: kind === "reserva" ? "patrimonio" : draft.category });
              }}
            >
              {Object.entries(KIND_LABEL).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Categoria" htmlFor={`${id}-c`}>
            <select id={`${id}-c`} className="select" value={draft.category} onChange={(e) => set({ category: e.target.value as Category })}>
              {Object.entries(CATEGORY).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          {draft.kind !== "reserva" && (
            <Field label="Série (ou padrão com *)" htmlFor={`${id}-s`} help="Ex.: td_ipca_*_taxa_compra para todos os Tesouro IPCA+.">
              <input id={`${id}-s`} className="input mono" list={`${id}-sl`} required value={draft.series_pattern} onChange={(e) => set({ series_pattern: e.target.value.trim() })} />
              <datalist id={`${id}-sl`}>
                {series.data?.map((s) => (
                  <option key={s.series_id} value={s.series_id}>
                    {s.label}
                  </option>
                ))}
              </datalist>
            </Field>
          )}
          {Object.keys(draft.params).map((k) => (
            <Field key={k} label={k.replaceAll("_", " ")} htmlFor={`${id}-p-${k}`}>
              {k === "operador" ? (
                <select id={`${id}-p-${k}`} className="select" value={String(draft.params[k])} onChange={(e) => param(k, e.target.value)}>
                  <option value=">=">maior ou igual a</option>
                  <option value="<=">menor ou igual a</option>
                </select>
              ) : k === "unidade" ? (
                <select id={`${id}-p-${k}`} className="select" value={String(draft.params[k])} onChange={(e) => param(k, e.target.value)}>
                  <option value="pp">pontos (p.p.)</option>
                  <option value="pct">percentual (%)</option>
                </select>
              ) : k === "direcao" ? (
                <select id={`${id}-p-${k}`} className="select" value={String(draft.params[k])} onChange={(e) => param(k, e.target.value)}>
                  <option value="qualquer">qualquer</option>
                  <option value="alta">alta</option>
                  <option value="baixa">baixa</option>
                </select>
              ) : (
                <input id={`${id}-p-${k}`} className="input" inputMode="decimal" required value={String(draft.params[k])} onChange={(e) => param(k, e.target.value)} />
              )}
            </Field>
          ))}
          <Field label="Prioridade" htmlFor={`${id}-pr`}>
            <select id={`${id}-pr`} className="select" value={draft.priority} onChange={(e) => set({ priority: Number(e.target.value) })}>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} — {PRIORITY[n]?.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Horizontes de avaliação (dias)" htmlFor={`${id}-h`}>
            <input
              id={`${id}-h`}
              className="input"
              value={draft.horizons.join(", ")}
              onChange={(e) => set({ horizons: e.target.value.split(/[ ,;]+/).map(Number).filter((n) => n > 0) })}
            />
          </Field>
        </div>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary btn-sm">
            Criar regra
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- Ativos

function Assets() {
  const [cat, setCat] = useState<"renda_fixa" | "macro" | "pessoa">("renda_fixa");
  const series = useAsync(() => getSeries(), []);
  const items = (series.data ?? []).filter((s) => (cat === "pessoa" ? s.source === "pessoa" : s.category === cat && s.source !== "pessoa"));
  return (
    <div className="stack">
      <Segmented
        label="Grupo de ativos"
        options={[
          { value: "renda_fixa", label: "Tesouro Direto" },
          { value: "macro", label: "Indicadores" },
          { value: "pessoa", label: "Ações, ETFs e FIIs" },
        ]}
        value={cat}
        onChange={setCat}
      />
      {cat === "pessoa" && (
        <>
          <Notice tone="warning" title="Sem fonte licenciada de cotações.">
            O Lastro não tem acesso autorizado às cotações da B3. Para acompanhar ações, ETFs e FIIs, informe você mesmo
            preços, proventos e eventos corporativos; o Diário registra que a fonte foi você.
          </Notice>
          <UserAssetForms series={series.data ?? []} onSaved={series.reload} />
        </>
      )}
      {series.loading && !series.data && <Loading />}
      <ErrorNotice error={series.error} onRetry={series.reload} />
      {series.data && items.length === 0 && <EmptyState title="Nada por aqui ainda" icon="pulse" />}
      {items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Ativo ou indicador</th>
                <th className="num">Último valor</th>
                <th>Referência</th>
                <th>Validade</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <SeriesRow key={s.series_id} s={s} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SeriesRow({ s }: { s: SeriesItem }) {
  return (
    <tr>
      <td>
        {s.label}
        <div className="tiny muted mono">{s.series_id}</div>
      </td>
      <td className="num">{s.last ? `${formatNumberBR(s.last.value, s.unit === "R$" ? 2 : 2)} ${s.unit}` : "—"}</td>
      <td>{s.last ? formatDate(s.last.reference_date) : "—"}</td>
      <td>
        <Badge tone={s.validity === "valido" ? "good" : s.validity === "desatualizado" ? "warning" : "neutral"}>{s.validity}</Badge>
        {s.last?.quality === "suspeito" && <Badge tone="warning">diverge de outra fonte</Badge>}
      </td>
    </tr>
  );
}

function UserAssetForms({ series, onSaved }: { series: SeriesItem[]; onSaved: () => void }) {
  const app = useApp();
  const id = useId();
  const mine = series.filter((s) => s.source === "pessoa");
  const [ticker, setTicker] = useState("");
  const [kind, setKind] = useState<"acoes" | "etf" | "fii">("acoes");
  const [target, setTarget] = useState("");
  const [obs, setObs] = useState({ reference_date: "", value: "", kind: "preco" as "preco" | "provento" });
  const [ev, setEv] = useState({ ex_date: "", kind: "desdobramento", factor: "" });

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
    <div className="grid-2">
      <Card title="Acompanhar um ativo" eyebrow="Informado por você">
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => addAsset(ticker, kind), "Ativo adicionado.");
          }}
        >
          <div className="form-grid">
            <Field label="Código" htmlFor={`${id}-t`}>
              <input id={`${id}-t`} className="input mono" required value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="PETR4" />
            </Field>
            <Field label="Tipo" htmlFor={`${id}-k`}>
              <select id={`${id}-k`} className="select" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                <option value="acoes">Ação</option>
                <option value="etf">ETF</option>
                <option value="fii">FII</option>
              </select>
            </Field>
          </div>
          <button type="submit" className="btn btn-secondary btn-sm">
            Adicionar
          </button>
        </form>
      </Card>
      {mine.length > 0 && (
        <Card title="Registrar preço, provento ou evento" eyebrow="Informado por você">
          <div className="stack">
            <Field label="Ativo" htmlFor={`${id}-a`}>
              <select id={`${id}-a`} className="select" value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">Escolha…</option>
                {mine.map((s) => (
                  <option key={s.series_id} value={s.series_id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
            <form
              className="form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                void run(() => addAssetObservation(target, { ...obs, value: obs.value.replace(",", ".") }), "Registrado.");
              }}
            >
              <Field label="Data" htmlFor={`${id}-od`}>
                <DateInput id={`${id}-od`} required value={obs.reference_date} onChange={(e) => setObs({ ...obs, reference_date: e.target.value })} />
              </Field>
              <Field label="Valor (R$)" htmlFor={`${id}-ov`}>
                <input id={`${id}-ov`} className="input" inputMode="decimal" required value={obs.value} onChange={(e) => setObs({ ...obs, value: e.target.value })} />
              </Field>
              <Field label="O que é" htmlFor={`${id}-ok`}>
                <select id={`${id}-ok`} className="select" value={obs.kind} onChange={(e) => setObs({ ...obs, kind: e.target.value as "preco" | "provento" })}>
                  <option value="preco">Preço de fechamento</option>
                  <option value="provento">Provento por cota</option>
                </select>
              </Field>
              <button type="submit" className="btn btn-secondary btn-sm" disabled={!target}>
                Registrar valor
              </button>
            </form>
            <form
              className="form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                void run(() => addCorporateEvent(target, { ...ev, factor: ev.factor.replace(",", ".") }), "Evento registrado.");
              }}
            >
              <Field label="Data ex" htmlFor={`${id}-ed`}>
                <DateInput id={`${id}-ed`} required value={ev.ex_date} onChange={(e) => setEv({ ...ev, ex_date: e.target.value })} />
              </Field>
              <Field label="Evento" htmlFor={`${id}-ek`}>
                <select id={`${id}-ek`} className="select" value={ev.kind} onChange={(e) => setEv({ ...ev, kind: e.target.value })}>
                  <option value="desdobramento">Desdobramento</option>
                  <option value="grupamento">Grupamento</option>
                  <option value="bonificacao">Bonificação</option>
                </select>
              </Field>
              <Field label="Fator (ações depois ÷ antes)" htmlFor={`${id}-ef`} help="Desdobramento 1:2 = 2; grupamento 10:1 = 0,1.">
                <input id={`${id}-ef`} className="input" inputMode="decimal" required value={ev.factor} onChange={(e) => setEv({ ...ev, factor: e.target.value })} />
              </Field>
              <button type="submit" className="btn btn-secondary btn-sm" disabled={!target}>
                Registrar evento
              </button>
            </form>
          </div>
        </Card>
      )}
    </div>
  );
}
