import { useId, useMemo, useState, type FormEvent } from "react";
import { createDecision, getDecisions } from "../api/endpoints";
import type { Decision, DecisionInput } from "../api/types";
import { Icon } from "../components/Icon";
import { Badge, Card, EmptyState, ErrorNotice, Field, Loading, MoneyField, Notice, PageHeader, parseFields } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDate, todayISO } from "../lib/dates";
import { decimalToInputBRL, formatBRL } from "../lib/money";
import { errorMessage, useAsync } from "../lib/useAsync";

interface Draft {
  date: string;
  question: string;
  alternatives: string[];
  information: string;
  risk_accepted: string;
  user_choice: string;
  planned_amount: string;
  confirmed: boolean;
  review_of_id: string | null;
}

const blank = (): Draft => ({
  date: todayISO(),
  question: "",
  alternatives: ["", ""],
  information: "",
  risk_accepted: "",
  user_choice: "",
  planned_amount: "",
  confirmed: false,
  review_of_id: null,
});

const reviewDraft = (d: Decision): Draft => ({
  date: todayISO(),
  question: d.question,
  alternatives: d.alternatives.length ? [...d.alternatives] : ["", ""],
  information: d.information,
  risk_accepted: d.risk_accepted,
  user_choice: d.user_choice,
  planned_amount: decimalToInputBRL(d.planned_amount),
  confirmed: d.confirmed,
  review_of_id: d.id,
});

export function DecisionsPage() {
  const app = useApp();
  const decisions = useAsync(getDecisions, []);
  const [draft, setDraft] = useState<Draft | null>(null);

  const byId = useMemo(() => new Map((decisions.data ?? []).map((d) => [d.id, d])), [decisions.data]);
  const reviewedBy = useMemo(() => {
    const m = new Map<string, Decision[]>();
    for (const d of decisions.data ?? []) if (d.review_of_id) m.set(d.review_of_id, [...(m.get(d.review_of_id) ?? []), d]);
    return m;
  }, [decisions.data]);

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Diário de decisões"
        title="O que você decidiu, e por quê"
        lede="Um registro permanente: entradas não são editadas nem apagadas. Para mudar de ideia, crie uma revisão ligada à decisão original."
        actions={
          !draft && (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setDraft(blank())}>
              <Icon name="plus" />
              Registrar decisão
            </button>
          )
        }
      />

      {draft && (
        <DecisionForm
          initial={draft}
          reviewOf={draft.review_of_id ? byId.get(draft.review_of_id) ?? null : null}
          onCancel={() => setDraft(null)}
          onSubmit={async (input) => {
            const created = await createDecision(input);
            decisions.setData((prev) => [created, ...(prev ?? [])]);
            setDraft(null);
            app.toast(input.review_of_id ? "Revisão registrada." : "Decisão registrada.");
          }}
        />
      )}

      {decisions.loading && !decisions.data && <Loading />}
      <ErrorNotice error={decisions.error} onRetry={decisions.reload} />

      {decisions.data && decisions.data.length === 0 && !draft && (
        <Card className="flat">
          <EmptyState
            icon="book"
            title="Nenhuma decisão registrada"
            action={
              <button type="button" className="btn btn-primary" onClick={() => setDraft(blank())}>
                Registrar a primeira
              </button>
            }
          >
            Anotar a pergunta, as alternativas e o risco aceito ajuda a decidir com calma e a aprender depois.
          </EmptyState>
        </Card>
      )}

      {decisions.data && decisions.data.length > 0 && (
        <Card title="Linha do tempo" eyebrow={`${decisions.data.length} registro(s)`}
          aside={<Icon name="book" style={{ width: 18, height: 18, color: "var(--muted)" }} />}>
          <ol className="timeline">
            {decisions.data.map((d) => {
              const original = d.review_of_id ? byId.get(d.review_of_id) : undefined;
              const reviews = reviewedBy.get(d.id) ?? [];
              return (
                <li key={d.id} className={`timeline-item ${d.review_of_id ? "review" : ""}`}>
                  <div className="row between">
                    <span className="mono muted">{formatDate(d.date)}</span>
                    <span className="row" style={{ gap: 6 }}>
                      {d.review_of_id && <Badge tone="neutral" icon="refresh">Revisão</Badge>}
                      {reviews.length > 0 && <Badge tone="neutral">Revisada {reviews.length}x</Badge>}
                      {d.confirmed ? <Badge tone="good">Confirmada</Badge> : <Badge tone="warning" icon="clock">Planejada</Badge>}
                    </span>
                  </div>
                  <h2 style={{ fontSize: "1.04rem" }}>{d.question}</h2>
                  {original && (
                    <p className="review-link">
                      Revisa a decisão de {formatDate(original.date)}: "{original.user_choice || original.question}"
                    </p>
                  )}
                  {d.review_of_id && !original && <p className="review-link">Revisa uma decisão anterior.</p>}
                  <div className="decision-choice">
                    <span className="eyebrow">Escolha</span>
                    <strong>{d.user_choice || "—"}</strong>
                    {d.planned_amount && <span className="tag">{formatBRL(d.planned_amount)}</span>}
                  </div>
                  {(d.alternatives.length > 0 || d.information || d.risk_accepted) && (
                    <dl className="kv-blocks small">
                      {d.alternatives.length > 0 && (
                        <div>
                          <dt className="eyebrow">Alternativas</dt>
                          <dd>
                            <ul className="bullets">
                              {d.alternatives.map((a, i) => (
                                <li key={i}>{a}</li>
                              ))}
                            </ul>
                          </dd>
                        </div>
                      )}
                      {d.information && (
                        <div>
                          <dt className="eyebrow">Informações consideradas</dt>
                          <dd style={{ whiteSpace: "pre-wrap" }}>{d.information}</dd>
                        </div>
                      )}
                      {d.risk_accepted && (
                        <div>
                          <dt className="eyebrow">Risco aceito</dt>
                          <dd style={{ whiteSpace: "pre-wrap" }}>{d.risk_accepted}</dd>
                        </div>
                      )}
                    </dl>
                  )}
                  <div>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setDraft(reviewDraft(d)); window.scrollTo({ top: 0 }); }}>
                      <Icon name="refresh" />
                      Revisar
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        </Card>
      )}
    </div>
  );
}

function DecisionForm({
  initial,
  reviewOf,
  onCancel,
  onSubmit,
}: {
  initial: Draft;
  reviewOf: Decision | null;
  onCancel: () => void;
  onSubmit: (d: DecisionInput) => Promise<void>;
}) {
  const [d, setD] = useState<Draft>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ids = { date: useId(), q: useId(), info: useId(), risk: useId(), choice: useId() };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!d.question.trim()) return setError("Escreva a pergunta que você está decidindo.");
    if (!d.user_choice.trim()) return setError("Registre a sua escolha (mesmo que seja esperar).");
    const p = parseFields({ amount: { text: d.planned_amount, kind: "money", label: "Valor planejado" } });
    if (!p.ok) return setError(p.error);
    setBusy(true);
    try {
      await onSubmit({
        date: d.date,
        question: d.question.trim(),
        alternatives: d.alternatives.map((a) => a.trim()).filter(Boolean),
        information: d.information.trim(),
        risk_accepted: d.risk_accepted.trim(),
        user_choice: d.user_choice.trim(),
        planned_amount: p.values.amount,
        confirmed: d.confirmed,
        review_of_id: d.review_of_id,
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="accent" title={reviewOf ? "Revisar decisão" : "Nova decisão"}
      eyebrow={reviewOf ? `Ligada à decisão de ${formatDate(reviewOf.date)}` : "Entrada permanente"}>
      <form onSubmit={submit} noValidate className="stack">
        {reviewOf && <Notice>A decisão original continua no diário. Esta revisão será registrada como uma nova entrada ligada a ela.</Notice>}
        <div className="form-grid">
          <Field label="Data" htmlFor={ids.date}>
            <input id={ids.date} type="date" className="input" value={d.date} onChange={(e) => setD({ ...d, date: e.target.value })} />
          </Field>
          <MoneyField label="Valor planejado" optional value={d.planned_amount} onChange={(v) => setD({ ...d, planned_amount: v })}
            help="Se a decisão envolve um valor, anote quanto." />
        </div>
        <Field label="Pergunta" htmlFor={ids.q} help="Ex.: quito o cartão agora ou começo a reserva?">
          <input id={ids.q} className="input" value={d.question} onChange={(e) => setD({ ...d, question: e.target.value })} maxLength={300} />
        </Field>
        <fieldset className="stack" style={{ gap: 8 }}>
          <legend className="field-label">Alternativas consideradas</legend>
          {d.alternatives.map((a, i) => (
            <div key={i} className="row" style={{ flexWrap: "nowrap" }}>
              <input className="input" value={a} aria-label={`Alternativa ${i + 1}`} maxLength={200}
                onChange={(e) => setD({ ...d, alternatives: d.alternatives.map((x, j) => (j === i ? e.target.value : x)) })} />
              {d.alternatives.length > 1 && (
                <button type="button" className="icon-btn" aria-label={`Remover alternativa ${i + 1}`}
                  onClick={() => setD({ ...d, alternatives: d.alternatives.filter((_, j) => j !== i) })}>
                  <Icon name="x" />
                </button>
              )}
            </div>
          ))}
          <div>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setD({ ...d, alternatives: [...d.alternatives, ""] })}>
              <Icon name="plus" />
              Adicionar alternativa
            </button>
          </div>
        </fieldset>
        <Field label="Informações consideradas" htmlFor={ids.info} help="Números, fontes ou conversas que pesaram.">
          <textarea id={ids.info} className="textarea" value={d.information} onChange={(e) => setD({ ...d, information: e.target.value })} maxLength={4000} />
        </Field>
        <Field label="Risco aceito" htmlFor={ids.risk} help="O que pode dar errado e você aceita.">
          <textarea id={ids.risk} className="textarea" value={d.risk_accepted} onChange={(e) => setD({ ...d, risk_accepted: e.target.value })} maxLength={2000} />
        </Field>
        <Field label="Sua escolha" htmlFor={ids.choice}>
          <input id={ids.choice} className="input" value={d.user_choice} onChange={(e) => setD({ ...d, user_choice: e.target.value })} maxLength={300} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={d.confirmed} onChange={(e) => setD({ ...d, confirmed: e.target.checked })} />
          <span>Já executei esta decisão (por conta própria, fora do Lastro)</span>
        </label>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Registrando…" : reviewOf ? "Registrar revisão" : "Registrar decisão"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </Card>
  );
}
