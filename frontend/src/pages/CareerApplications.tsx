// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira · candidaturas: Kanban por etapa, tabela, e a página de cada candidatura com documentos e histórico. */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  applicationAction, getApplication, getApplications, resumeDocumentUrl,
  type Application, type ApplicationAction, type ApplicationDetail, type Attempt, type Stage,
} from "../api/carreira";
import { ApplicationBadges, Skeleton, Timeline } from "../components/Career";
import { Icon } from "../components/Icon";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader, Segmented } from "../components/ui";
import { useApp } from "../lib/appContext";
import { COLUMNS, STAGE, WORKPLACE, sourceLabel, usePolling } from "../lib/career";
import { formatDate, formatDateTime } from "../lib/dates";
import { errorMessage, useAsync } from "../lib/useAsync";
import "../styles/carreira.css";

type View = "kanban" | "tabela";

function readView(): View {
  try {
    return localStorage.getItem("lastro.carreira.visao") === "tabela" ? "tabela" : "kanban";
  } catch {
    return "kanban";
  }
}

/** O que falta fazer, a partir do estado real (envio e etapa separados). */
export function nextStep(a: Pick<Application, "candidatura_status" | "etapa" | "coluna" | "aderencia">): string {
  switch (a.candidatura_status) {
    case "precisa_de_voce": return "Resolver o que o agente pediu";
    case "aguardando_acesso": return "Resolver o acesso em Contas e acessos";
    case "incerta": return "Verificar se o envio aconteceu";
    case "falhou": return "Enviar manualmente ou retirar";
    case "curriculo": return a.aderencia != null && a.aderencia < 60 ? "Abaixo de 60%: envio manual, se quiser" : "Aguardando o Aplicador";
    default: break;
  }
  if (a.etapa === "entrevista") return "Preparar a entrevista";
  if (a.etapa === "teste") return "Fazer o teste";
  if (a.etapa === "proposta") return "Responder a proposta";
  return a.coluna === "enviada" ? "Aguardar retorno" : "—";
}

export function CareerApplicationsPage() {
  const { data, error, reload } = useAsync(getApplications, []);
  usePolling(reload);
  const [view, setView] = useState<View>(readView);
  const choose = (v: View) => {
    setView(v);
    try {
      localStorage.setItem("lastro.carreira.visao", v);
    } catch {
      /* sem armazenamento: só não lembra */
    }
  };

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Candidaturas"
        lede="O estado do envio (agente) e a etapa informada pela empresa aparecem separados."
        actions={<Segmented label="Visualização" value={view} onChange={choose}
          options={[{ value: "kanban", label: "Kanban" }, { value: "tabela", label: "Tabela" }]} />} />
      <ErrorNotice error={error && !data ? error : null} onRetry={reload} />
      {!data && !error && <Skeleton rows={6} height={40} />}
      {data && data.length === 0 && (
        <EmptyState title="Nenhuma candidatura ainda" icon="layers">
          O Alfaiate prepara o currículo das vagas compatíveis e o Aplicador envia as de maior aderência, das 8 h às 21 h.
          Acompanhe a fila em <Link to="/carreira/agente">Agente de carreira</Link>.
        </EmptyState>
      )}
      {data && data.length > 0 && (view === "kanban" ? <Board items={data} /> : <Table items={data} />)}
    </div>
  );
}

export function Board({ items }: { items: Application[] }) {
  return (
    <div className="career-board" role="list" aria-label="Candidaturas por etapa">
      {COLUMNS.map((col) => {
        const cards = items.filter((a) => a.coluna === col.key);
        return (
          <section key={col.key} className="career-column" role="listitem" aria-labelledby={`col-${col.key}`}>
            <header>
              <h2 id={`col-${col.key}`}>{col.label}</h2>
              <span className="tag">{cards.length}</span>
            </header>
            <p className="tiny muted">{col.hint}</p>
            <ul>
              {cards.map((a) => (
                <li key={a.id}>
                  <Link to={`/carreira/candidaturas/${a.n}`} className="career-card">
                    <span className="career-card-title">{a.title}</span>
                    <span className="small muted">{a.company || "Empresa não informada"}</span>
                    {a.candidatura_status && <ApplicationBadges status={a.candidatura_status} etapa={a.etapa} />}
                    <span className="tiny muted">{sourceLabel(a.source)} · atualizada {formatDate(a.atualizada_em)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function Table({ items }: { items: Application[] }) {
  return (
    <div className="table-wrap">
      <table className="table career-table">
        <thead>
          <tr>
            <th scope="col">Empresa</th><th scope="col">Cargo</th><th scope="col">Plataforma</th><th scope="col">Envio</th>
            <th scope="col">Etapa atual</th><th scope="col">Atualizada</th><th scope="col">Próxima ação</th>
          </tr>
        </thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.id}>
              <td>{a.company || "—"}</td>
              <td><Link to={`/carreira/candidaturas/${a.n}`}>{a.title}</Link></td>
              <td>{sourceLabel(a.source)}</td>
              <td className="mono small">{a.enviada_em ? formatDate(a.enviada_em) : "—"}</td>
              <td>{a.candidatura_status && <ApplicationBadges status={a.candidatura_status} etapa={a.etapa} />}</td>
              <td className="mono small">{formatDate(a.atualizada_em)}</td>
              <td className="small">{nextStep(a)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const ATTEMPT: Record<Attempt["status"], { label: string; tone: "good" | "serious" | "warning" | "neutral" | "critical" }> = {
  enviada: { label: "Enviada", tone: "good" },
  incerta: { label: "Resultado desconhecido", tone: "serious" },
  precisa_de_voce: { label: "Precisa de você", tone: "warning" },
  nao_aplicavel: { label: "Não aplicável", tone: "neutral" },
  falhou: { label: "Falhou", tone: "critical" },
};
const EMAIL: Record<string, string> = {
  convite_teste: "Convite para teste", convite_entrevista: "Convite para entrevista", recusa: "Retorno negativo",
  proposta: "Proposta", confirmacao: "Confirmação", andamento: "Andamento",
};

export function CareerApplicationPage() {
  const n = Number(useParams().n);
  const { toast } = useApp();
  const { data, error, reload, setData } = useAsync(() => getApplication(n), [n]);
  const [busy, setBusy] = useState(false);
  usePolling(reload, 30_000);

  async function act(body: ApplicationAction, done: string) {
    setBusy(true);
    try {
      setData(await applicationAction(n, body));
      toast(done);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <ErrorNotice error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={8} height={24} />;
  const d: ApplicationDetail = data;
  const sent = d.envios.find((e) => e.status === "enviada");

  return (
    <div className="stack-lg">
      <nav aria-label="Trilha" className="small"><Link to="/carreira/candidaturas" className="link-arrow">← Candidaturas</Link></nav>
      <PageHeader eyebrow={`Candidatura #${d.n} · ${sourceLabel(d.source)}`} title={d.title} lede={d.company || "Empresa não informada"}
        actions={<ApplicationBadges status={d.status} etapa={d.etapa} />} />

      {(d.status === "incerta" || d.status === "precisa_de_voce") && (
        <div className="notice warning" role="status">
          <Icon name="alert" />
          <div className="stack-sm">
            <div>
              <strong>{d.status === "incerta" ? "O envio não foi confirmado." : "O agente parou e precisa de você."} </strong>
              {d.envios.at(-1)?.motivo}
            </div>
            <div className="row">
              <Link className="btn btn-secondary btn-sm" to="/carreira/navegador">Abrir navegador do agente</Link>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy}
                onClick={() => act({ acao: "confirmar_envio" }, "Envio confirmado.")}>Confirmar que foi enviada</button>
              <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
                onClick={() => act({ acao: "nao_enviada" }, "Marcada como não enviada.")}>Não foi enviada</button>
            </div>
          </div>
        </div>
      )}

      <div className="career-split">
        <Card title="Informações gerais">
          <dl className="career-facts">
            <div><dt>Empresa</dt><dd>{d.company || "Não informada"}</dd></div>
            <div><dt>Cargo</dt><dd><Link to={`/carreira/vagas/${d.n}`}>{d.title}</Link></dd></div>
            <div><dt>Plataforma</dt><dd>{sourceLabel(d.source)}</dd></div>
            <div><dt>Localização</dt><dd>{[d.location, WORKPLACE[d.workplace]].filter(Boolean).join(" · ")}</dd></div>
            <div><dt>Link</dt><dd><a href={d.url} target="_blank" rel="noopener noreferrer">vaga original</a></dd></div>
            <div><dt>Data da candidatura</dt><dd>{sent ? formatDateTime(sent.created_at) : "sem envio confirmado"}</dd></div>
            <div><dt>Aderência</dt><dd>{d.aderencia}% · {d.resumo}</dd></div>
          </dl>
        </Card>

        <Card title="Etapa do processo" eyebrow="Informada pela empresa">
          <div className="stack-sm">
            <p className="small muted">O Carteiro atualiza pelos e-mails. Ajuste aqui se souber de algo que não chegou por e-mail.</p>
            <label className="career-filter">
              <span>Etapa atual</span>
              <select className="select" value={d.etapa ?? ""} disabled={busy}
                onChange={(e) => e.target.value && act({ acao: "etapa", etapa: e.target.value as Stage }, "Etapa atualizada.")}>
                <option value="" disabled>Sem retorno</option>
                {Object.entries(STAGE).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
              </select>
            </label>
            {d.status !== "retirada" && (
              <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
                onClick={() => window.confirm("Retirar esta candidatura? O histórico continua guardado.")
                  && act({ acao: "retirar" }, "Candidatura retirada.")}>Retirar candidatura</button>
            )}
          </div>
        </Card>
      </div>

      <Card title="Documentos">
        <div className="stack-sm">
          {d.curriculo_id ? (
            <div className="row between">
              <span>Currículo usado <span className="tag">v{d.curriculo_id}</span></span>
              <span className="row">
                <Link className="btn btn-secondary btn-sm" to={`/carreira/curriculos/${d.curriculo_id}`}>Ver</Link>
                <a className="btn btn-ghost btn-sm" href={resumeDocumentUrl(d.curriculo_id)} target="_blank" rel="noopener">
                  <Icon name="download" /> Imprimir / PDF
                </a>
              </span>
            </div>
          ) : <p className="small muted">Sem currículo registrado.</p>}
          {d.carta ? (
            <details>
              <summary>Carta de apresentação</summary>
              <p className="career-description">{d.carta}</p>
            </details>
          ) : <p className="small muted">Sem carta de apresentação.</p>}
        </div>
      </Card>

      <Card title="Execução" eyebrow="Tentativas do Aplicador">
        {d.envios.length === 0 ? <p className="small muted">Nenhuma tentativa de envio ainda.</p> : (
          <ol className="career-attempts">
            {d.envios.map((e, i) => (
              <li key={e.id}>
                <div className="row between">
                  <strong>Tentativa {i + 1}</strong>
                  <Badge tone={ATTEMPT[e.status].tone}>{ATTEMPT[e.status].label}</Badge>
                </div>
                <div className="tiny muted">{formatDateTime(e.created_at)} · Aplicador{e.curriculo_id ? ` · currículo v${e.curriculo_id}` : ""}</div>
                <p className="small">{e.motivo}</p>
                {e.evidencia && <p className="small"><span className="muted">Evidência: </span>“{e.evidencia}”</p>}
                {e.url_final && <a className="small" href={e.url_final} target="_blank" rel="noopener noreferrer">página final</a>}
                {e.respostas.length > 0 && (
                  <details>
                    <summary className="small">Respostas no formulário ({e.respostas.length})</summary>
                    <dl className="career-answers">
                      {e.respostas.map((r, k) => <div key={k}><dt>{r.pergunta}</dt><dd>{r.resposta}</dd></div>)}
                    </dl>
                  </details>
                )}
              </li>
            ))}
          </ol>
        )}
      </Card>

      <div className="career-split">
        <Card title="Histórico">
          <Timeline events={d.eventos} />
        </Card>
        <Card title="Retornos por e-mail">
          {d.emails.length === 0 ? <p className="small muted">Nenhum e-mail ligado a esta candidatura.</p> : (
            <ul className="career-list">
              {d.emails.map((m, i) => (
                <li key={i} className="stack-sm">
                  <span className="row"><Badge tone="gold">{EMAIL[m.tipo] ?? m.tipo}</Badge>
                    <span className="tiny muted">{formatDateTime(m.received_at ?? m.created_at)}</span></span>
                  <span className="small">{m.subject}</span>
                  {m.resumo && <span className="small muted">{m.resumo}</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
