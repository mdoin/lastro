// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira · visão geral: números reais do banco, agente, próximas ações e atividade recente. */
import { Link } from "react-router-dom";
import { getSummary, type NextAction, type Summary } from "../api/carreira";
import { AgentStatusLine, Metric, Skeleton } from "../components/Career";
import { Icon } from "../components/Icon";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader } from "../components/ui";
import { RUN_KIND, RUN_STATE, eventHref, eventText, eventTone, percent, usePolling } from "../lib/career";
import { formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/carreira.css";

const ACTION: Record<NextAction["tipo"], { label: string; tone: "good" | "gold" | "warning" | "serious" | "critical" }> = {
  entrevista: { label: "Entrevista", tone: "good" },
  teste: { label: "Teste", tone: "gold" },
  proposta: { label: "Proposta", tone: "good" },
  intervencao: { label: "Precisa de você", tone: "warning" },
  verificar_envio: { label: "Verificar envio", tone: "serious" },
  falha: { label: "Falha", tone: "critical" },
};

export function CareerOverviewPage() {
  const { data, error, reload } = useAsync(getSummary, []);
  usePolling(reload);

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Visão geral" lede="O que os agentes encontraram, enviaram e o que espera por você." />
      <ErrorNotice error={error && !data ? error : null} onRetry={reload} />
      {!data && !error && <Skeleton rows={6} height={28} />}
      {data && <Overview data={data} />}
    </div>
  );
}

export function Overview({ data }: { data: Summary }) {
  const m = data.metricas;
  const a = data.agente;
  return (
    <>
      <section aria-label="Indicadores" className="career-metrics">
        <Metric label="Oportunidades" value={m.total} sub={`${m.novas_7d} nos últimos 7 dias`} to="/carreira/vagas?compat=todas" />
        <Metric label="Compatíveis" value={m.compativeis} sub={`${m.talvez} para conferir`} to="/carreira/vagas?compat=compativel" />
        <Metric label="Enviadas" value={m.enviadas} sub="com confirmação" to="/carreira/candidaturas" />
        <Metric label="Aguardando resposta" value={m.aguardando} sub="enviadas sem retorno" />
        <Metric label="Em andamento" value={m.em_andamento} sub={`${m.entrevistas} em entrevista`} />
        <Metric label="Rejeições" value={m.rejeicoes} sub="confirmadas pela empresa" />
        <Metric label="Falhas e incertas" value={m.falhas + m.incertas} sub={`${m.incertas} sem confirmação de envio`}
          tone={m.falhas + m.incertas ? "warning" : undefined} />
        <Metric label="Taxa de resposta" value={percent(m.taxa_resposta)}
          sub={m.enviadas ? `${m.respondidas} de ${m.enviadas} enviadas` : "nenhuma enviada ainda"} />
      </section>

      <div className="career-split">
        <Card title="Agente" aside={<Link className="link-arrow small" to="/carreira/agente">Detalhes</Link>}>
          <div className="stack-sm">
            <AgentStatusLine agent={a} />
            <dl className="career-facts">
              <div><dt>Última execução</dt><dd>{a.ultima ? `${RUN_KIND[a.ultima.tipo]} · ${RUN_STATE[a.ultima.estado].label}${
                a.ultima.resultado ? ` · ${a.ultima.resultado}` : ""}` : "nenhuma registrada"}</dd></div>
              <div><dt>Terminou</dt><dd>{formatDateTime(a.ultima?.finished_at)}</dd></div>
              <div><dt>Próximo ciclo</dt><dd>{a.proximo_ciclo ? formatDateTime(a.proximo_ciclo) : "ainda não informado pelo serviço"}</dd></div>
              <div><dt>Na fila</dt><dd>{a.fila.curriculos.length} currículo(s) · {a.fila.envios.length} envio(s)</dd></div>
            </dl>
            {a.erros[0] && (
              <p className="small career-error"><Icon name="alert" /> {RUN_KIND[a.erros[0].tipo]}: {a.erros[0].erro || "falhou"} ({formatDateTime(a.erros[0].started_at)})</p>
            )}
          </div>
        </Card>

        <Card title="Próximas ações">
          {data.proximas.length === 0 ? (
            <p className="small muted">Nada esperando por você agora. Entrevistas, testes, envios sem confirmação e falhas aparecem aqui.</p>
          ) : (
            <ul className="career-list">
              {data.proximas.slice(0, 8).map((p) => (
                <li key={`${p.tipo}-${p.n}`}>
                  <Link to={`/carreira/candidaturas/${p.n}`} className="career-list-link">
                    <Badge tone={ACTION[p.tipo].tone}>{ACTION[p.tipo].label}</Badge>
                    <span className="career-list-main">
                      <span className="career-list-title">{p.title}</span>
                      <span className="small muted">{p.company || "empresa não informada"}{p.prazo ? ` · prazo ${p.prazo}` : ""}</span>
                      {p.motivo && ["intervencao", "verificar_envio", "falha"].includes(p.tipo) && (
                        <span className="small">{p.motivo}</span>
                      )}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Atividade recente" aside={<span className="tiny muted">atualiza sozinha</span>}>
        {data.atividade.length === 0 ? (
          <EmptyState title="Nenhuma atividade ainda" icon="pulse">
            Quando o caçador encontrar vagas e os agentes trabalharem nelas, cada passo aparece aqui.
          </EmptyState>
        ) : (
          <ol className="career-feed">
            {data.atividade.map((e) => (
              <li key={e.id} data-tone={eventTone(e.tipo)}>
                <Link to={eventHref(e)}>
                  <span className="career-timeline-dot" aria-hidden="true" />
                  <span className="career-feed-main">
                    <span>{eventText(e)}</span>
                    <span className="small muted">{e.title}{e.company ? ` — ${e.company}` : ""}</span>
                  </span>
                  <time className="tiny muted mono" dateTime={e.created_at}>{formatDateTime(e.created_at)}</time>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </>
  );
}
