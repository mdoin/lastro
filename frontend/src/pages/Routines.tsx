import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  createRoutine,
  deleteRoutine,
  getInbox,
  getRoutineRuns,
  getRoutines,
  markInboxRead,
  runRoutine,
  updateRoutine,
} from "../api/endpoints";
import type { MissedPolicy, Routine, RoutineInput, RoutineRun, Schedule, ScheduleKind } from "../api/types";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { Badge, Card, EmptyState, ErrorNotice, Field, Loading, Notice, PageHeader, Segmented, Tag } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDateTime, todayISO } from "../lib/dates";
import { describeSchedule, RUN_STATUS, SCHEDULE_KIND_LABEL, WEEKDAYS } from "../lib/labels";
import { errorMessage, useAsync } from "../lib/useAsync";
import { DateInput } from "../components/DateInput";

const TIMEZONES = [
  "America/Sao_Paulo",
  "America/Manaus",
  "America/Cuiaba",
  "America/Belem",
  "America/Fortaleza",
  "America/Recife",
  "America/Bahia",
  "America/Porto_Velho",
  "America/Rio_Branco",
  "America/Noronha",
];

const blank: RoutineInput = {
  name: "",
  instruction: "",
  schedule: { kind: "monthly", time: "08:00", day: 1 },
  timezone: "America/Sao_Paulo",
  active: true,
  missed_policy: "run_once",
  use_panel: false,
};

type Tab = "rotinas" | "caixa";

export function RoutinesPage() {
  const app = useApp();
  const routines = useAsync(getRoutines, []);
  const inbox = useAsync(getInbox, []);
  const [tab, setTab] = useState<Tab>("rotinas");
  const [editing, setEditing] = useState<{ id: string | null; value: RoutineInput } | null>(null);

  const unread = inbox.data?.filter((r) => !r.read).length ?? 0;

  async function markRead(id: string) {
    try {
      await markInboxRead(id);
      inbox.setData((prev) => (prev ?? []).map((r) => (r.id === id ? { ...r, read: true } : r)));
      void app.refresh();
    } catch (e) {
      app.toast(errorMessage(e), "error");
    }
  }

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Rotinas"
        title="O mentor acompanhando por você"
        lede="Rotinas rodam no horário marcado e deixam o resultado na caixa de entrada. Elas só leem e analisam: nenhuma rotina movimenta dinheiro."
        actions={
          !editing && (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => { setTab("rotinas"); setEditing({ id: null, value: structuredClone(blank) }); }}>
              <Icon name="plus" />
              Nova rotina
            </button>
          )
        }
      />

      <Segmented<Tab>
        label="Seção"
        value={tab}
        onChange={setTab}
        options={[
          { value: "rotinas", label: "Rotinas" },
          { value: "caixa", label: unread ? `Caixa de entrada (${unread})` : "Caixa de entrada" },
        ]}
      />

      {tab === "caixa" && (
        <Card title="Caixa de entrada" eyebrow={unread ? `${unread} não lido(s)` : "Tudo lido"}>
          {inbox.loading && !inbox.data && <Loading />}
          <ErrorNotice error={inbox.error} onRetry={inbox.reload} />
          {inbox.data && inbox.data.length === 0 && <p className="small muted">Nenhum resultado ainda.</p>}
          {inbox.data && inbox.data.length > 0 && (
            <ul className="list">
              {inbox.data.map((r) => (
                <InboxItem key={r.id} run={r} routineName={routines.data?.find((x) => x.id === r.routine_id)?.name} onRead={markRead} />
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === "rotinas" && (
        <>
          {editing && (
            <RoutineForm
              initial={editing.value}
              isNew={editing.id === null}
              onCancel={() => setEditing(null)}
              onSubmit={async (value) => {
                const saved = editing.id ? await updateRoutine(editing.id, value) : await createRoutine(value);
                routines.setData((prev) => {
                  const list = prev ?? [];
                  return editing.id ? list.map((r) => (r.id === saved.id ? saved : r)) : [...list, saved];
                });
                setEditing(null);
                app.toast(editing.id ? "Rotina atualizada." : "Rotina criada.");
              }}
            />
          )}
          {routines.loading && !routines.data && <Loading />}
          <ErrorNotice error={routines.error} onRetry={routines.reload} />
          {routines.data && routines.data.length === 0 && !editing && (
            <Card className="flat">
              <EmptyState
                icon="clock"
                title="Nenhuma rotina"
                action={
                  <button type="button" className="btn btn-primary" onClick={() => setEditing({ id: null, value: structuredClone(blank) })}>
                    Criar primeira rotina
                  </button>
                }
              >
                Exemplo: "Todo dia 1º, revise meu retrato do mês e diga se a reserva avançou."
              </EmptyState>
            </Card>
          )}
          <div className="stack">
            {routines.data?.map((r) => (
              <RoutineCard
                key={r.id}
                routine={r}
                onEdit={() =>
                  setEditing({
                    id: r.id,
                    value: {
                      name: r.name,
                      instruction: r.instruction,
                      schedule: { ...r.schedule },
                      timezone: r.timezone,
                      active: r.active,
                      missed_policy: r.missed_policy,
                      use_panel: r.use_panel,
                    },
                  })
                }
                onDeleted={() => routines.setData((prev) => (prev ?? []).filter((x) => x.id !== r.id))}
                onRan={() => {
                  void routines.reload();
                  void inbox.reload();
                }}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function InboxItem({ run, routineName, onRead }: { run: RoutineRun; routineName?: string; onRead: (id: string) => void }) {
  return (
    <li className="stack" style={{ gap: 8 }}>
      <div className="row between">
        <span className="row" style={{ gap: 8 }}>
          {!run.read && <span className="unread-dot" role="img" aria-label="Não lido" />}
          <strong className="small">{routineName ?? "Rotina"}</strong>
          <span className="mono muted">{formatDateTime(run.finished_at ?? run.started_at ?? run.scheduled_for)}</span>
        </span>
        <Badge tone={RUN_STATUS[run.status].tone}>{RUN_STATUS[run.status].label}</Badge>
      </div>
      {run.summary ? <div className="small"><Markdown text={run.summary} /></div> : <p className="tiny muted">Sem resumo.</p>}
      <div className="row">
        {run.conversation_id && (
          <Link className="btn btn-ghost btn-sm" to={`/mentor/${run.conversation_id}`} onClick={() => !run.read && onRead(run.id)}>
            Abrir conversa
          </Link>
        )}
        {!run.read && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onRead(run.id)}>
            Marcar como lido
          </button>
        )}
      </div>
    </li>
  );
}

function RoutineCard({
  routine: r,
  onEdit,
  onDeleted,
  onRan,
}: {
  routine: Routine;
  onEdit: () => void;
  onDeleted: () => void;
  onRan: () => void;
}) {
  const app = useApp();
  const [runs, setRuns] = useState<RoutineRun[] | null>(null);
  const [showRuns, setShowRuns] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleRuns() {
    const next = !showRuns;
    setShowRuns(next);
    if (next) {
      try {
        setRuns(await getRoutineRuns(r.id));
      } catch (e) {
        setError(errorMessage(e));
      }
    }
  }

  async function runNow() {
    setBusy(true);
    setError(null);
    try {
      const run = await runRoutine(r.id);
      app.toast("Execução enfileirada. O resultado chega na caixa de entrada.", "info");
      if (showRuns) setRuns((prev) => [run, ...(prev ?? [])]);
      onRan();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Excluir a rotina "${r.name}"?`)) return;
    try {
      await deleteRoutine(r.id);
      onDeleted();
      app.toast("Rotina excluída.");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <Card as="article" title={r.name} eyebrow={describeSchedule(r.schedule)}
      aside={
        <span className="row" style={{ gap: 6 }}>
          {r.use_panel && <Badge tone="neutral" icon="panel">Painel</Badge>}
          {r.active ? <Badge tone="good">Ativa</Badge> : <Badge tone="neutral" icon="stop">Pausada</Badge>}
        </span>
      }
      footer={
        <>
          <span className="row" style={{ gap: 4 }}>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => void runNow()} disabled={busy}>
              <Icon name="play" />
              {busy ? "Enviando…" : "Rodar agora"}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={onEdit}>
              <Icon name="edit" />
              Editar
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void toggleRuns()} aria-expanded={showRuns}>
              <Icon name="clock" />
              Histórico
            </button>
          </span>
          <button type="button" className="btn btn-ghost btn-sm" style={{ color: "var(--danger)" }}
            onClick={() => void remove()} aria-label={`Excluir rotina ${r.name}`}>
            <Icon name="trash" />
            Excluir
          </button>
        </>
      }>
      <div className="stack">
        <p className="routine-instruction">{r.instruction}</p>
        <dl className="kv wrap small">
          <dt>Próxima execução</dt>
          <dd>{r.active ? <span className="mono">{formatDateTime(r.next_run_at, r.timezone)}</span> : "—"}</dd>
          <dt>Última execução</dt>
          <dd>
            {r.last_run ? (
              <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                <span className="mono">
                  {formatDateTime(r.last_run.finished_at ?? r.last_run.started_at ?? r.last_run.scheduled_for, r.timezone)}
                </span>
                <Badge tone={RUN_STATUS[r.last_run.status].tone}>{RUN_STATUS[r.last_run.status].label}</Badge>
              </span>
            ) : (
              "nunca"
            )}
          </dd>
          <dt>Fuso</dt>
          <dd>
            <Tag>{r.timezone}</Tag>
          </dd>
          <dt>Se perder o horário</dt>
          <dd>{r.missed_policy === "skip" ? "Pular" : "Rodar uma vez ao voltar"}</dd>
        </dl>
        {error && <Notice tone="error">{error}</Notice>}
        {showRuns && (
          <div className="card sunken" style={{ padding: 12 }}>
            {!runs && <Loading />}
            {runs && runs.length === 0 && <p className="small muted">Nenhuma execução ainda.</p>}
            {runs && runs.length > 0 && (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Agendada para</th>
                      <th>Concluída</th>
                      <th>Status</th>
                      <th>Resumo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((x) => (
                      <tr key={x.id}>
                        <td className="nowrap mono">{formatDateTime(x.scheduled_for, r.timezone)}</td>
                        <td className="nowrap mono">{formatDateTime(x.finished_at, r.timezone)}</td>
                        <td><Badge tone={RUN_STATUS[x.status].tone}>{RUN_STATUS[x.status].label}</Badge></td>
                        <td className="small">
                          {x.summary ? (x.summary.length > 140 ? `${x.summary.slice(0, 140)}…` : x.summary) : "—"}
                          {x.conversation_id && (
                            <>
                              {" "}
                              <Link to={`/mentor/${x.conversation_id}`}>abrir</Link>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function RoutineForm({
  initial,
  isNew,
  onCancel,
  onSubmit,
}: {
  initial: RoutineInput;
  isNew: boolean;
  onCancel: () => void;
  onSubmit: (v: RoutineInput) => Promise<void>;
}) {
  const [v, setV] = useState<RoutineInput>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ids = {
    name: useId(),
    instr: useId(),
    kind: useId(),
    time: useId(),
    weekday: useId(),
    day: useId(),
    date: useId(),
    tz: useId(),
    tzList: useId(),
  };

  const setSchedule = (patch: Partial<Schedule>) => setV((x) => ({ ...x, schedule: { ...x.schedule, ...patch } }));

  function changeKind(kind: ScheduleKind) {
    const base: Schedule = { kind, time: v.schedule.time || "08:00" };
    if (kind === "weekly") base.weekday = v.schedule.weekday ?? 0;
    if (kind === "monthly") base.day = v.schedule.day ?? 1;
    if (kind === "once") base.date = v.schedule.date ?? todayISO();
    setV((x) => ({ ...x, schedule: base }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!v.name.trim()) return setError("Dê um nome à rotina.");
    if (!v.instruction.trim()) return setError("Escreva a instrução para o mentor.");
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(v.schedule.time)) return setError("Horário inválido (use HH:MM).");
    if (v.schedule.kind === "once" && !v.schedule.date) return setError("Escolha a data.");
    if (!v.timezone.trim()) return setError("Informe o fuso horário.");
    // Envia só os campos do tipo escolhido.
    const s: Schedule = { kind: v.schedule.kind, time: v.schedule.time };
    if (s.kind === "weekly") s.weekday = v.schedule.weekday ?? 0;
    if (s.kind === "monthly") s.day = v.schedule.day ?? 1;
    if (s.kind === "once") s.date = v.schedule.date!;
    setBusy(true);
    try {
      await onSubmit({ ...v, name: v.name.trim(), instruction: v.instruction.trim(), timezone: v.timezone.trim(), schedule: s });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={isNew ? "Nova rotina" : "Editar rotina"} className="accent">
      <form onSubmit={submit} noValidate className="stack">
        <div className="form-grid">
          <Field label="Nome" htmlFor={ids.name} help="Como a rotina aparece na lista e na caixa de entrada.">
            <input id={ids.name} className="input" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} maxLength={80} />
          </Field>
        </div>
        <Field label="Instrução para o mentor" htmlFor={ids.instr}
          help="O que ele deve analisar a cada execução. Ele só lê dados e escreve um resumo.">
          <textarea id={ids.instr} className="textarea" value={v.instruction} onChange={(e) => setV({ ...v, instruction: e.target.value })}
            maxLength={4000} placeholder="Ex.: compare o retrato deste mês com o anterior e diga o que mudou na reserva e nas dívidas." />
        </Field>

        <fieldset className="stack">
          <legend className="field-label">Agenda</legend>
          <Segmented<ScheduleKind>
            label="Frequência"
            value={v.schedule.kind}
            onChange={changeKind}
            options={(Object.keys(SCHEDULE_KIND_LABEL) as ScheduleKind[]).map((k) => ({ value: k, label: SCHEDULE_KIND_LABEL[k] }))}
          />
          <div className="form-grid">
            {v.schedule.kind === "weekly" && (
              <Field label="Dia da semana" htmlFor={ids.weekday}>
                <select id={ids.weekday} className="select" value={v.schedule.weekday ?? 0} onChange={(e) => setSchedule({ weekday: Number(e.target.value) })}>
                  {WEEKDAYS.map((w, i) => (
                    <option key={w} value={i}>{w}</option>
                  ))}
                </select>
              </Field>
            )}
            {v.schedule.kind === "monthly" && (
              <Field label="Dia do mês" htmlFor={ids.day} help="De 1 a 28, para existir em todos os meses.">
                <select id={ids.day} className="select" value={v.schedule.day ?? 1} onChange={(e) => setSchedule({ day: Number(e.target.value) })}>
                  {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </Field>
            )}
            {v.schedule.kind === "once" && (
              <Field label="Data" htmlFor={ids.date}>
                <DateInput id={ids.date} value={v.schedule.date ?? ""} onChange={(e) => setSchedule({ date: e.target.value })} />
              </Field>
            )}
            <Field label="Horário" htmlFor={ids.time}>
              <input id={ids.time} type="time" className="input" value={v.schedule.time} onChange={(e) => setSchedule({ time: e.target.value })} />
            </Field>
            <Field label="Fuso horário" htmlFor={ids.tz}>
              <input id={ids.tz} className="input" list={ids.tzList} value={v.timezone} onChange={(e) => setV({ ...v, timezone: e.target.value })} />
              <datalist id={ids.tzList}>
                {TIMEZONES.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </Field>
          </div>
        </fieldset>

        <fieldset className="stack" style={{ gap: 10 }}>
          <legend className="field-label">Se o servidor estiver desligado no horário</legend>
          {(["run_once", "skip"] as MissedPolicy[]).map((p) => (
            <label key={p} className="check">
              <input type="radio" name="missed" checked={v.missed_policy === p} onChange={() => setV({ ...v, missed_policy: p })} />
              <span>{p === "run_once" ? "Rodar uma vez quando voltar" : "Pular a execução perdida"}</span>
            </label>
          ))}
        </fieldset>

        <div className="stack" style={{ gap: 10 }}>
          <label className="check">
            <input type="checkbox" checked={v.use_panel} onChange={(e) => setV({ ...v, use_panel: e.target.checked })} />
            <span>
              Usar o painel de especialistas
              <span className="help muted tiny" style={{ display: "block" }}>Análise mais completa, com Auditor; consome mais do seu provedor de IA.</span>
            </span>
          </label>
          <label className="check">
            <input type="checkbox" checked={v.active} onChange={(e) => setV({ ...v, active: e.target.checked })} />
            <span>Ativa</span>
          </label>
        </div>

        <p className="small muted">Resumo: {describeSchedule(v.schedule)} ({v.timezone}).</p>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Salvando…" : isNew ? "Criar rotina" : "Salvar alterações"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </Card>
  );
}
