import { useEffect, useId, useState, type FormEvent } from "react";
import { createSnapshot, getLatestSnapshot, getSnapshotHistory } from "../api/endpoints";
import type { Debt, Snapshot, SnapshotHistoryItem } from "../api/types";
import { Icon } from "../components/Icon";
import { compactTick, Legend, LineChart } from "../components/LineChart";
import {
  Card,
  Disclaimer,
  EmptyState,
  ErrorNotice,
  Field,
  Loading,
  MoneyField,
  Notice,
  PageHeader,
  parseFields,
} from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDate, formatDateTime, todayISO } from "../lib/dates";
import { decimalToInputBRL, formatBRL, fractionToPercentInput, isNegative, toChartNumber } from "../lib/money";
import { errorMessage, useAsync } from "../lib/useAsync";

interface DebtDraft {
  key: number;
  name: string;
  balance: string;
  rate: string;
  payment: string;
}

interface Draft {
  as_of: string;
  income: string;
  essential: string;
  variable: string;
  reserve: string;
  available: string;
  debts: DebtDraft[];
}

let debtKey = 0;
const emptyDebt = (): DebtDraft => ({ key: ++debtKey, name: "", balance: "", rate: "", payment: "" });

function draftFrom(s: Snapshot | null): Draft {
  if (!s) return { as_of: todayISO(), income: "", essential: "", variable: "", reserve: "", available: "", debts: [] };
  return {
    as_of: todayISO(),
    income: decimalToInputBRL(s.net_monthly_income),
    essential: decimalToInputBRL(s.essential_expenses),
    variable: decimalToInputBRL(s.variable_expenses),
    reserve: decimalToInputBRL(s.liquid_reserve),
    available: decimalToInputBRL(s.available_this_month),
    debts: s.debts.map((d) => ({
      key: ++debtKey,
      name: d.name,
      balance: decimalToInputBRL(d.balance),
      rate: fractionToPercentInput(d.monthly_rate),
      payment: decimalToInputBRL(d.monthly_payment),
    })),
  };
}

export function FinancesPage() {
  const app = useApp();
  const latest = useAsync(getLatestSnapshot, []);
  const history = useAsync(getSnapshotHistory, []);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (latest.data !== undefined && draft === null) setDraft(draftFrom(latest.data));
  }, [latest.data, draft]);

  const set = (k: keyof Omit<Draft, "debts">) => (v: string) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const setDebt = (key: number, field: keyof Omit<DebtDraft, "key">, v: string) =>
    setDraft((d) => (d ? { ...d, debts: d.debts.map((x) => (x.key === key ? { ...x, [field]: v } : x)) } : d));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!draft) return;
    setFormError(null);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.as_of)) return setFormError("Informe a data de referência.");
    const main = parseFields({
      income: { text: draft.income, kind: "money", label: "Renda líquida mensal", required: true },
      essential: { text: draft.essential, kind: "money", label: "Despesas essenciais", required: true },
      variable: { text: draft.variable, kind: "money", label: "Despesas variáveis", required: true },
      reserve: { text: draft.reserve, kind: "money", label: "Reserva líquida", required: true },
      available: { text: draft.available, kind: "money", label: "Disponível este mês", required: true },
    });
    if (!main.ok) return setFormError(main.error);
    const debts: Debt[] = [];
    for (const [i, d] of draft.debts.entries()) {
      const label = d.name.trim() || `Dívida ${i + 1}`;
      if (!d.name.trim() && !d.balance.trim() && !d.rate.trim() && !d.payment.trim()) continue;
      if (!d.name.trim()) return setFormError(`${label}: dê um nome à dívida.`);
      const p = parseFields({
        balance: { text: d.balance, kind: "money", label: `${label} — saldo`, required: true },
        rate: { text: d.rate, kind: "percent", label: `${label} — juros ao mês`, required: true },
        payment: { text: d.payment, kind: "money", label: `${label} — parcela`, required: true },
      });
      if (!p.ok) return setFormError(p.error);
      debts.push({
        name: d.name.trim(),
        balance: p.values.balance!,
        monthly_rate: p.values.rate!,
        monthly_payment: p.values.payment!,
      });
    }
    setSaving(true);
    try {
      const created = await createSnapshot({
        as_of: draft.as_of,
        net_monthly_income: main.values.income!,
        essential_expenses: main.values.essential!,
        variable_expenses: main.values.variable!,
        liquid_reserve: main.values.reserve!,
        available_this_month: main.values.available!,
        debts,
      });
      latest.setData(created);
      setDraft(draftFrom(created));
      await history.reload();
      await app.refresh();
      app.toast("Retrato salvo. O histórico anterior foi preservado.");
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Minha vida financeira"
        title="O retrato do mês"
        lede="Cada retrato é uma fotografia: salvar cria um novo registro e o histórico nunca é reescrito. Valores em reais, no formato 1.234,56."
      />

      {latest.loading && !draft && <Loading />}
      <ErrorNotice error={latest.error} onRetry={latest.reload} />

      {latest.data && (
        <Notice>
          Último retrato: <strong>{formatDate(latest.data.as_of)}</strong> (registrado em {formatDateTime(latest.data.created_at)}).
          O formulário já vem preenchido com ele; ajuste o que mudou e salve um novo.
        </Notice>
      )}
      {latest.data === null && (
        <Notice>
          Este será o seu primeiro retrato. Use números aproximados se precisar: dá para corrigir no mês seguinte.
        </Notice>
      )}

      {draft && (
        <form onSubmit={submit} noValidate className="stack-lg">
          <Card title="Renda, despesas e reserva" eyebrow="Mês de referência">
            <div className="form-grid">
              <DateField value={draft.as_of} onChange={set("as_of")} />
              <MoneyField label="Renda líquida mensal" value={draft.income} onChange={set("income")} required
                help="Quanto entra por mês, já sem impostos e INSS. É a base de todo o plano." />
              <MoneyField label="Despesas essenciais" value={draft.essential} onChange={set("essential")} required
                help="Moradia, alimentação, saúde, transporte. Define o tamanho da reserva de emergência." />
              <MoneyField label="Despesas variáveis" value={draft.variable} onChange={set("variable")} required
                help="Lazer, compras, assinaturas. Mostra onde existe margem para ajustar." />
              <MoneyField label="Reserva líquida" value={draft.reserve} onChange={set("reserve")} required
                help="Dinheiro que dá para sacar rápido e sem perda. Mede sua proteção contra imprevistos." />
              <MoneyField label="Disponível este mês" value={draft.available} onChange={set("available")} required
                help="O que sobrou e está livre para decidir agora. É o valor que o diagnóstico distribui." />
            </div>
          </Card>

          <Card
            title="Dívidas"
            eyebrow="Opcional"
            aside={
              <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => setDraft((d) => (d ? { ...d, debts: [...d.debts, emptyDebt()] } : d))}>
                <Icon name="plus" />
                Adicionar dívida
              </button>
            }
          >
            {draft.debts.length === 0 ? (
              <p className="small muted">
                Sem dívidas informadas. Se tiver cartão parcelado, empréstimo ou financiamento, inclua: juros altos mudam a
                prioridade do mês.
              </p>
            ) : (
              <div className="stack">
                {draft.debts.map((d, i) => (
                  <fieldset key={d.key} className="card sunken" style={{ padding: 16 }}>
                    <legend className="visually-hidden">Dívida {i + 1}</legend>
                    <div className="row between" style={{ marginBottom: 12 }}>
                      <span className="eyebrow">Dívida {i + 1}</span>
                      <button type="button" className="btn btn-ghost btn-sm" aria-label={`Remover dívida ${d.name || i + 1}`}
                        onClick={() => setDraft((x) => (x ? { ...x, debts: x.debts.filter((y) => y.key !== d.key) } : x))}>
                        <Icon name="trash" />
                        Remover
                      </button>
                    </div>
                    <div className="form-grid">
                      <TextField label="Nome" value={d.name} onChange={(v) => setDebt(d.key, "name", v)}
                        help="Para você reconhecer depois (ex.: cartão, consignado)." />
                      <MoneyField label="Saldo devedor" value={d.balance} onChange={(v) => setDebt(d.key, "balance", v)} required
                        help="Quanto falta pagar hoje." />
                      <MoneyField kind="percent" label="Juros ao mês" value={d.rate} onChange={(v) => setDebt(d.key, "rate", v)} required
                        help="Como no contrato ou fatura (ex.: 2,5). Compara o custo da dívida com investir." />
                      <MoneyField label="Parcela mensal" value={d.payment} onChange={(v) => setDebt(d.key, "payment", v)} required
                        help="Entra no cálculo de quanto da renda já está comprometida." />
                    </div>
                  </fieldset>
                ))}
              </div>
            )}
          </Card>

          {formError && <Notice tone="error">{formError}</Notice>}
          <div className="row">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              <Icon name="check" />
              {saving ? "Salvando…" : "Salvar novo retrato"}
            </button>
            <span className="tiny muted">Os dados ficam só no seu servidor.</span>
          </div>
        </form>
      )}

      <HistoryCard items={history.data} loading={history.loading} />
      <Disclaimer text={app.disclaimer} />
    </div>
  );
}

function DateField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <Field label="Data de referência" htmlFor={id} help="A que dia estes números se referem. Normalmente, hoje.">
      <input id={id} type="date" className="input" value={value} onChange={(e) => onChange(e.target.value)} required
        aria-describedby={`${id}-help`} />
    </Field>
  );
}

function TextField({ label, value, onChange, help }: { label: string; value: string; onChange: (v: string) => void; help?: string }) {
  const id = useId();
  return (
    <Field label={label} htmlFor={id} help={help}>
      <input id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)} maxLength={80}
        aria-describedby={help ? `${id}-help` : undefined} />
    </Field>
  );
}

function HistoryCard({ items, loading }: { items: SnapshotHistoryItem[] | undefined; loading: boolean }) {
  return (
    <Card title="Histórico" eyebrow="Evolução dos retratos">
      {loading && !items && <Loading />}
      {items && items.length === 0 && (
        <EmptyState icon="trend" title="Sem histórico ainda">Depois do primeiro retrato, a evolução aparece aqui.</EmptyState>
      )}
      {items && items.length > 0 && (
        <div className="stack">
          {items.length >= 2 ? (
            <>
              <div className="row between">
                <span className="chart-title">Reserva líquida e dívidas (R$)</span>
                <Legend
                  items={[
                    { label: "Reserva líquida", color: "var(--series-1)" },
                    { label: "Dívidas", color: "var(--series-2)" },
                  ]}
                />
              </div>
              <LineChart
                ariaLabel={`Evolução da reserva líquida e das dívidas em ${items.length} retratos`}
                series={[
                  {
                    key: "reserve",
                    label: "Reserva líquida",
                    color: "var(--series-1)",
                    endLabel: "Reserva",
                    points: items.map((h, i) => ({ x: i, y: toChartNumber(h.liquid_reserve), raw: h.liquid_reserve })),
                  },
                  {
                    key: "debt",
                    label: "Dívidas",
                    color: "var(--series-2)",
                    endLabel: "Dívidas",
                    points: items.map((h, i) => ({ x: i, y: toChartNumber(h.total_debt), raw: h.total_debt })),
                  },
                ]}
                formatX={(x) => formatDate(items[Math.round(x)]?.as_of)}
                formatTick={compactTick}
                formatValue={formatBRL}
                height={220}
              />
            </>
          ) : (
            <p className="small muted">Com dois ou mais retratos, um gráfico mostra a evolução.</p>
          )}
          <div className="table-wrap">
            <table className="table">
              <caption className="visually-hidden">Histórico de retratos, do mais recente ao mais antigo</caption>
              <thead>
                <tr>
                  <th>Data</th>
                  <th className="num">Renda</th>
                  <th className="num">Reserva</th>
                  <th className="num">Dívidas</th>
                  <th className="num">Fluxo livre</th>
                </tr>
              </thead>
              <tbody>
                {[...items].reverse().map((h) => (
                  <tr key={h.id}>
                    <td className="nowrap">{formatDate(h.as_of)}</td>
                    <td className="num">{formatBRL(h.net_monthly_income)}</td>
                    <td className="num">{formatBRL(h.liquid_reserve)}</td>
                    <td className="num">{formatBRL(h.total_debt)}</td>
                    <td className={`num ${isNegative(h.free_cash_flow) ? "neg" : ""}`}>{formatBRL(h.free_cash_flow)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
