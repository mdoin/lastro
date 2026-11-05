// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira · agente: estado real das execuções, fila derivada dos dados e falhas recentes. */
import { Link } from "react-router-dom";
import { getAgent, type AgentRun } from "../api/carreira";
import { AgentStatusLine, Skeleton } from "../components/Career";
import { Icon } from "../components/Icon";
import { Badge, Card, ErrorNotice, PageHeader } from "../components/ui";
import { RUN_KIND, RUN_STATE, usePolling } from "../lib/career";
import { formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/carreira.css";

function duration(run: AgentRun): string {
  const end = run.finished_at ? new Date(run.finished_at) : new Date();
  const s = Math.max(0, Math.round((end.getTime() - new Date(run.started_at).getTime()) / 1000));
  return s < 60 ? `${s} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
}

export function CareerAgentPage() {
  const { data, error, reload } = useAsync(getAgent, []);
  usePolling(reload, 10_000);

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Agente de carreira"
        lede="Caçador, Alfaiate e Aplicador rodam no serviço lastro-carreira, com a interface aberta ou não."
        actions={<Link className="btn btn-secondary btn-sm" to="/carreira/navegador"><Icon name="globe" /> Navegador do agente</Link>} />
      <ErrorNotice error={error && !data ? error : null} onRetry={reload} />
      {!data && !error && <Skeleton rows={6} height={28} />}
      {data && (
        <>
          <Card title="Agora">
            <div className="stack-sm">
              <AgentStatusLine agent={data} />
              {data.atual?.travada && (
                <p className="small career-error"><Icon name="alert" /> Passou do prazo esperado sem terminar. Se o serviço
                  reiniciar, a execução é marcada como interrompida; a candidatura em questão não é reenviada às cegas.</p>
              )}
              <dl className="career-facts">
                <div><dt>Última execução</dt><dd>{data.ultima ? `${RUN_KIND[data.ultima.tipo]} · ${RUN_STATE[data.ultima.estado].label}` : "nenhuma"}</dd></div>
                <div><dt>Resultado</dt><dd>{data.ultima?.resultado || data.ultima?.erro || "—"}</dd></div>
                <div><dt>Terminou</dt><dd>{formatDateTime(data.ultima?.finished_at)}</dd></div>
                <div><dt>Próxima busca</dt><dd>{data.proximo_ciclo ? formatDateTime(data.proximo_ciclo) : "ainda não informado pelo serviço"}</dd></div>
                <div><dt>Próxima volta da fila</dt><dd>{data.proxima_fila ? formatDateTime(data.proxima_fila) : "ainda não informado pelo serviço"}</dd></div>
                <div><dt>Envios hoje</dt><dd>{data.fila.envios_hoje} de {data.fila.limite_diario} (até {data.fila.por_ciclo} por ciclo, das 8 h às 21 h)</dd></div>
              </dl>
            </div>
          </Card>

          <div className="career-split">
            <Card title="Fila: currículos" aside={<span className="tag">{data.fila.curriculos.length}</span>}>
              {data.fila.curriculos.length === 0 ? <p className="small muted">Nenhuma vaga compatível esperando currículo.</p> : (
                <ul className="career-list">
                  {data.fila.curriculos.map((q) => (
                    <li key={q.n}><Link to={`/carreira/vagas/${q.n}`} className="career-list-link">
                      <span className="career-list-main"><span className="career-list-title">{q.title}</span>
                        <span className="small muted">{q.company || "Empresa não informada"}</span></span>
                    </Link></li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Fila: envios" aside={<span className="tag">{data.fila.envios.length}</span>}>
              {data.fila.envios.length === 0 ? <p className="small muted">Nenhuma candidatura pronta para envio (aderência ≥ 60%).</p> : (
                <ul className="career-list">
                  {data.fila.envios.map((q) => (
                    <li key={q.n}><Link to={`/carreira/candidaturas/${q.n}`} className="career-list-link">
                      <span className="tag">{q.aderencia}%</span>
                      <span className="career-list-main"><span className="career-list-title">{q.title}</span>
                        <span className="small muted">{q.company || "Empresa não informada"}</span></span>
                    </Link></li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card title="Execuções recentes">
            {data.recentes.length === 0 ? (
              <p className="small muted">Nenhuma execução registrada ainda. A primeira aparece no próximo ciclo do serviço.</p>
            ) : (
              <div className="table-wrap">
                <table className="table career-table">
                  <thead>
                    <tr><th scope="col">Tarefa</th><th scope="col">Vaga</th><th scope="col">Estado</th><th scope="col">Início</th>
                      <th scope="col" className="num">Duração</th><th scope="col">Resultado</th></tr>
                  </thead>
                  <tbody>
                    {data.recentes.map((r) => (
                      <tr key={r.id}>
                        <td>{RUN_KIND[r.tipo]}</td>
                        <td>{r.n ? <Link to={`/carreira/vagas/${r.n}`}>{r.title}</Link> : "—"}</td>
                        <td><Badge tone={r.travada ? "critical" : RUN_STATE[r.estado].tone}>{r.travada ? "Travada" : RUN_STATE[r.estado].label}</Badge></td>
                        <td className="mono small">{formatDateTime(r.started_at)}</td>
                        <td className="num small">{duration(r)}</td>
                        <td className="small">{r.erro ? <span className="career-error">{r.erro}</span> : r.resultado || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
