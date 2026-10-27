// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { getDiagnosis, getGoals, getInbox, getLatestSnapshot, markInboxRead } from "../api/endpoints";
import type { Diagnosis, Goal, GuidanceStage, RoutineRun, Snapshot } from "../api/types";
import { FlowDiagram, type FlowItem } from "../components/FlowDiagram";
import { BrandMark, Icon, type IconName } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { RollingNumber } from "../components/RollingNumber";
import {
  Badge,
  Card,
  Disclaimer,
  ErrorNotice,
  FirstSnapshotCTA,
  Loading,
  Notice,
  PageHeader,
  ProgressRing,
  Tag,
} from "../components/ui";
import { useApp } from "../lib/appContext";
import { daysSince, formatDate, formatDateTime, relativeDays } from "../lib/dates";
import { GOAL_STATUS, RUN_STATUS, STAGE_LABEL, STAGE_ORDER } from "../lib/labels";
import {
  addDecimals,
  formatBRL,
  formatNumberBR,
  formatPct,
  formatPercentPoints,
  isNegative,
  ratioDecimal,
  subtractDecimals,
  toChartNumber,
} from "../lib/money";
import { useAsync } from "../lib/useAsync";

const STALE_DAYS = 35;

/** Rótulos curtos e ícones da escada de prioridades (o nome completo fica no título do painel). */
const STAGE_TILE: Record<GuidanceStage, { name: string; icon: IconName }> = {
  sem_recurso_disponivel: { name: "Recurso", icon: "coins" },
  organizar_orcamento: { name: "Orçamento", icon: "sliders" },
  priorizar_divida: { name: "Dívidas", icon: "card" },
  construir_reserva: { name: "Reserva", icon: "shield" },
  investir_para_metas: { name: "Metas", icon: "trend" },
};

export function OverviewPage() {
  const app = useApp();
  const diag = useAsync<Diagnosis | null>(async () => {
    try {
      const d = await getDiagnosis();
      if (d.guidance.disclaimer) app.setDisclaimer(d.guidance.disclaimer);
      return d;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  }, []);
  const snapshot = useAsync(getLatestSnapshot, []);
  const goals = useAsync(getGoals, []);
  const inbox = useAsync(getInbox, []);

  const d = diag.data;
  const age = d ? daysSince(d.as_of) : null;
  const stale = app.status?.data.stale || (age !== null && age > STALE_DAYS);

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Visão geral"
        title="Sua posição hoje"
        lede={
          d ? (
            <>
              Dados de <strong>{formatDate(d.as_of)}</strong> ({relativeDays(d.as_of)}). Todos os números vêm do motor
              financeiro, calculados a partir do seu último retrato.
            </>
          ) : undefined
        }
      />

      {diag.loading && !diag.data && <Loading />}
      <ErrorNotice error={diag.error} onRetry={diag.reload} />

      {stale && d && (
        <Notice tone="warning" title="Dados desatualizados.">
          O último retrato é de {formatDate(d.as_of)}. Atualize renda, despesas e dívidas para que o diagnóstico reflita o
          mês atual. <Link to="/vida-financeira">Atualizar agora</Link>
        </Notice>
      )}

      {diag.data === null && !diag.loading && <FirstSnapshotCTA what="sua visão geral" />}

      {d && (
        <>
          <Hero d={d} />
          <NextStep d={d} />
          <div className="split">
            <FlowCard d={d} snapshot={snapshot.data} loading={snapshot.loading} />
            <div className="stack">
              <AttentionCard d={d} goals={goals.data ?? []} inbox={inbox.data ?? []} stale={!!stale} />
              {d.guidance.checklist.length > 0 && <ChecklistCard items={d.guidance.checklist} asOf={d.as_of} />}
            </div>
          </div>
          {d.guidance.allocation.length > 0 && <AllocationCard d={d} />}
        </>
      )}

      <div className="grid-2">
        <GoalsCard goals={goals.data} loading={goals.loading} error={goals.error} />
        <InboxCard
          runs={inbox.data}
          loading={inbox.loading}
          onRead={async (id) => {
            await markInboxRead(id);
            inbox.setData((prev) => (prev ?? []).map((r) => (r.id === id ? { ...r, read: true } : r)));
            void app.refresh();
          }}
        />
      </div>

      {d && <Disclaimer text={d.guidance.disclaimer} />}
    </div>
  );
}

// ---------------------------------------------------------------- Herói

function Hero({ d }: { d: Diagnosis }) {
  const net = subtractDecimals(d.reserve.current, d.total_debt);
  const netNeg = !!net && isNegative(net);
  const fcfNeg = isNegative(d.free_cash_flow);
  const stepIdx = STAGE_ORDER.indexOf(d.guidance.stage);
  return (
    <section className="hero reveal" aria-labelledby="hero-title">
      <div className="hero-main">
        <div className="hero-label">
          <span id="hero-title">Posição líquida</span>
          <Tag>{formatDate(d.as_of)}</Tag>
          {netNeg && (
            <Badge tone="critical" icon="alert">
              Negativa
            </Badge>
          )}
        </div>
        <RollingNumber
          value={formatBRL(net)}
          className="hero-figure"
          // Cabe em qualquer largura: o corpo diminui conforme o número de caracteres.
          style={{ fontSize: `clamp(1.6rem, ${(100 / (Math.max(8, formatBRL(net).length) * 0.6)).toFixed(2)}cqi, 4.1rem)` }}
        />
        <div className="hero-pill">
          <span>
            Reserva <strong className="num">{formatBRL(d.reserve.current)}</strong>
          </span>
          <span className="sep" aria-hidden="true" />
          <span>
            Dívidas <strong className="num">{formatBRL(d.total_debt)}</strong>
          </span>
        </div>
        <div className="hero-actions">
          <Link className="btn btn-primary" to="/vida-financeira">
            <Icon name="plus" />
            Novo retrato
          </Link>
          <Link className="btn btn-secondary" to="/mentor">
            <Icon name="chat" />
            Conversar com o mentor
          </Link>
        </div>
        <dl className="hero-stats">
          <div>
            <dt>Fluxo livre no mês</dt>
            <dd className={fcfNeg ? "neg" : ""}>
              {formatBRL(d.free_cash_flow)}
              <small>{fcfNeg ? "As saídas superam a renda" : "Renda menos despesas e parcelas"}</small>
            </dd>
          </div>
          <div>
            <dt>Dívidas</dt>
            <dd>
              {formatBRL(d.total_debt)}
              <small>
                {d.debt_commitment_ratio !== null
                  ? `${formatPct(d.debt_commitment_ratio)} da renda em parcelas`
                  : "Sem parcelas informadas"}
              </small>
            </dd>
          </div>
          <div>
            <dt>Etapa</dt>
            <dd>
              {stepIdx + 1} de {STAGE_ORDER.length}
              <small>{STAGE_TILE[d.guidance.stage]?.name ?? d.guidance.stage}</small>
            </dd>
          </div>
        </dl>
      </div>
      <div className="hero-side">
        <LastroCard d={d} />
      </div>
    </section>
  );
}

/** O "cartão" do lastro: a reserva de emergência em metal escovado, um segmento por mês da meta. */
function LastroCard({ d }: { d: Diagnosis }) {
  const r = d.reserve;
  const cov = r.coverage_months !== null ? toChartNumber(r.coverage_months) : 0;
  const months = Math.max(1, r.target_months);
  return (
    <section className="lastro-card" aria-label="Reserva de emergência">
      <span className="lc-lines" aria-hidden="true" />
      <div className="lc-top">
        <span className="lc-brand">
          <BrandMark />
          Lastro
        </span>
        {r.complete ? <Badge tone="good">Completa</Badge> : <Badge tone="warning">Em construção</Badge>}
      </div>
      <div className="lc-figure">
        <span className="lc-label">Reserva de emergência</span>
        <span className="lc-value">
          <span className="num">{formatBRL(r.current)}</span>{" "}
          <small>
            {r.coverage_months !== null ? formatNumberBR(r.coverage_months, 1) : "—"} de {r.target_months} meses
          </small>
        </span>
      </div>
      <div
        className="lc-segs"
        role="meter"
        aria-label={`Reserva cobre ${r.coverage_months !== null ? formatNumberBR(r.coverage_months, 1) : "0"} de ${r.target_months} meses de despesas essenciais`}
        aria-valuemin={0}
        aria-valuemax={r.target_months}
        aria-valuenow={Math.min(cov, r.target_months)}
      >
        {Array.from({ length: months }, (_, k) => (
          <span key={k} className="lc-seg">
            <span style={{ width: `${Math.max(0, Math.min(1, cov - k)) * 100}%` }} />
          </span>
        ))}
      </div>
      <div className="lc-foot">
        {r.coverage_months === null ? (
          <span>Sem despesas essenciais informadas, não há como medir a cobertura.</span>
        ) : (
          <>
            <span>
              Meta <strong>{formatBRL(r.target_amount)}</strong>
            </span>
            <span>
              Falta <strong>{formatBRL(r.gap)}</strong>
            </span>
          </>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- Próximo passo

function NextStep({ d }: { d: Diagnosis }) {
  const g = d.guidance;
  const stepIdx = Math.max(0, STAGE_ORDER.indexOf(g.stage));
  const pos = STAGE_ORDER.length > 1 ? (stepIdx / (STAGE_ORDER.length - 1)) * 100 : 0;
  return (
    <Card
      className="accent"
      eyebrow="Próximo passo"
      title={STAGE_LABEL[g.stage] ?? g.stage}
      aside={<Tag>Etapa {stepIdx + 1} de {STAGE_ORDER.length}</Tag>}
      footer={
        <>
          <span>{g.follow_up || "Revise o retrato no começo do próximo mês."}</span>
          <Link className="btn btn-primary btn-sm" to="/mentor">
            <Icon name="chat" />
            Conversar com o mentor
          </Link>
        </>
      }
    >
      <div className="stack" style={{ gap: 22 }}>
        <p className="next-sentence">{g.next_step}</p>
        <div className="stack" style={{ gap: 10 }}>
          <ol className="stages" aria-label="Escada de prioridades">
            {STAGE_ORDER.map((s, i) => {
              const tile = STAGE_TILE[s];
              const state = i < stepIdx ? "done" : i === stepIdx ? "current" : "next";
              return (
                <li key={s} className={`stage ${state}`} aria-current={i === stepIdx ? "step" : undefined} title={STAGE_LABEL[s]}>
                  <span className="stage-tile" aria-hidden="true">
                    <Icon name={tile.icon} />
                  </span>
                  <span className="stage-name">{tile.name}</span>
                  <span className="stage-sub">Etapa {i + 1}</span>
                  <span className="visually-hidden">
                    {STAGE_LABEL[s]}
                    {state === "done" ? " (superada)" : state === "current" ? " (etapa atual)" : ""}
                  </span>
                </li>
              );
            })}
          </ol>
          <div className="stage-track" aria-hidden="true">
            <span style={{ width: `${pos}%` }} />
            <i style={{ left: `${pos}%` }} />
          </div>
        </div>
        {g.situation.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <div className="row between">
              <span className="eyebrow">Situação do mês</span>
              <span className="tag plain">{g.situation.length === 1 ? "1 ponto" : `${g.situation.length} pontos`}</span>
            </div>
            <ol className="log" aria-label="Situação do mês">
              {g.situation.map((s, i) => (
                <li key={i} style={{ animationDelay: `${120 + i * 70}ms` }}>
                  <span className="log-t">{String(i + 1).padStart(2, "0")}</span>
                  <span className="log-dot" style={{ ["--c" as string]: "var(--gold-mark)" }} aria-hidden="true" />
                  <span>{s}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- Fluxo do mês

function FlowCard({ d, snapshot, loading }: { d: Diagnosis; snapshot: Snapshot | null | undefined; loading: boolean }) {
  const s = snapshot;
  const income = s?.net_monthly_income ?? null;
  const usable = !!s && s.as_of === d.as_of && !!income && toChartNumber(income) > 0;

  let items: FlowItem[] = [];
  let committed: string | null = null;
  if (usable && s && income) {
    const payments = s.debts.length ? (addDecimals(...s.debts.map((x) => x.monthly_payment)) ?? "0") : "0";
    const fcf = d.free_cash_flow;
    const deficit = isNegative(fcf);
    const free = deficit ? (subtractDecimals("0", fcf) ?? "0") : fcf;
    const share = (v: string) => ratioDecimal(v, income, 4);
    const mk = (key: string, label: string, value: string, color: string, suffix = "da renda"): FlowItem => {
      const sh = share(value);
      return {
        key,
        label,
        valueText: formatBRL(value),
        shareText: `${formatPct(sh, 1)} ${suffix}`,
        weight: toChartNumber(sh),
        color,
      };
    };
    items = [
      mk("essential", "Essenciais", s.essential_expenses, "var(--flow-1)"),
      mk("debt", "Parcelas", payments, "var(--flow-2)"),
      mk("variable", "Variáveis", s.variable_expenses, "var(--flow-3)"),
      deficit
        ? mk("deficit", "Déficit", free, "var(--critical)", "acima da renda")
        : mk("free", "Livre", free, "var(--flow-4)"),
    ];
    committed = share(addDecimals(s.essential_expenses, payments) ?? "0");
  }

  return (
    <Card
      eyebrow="Fluxo do mês"
      title="Para onde vai sua renda"
      aside={<Icon name="flow" style={{ width: 18, height: 18, color: "var(--muted)" }} />}
      footer={
        <>
          <span>Livre = renda − essenciais − variáveis − parcelas</span>
          <Link className="link-arrow" to="/vida-financeira">
            Atualizar retrato
            <Icon name="arrow" />
          </Link>
        </>
      }
    >
      {loading && !s && <Loading />}
      {!loading && !usable && (
        <p className="small muted">O fluxo aparece quando o último retrato tem renda informada.</p>
      )}
      {usable && income && (
        <div className="stack" style={{ gap: 16 }}>
          <div className="stack" style={{ gap: 6 }}>
            <div className="eyebrow">Renda líquida</div>
            <div className="big-figure">
              <span className="bf-value">{formatBRL(income)}</span>
              <span className="bf-unit">/ mês</span>
            </div>
            <div className="flow-stats">
              <span>
                Comprometido <b>{formatPct(committed, 1)}</b>
              </span>
              <span>·</span>
              <span>
                Parcelas{" "}
                <b>{d.debt_commitment_ratio !== null ? formatPct(d.debt_commitment_ratio, 1) : "—"}</b>
              </span>
              <span>·</span>
              <span>
                Livre <b className={isNegative(d.free_cash_flow) ? "neg" : ""}>{formatBRL(d.free_cash_flow)}</b>
              </span>
            </div>
          </div>
          <FlowDiagram
            source="Renda"
            items={items}
            caption={`Renda de ${formatBRL(income)} dividida entre ${items.map((i) => `${i.label} ${i.valueText}`).join(", ")}.`}
          />
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- Pendências

function AttentionCard({
  d,
  goals,
  inbox,
  stale,
}: {
  d: Diagnosis;
  goals: Goal[];
  inbox: RoutineRun[];
  stale: boolean;
}) {
  const { status } = useApp();
  const items: { text: string; to?: string; tone: "warning" | "serious" | "critical" | "neutral" }[] = [];
  if (stale) items.push({ text: "Retrato financeiro desatualizado.", to: "/vida-financeira", tone: "warning" });
  if (isNegative(d.free_cash_flow)) items.push({ text: "Orçamento do mês está negativo.", to: "/vida-financeira", tone: "critical" });
  for (const m of d.guidance.missing_information) items.push({ text: `Falta informar: ${m}`, to: "/vida-financeira", tone: "neutral" });
  for (const g of goals.filter((g) => g.status !== "no_rumo"))
    items.push({ text: `Meta "${g.name}": ${GOAL_STATUS[g.status].label.toLowerCase()}.`, to: "/metas", tone: g.status === "revisar" ? "serious" : "warning" });
  const failed = inbox.filter((r) => r.status === "failed" && !r.read).length;
  if (failed) items.push({ text: `${failed} rotina(s) falharam.`, to: "/rotinas", tone: "critical" });
  const unread = inbox.filter((r) => !r.read && r.status !== "failed").length;
  if (unread) items.push({ text: `${unread} resultado(s) de rotina não lido(s).`, to: "/rotinas", tone: "neutral" });
  if (status?.mentor.limit_until)
    items.push({ text: `Mentor em pausa pelo limite do provedor de IA até ${formatDateTime(status.mentor.limit_until)}.`, tone: "warning" });
  if (status && status.mentor.available && status.mentor.ai_configured === false)
    items.push({ text: "Nenhum provedor de IA conectado: o Mentor e os especialistas estão parados.", to: "/configuracoes", tone: "warning" });
  else if (status && status.mentor.available && status.mentor.logged_in === false)
    items.push({ text: "O Claude Code do servidor está sem login.", to: "/configuracoes", tone: "warning" });

  return (
    <Card title="O que precisa de atenção" eyebrow="Pendências" aside={<Tag>{items.length}</Tag>}>
      {items.length === 0 ? (
        <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
          <span className="status-dot good" style={{ marginTop: 7 }} aria-hidden="true" />
          <p className="small muted">Nada pendente agora. Revise o retrato no começo do próximo mês.</p>
        </div>
      ) : (
        <ul className="attn">
          {items.map((it, i) => (
            <li key={i}>
              <span className={`status-dot ${it.tone === "neutral" ? "" : it.tone}`} aria-hidden="true" />
              {it.to ? <Link to={it.to}>{it.text}</Link> : <span>{it.text}</span>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- Checklist

function readChecks(key: string): number[] {
  try {
    const raw = window.localStorage.getItem(key);
    const v: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x): x is number => Number.isInteger(x)) : [];
  } catch {
    return [];
  }
}

/** Checklist do mês, marcável. As marcações são só uma conveniência deste navegador. */
function ChecklistCard({ items, asOf }: { items: string[]; asOf: string }) {
  const key = `lastro.checklist.${asOf}`;
  const [done, setDone] = useState<number[]>(() => readChecks(key));
  useEffect(() => setDone(readChecks(key)), [key]);

  function toggle(i: number) {
    setDone((prev) => {
      const next = prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i];
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* armazenamento indisponível: a marcação vale só nesta visita */
      }
      return next;
    });
  }

  const count = items.filter((_, i) => done.includes(i)).length;
  return (
    <Card
      eyebrow="Para fazer"
      title="Checklist do mês"
      aside={
        <ProgressRing value={count} max={items.length} segments={items.length} size={36} stroke={3.2}
          label={`${count} de ${items.length} itens concluídos`}>
          {count}
        </ProgressRing>
      }
      footer={<span>As marcações ficam só neste navegador.</span>}
    >
      <ul className="checklist">
        {items.map((c, i) => {
          const on = done.includes(i);
          return (
            <li key={i} className={on ? "done" : ""}>
              <button type="button" role="checkbox" aria-checked={on} className="ck-item" onClick={() => toggle(i)}>
                <span className="ck" aria-hidden="true">
                  <Icon name="check" />
                </span>
                <span className="ck-text">{c}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

// ---------------------------------------------------------------- Sugestão de destino

function AllocationCard({ d }: { d: Diagnosis }) {
  const g = d.guidance;
  return (
    <Card
      title="Sugestão de destino do recurso disponível"
      eyebrow="Diagnóstico do mês"
      footer={<span>É uma sugestão do motor, não uma ordem. Você decide o que fazer.</span>}
    >
      <div className="stack">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Destino</th>
                <th className="num">Participação</th>
                <th className="num">Valor</th>
              </tr>
            </thead>
            <tbody>
              {g.allocation.map((a, i) => (
                <tr key={i}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{a.purpose}</div>
                    <div className="tiny muted">{a.rationale}</div>
                  </td>
                  <td className="num">
                    <span className="row" style={{ justifyContent: "flex-end", flexWrap: "nowrap", gap: 10 }}>
                      <span className="sharebar" aria-hidden="true">
                        <span style={{ width: `${Math.max(0, Math.min(100, toChartNumber(a.percent)))}%`, ["--c" as string]: "var(--gold-mark)" }} />
                      </span>
                      {formatPercentPoints(a.percent)}
                    </span>
                  </td>
                  <td className="num" style={{ fontWeight: 600 }}>{formatBRL(a.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(g.comparisons.length > 0 || g.premises.length > 0 || g.notes.length > 0) && (
          <details>
            <summary>Comparações, premissas e notas</summary>
            <div className="stack small">
              {g.comparisons.length > 0 && (
                <ul className="bullets">
                  {g.comparisons.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              )}
              {g.premises.length > 0 && (
                <div>
                  <div className="eyebrow" style={{ marginBottom: 6 }}>Premissas</div>
                  <ul className="bullets">
                    {g.premises.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}
              {g.notes.length > 0 && (
                <ul className="bullets muted">
                  {g.notes.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              )}
            </div>
          </details>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- Metas e rotinas

function GoalsCard({ goals, loading, error }: { goals: Goal[] | undefined; loading: boolean; error: ApiError | null }) {
  return (
    <Card
      title="Metas"
      eyebrow="Progresso"
      aside={
        <Link className="link-arrow" to="/metas">
          Ver todas
          <Icon name="arrow" />
        </Link>
      }
    >
      {loading && !goals && <Loading />}
      <ErrorNotice error={error} />
      {goals && goals.length === 0 && (
        <p className="small muted">
          Nenhuma meta ainda. <Link to="/metas">Criar a primeira meta</Link>
        </p>
      )}
      {goals && goals.length > 0 && (
        <ul className="list">
          {goals.slice(0, 4).map((g) => {
            const cur = toChartNumber(g.current_amount);
            const tgt = toChartNumber(g.target_real_value);
            const pct = tgt > 0 ? Math.max(0, Math.min(100, Math.round((cur / tgt) * 100))) : 0;
            return (
              <li key={g.id} className="goal-row">
                <ProgressRing value={cur} max={tgt} size={40} label={`Progresso da meta ${g.name}`}>
                  <span style={{ fontSize: 10.5 }}>{pct}%</span>
                </ProgressRing>
                <div style={{ minWidth: 0 }}>
                  <div className="goal-name">{g.name}</div>
                  <div className="goal-sub">
                    {formatBRL(g.current_amount)} de {formatBRL(g.target_real_value)} · prazo {formatDate(g.deadline)}
                  </div>
                </div>
                <Badge tone={GOAL_STATUS[g.status].tone}>{GOAL_STATUS[g.status].label}</Badge>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function InboxCard({
  runs,
  loading,
  onRead,
}: {
  runs: RoutineRun[] | undefined;
  loading: boolean;
  onRead: (id: string) => Promise<void>;
}) {
  const unread = runs?.filter((r) => !r.read).length ?? 0;
  return (
    <Card
      title="Resultados das rotinas"
      eyebrow="Caixa de entrada"
      aside={
        <span className="row" style={{ gap: 10 }}>
          {unread > 0 && <Tag>{unread} novo(s)</Tag>}
          <Link className="link-arrow" to="/rotinas">
            Rotinas
            <Icon name="arrow" />
          </Link>
        </span>
      }
    >
      {loading && !runs && <Loading />}
      {runs && runs.length === 0 && <p className="small muted">Nenhum resultado ainda. Crie uma rotina para o mentor acompanhar algo por você.</p>}
      {runs && runs.length > 0 && (
        <ul className="list">
          {runs.slice(0, 5).map((r) => (
            <li key={r.id} className="stack" style={{ gap: 8 }}>
              <div className="row between">
                <span className="row small" style={{ gap: 8 }}>
                  {!r.read && <span className="unread-dot" role="img" aria-label="Não lido" />}
                  <span className="mono muted">{formatDateTime(r.finished_at ?? r.started_at ?? r.scheduled_for)}</span>
                </span>
                <Badge tone={RUN_STATUS[r.status].tone}>{RUN_STATUS[r.status].label}</Badge>
              </div>
              {r.summary && (
                <div className="small" style={{ maxHeight: 120, overflow: "hidden" }}>
                  <Markdown text={r.summary} />
                </div>
              )}
              <div className="row" style={{ gap: 4 }}>
                {r.conversation_id && (
                  <Link className="btn btn-ghost btn-sm" to={`/mentor/${r.conversation_id}`} onClick={() => !r.read && void onRead(r.id)}>
                    Abrir conversa
                  </Link>
                )}
                {!r.read && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onRead(r.id)}>
                    Marcar como lido
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
