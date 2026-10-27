// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { getAssumptions, getLatestSnapshot, postProjection, putAssumptions } from "../api/endpoints";
import type { AssumptionsResponse, Projection, ProjectionRequest, Scenario } from "../api/types";
import { Icon } from "../components/Icon";
import { compactTick, Legend, LineChart } from "../components/LineChart";
import {
  Badge,
  Card,
  CopyButton,
  Disclaimer,
  EmptyState,
  ErrorNotice,
  Field,
  Loading,
  MoneyField,
  Notice,
  PageHeader,
  Tag,
  parseFields,
} from "../components/ui";
import { useApp } from "../lib/appContext";
import { decimalToInputBRL, formatBRL, formatPct, fractionToPercentInput, toChartNumber } from "../lib/money";
import { errorMessage, useAsync } from "../lib/useAsync";

const MAX_MONTHS = 960;

function formatMonth(m: number): string {
  const mm = Math.round(m);
  if (mm === 0) return "hoje";
  if (mm < 12) return `${mm} ${mm === 1 ? "mês" : "meses"}`;
  const y = Math.floor(mm / 12);
  const r = mm % 12;
  return r === 0 ? `${y} ${y === 1 ? "ano" : "anos"}` : `${y}a ${r}m`;
}

const snapYear = (m: number) => (m >= 12 ? Math.round(m / 12) * 12 : m);

/** "13-18, 30" → [13..18, 30]. */
export function parsePausedMonths(text: string, max: number): { ok: true; value: number[] } | { ok: false; error: string } {
  const out = new Set<number>();
  const parts = text.split(/[,;\s]+/).filter(Boolean);
  for (const p of parts) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(p);
    if (!m) return { ok: false, error: `Pausa inválida: "${p}". Use números de meses, como 13-18, 30.` };
    const a = Number(m[1]);
    const b = m[2] ? Number(m[2]) : a;
    if (a < 1 || b < a || b > max) return { ok: false, error: `Meses de pausa devem estar entre 1 e ${max}.` };
    for (let i = a; i <= b; i++) out.add(i);
  }
  return { ok: true, value: [...out].sort((x, y) => x - y) };
}

export function FuturePage() {
  const app = useApp();
  const assumptions = useAsync(getAssumptions, []);
  const latest = useAsync(getLatestSnapshot, []);

  const [initial, setInitial] = useState("0");
  const [contribution, setContribution] = useState("");
  const [months, setMonths] = useState(240);
  const [increase, setIncrease] = useState("");
  const [paused, setPaused] = useState("");
  const [result, setResult] = useState<Projection[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRequest, setLastRequest] = useState<ProjectionRequest | null>(null);
  const monthsId = useId();
  const pausedId = useId();

  async function run(req: ProjectionRequest) {
    setRunning(true);
    setError(null);
    try {
      const r = await postProjection(req);
      setResult(r.projections);
      setLastRequest(req);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRunning(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const p = parseFields({
      initial: { text: initial, kind: "money", label: "Valor inicial", required: true },
      contribution: { text: contribution, kind: "money", label: "Aporte mensal", required: true },
      increase: { text: increase, kind: "percent", label: "Reajuste anual do aporte" },
    });
    if (!p.ok) return setError(p.error);
    const pm = paused.trim() ? parsePausedMonths(paused, months) : { ok: true as const, value: [] };
    if (!pm.ok) return setError(pm.error);
    const req: ProjectionRequest = {
      initial: p.values.initial!,
      contribution: p.values.contribution!,
      months,
      include_path: true,
    };
    if (p.values.increase) req.contribution_annual_increase = p.values.increase;
    if (pm.value.length) req.paused_months = pm.value;
    void run(req);
  }

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Meu futuro"
        title="Simulação de patrimônio"
        lede="Três cenários lado a lado, a partir das premissas que você controla. É uma simulação determinística, não uma previsão: o futuro real será diferente."
      />

      <Card title="Parâmetros da simulação" eyebrow="Seu plano">
        <form onSubmit={submit} noValidate className="stack">
          <div className="form-grid">
            <MoneyField label="Valor inicial" value={initial} onChange={setInitial} required
              help="Quanto você já tem guardado para este plano." />
            <MoneyField label="Aporte mensal" value={contribution} onChange={setContribution} required
              help="Quanto pretende depositar por mês, no fim de cada mês." />
            <MoneyField kind="percent" optional label="Reajuste anual do aporte" value={increase} onChange={setIncrease}
              help="Ex.: 5 se o aporte crescer 5% a cada ano." />
          </div>
          <Field label={`Horizonte: ${formatMonth(months)} (${months} meses)`} htmlFor={monthsId}
            help="Arraste para escolher em anos; ajuste fino em meses no campo ao lado.">
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input id={monthsId} type="range" min={12} max={MAX_MONTHS} step={12} value={Math.max(12, months)}
                onChange={(e) => setMonths(Number(e.target.value))} aria-valuetext={formatMonth(months)}
                aria-describedby={`${monthsId}-help`}
                style={{ ["--pct" as string]: `${((Math.min(MAX_MONTHS, Math.max(12, months)) - 12) / (MAX_MONTHS - 12)) * 100}%` }} />
              <input className="input num" style={{ width: 96, flex: "none" }} type="number" min={0} max={MAX_MONTHS}
                inputMode="numeric" value={months} aria-label="Horizonte em meses"
                onChange={(e) => setMonths(Math.max(0, Math.min(MAX_MONTHS, Math.trunc(Number(e.target.value) || 0))))} />
            </div>
          </Field>
          <details>
            <summary>Pausas nos aportes (opcional)</summary>
            <Field label="Meses sem aporte" htmlFor={pausedId}
              help="Números dos meses, separados por vírgula; use hífen para intervalos. Ex.: 13-18, 30">
              <input id={pausedId} className="input" value={paused} onChange={(e) => setPaused(e.target.value)}
                placeholder="13-18, 30" inputMode="numeric" aria-describedby={`${pausedId}-help`} />
            </Field>
          </details>
          {error && <Notice tone="error">{error}</Notice>}
          <div className="row">
            <button type="submit" className="btn btn-primary" disabled={running}>
              <Icon name="trend" />
              {running ? "Simulando…" : "Simular"}
            </button>
            {latest.data && (
              <button type="button" className="btn btn-ghost btn-sm"
                onClick={() => setInitial(decimalToInputBRL(latest.data!.liquid_reserve))}>
                Usar reserva atual ({formatBRL(latest.data.liquid_reserve)}) como valor inicial
              </button>
            )}
          </div>
        </form>
      </Card>

      {!result && !running && (
        <Card className="flat">
          <EmptyState title="Nenhuma simulação ainda">
            Preencha o aporte mensal e clique em Simular. Os resultados usam as premissas salvas abaixo.
          </EmptyState>
        </Card>
      )}
      {running && !result && <Loading label="Calculando cenários…" />}
      {result && <Results projections={result} dim={running} />}

      <AssumptionsEditor
        state={assumptions.data}
        loading={assumptions.loading}
        error={assumptions.error}
        onSaved={(a) => {
          assumptions.setData(a);
          app.toast("Premissas salvas.");
          if (lastRequest) void run(lastRequest);
        }}
      />

      <Disclaimer
        text={app.disclaimer}
        extra={<p>Simulações usam premissas hipotéticas e não são promessa de rentabilidade. Você decide.</p>}
      />
    </div>
  );
}

function Results({ projections, dim }: { projections: Projection[]; dim: boolean }) {
  const yMax = useMemo(
    () => Math.max(0, ...projections.flatMap((p) => (p.path ?? []).map((pt) => toChartNumber(pt[1])))),
    [projections],
  );
  const limitations = useMemo(() => [...new Set(projections.flatMap((p) => p.limitations))], [projections]);
  const engine = projections[0]?.engine_version;

  return (
    <div className="stack-lg" style={{ opacity: dim ? 0.55 : 1, transition: "opacity .2s" }} aria-busy={dim}>
      <section className="scenario-tiles reveal" aria-label="Resultado final por cenário, em dinheiro de hoje">
        {projections.map((p) => (
          <div key={p.scenario} className="scenario-tile">
            <div className="row between" style={{ flexWrap: "nowrap" }}>
              <span className="eyebrow">{p.scenario}</span>
              <Tag>{formatPct(p.assumptions.annual_return)} a.a.</Tag>
            </div>
            <div className="st-value">{formatBRL(p.final_real_todays_money)}</div>
            <div className="small muted">
              em dinheiro de hoje · nominal <span className="num">{formatBRL(p.final_nominal)}</span>
            </div>
          </div>
        ))}
      </section>
      <Card title="Trajetória por cenário" eyebrow="Mesma escala nos três gráficos"
        aside={
          <Legend items={[
            { label: "Nominal", color: "var(--series-1)" },
            { label: "Em dinheiro de hoje", color: "var(--series-2)" },
          ]} />
        }>
        <div className="multiples">
          {projections.map((p) => (
            <div key={p.scenario} className="multiple">
              <div>
                <div className="chart-title">{p.scenario}</div>
                <div className="tiny muted">
                  Retorno {formatPct(p.assumptions.annual_return)} a.a. · inflação {formatPct(p.assumptions.annual_inflation)} ·
                  taxa {formatPct(p.assumptions.annual_fee)}
                </div>
              </div>
              {p.path && p.path.length > 1 ? (
                <LineChart
                  ariaLabel={`Cenário ${p.scenario}: patrimônio nominal e em dinheiro de hoje ao longo do tempo`}
                  yMax={yMax}
                  height={200}
                  formatX={formatMonth}
                  snapX={snapYear}
                  formatTick={compactTick}
                  formatValue={formatBRL}
                  series={[
                    { key: "n", label: "Nominal", color: "var(--series-1)",
                      points: p.path.map(([m, n]) => ({ x: m, y: toChartNumber(n), raw: n })) },
                    { key: "r", label: "Em dinheiro de hoje", color: "var(--series-2)",
                      points: p.path.map(([m, , r]) => ({ x: m, y: toChartNumber(r), raw: r })) },
                  ]}
                />
              ) : (
                <p className="tiny muted">Sem trajetória para exibir.</p>
              )}
              <dl className="kv small">
                <dt>Nominal no fim</dt>
                <dd>{formatBRL(p.final_nominal)}</dd>
                <dt>Em dinheiro de hoje</dt>
                <dd><strong>{formatBRL(p.final_real_todays_money)}</strong></dd>
              </dl>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Resultados" eyebrow={engine ? `Motor ${engine}` : undefined}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Cenário</th>
                <th className="num">Final nominal</th>
                <th className="num">Em dinheiro de hoje</th>
                <th className="num">Total aportado</th>
                <th className="num">Resgates</th>
                <th className="num">Resultado de mercado</th>
              </tr>
            </thead>
            <tbody>
              {projections.map((p) => (
                <tr key={p.scenario}>
                  <td className="nowrap">{p.scenario}</td>
                  <td className="num">{formatBRL(p.final_nominal)}</td>
                  <td className="num">{formatBRL(p.final_real_todays_money)}</td>
                  <td className="num">{formatBRL(p.total_contributed)}</td>
                  <td className="num">{formatBRL(p.total_withdrawn)}</td>
                  <td className="num">{formatBRL(p.market_result)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="stack" style={{ gap: 6, marginTop: 16 }}>
          <div className="eyebrow">Impressões digitais</div>
          <p className="tiny muted">
            SHA-256 da versão do motor + entradas + premissas: permite conferir que um resultado foi gerado exatamente
            com estes dados.
          </p>
          <ul className="list">
            {projections.map((p) => (
              <li key={p.scenario} className="row between" style={{ padding: "8px 0", flexWrap: "nowrap" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="small">{p.scenario}</div>
                  <code className="mono muted" style={{ overflowWrap: "anywhere", fontSize: "0.74rem" }}>{p.inputs_fingerprint}</code>
                </div>
                <CopyButton text={p.inputs_fingerprint} label="Copiar" />
              </li>
            ))}
          </ul>
        </div>
        <PathTable projections={projections} />
      </Card>

      <Card className="sunken" title="Limitações desta simulação" eyebrow="Sempre leia">
        <ul className="bullets small">
          {limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function PathTable({ projections }: { projections: Projection[] }) {
  const rows = useMemo(() => {
    const first = projections[0]?.path ?? [];
    return first.filter(([m]) => m % 12 === 0 || m === first[first.length - 1]?.[0]).map(([m]) => m);
  }, [projections]);
  if (!rows.length) return null;
  return (
    <details style={{ marginTop: 12 }}>
      <summary>Ver os dados dos gráficos em tabela (ano a ano)</summary>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Momento</th>
              {projections.map((p) => (
                <th key={p.scenario} className="num">{p.scenario}: nominal / hoje</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m}>
                <td className="nowrap">{formatMonth(m)}</td>
                {projections.map((p) => {
                  const pt = p.path?.find((x) => x[0] === m);
                  return (
                    <td key={p.scenario} className="num">
                      {pt ? `${formatBRL(pt[1])} / ${formatBRL(pt[2])}` : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

interface ScenarioDraft {
  key: number;
  name: string;
  ret: string;
  infl: string;
  fee: string;
  note: string;
}
let scKey = 0;
const toDraft = (s: Scenario): ScenarioDraft => ({
  key: ++scKey,
  name: s.name,
  ret: fractionToPercentInput(s.annual_return),
  infl: fractionToPercentInput(s.annual_inflation),
  fee: fractionToPercentInput(s.annual_fee),
  note: s.note,
});

function AssumptionsEditor({
  state,
  loading,
  error,
  onSaved,
}: {
  state: AssumptionsResponse | undefined;
  loading: boolean;
  error: { detail: string } | null;
  onSaved: (a: AssumptionsResponse) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<ScenarioDraft[]>([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (state && !editing) setRows(state.scenarios.map(toDraft));
  }, [state, editing]);

  const update = (key: number, field: keyof Omit<ScenarioDraft, "key">, v: string) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, [field]: v } : r)));

  async function save(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const scenarios: Scenario[] = [];
    for (const [i, r] of rows.entries()) {
      const label = r.name.trim() || `Cenário ${i + 1}`;
      if (!r.name.trim()) return setFormError(`${label}: dê um nome ao cenário.`);
      const p = parseFields({
        ret: { text: r.ret, kind: "percent", label: `${label} — retorno anual`, required: true, allowNegative: true },
        infl: { text: r.infl, kind: "percent", label: `${label} — inflação anual`, required: true, allowNegative: true },
        fee: { text: r.fee || "0", kind: "percent", label: `${label} — taxa anual` },
      });
      if (!p.ok) return setFormError(p.error);
      scenarios.push({ name: r.name.trim(), annual_return: p.values.ret!, annual_inflation: p.values.infl!, annual_fee: p.values.fee ?? "0", note: r.note.trim() });
    }
    if (scenarios.length < 1 || scenarios.length > 5) return setFormError("Use de 1 a 5 cenários.");
    if (new Set(scenarios.map((s) => s.name.toLowerCase())).size !== scenarios.length)
      return setFormError("Cada cenário precisa de um nome diferente.");
    setSaving(true);
    try {
      const saved = await putAssumptions(scenarios);
      setEditing(false);
      onSaved(saved);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card
      title="Premissas dos cenários"
      eyebrow="Hipóteses, não previsões"
      aside={state?.is_default ? <Badge tone="gold" icon="info">Padrões ilustrativos</Badge> : <Badge tone="neutral" icon="edit">Definidas por você</Badge>}
    >
      {loading && !state && <Loading />}
      <ErrorNotice error={error} />
      {state && (
        <div className="stack">
          <p className="small">
            Estas são <strong>hipóteses que você controla</strong>: retorno, inflação e taxa por ano. Não são ofertas de
            mercado nem promessa de rentabilidade. Mude-as para ver como o resultado depende delas.
          </p>
          {state.note && <p className="small muted">{state.note}</p>}

          {!editing ? (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Cenário</th>
                      <th className="num">Retorno a.a.</th>
                      <th className="num">Inflação a.a.</th>
                      <th className="num">Taxa a.a.</th>
                      <th>Nota</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.scenarios.map((s) => (
                      <tr key={s.name}>
                        <td className="nowrap">{s.name}</td>
                        <td className="num">{formatPct(s.annual_return)}</td>
                        <td className="num">{formatPct(s.annual_inflation)}</td>
                        <td className="num">{formatPct(s.annual_fee)}</td>
                        <td className="small muted">{s.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>
                  <Icon name="edit" />
                  Editar premissas
                </button>
              </div>
            </>
          ) : (
            <form onSubmit={save} noValidate className="stack">
              {rows.map((r, i) => (
                <fieldset key={r.key} className="card sunken" style={{ padding: 16 }}>
                  <legend className="visually-hidden">Cenário {i + 1}</legend>
                  <div className="row between" style={{ marginBottom: 12 }}>
                    <span className="eyebrow">Hipótese {i + 1}</span>
                    {rows.length > 1 && (
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
                        aria-label={`Remover cenário ${r.name || i + 1}`}>
                        <Icon name="trash" />
                        Remover
                      </button>
                    )}
                  </div>
                  <div className="form-grid">
                    <InlineText label="Nome" value={r.name} onChange={(v) => update(r.key, "name", v)} />
                    <MoneyField kind="percent" label="Retorno anual (hipótese)" value={r.ret} onChange={(v) => update(r.key, "ret", v)} required
                      help="Rentabilidade bruta suposta por ano." />
                    <MoneyField kind="percent" label="Inflação anual (hipótese)" value={r.infl} onChange={(v) => update(r.key, "infl", v)} required
                      help="Usada para converter em dinheiro de hoje." />
                    <MoneyField kind="percent" label="Taxa anual" value={r.fee} onChange={(v) => update(r.key, "fee", v)}
                      help="Taxa de administração sobre o patrimônio." />
                    <InlineText label="Nota" value={r.note} onChange={(v) => update(r.key, "note", v)} />
                  </div>
                </fieldset>
              ))}
              {formError && <Notice tone="error">{formError}</Notice>}
              <div className="row">
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? "Salvando…" : "Salvar premissas"}
                </button>
                {rows.length < 5 && (
                  <button type="button" className="btn btn-secondary btn-sm"
                    onClick={() => setRows((rs) => [...rs, { key: ++scKey, name: "", ret: "", infl: "", fee: "0", note: "" }])}>
                    <Icon name="plus" />
                    Adicionar cenário
                  </button>
                )}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setEditing(false); setFormError(null); }}>
                  Cancelar
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </Card>
  );
}

function InlineText({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <Field label={label} htmlFor={id}>
      <input id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)} maxLength={120} />
    </Field>
  );
}
