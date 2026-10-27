import { useId, useState, type FormEvent } from "react";
import { createGoal, deleteGoal, getGoals, updateGoal } from "../api/endpoints";
import type { Goal, GoalInput, Liquidity } from "../api/types";
import { Icon } from "../components/Icon";
import {
  Badge,
  Card,
  Disclaimer,
  EmptyState,
  ErrorNotice,
  Field,
  Loading,
  Meter,
  MoneyField,
  Notice,
  PageHeader,
  ProgressRing,
  Tag,
  parseFields,
} from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDate } from "../lib/dates";
import { GOAL_STATUS, LIQUIDITY_LABEL } from "../lib/labels";
import { decimalToInputBRL, formatBRL, toChartNumber } from "../lib/money";
import { errorMessage, useAsync } from "../lib/useAsync";

interface Draft {
  name: string;
  target: string;
  current: string;
  deadline: string;
  priority: number;
  liquidity: Liquidity;
}

const blank: Draft = { name: "", target: "", current: "0", deadline: "", priority: 3, liquidity: "longo_prazo" };

const fromGoal = (g: Goal): Draft => ({
  name: g.name,
  target: decimalToInputBRL(g.target_real_value),
  current: decimalToInputBRL(g.current_amount),
  deadline: g.deadline,
  priority: g.priority,
  liquidity: g.liquidity,
});

export function GoalsPage() {
  const app = useApp();
  const goals = useAsync(getGoals, []);
  const [editing, setEditing] = useState<{ id: string | null; draft: Draft } | null>(null);

  async function remove(g: Goal) {
    if (!window.confirm(`Excluir a meta "${g.name}"? Esta ação não pode ser desfeita.`)) return;
    try {
      await deleteGoal(g.id);
      goals.setData((prev) => (prev ?? []).filter((x) => x.id !== g.id));
      app.toast("Meta excluída.");
    } catch (e) {
      app.toast(errorMessage(e), "error");
    }
  }

  const sorted = [...(goals.data ?? [])].sort((a, b) => a.priority - b.priority || a.deadline.localeCompare(b.deadline));

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Metas"
        title="O que você está construindo"
        lede="Metas em dinheiro de hoje: o aporte necessário já considera a inflação de cada cenário."
        actions={
          !editing && (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setEditing({ id: null, draft: { ...blank } })}>
              <Icon name="plus" />
              Nova meta
            </button>
          )
        }
      />

      {editing && (
        <GoalForm
          initial={editing.draft}
          isNew={editing.id === null}
          onCancel={() => setEditing(null)}
          onSubmit={async (input) => {
            const saved = editing.id ? await updateGoal(editing.id, input) : await createGoal(input);
            goals.setData((prev) => {
              const list = prev ?? [];
              return editing.id ? list.map((g) => (g.id === saved.id ? saved : g)) : [...list, saved];
            });
            setEditing(null);
            app.toast(editing.id ? "Meta atualizada." : "Meta criada.");
            void app.refresh();
          }}
        />
      )}

      {goals.loading && !goals.data && <Loading />}
      <ErrorNotice error={goals.error} onRetry={goals.reload} />

      {goals.data && goals.data.length === 0 && !editing && (
        <Card className="flat">
          <EmptyState
            icon="target"
            title="Nenhuma meta ainda"
            action={
              <button type="button" className="btn btn-primary" onClick={() => setEditing({ id: null, draft: { ...blank } })}>
                Criar primeira meta
              </button>
            }
          >
            Uma meta tem nome, valor em dinheiro de hoje e prazo. O Lastro calcula quanto aportar por mês em cada cenário.
          </EmptyState>
        </Card>
      )}

      <div className="grid-2">
        {sorted.map((g) => {
          const cur = toChartNumber(g.current_amount);
          const tgt = toChartNumber(g.target_real_value);
          const pct = tgt > 0 ? Math.max(0, Math.min(100, Math.round((cur / tgt) * 100))) : 0;
          return (
            <Card
              key={g.id}
              as="article"
              title={g.name}
              eyebrow={`Prioridade ${g.priority} · ${LIQUIDITY_LABEL[g.liquidity]}`}
              aside={<Badge tone={GOAL_STATUS[g.status].tone}>{GOAL_STATUS[g.status].label}</Badge>}
              footer={
                <>
                  <span className="mono">
                    {g.months_left === 1 ? "falta 1 mês" : `faltam ${g.months_left} meses`}
                  </span>
                  <span className="row" style={{ gap: 4 }}>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing({ id: g.id, draft: fromGoal(g) })}>
                      <Icon name="edit" />
                      Editar
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" style={{ color: "var(--danger)" }}
                      onClick={() => void remove(g)} aria-label={`Excluir meta ${g.name}`}>
                      <Icon name="trash" />
                      Excluir
                    </button>
                  </span>
                </>
              }
            >
              <div className="stack">
                <div className="goal-figure">
                  <ProgressRing value={cur} max={tgt} size={52} stroke={4} label={`Progresso da meta ${g.name}: ${pct}%`}>
                    <span style={{ fontSize: 12 }}>{pct}%</span>
                  </ProgressRing>
                  <div style={{ minWidth: 0 }}>
                    <div className="gf-value">{formatBRL(g.current_amount)}</div>
                    <div className="small muted">de {formatBRL(g.target_real_value)} em dinheiro de hoje</div>
                  </div>
                </div>
                <Meter gold value={cur} max={tgt} label={`Progresso da meta ${g.name}`} />
                <div className="row" style={{ gap: 6 }}>
                  <Tag>base {formatDate(g.base_date)}</Tag>
                  <Tag>prazo {formatDate(g.deadline)}</Tag>
                </div>
                <div>
                  <div className="eyebrow" style={{ marginBottom: 4 }}>Aporte mensal necessário</div>
                  <dl className="scenario-rows" style={{ margin: 0 }}>
                    {Object.entries(g.required_monthly).map(([sc, v]) => (
                      <div key={sc}>
                        <dt>{sc}</dt>
                        <dd>{formatBRL(v)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      <Disclaimer text={app.disclaimer}
        extra={<p>O aporte necessário depende das premissas de cada cenário (editáveis em Meu futuro). Não é garantia de que a meta será atingida.</p>} />
    </div>
  );
}

function GoalForm({
  initial,
  isNew,
  onCancel,
  onSubmit,
}: {
  initial: Draft;
  isNew: boolean;
  onCancel: () => void;
  onSubmit: (g: GoalInput) => Promise<void>;
}) {
  const [d, setD] = useState<Draft>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nameId = useId();
  const deadlineId = useId();
  const prioId = useId();
  const liqId = useId();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!d.name.trim()) return setError("Dê um nome à meta.");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d.deadline)) return setError("Informe o prazo.");
    const p = parseFields({
      target: { text: d.target, kind: "money", label: "Valor da meta", required: true },
      current: { text: d.current || "0", kind: "money", label: "Já guardado" },
    });
    if (!p.ok) return setError(p.error);
    setBusy(true);
    try {
      await onSubmit({
        name: d.name.trim(),
        target_real_value: p.values.target!,
        current_amount: p.values.current ?? "0",
        deadline: d.deadline,
        priority: d.priority,
        liquidity: d.liquidity,
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={isNew ? "Nova meta" : "Editar meta"} className="accent">
      <form onSubmit={submit} noValidate className="stack">
        <div className="form-grid">
          <Field label="Nome" htmlFor={nameId} help="Ex.: reserva de emergência, entrada do apartamento.">
            <input id={nameId} className="input" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} maxLength={80} required />
          </Field>
          <MoneyField label="Valor da meta (em dinheiro de hoje)" value={d.target} onChange={(v) => setD({ ...d, target: v })} required
            help="Quanto custaria hoje. A inflação é tratada em cada cenário." />
          <MoneyField label="Já guardado" value={d.current} onChange={(v) => setD({ ...d, current: v })}
            help="Quanto já está separado para esta meta." />
          <Field label="Prazo" htmlFor={deadlineId} help="Até quando quer chegar lá.">
            <input id={deadlineId} type="date" className="input" value={d.deadline} onChange={(e) => setD({ ...d, deadline: e.target.value })} required />
          </Field>
          <Field label="Prioridade" htmlFor={prioId} help="1 = mais importante.">
            <select id={prioId} className="select" value={d.priority} onChange={(e) => setD({ ...d, priority: Number(e.target.value) })}>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </Field>
          <Field label="Liquidez" htmlFor={liqId} help="Quão rápido vai precisar sacar o dinheiro.">
            <select id={liqId} className="select" value={d.liquidity} onChange={(e) => setD({ ...d, liquidity: e.target.value as Liquidity })}>
              {(Object.keys(LIQUIDITY_LABEL) as Liquidity[]).map((l) => (
                <option key={l} value={l}>{LIQUIDITY_LABEL[l]}</option>
              ))}
            </select>
          </Field>
        </div>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Salvando…" : isNew ? "Criar meta" : "Salvar alterações"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </Card>
  );
}
