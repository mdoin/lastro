// SPDX-License-Identifier: AGPL-3.0-or-later
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  addOutcome,
  addRevision,
  confirmDraft,
  createManualDecision,
  discardDraft,
  discussDecision,
  getDiary,
  getReviewContext,
  postponeDraft,
  setReviewPlan,
} from "../api/endpoints";
import { getLabJournal } from "../api/lab";
import { DECISION_LABEL, type Decision as RadarDecision } from "../api/radar";
import type { DecisionDraft, DiaryDecision, DraftContent, FinancialContext } from "../api/types";
import { DateInput } from "../components/DateInput";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { Badge, Card, EmptyState, ErrorNotice, Loading, MoneyField, Notice, PageHeader, Segmented, parseFields } from "../components/ui";
import { useApp } from "../lib/appContext";
import { formatDate, formatDateTime, todayISO } from "../lib/dates";
import { STAGE_LABEL } from "../lib/labels";
import { formatBRL } from "../lib/money";
import { errorMessage, useAsync } from "../lib/useAsync";
import "../styles/radar.css";
import "../styles/diary.css";

type View = "decisoes" | "radar" | "resultados" | "historico";
type Mode = "registro" | "revisar" | "resultado";

const newId = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
const REVIEW_OPTIONS = [["", "Não agendar"], ["1", "Em 1 mês"], ["3", "Em 3 meses"], ["6", "Em 6 meses"], ["12", "Em 12 meses"]] as const;

/** Uma ação assíncrona com estado de ocupado e erro, para os formulários curtos desta tela. */
function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, setError, run };
}

export function DecisionsPage() {
  const app = useApp();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const diary = useAsync(getDiary, []);
  const [openDraft, setOpenDraft] = useState<string | null>(params.get("rascunho"));
  const [active, setActive] = useState<{ id: string; mode: Mode } | null>(null);
  const [manual, setManual] = useState(false);
  const [view, setView] = useState<View>("decisoes");
  const d = diary.data;
  const today = d?.today ?? todayISO();
  const pending = (d?.drafts ?? []).filter((x) => x.status === "pendente" || x.status === "adiado");
  const returning = pending.filter((x) => x.status === "adiado" && x.remind_on && x.remind_on <= today);
  const waiting = pending.filter((x) => !returning.includes(x));

  const shown = useMemo(() => {
    const all = d?.decisions ?? [];
    if (view === "radar") return all.filter((x) => x.opportunity_id);
    if (view === "resultados") return all.filter((x) => x.entries.some((e) => e.kind === "resultado"));
    return all;
  }, [d, view]);

  async function discuss(id: string) {
    try {
      const conv = await discussDecision(id);
      navigate(`/mentor/${conv.id}`);
    } catch (err) {
      app.toast(errorMessage(err), "error");
    }
  }

  function changed(message?: string) {
    if (message) app.toast(message);
    void diary.reload();
  }

  return (
    <div className="stack-lg">
      <PageHeader
        eyebrow="Diário de decisões"
        title="O que discutimos, e o que você decidiu"
        lede="O Conselho prepara os registros; você confirma. Nada vira decisão sem a sua confirmação, e o que foi confirmado não é editado: mudanças viram revisões ligadas ao original."
        actions={
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setManual((v) => !v)} aria-expanded={manual}>
            <Icon name="edit" />
            Registro manual
          </button>
        }
      />

      {manual && <ManualForm onCancel={() => setManual(false)} onDone={() => { setManual(false); changed("Decisão registrada."); }} />}

      {diary.loading && !d && <Loading />}
      <ErrorNotice error={diary.error} onRetry={diary.reload} />
      <LabAnalyses />

      {d && (d.due_reviews.length > 0 || returning.length > 0) && (
        <Card title="Revisões pendentes" eyebrow="O Lastro pergunta">
          <ul className="diary-list">
            {d.due_reviews.map((r) => (
              <li key={r.decision_id} className="diary-ask">
                <p>{r.pergunta}</p>
                <div className="row">
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => { setView("decisoes"); setActive({ id: r.decision_id, mode: "revisar" }); }}>
                    <Icon name="refresh" /> Revisar agora
                  </button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => void discuss(r.decision_id)}>
                    <Icon name="chat" /> Discutir com o Mentor
                  </button>
                </div>
              </li>
            ))}
            {returning.map((x) => (
              <li key={x.id} className="diary-ask">
                <p>Você adiou “{x.content.titulo}” para {formatDate(x.remind_on)}. Quer decidir agora?</p>
                <div className="row">
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => setOpenDraft(x.id)}>Ver rascunho</button>
                </div>
                {openDraft === x.id && <DraftReview draft={x} onDone={changed} />}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {d && (
        <Card title="Rascunhos do Conselho" eyebrow={waiting.length ? `${waiting.length} aguardando você` : "Nada pendente"}
          aside={<Icon name="layers" style={{ width: 18, height: 18, color: "var(--muted)" }} />}>
          {waiting.length === 0 ? (
            <p className="small muted">
              Quando uma conversa com o Mentor ou o Conselho chegar a uma decisão, o rascunho aparece aqui. Em qualquer resposta
              da equipe você também pode tocar em <strong>Registrar no Diário</strong>.
            </p>
          ) : (
            <ul className="diary-list">
              {waiting.map((x) => (
                <li key={x.id} className="diary-draft">
                  <div className="row between">
                    <span className="row" style={{ gap: 6 }}>
                      <Badge tone="neutral" icon="layers">Proposta · {x.content.sintese.agente}</Badge>
                      {x.review_of_id && <Badge tone="neutral" icon="refresh">Revisão</Badge>}
                      {x.content.radar && <Badge tone="neutral" icon="pulse">Radar · {x.content.radar.ativo}</Badge>}
                      {x.status === "adiado" && <Badge tone="warning" icon="clock">Adiado{x.remind_on ? ` até ${formatDate(x.remind_on)}` : ""}</Badge>}
                    </span>
                    <span className="mono tiny muted">{formatDateTime(x.created_at)}</span>
                  </div>
                  <h2 className="diary-title">{x.content.titulo}</h2>
                  <p className="small muted">
                    {x.content.recomendada !== null && x.content.alternativas[x.content.recomendada]
                      ? `A análise favorece: ${x.content.alternativas[x.content.recomendada]!.titulo}. `
                      : ""}
                    {x.content.alternativas.length} alternativa(s) · {x.content.pareceres.length} parecer(es) ·{" "}
                    {x.content.auditoria ? `auditoria ${x.content.auditoria.verdict}` : "sem auditoria"}
                  </p>
                  <div>
                    <button type="button" className="btn btn-primary btn-sm" aria-expanded={openDraft === x.id}
                      onClick={() => setOpenDraft(openDraft === x.id ? null : x.id)}>
                      {openDraft === x.id ? "Fechar" : "Revisar e confirmar"}
                    </button>
                  </div>
                  {openDraft === x.id && <DraftReview draft={x} onDone={changed} />}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {d && (
        <Card title="Memória de decisões" eyebrow={`${d.decisions.length} decisão(ões) confirmada(s)`}
          aside={d.chain.ok
            ? <Badge tone="good" icon="lock">Registro íntegro · {d.chain.registros}</Badge>
            : <Badge tone="critical" icon="alert">Registro alterado fora do Lastro (nº {d.chain.falhas.join(", ")})</Badge>}>
          <div className="stack">
            <Segmented label="Mostrar" value={view} onChange={setView} variant="mono" options={[
              { value: "decisoes", label: "Decisões" },
              { value: "radar", label: "Oportunidades" },
              { value: "resultados", label: "Resultados" },
              { value: "historico", label: "Histórico" },
            ]} />
            {view === "historico" ? (
              <History drafts={d.drafts} decisions={d.decisions} />
            ) : shown.length === 0 ? (
              <EmptyState icon="book" title={view === "decisoes" ? "Nenhuma decisão confirmada" : "Nada por aqui ainda"}>
                {view === "radar" ? "Decisões ligadas a sinais do Radar aparecem aqui, com o que aconteceu depois."
                  : view === "resultados" ? "Registre o que aconteceu depois de uma decisão para comparar com o que foi pensado."
                  : "Converse com o Mentor ou leve uma questão ao Conselho; os rascunhos aparecem acima para você confirmar."}
              </EmptyState>
            ) : (
              <ol className="timeline">
                {shown.map((x) => (
                  <DecisionItem key={x.id} d={x} mode={active?.id === x.id ? active.mode : null}
                    setMode={(mode) => setActive(mode ? { id: x.id, mode } : null)} onChanged={changed} onDiscuss={() => void discuss(x.id)} />
                ))}
              </ol>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Registro (o que os agentes prepararam)

const CONTEXT_ROWS: [keyof FinancialContext, string, boolean][] = [
  ["net_monthly_income", "Renda líquida", true],
  ["essential_expenses", "Despesas essenciais", true],
  ["variable_expenses", "Despesas variáveis", true],
  ["liquid_reserve", "Reserva", true],
  ["reserve_coverage_months", "Meses cobertos pela reserva", false],
  ["total_debt", "Dívidas", true],
  ["free_cash_flow", "Sobra do mês", true],
  ["available_this_month", "Disponível no mês", true],
];

function ContextTable({ ctx }: { ctx: FinancialContext | null | undefined }) {
  if (!ctx) return <p className="small muted">Sem retrato financeiro registrado.</p>;
  return (
    <dl className="kv small">
      <dt>Retrato de</dt>
      <dd>{formatDate(ctx.as_of)}</dd>
      {CONTEXT_ROWS.filter(([k]) => ctx[k] !== undefined && ctx[k] !== null).map(([k, label, money]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{label}</dt>
          <dd className="mono">{money ? formatBRL(String(ctx[k])) : String(ctx[k])}</dd>
        </div>
      ))}
      {ctx.stage && (<><dt>Etapa</dt><dd>{STAGE_LABEL[ctx.stage]}</dd></>)}
    </dl>
  );
}

function Section({ label, children, empty }: { label: string; children?: ReactNode; empty?: boolean }) {
  return (
    <div className="diary-section">
      <span className="eyebrow">{label}</span>
      {empty ? <p className="small muted">Não apareceu na conversa.</p> : children}
    </div>
  );
}

function Bullets({ items }: { items: string[] }) {
  return <ul className="bullets small">{items.map((t, i) => <li key={i}>{t}</li>)}</ul>;
}

/** O registro preparado pelos agentes, como era no momento: nunca editado. */
function RecordView({ c, at }: { c: DraftContent; at: string }) {
  return (
    <section className="radar-known" aria-label="Registro preparado pelos agentes">
      <div className="radar-era"><Icon name="lock" /> Preparado em {formatDateTime(at)} · registro original</div>
      <Section label={c.pergunta_de === "pessoa" ? "Sua pergunta" : "Ponto de partida (Lastro Radar)"}>
        <p className="small" style={{ whiteSpace: "pre-wrap" }}>{c.pergunta_original || "—"}</p>
      </Section>
      <Section label="Contexto financeiro na época">
        <ContextTable ctx={c.contexto_financeiro} />
        {c.contexto_do_agente && <p className="small">{c.contexto_do_agente}</p>}
      </Section>
      <Section label="Alternativas consideradas" empty={!c.alternativas.length}>
        <ul className="bullets small">
          {c.alternativas.map((a, i) => (
            <li key={i}><strong>{a.titulo}</strong>{a.descricao ? ` — ${a.descricao}` : ""}{c.recomendada === i && <> <span className="tag plain">favorecida pela análise</span></>}</li>
          ))}
        </ul>
      </Section>
      <Section label="Informações utilizadas" empty={!c.informacoes.length}><Bullets items={c.informacoes} /></Section>
      <Section label="Riscos identificados" empty={!c.riscos.length}><Bullets items={c.riscos} /></Section>
      <Section label="Divergências" empty={!c.divergencias}><Markdown text={c.divergencias} /></Section>
      <details className="diary-details">
        <summary>Síntese · {c.sintese.agente}</summary>
        <Markdown text={c.sintese.texto} />
      </details>
      {c.pareceres.map((p, i) => (
        <details key={i} className="diary-details">
          <summary>Parecer · {p.agente}{p.consulta_interna ? " (consulta interna)" : ""}</summary>
          <Markdown text={p.texto} />
        </details>
      ))}
      {c.calculos.length > 0 && (
        <details className="diary-details">
          <summary>{c.calculos.length} cálculo(s) do motor</summary>
          <ul className="bullets small">
            {c.calculos.map((k) => (
              <li key={k.fingerprint}>
                <span className="mono">{k.operacao}</span> ({k.natureza}) · {Object.entries(k.resultado).filter(([, v]) => typeof v !== "object").map(([key, v]) => `${key}: ${String(v)}`).join(" · ")}
                <span className="tiny muted"> · {k.fingerprint.slice(0, 8)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {c.fontes.length > 0 && (
        <details className="diary-details">
          <summary>{c.fontes.length} fonte(s)</summary>
          <ul className="bullets small">
            {c.fontes.map((s, i) => <li key={i}>{s.label}{s.reference_date ? ` · ref. ${formatDate(s.reference_date)}` : ""}</li>)}
          </ul>
        </details>
      )}
      <div className="row" style={{ gap: 8 }}>
        {c.auditoria ? <Badge tone={c.auditoria.verdict === "PASSA" ? "good" : c.auditoria.verdict === "REPROVA" ? "critical" : "warning"} icon="shieldCheck">Auditoria: {c.auditoria.verdict}</Badge>
          : <Badge tone="neutral">Sem auditoria</Badge>}
        <Link className="small" to={`/mentor/${c.conversa.id}`}>Conversa original: {c.conversa.titulo}</Link>
        {c.radar && <Link className="small" to={`/oportunidades/${c.radar.opportunity_id}`}>Sinal do Radar: {c.radar.ativo}</Link>}
      </div>
      {c.auditoria && c.auditoria.reasons.length > 0 && <Bullets items={c.auditoria.reasons} />}
    </section>
  );
}

// ---------------------------------------------------------------- Confirmação

function DraftReview({ draft, onDone }: { draft: DecisionDraft; onDone: (message?: string) => void }) {
  const c = draft.content;
  const hasAlts = c.alternativas.length > 0;
  const [pick, setPick] = useState<number | "outra" | null>(hasAlts ? null : "outra"); // nada pré-marcado: escolha explícita
  const [other, setOther] = useState("");
  const [why, setWhy] = useState("");
  const [fix, setFix] = useState("");
  const [review, setReview] = useState("");
  const [radar, setRadar] = useState("");
  const [postponing, setPostponing] = useState(false);
  const [until, setUntil] = useState("");
  const act = useAction();

  function confirm(e: FormEvent) {
    e.preventDefault();
    if (pick === null) return act.setError("Escolha uma alternativa ou escreva o que você decidiu.");
    if (pick === "outra" && !other.trim()) return act.setError("Escreva o que você decidiu.");
    void act.run(async () => {
      await confirmDraft(draft.id, {
        alternativa: typeof pick === "number" ? pick : null, escolha: pick === "outra" ? other.trim() : "",
        justificativa: why.trim(), correcoes: fix.trim(), review_every_months: review ? Number(review) : null,
        radar_decisao: radar || null,
      });
      onDone(draft.review_of_id ? "Revisão registrada no Diário." : "Decisão registrada no Diário.");
    });
  }

  return (
    <div className="stack diary-review">
      <RecordView c={c} at={draft.created_at} />
      <form className="stack" onSubmit={confirm} noValidate>
        <fieldset className="stack" style={{ gap: 8 }}>
          <legend className="field-label">O que você decidiu?</legend>
          {c.alternativas.map((a, i) => (
            <label key={i} className="diary-option">
              <input type="radio" name={`pick-${draft.id}`} checked={pick === i} onChange={() => setPick(i)} />
              <span><strong>{a.titulo}</strong>{a.descricao && <span className="small muted"> — {a.descricao}</span>}</span>
              {c.recomendada === i && <span className="tag plain">favorecida pela análise</span>}
            </label>
          ))}
          {hasAlts && (
            <label className="diary-option">
              <input type="radio" name={`pick-${draft.id}`} checked={pick === "outra"} onChange={() => setPick("outra")} />
              <span>Outra escolha</span>
            </label>
          )}
          {pick === "outra" && (
            <input className="input" aria-label="Sua decisão" placeholder="Ex.: esperar o próximo mês" value={other}
              onChange={(e) => setOther(e.target.value)} maxLength={500} />
          )}
        </fieldset>
        <label className="field">
          <span className="field-label">Por quê? <span className="muted">(opcional)</span></span>
          <textarea className="textarea" rows={2} value={why} onChange={(e) => setWhy(e.target.value)} maxLength={2000} />
        </label>
        <details className="diary-details">
          <summary>Corrigir alguma informação</summary>
          <p className="tiny muted">O registro dos agentes fica como está; sua correção é guardada ao lado, com o seu nome.</p>
          <textarea className="textarea" rows={2} aria-label="Correções" value={fix} onChange={(e) => setFix(e.target.value)} maxLength={2000} />
        </details>
        <div className="form-grid">
          <label className="field">
            <span className="field-label">Revisar esta decisão</span>
            <select className="select" value={review} onChange={(e) => setReview(e.target.value)}>
              {REVIEW_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          {c.radar && (
            <label className="field">
              <span className="field-label">No Diário de Oportunidades</span>
              <select className="select" value={radar} onChange={(e) => setRadar(e.target.value)}>
                <option value="">Não registrar</option>
                {(Object.keys(DECISION_LABEL) as RadarDecision[]).map((k) => <option key={k} value={k}>{DECISION_LABEL[k]}</option>)}
              </select>
            </label>
          )}
        </div>
        <Notice>Ao confirmar, o registro fica permanente: data, contexto, fontes, pareceres e a sua escolha. Mudanças depois viram revisões.</Notice>
        {c.radar && <Notice tone="warning">Decidir não é executar: registre a operação no Radar só quando ela acontecer.</Notice>}
        {act.error && <Notice tone="error">{act.error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={act.busy}>{act.busy ? "Registrando…" : "Confirmar minha decisão"}</button>
          <button type="button" className="btn btn-ghost" disabled={act.busy} onClick={() => setPostponing((v) => !v)} aria-expanded={postponing}>
            <Icon name="clock" /> Adiar
          </button>
          <button type="button" className="btn btn-ghost" disabled={act.busy}
            onClick={() => void act.run(async () => { await discardDraft(draft.id); onDone("Rascunho descartado (fica no histórico)."); })}>
            <Icon name="x" /> Descartar
          </button>
        </div>
        {postponing && (
          <div className="row">
            <div className="field">
              <label htmlFor={`until-${draft.id}`}>Lembrar em <span className="muted">(opcional)</span></label>
              <DateInput id={`until-${draft.id}`} value={until} onChange={(e) => setUntil(e.target.value)} />
            </div>
            <button type="button" className="btn btn-ghost btn-sm" disabled={act.busy}
              onClick={() => void act.run(async () => { await postponeDraft(draft.id, { until: until || null }); onDone("Decisão adiada."); })}>
              Adiar decisão
            </button>
          </div>
        )}
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- Decisões confirmadas

function DecisionItem({ d, mode, setMode, onChanged, onDiscuss }: {
  d: DiaryDecision; mode: Mode | null; setMode: (m: Mode | null) => void; onChanged: (message?: string) => void; onDiscuss: () => void;
}) {
  const origin = d.entries[0]!.payload;
  const results = d.entries.filter((e) => e.kind === "resultado");
  const author = origin.registro?.sintese.agente;
  const toggle = (m: Mode) => setMode(mode === m ? null : m);
  return (
    <li className={`timeline-item ${d.versao > 1 ? "review" : ""}`}>
      <div className="row between">
        <span className="mono muted">{formatDate(d.created_at)}</span>
        <span className="row" style={{ gap: 6 }}>
          {d.versao > 1 && <Badge tone="neutral" icon="refresh">Versão {d.versao}</Badge>}
          {d.opportunity_id && <Badge tone="neutral" icon="pulse">Radar</Badge>}
          {d.executada ? <Badge tone="good" icon="check">Execução informada</Badge> : null}
          {d.review_plan && <Badge tone="neutral" icon="calendar">Revisar em {formatDate(d.review_plan.next_on)}</Badge>}
          <Badge tone="neutral">{author ? `Proposta de ${author}` : "Registro manual"}</Badge>
        </span>
      </div>
      <h2 style={{ fontSize: "1.04rem" }}>{d.titulo}</h2>
      <div className="decision-choice">
        <span className="eyebrow">Sua decisão</span>
        <strong>{d.escolha}</strong>
        {origin.valor_planejado && <span className="tag">{formatBRL(origin.valor_planejado)}</span>}
      </div>
      {results.length > 0 && <p className="small"><span className="eyebrow">Depois</span> {results[results.length - 1]!.payload.texto}</p>}
      <div className="row" style={{ gap: 4 }}>
        <button type="button" className="btn btn-ghost btn-sm" aria-expanded={mode === "registro"} onClick={() => toggle("registro")}><Icon name="book" /> Registro</button>
        <button type="button" className="btn btn-ghost btn-sm" aria-expanded={mode === "revisar"} onClick={() => toggle("revisar")}><Icon name="refresh" /> Revisar</button>
        <button type="button" className="btn btn-ghost btn-sm" aria-expanded={mode === "resultado"} onClick={() => toggle("resultado")}><Icon name="check" /> O que aconteceu</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onDiscuss}><Icon name="chat" /> Discutir com o Mentor</button>
      </div>
      {mode === "registro" && <DecisionRecord d={d} onChanged={onChanged} />}
      {mode === "revisar" && <RevisionPanel d={d} onDone={(m) => { setMode(null); onChanged(m); }} />}
      {mode === "resultado" && <OutcomeForm d={d} onDone={(m) => { setMode(null); onChanged(m); }} />}
    </li>
  );
}

function DecisionRecord({ d, onChanged }: { d: DiaryDecision; onChanged: (message?: string) => void }) {
  const [first, ...later] = d.entries;
  const p = first!.payload;
  const act = useAction();
  return (
    <div className="stack diary-review">
      {p.registro ? <RecordView c={p.registro} at={first!.created_at} /> : (
        <section className="radar-known" aria-label="Registro manual">
          <div className="radar-era"><Icon name="lock" /> Registrado por você em {formatDate(p.data ?? first!.created_at)}{p.importado_do_diario_anterior ? " · diário anterior" : ""}</div>
          {p.pergunta && <Section label="Pergunta"><p className="small">{p.pergunta}</p></Section>}
          {!!p.alternativas?.length && <Section label="Alternativas"><Bullets items={p.alternativas.map((a) => a.titulo)} /></Section>}
          {!!p.informacoes?.length && <Section label="Informações consideradas"><Bullets items={p.informacoes} /></Section>}
          {!!p.riscos?.length && <Section label="Risco aceito"><Bullets items={p.riscos} /></Section>}
          <Section label="Contexto financeiro na época"><ContextTable ctx={p.contexto_financeiro} /></Section>
        </section>
      )}
      <section className="diary-confirmed" aria-label="Sua confirmação">
        <div className="radar-era"><Icon name="check" /> Confirmado por você em {formatDateTime(first!.created_at)}</div>
        <p><strong>{p.escolha?.texto}</strong>{p.escolha?.segue_recomendacao === false && <span className="tag plain">diferente da análise</span>}</p>
        {p.justificativa && <p className="small">Por quê: {p.justificativa}</p>}
        {p.correcoes && <p className="small">Suas correções: {p.correcoes}</p>}
      </section>
      {later.map((e) => (
        <section key={e.id} className="radar-later" aria-label={e.kind === "revisao" ? "Revisão" : "Resultado observado"}>
          <div className="radar-era"><Icon name="clock" /> {e.kind === "revisao" ? `Revisão · versão ${e.version}` : "Resultado observado"} · {formatDateTime(e.created_at)}</div>
          {e.kind === "revisao" ? (
            <>
              <p><strong>{e.payload.escolha?.texto}</strong>{e.payload.mantem && <span className="tag plain">manteve</span>}</p>
              {e.payload.justificativa && <p className="small">Por quê: {e.payload.justificativa}</p>}
            </>
          ) : (
            <>
              <p className="small">{e.payload.texto}</p>
              <p className="tiny muted">
                Observado em {formatDate(e.payload.observado_em)} ·{" "}
                {e.payload.executada === true ? "você executou" : e.payload.executada === false ? "não executada" : "execução não informada"}
              </p>
            </>
          )}
        </section>
      ))}
      <label className="field" style={{ maxWidth: 260 }}>
        <span className="field-label">Revisão periódica</span>
        <select className="select" disabled={act.busy} value={d.review_plan ? String(d.review_plan.every_months) : ""}
          onChange={(e) => void act.run(async () => { await setReviewPlan(d.id, e.target.value ? Number(e.target.value) : null); onChanged("Revisão periódica atualizada."); })}>
          {REVIEW_OPTIONS.map(([v, l]) => <option key={v} value={v}>{v ? l.replace("Em", "A cada") : l}</option>)}
        </select>
      </label>
      {act.error && <Notice tone="error">{act.error}</Notice>}
      <p className="tiny muted mono">Registro {first!.sha256.slice(0, 12)}…</p>
    </div>
  );
}

function RevisionPanel({ d, onDone }: { d: DiaryDecision; onDone: (message?: string) => void }) {
  const ctx = useAsync(() => getReviewContext(d.id), [d.id]);
  const [keep, setKeep] = useState(false);
  const [choice, setChoice] = useState("");
  const [why, setWhy] = useState("");
  const [clientId] = useState(newId);
  const act = useAction();

  function submit(e: FormEvent) {
    e.preventDefault();
    const escolha = keep ? d.escolha : choice.trim();
    if (!escolha) return act.setError("Escreva o que você decidiu agora (ou marque que mantém).");
    void act.run(async () => {
      await addRevision(d.id, { escolha, mantem: keep, justificativa: why.trim(), client_id: clientId });
      onDone("Revisão registrada.");
    });
  }

  return (
    <div className="stack diary-review">
      {ctx.loading && !ctx.data && <Loading />}
      <ErrorNotice error={ctx.error} onRetry={ctx.reload} />
      {ctx.data && (
        <div className="grid-2">
          <section className="radar-known" aria-label="Na época">
            <div className="radar-era"><Icon name="lock" /> Na época · {formatDate(d.created_at)}</div>
            <ContextTable ctx={ctx.data.na_epoca} />
          </section>
          <section className="radar-later" aria-label="Hoje">
            <div className="radar-era"><Icon name="clock" /> Dados de hoje</div>
            <ContextTable ctx={ctx.data.hoje} />
            {ctx.data.radar && (
              <p className="small">
                Radar: estado {ctx.data.radar.estado_hoje.replace(/_/g, " ")}; {ctx.data.radar.avaliacoes.filter((o) => o.status === "calculado").length} avaliação(ões)
                posterior(es); {ctx.data.radar.operacoes_informadas.length} operação(ões) informada(s).
              </p>
            )}
          </section>
        </div>
      )}
      <form className="stack" onSubmit={submit} noValidate>
        <label className="check">
          <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
          <span>Mantenho a decisão: “{d.escolha}”</span>
        </label>
        {!keep && (
          <label className="field">
            <span className="field-label">O que você decide agora</span>
            <input className="input" value={choice} onChange={(e) => setChoice(e.target.value)} maxLength={500} />
          </label>
        )}
        <label className="field">
          <span className="field-label">Por quê? <span className="muted">(opcional)</span></span>
          <textarea className="textarea" rows={2} value={why} onChange={(e) => setWhy(e.target.value)} maxLength={2000} />
        </label>
        {act.error && <Notice tone="error">{act.error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary btn-sm" disabled={act.busy}>{act.busy ? "Registrando…" : "Registrar revisão"}</button>
        </div>
      </form>
    </div>
  );
}

function OutcomeForm({ d, onDone }: { d: DiaryDecision; onDone: (message?: string) => void }) {
  const [text, setText] = useState("");
  const [executed, setExecuted] = useState("");
  const [when, setWhen] = useState(todayISO());
  const [clientId] = useState(newId);
  const act = useAction();

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return act.setError("Descreva o que aconteceu.");
    void act.run(async () => {
      await addOutcome(d.id, { texto: text.trim(), executada: executed === "" ? null : executed === "sim", observado_em: when, client_id: clientId });
      onDone("Resultado registrado.");
    });
  }

  return (
    <form className="stack diary-review" onSubmit={submit} noValidate>
      <label className="field">
        <span className="field-label">O que aconteceu depois?</span>
        <textarea className="textarea" rows={2} value={text} onChange={(e) => setText(e.target.value)} maxLength={2000}
          placeholder="Ex.: completei a reserva em março; a taxa caiu e eu não apliquei." />
      </label>
      <div className="form-grid">
        <label className="field">
          <span className="field-label">Você executou a decisão?</span>
          <select className="select" value={executed} onChange={(e) => setExecuted(e.target.value)}>
            <option value="">Não quero informar</option>
            <option value="sim">Sim, executei por conta própria</option>
            <option value="nao">Não executei</option>
          </select>
        </label>
        <div className="field">
          <label htmlFor={`when-${d.id}`}>Observado em</label>
          <DateInput id={`when-${d.id}`} value={when} onChange={(e) => setWhen(e.target.value)} />
        </div>
      </div>
      {act.error && <Notice tone="error">{act.error}</Notice>}
      <div className="row">
        <button type="submit" className="btn btn-primary btn-sm" disabled={act.busy}>{act.busy ? "Registrando…" : "Registrar resultado"}</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- Histórico (análise ≠ proposta ≠ decisão ≠ revisão ≠ resultado)

function History({ drafts, decisions }: { drafts: DecisionDraft[]; decisions: DiaryDecision[] }) {
  const events = useMemo(() => {
    const out: { at: string; kind: string; who: string; text: string }[] = [];
    for (const x of drafts) {
      if (x.content.pareceres.length) {
        out.push({ at: x.created_at, kind: "Análise", who: [...new Set(x.content.pareceres.map((p) => p.agente))].join(", "),
          text: `${x.content.pareceres.length} parecer(es) sobre “${x.content.titulo}”` });
      }
      out.push({ at: x.created_at, kind: "Proposta", who: x.content.sintese.agente, text: x.content.titulo });
      if (x.decided_at && (x.status === "adiado" || x.status === "descartado")) {
        out.push({ at: x.decided_at, kind: x.status === "adiado" ? "Adiada" : "Descartada", who: "Você", text: x.content.titulo });
      }
    }
    for (const d of decisions) {
      for (const e of d.entries) {
        const label = e.kind === "decisao" ? "Decisão confirmada" : e.kind === "revisao" ? `Revisão · v${e.version}` : "Resultado observado";
        out.push({ at: e.created_at, kind: label, who: "Você", text: e.kind === "resultado" ? `${d.titulo}: ${e.payload.texto ?? ""}` : `${d.titulo}: ${e.payload.escolha?.texto ?? ""}` });
      }
    }
    return out.sort((a, b) => b.at.localeCompare(a.at));
  }, [drafts, decisions]);
  if (!events.length) return <p className="small muted">Nada registrado ainda.</p>;
  return (
    <ol className="diary-history">
      {events.map((e, i) => (
        <li key={i}>
          <span className="mono tiny muted">{formatDateTime(e.at)}</span>
          <span className="tag plain">{e.kind}</span>
          <span className="small"><strong>{e.who}</strong> · {e.text}</span>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------- Registro manual (secundário)

function ManualForm({ onCancel, onDone }: { onCancel: () => void; onDone: () => void }) {
  const [f, setF] = useState({ titulo: "", escolha: "", alternativas: "", informacoes: "", riscos: "", justificativa: "", valor: "", data: todayISO(), review: "" });
  const [clientId] = useState(newId);
  const act = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.titulo.trim()) return act.setError("Escreva a pergunta que você decidiu.");
    if (!f.escolha.trim()) return act.setError("Registre a sua escolha (mesmo que seja esperar).");
    const p = parseFields({ amount: { text: f.valor, kind: "money", label: "Valor planejado" } });
    if (!p.ok) return act.setError(p.error);
    void act.run(async () => {
      await createManualDecision({
        titulo: f.titulo.trim(), escolha: f.escolha.trim(), data: f.data,
        alternativas: f.alternativas.split("\n").map((a) => a.trim()).filter(Boolean),
        informacoes: f.informacoes.trim(), riscos: f.riscos.trim(), justificativa: f.justificativa.trim(),
        valor_planejado: p.values.amount, review_every_months: f.review ? Number(f.review) : null, client_id: clientId,
      });
      onDone();
    });
  }

  return (
    <Card className="accent" title="Registro manual" eyebrow="Sem conversa com a equipe">
      <form onSubmit={submit} noValidate className="stack">
        <div className="form-grid">
          <label className="field"><span className="field-label">Pergunta</span><input className="input" value={f.titulo} onChange={set("titulo")} maxLength={200} placeholder="Ex.: quito o cartão ou começo a reserva?" /></label>
          <label className="field"><span className="field-label">Sua escolha</span><input className="input" value={f.escolha} onChange={set("escolha")} maxLength={500} /></label>
        </div>
        <label className="field"><span className="field-label">Alternativas consideradas <span className="muted">(uma por linha)</span></span><textarea className="textarea" rows={2} value={f.alternativas} onChange={set("alternativas")} /></label>
        <div className="form-grid">
          <label className="field"><span className="field-label">Informações consideradas</span><textarea className="textarea" rows={2} value={f.informacoes} onChange={set("informacoes")} maxLength={2000} /></label>
          <label className="field"><span className="field-label">Risco aceito</span><textarea className="textarea" rows={2} value={f.riscos} onChange={set("riscos")} maxLength={1000} /></label>
        </div>
        <label className="field"><span className="field-label">Por quê? <span className="muted">(opcional)</span></span><textarea className="textarea" rows={2} value={f.justificativa} onChange={set("justificativa")} maxLength={2000} /></label>
        <div className="form-grid">
          <div className="field"><label htmlFor="manual-date">Data</label><DateInput id="manual-date" value={f.data} onChange={set("data")} /></div>
          <MoneyField label="Valor planejado" optional value={f.valor} onChange={(v) => setF({ ...f, valor: v })} />
          <label className="field"><span className="field-label">Revisar</span>
            <select className="select" value={f.review} onChange={set("review")}>{REVIEW_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          </label>
        </div>
        {act.error && <Notice tone="error">{act.error}</Notice>}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={act.busy}>{act.busy ? "Registrando…" : "Registrar decisão"}</button>
          <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancelar</button>
        </div>
      </form>
    </Card>
  );
}

/** Análises do Laboratório do Conselho: produzidas por IA, separadas das decisões (que só você registra). */
function LabAnalyses() {
  const q = useAsync(getLabJournal, []);
  const items = (q.data ?? []).filter((j) => j.kind === "analise_ia").slice(0, 5);
  if (!items.length) return null;
  return (
    <Card title="Análises do Laboratório" eyebrow="Produzidas por IA — não são decisões suas">
      <ul className="diary-list">
        {items.map((j) => (
          <li key={j.id} className="small">
            <Link to={`/laboratorio/${j.experiment_id}`}>{String(j.payload.problema ?? "Experimento")}</Link>
            <span className="muted"> · {formatDateTime(j.created_at)} · Bento sozinho × Conselho</span>
          </li>
        ))}
      </ul>
      <p className="tiny muted">Recomendação não é decisão, e decisão não é operação. Para registrar o que você decidiu, use o experimento ou o registro manual.</p>
    </Card>
  );
}
