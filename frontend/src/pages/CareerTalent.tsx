// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira · Talent: perfil, estratégia, avaliações, revisões e resultados, exatamente como o agente gravou. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { decideProposal, getTalent, type TalentEvaluation, type TalentGroup, type TalentReview } from "../api/carreira";
import { Metric, Skeleton } from "../components/Career";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader, Segmented } from "../components/ui";
import { percent, usePolling } from "../lib/career";
import { formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/carreira.css";

type Tab = "perfil" | "estrategia" | "avaliacoes" | "revisoes" | "resultados";
const TABS: { value: Tab; label: string }[] = [
  { value: "perfil", label: "Perfil" }, { value: "estrategia", label: "Estratégia" },
  { value: "avaliacoes", label: "Avaliações" }, { value: "revisoes", label: "Revisões" },
  { value: "resultados", label: "Resultados" },
];
const SITUACAO = { atendido: "good", parcial: "warning", ausente: "neutral" } as const;
const RESULTADO = {
  aprovado: { label: "Aprovado", tone: "good" }, correcoes: { label: "Correções necessárias", tone: "warning" },
  bloqueado: { label: "Bloqueado por inconsistência factual", tone: "critical" },
} as const;

export function Evaluation({ a }: { a: TalentEvaluation }) {
  return (
    <details className="talent-item">
      <summary>
        <Badge tone={a.elegivel ? "good" : "neutral"}>{a.elegivel ? "Elegível" : "Não elegível"}</Badge>
        <span className="tag">{a.pontuacao}</span>
        <span className="career-list-main"><span className="career-list-title">{a.title}</span>
          <span className="small muted">{a.company || "Empresa não informada"} · {formatDateTime(a.created_at)}</span></span>
      </summary>
      <div className="stack-sm talent-body">
        <p className="small">{a.justificativa}</p>
        <p className="small"><strong>Posicionamento ({a.perfil_curriculo}):</strong> {a.posicionamento || "—"}</p>
        <ul className="talent-checks">
          {a.filtros.map((f) => <li key={f.filtro}><Badge tone={f.ok ? "good" : "critical"}>{f.ok ? "ok" : "barra"}</Badge> {f.filtro}: {f.motivo}</li>)}
        </ul>
        <div className="table-wrap"><table className="table career-table">
          <thead><tr><th scope="col">Requisito</th><th scope="col">Tipo</th><th scope="col">Situação</th><th scope="col">Evidência no perfil</th></tr></thead>
          <tbody>{a.requisitos.map((r) => (
            <tr key={r.texto}><td>{r.texto}</td><td className="small">{r.tipo === "obrigatorio" ? "obrigatório" : "desejável"}</td>
              <td><Badge tone={SITUACAO[r.situacao]}>{r.situacao}</Badge></td>
              <td className="small">{r.evidencia || (r.evidencia_recusada ? "evidência citada não está no perfil" : "—")}</td></tr>))}
          </tbody></table></div>
        <div className="table-wrap"><table className="table career-table">
          <thead><tr><th scope="col">Critério da rubrica</th><th scope="col" className="num">Pontos</th><th scope="col">Por quê</th></tr></thead>
          <tbody>{a.criterios.map((c) => (
            <tr key={c.criterio}><td>{c.criterio}</td><td className="num">{c.pontos} / {c.peso}</td><td className="small">{c.motivo}</td></tr>))}
          </tbody></table></div>
        {a.destaques.length > 0 && <ul className="small">{a.destaques.map((d) => <li key={d.item}><strong>Destacar {d.item}:</strong> {d.motivo}</li>)}</ul>}
        {a.orientacoes.length > 0 && <><p className="small muted">Orientações ao Alfaiate</p>
          <ul className="small">{a.orientacoes.map((o) => <li key={o}>{o}</li>)}</ul></>}
        <p className="small muted">Rubrica {a.rubrica}. A pontuação é compatibilidade pela rubrica, não chance de contratação.
          {" "}<Link to={`/carreira/vagas/${a.n}`}>Ver vaga</Link></p>
      </div>
    </details>
  );
}

export function Review({ r }: { r: TalentReview }) {
  return (
    <details className="talent-item">
      <summary>
        <Badge tone={RESULTADO[r.resultado].tone}>{RESULTADO[r.resultado].label}</Badge>
        <span className="tag">rodada {r.rodada}</span>
        <span className="career-list-main"><span className="career-list-title">{r.title}</span>
          <span className="small muted">{r.resumo}</span></span>
      </summary>
      <div className="stack-sm talent-body">
        {r.problemas.length === 0 ? <p className="small muted">Nenhum problema encontrado.</p> : (
          <ul className="talent-checks">{r.problemas.map((p, i) => (
            <li key={i}><Badge tone={p.gravidade === "bloqueante" ? "critical" : p.gravidade === "importante" ? "warning" : "neutral"}>
              {p.criterio.replace(/_/g, " ")}</Badge> {p.correcao}{p.trecho && <span className="muted"> (trecho: “{p.trecho}”)</span>}</li>))}
          </ul>)}
        <ul className="talent-checks small">{r.checagens.map((c, i) => (
          <li key={i}><Badge tone={c.ok ? "good" : "warning"}>{c.ok ? "ok" : "falha"}</Badge> {c.criterio.replace(/_/g, " ")}: {c.detalhe}</li>))}
        </ul>
        <p className="small muted">{formatDateTime(r.created_at)} · <Link to={`/carreira/curriculos/${r.curriculo_id}`}>Currículo avaliado</Link>
          {" "}· <Link to={`/carreira/candidaturas/${r.n}`}>Candidatura</Link></p>
      </div>
    </details>
  );
}

function Groups({ title, groups }: { title: string; groups: TalentGroup[] }) {
  return (
    <Card title={title}>
      {groups.length === 0 ? <p className="small muted">Nenhuma candidatura enviada ainda.</p> : (
        <div className="table-wrap"><table className="table career-table">
          <thead><tr><th scope="col">Grupo</th><th scope="col" className="num">Enviadas</th><th scope="col" className="num">Respostas</th>
            <th scope="col" className="num">Entrevistas</th><th scope="col">Amostra</th></tr></thead>
          <tbody>{groups.map((g) => (
            <tr key={g.grupo}><td>{g.grupo}</td><td className="num">{g.enviadas}</td><td className="num">{g.respostas}</td>
              <td className="num">{g.entrevistas}</td><td className="small">{g.amostra_suficiente ? "suficiente" : "pequena: só descritivo"}</td></tr>))}
          </tbody></table></div>)}
    </Card>
  );
}

export function CareerTalentPage() {
  const { data, error, reload } = useAsync(getTalent, []);
  const [tab, setTab] = useState<Tab>("perfil");
  const [busy, setBusy] = useState(false);
  usePolling(reload, 60_000);

  async function decide(id: number, decisao: "aprovada" | "recusada") {
    setBusy(true);
    try { await decideProposal(id, decisao); reload(); } finally { setBusy(false); }
  }

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Talent"
        lede="Especialista em recrutamento: avalia cada vaga pelos seus critérios, orienta o Alfaiate, revisa o currículo antes do envio e aprende com os resultados. Só trabalha com o que está no seu perfil." />
      <ErrorNotice error={error && !data ? error : null} onRetry={reload} />
      {!data && !error && <Skeleton rows={6} height={28} />}
      {data && (
        <>
          <Segmented label="Área do Talent" value={tab} onChange={setTab} options={TABS} />

          {tab === "perfil" && (
            <div className="stack-lg">
              {!data.perfil.arquivo && <EmptyState title="Perfil não encontrado">O Talent lê o perfil base do servidor (perfil.md). Sem ele, nenhuma vaga é avaliada.</EmptyState>}
              <div className="career-split">
                <Card title="Pontos fortes" aside={<span className="small muted">requisitos atendidos com evidência</span>}>
                  {data.perfil.pontos_fortes.length === 0 ? <p className="small muted">Aparecem depois das primeiras avaliações.</p> : (
                    <ul className="career-list">{data.perfil.pontos_fortes.map((t) => (
                      <li key={t.termo} className="talent-row"><span>{t.termo}</span><span className="small muted">atendido em {t.atendido} de {t.vagas} vaga(s)</span></li>))}</ul>)}
                </Card>
                <Card title="Lacunas" aside={<span className="small muted">pedidos que o perfil não comprova</span>}>
                  {data.perfil.lacunas.length === 0 ? <p className="small muted">Nenhuma lacuna registrada.</p> : (
                    <ul className="career-list">{data.perfil.lacunas.map((t) => (
                      <li key={t.termo} className="talent-row"><span>{t.termo}</span><span className="small muted">ausente em {t.ausente} de {t.vagas} vaga(s)</span></li>))}</ul>)}
                </Card>
              </div>
              <Card title="Informações pendentes e propostas" aside={<span className="small muted">nada muda no perfil sem você</span>}>
                {data.propostas.length === 0 ? <p className="small muted">Nenhuma proposta. Elas saem da análise semanal.</p> : (
                  <ul className="career-list">{data.propostas.map((p) => (
                    <li key={p.id} className="talent-proposal">
                      <div className="career-list-main"><span>{p.proposta}</span>
                        <span className="small muted">{p.alvo === "perfil" ? "Perfil (a confirmar)" : "Currículo-base"} · origem: {p.origem}</span></div>
                      {p.status === "pendente" ? (
                        <span className="talent-actions">
                          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => decide(p.id, "aprovada")}>Aprovar</button>
                          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => decide(p.id, "recusada")}>Recusar</button>
                        </span>
                      ) : <Badge tone={p.status === "aprovada" ? "good" : "neutral"}>{p.status}</Badge>}
                    </li>))}</ul>)}
                <p className="small muted">Aprovar registra a sua decisão; a edição do perfil e do currículo-base continua sendo sua.</p>
              </Card>
              <Card title="Perfil profissional (fonte de verdade)" aside={<span className="small muted">confirmado por você</span>}>
                <dl className="career-facts">{Object.entries(data.perfil.secoes).map(([secao, itens]) => (
                  <div key={secao}><dt>{secao}</dt><dd><ul className="small talent-plain">{itens.map((i) => <li key={i}>{i}</li>)}</ul></dd></div>))}
                </dl>
              </Card>
            </div>
          )}

          {tab === "estrategia" && (
            <div className="stack-lg">
              <div className="career-split">
                <Card title="Critérios obrigatórios (seus)" aside={<span className="small muted">o Talent não altera</span>}>
                  <ul className="small">{data.estrategia.criterios.map((c) => <li key={c}>{c}</li>)}</ul>
                  <p className="small muted">Uma vaga que viola um critério não é aprovada por pontuação alta.</p>
                </Card>
                <Card title={`Rubrica ${data.estrategia.rubrica}`}>
                  <ul className="career-list">{data.estrategia.pesos.map((p) => (
                    <li key={p.criterio} className="talent-row"><span>{p.criterio}</span><span className="num">{p.peso}</span></li>))}</ul>
                  <p className="small muted">Elegível: critérios ok e compatibilidade ≥ {data.estrategia.limiar}. Revisão: até {data.estrategia.max_rodadas} rodadas.</p>
                </Card>
              </div>
              <Card title="Perfis de currículo em uso" aside={<span className="small muted">vagas elegíveis por perfil</span>}>
                {data.estrategia.perfis.length === 0 ? <p className="small muted">Nenhuma vaga elegível avaliada ainda.</p> : (
                  <ul className="career-list">{data.estrategia.perfis.map((p) => (
                    <li key={p.perfil} className="talent-row"><span>{p.perfil}</span><span className="num">{p.vagas}</span></li>))}</ul>)}
              </Card>
              <Card title="Recomendações" aside={data.estrategia.analise && <span className="small muted">análise de {formatDateTime(data.estrategia.analise.created_at)}</span>}>
                {!data.estrategia.analise ? <p className="small muted">A primeira análise roda na próxima volta da fila.</p> : (
                  <ul className="career-list">{data.estrategia.analise.recomendacoes.map((r, i) => (
                    <li key={i} className="talent-proposal"><div className="career-list-main"><span>{r.texto}</span>
                      <span className="small muted">base: {r.base}</span></div>
                      <Badge tone={r.forca === "indicativa" ? "gold" : "neutral"}>{r.forca}</Badge></li>))}</ul>)}
              </Card>
            </div>
          )}

          {tab === "avaliacoes" && (
            <Card title="Oportunidades analisadas" aside={<span className="tag">{data.avaliacoes.length}</span>}>
              {data.avaliacoes.length === 0 ? <p className="small muted">Nenhuma avaliação ainda. O Talent avalia até 3 vagas compatíveis por volta da fila.</p>
                : <div className="stack-sm">{data.avaliacoes.map((a) => <Evaluation key={a.id} a={a} />)}</div>}
            </Card>
          )}

          {tab === "revisoes" && (
            <Card title="Revisões curriculares" aside={<span className="tag">{data.revisoes.length}</span>}>
              {data.revisoes.length === 0 ? <p className="small muted">Nenhuma revisão ainda. Cada currículo do Alfaiate passa pelo Talent antes do Aplicador.</p>
                : <div className="stack-sm">{data.revisoes.map((r) => <Review key={r.id} r={r} />)}</div>}
            </Card>
          )}

          {tab === "resultados" && (
            <div className="stack-lg">
              <section aria-label="Indicadores" className="career-metrics">
                <Metric label="Candidaturas" value={data.resultados.candidaturas} sub={`${data.resultados.enviadas} enviadas`} />
                <Metric label="Respostas" value={data.resultados.respostas} sub={`taxa ${percent(data.resultados.taxa_resposta)}`} />
                <Metric label="Entrevistas" value={data.resultados.entrevistas} sub={`taxa ${percent(data.resultados.taxa_entrevista)}`} />
                <Metric label="Rejeições confirmadas" value={data.resultados.rejeicoes} />
                <Metric label="Vagas avaliadas" value={data.resultados.avaliadas} sub={`${data.resultados.elegiveis} elegíveis`} />
              </section>
              {!data.resultados.amostra_suficiente && (
                <p className="small muted">Menos de {data.resultados.min_amostra} candidaturas enviadas: os números são descritivos, sem comparação entre grupos.</p>)}
              <div className="career-split">
                <Groups title="Por plataforma" groups={data.resultados.por_plataforma} />
                <Groups title="Por perfil de currículo" groups={data.resultados.por_perfil} />
              </div>
              <div className="career-split">
                <Card title="Requisitos mais frequentes">
                  {data.resultados.requisitos.length === 0 ? <p className="small muted">Sem avaliações ainda.</p> : (
                    <div className="table-wrap"><table className="table career-table">
                      <thead><tr><th scope="col">Requisito</th><th scope="col" className="num">Vagas</th><th scope="col" className="num">Atendido</th><th scope="col" className="num">Ausente</th></tr></thead>
                      <tbody>{data.resultados.requisitos.map((t) => (
                        <tr key={t.termo}><td>{t.termo}</td><td className="num">{t.vagas}</td><td className="num">{t.atendido}</td><td className="num">{t.ausente}</td></tr>))}
                      </tbody></table></div>)}
                </Card>
                <Card title="Motivos de descarte e rejeição">
                  <ul className="small">
                    {data.resultados.motivos_inelegivel.map((m) => <li key={m.motivo}>{m.motivo}: {m.vagas} vaga(s)</li>)}
                    {data.resultados.rejeicoes_conhecidas.map((r, i) => <li key={i}>Recusa {r.empresa || "sem empresa"}: {r.resumo}</li>)}
                  </ul>
                  {data.resultados.motivos_inelegivel.length + data.resultados.rejeicoes_conhecidas.length === 0 &&
                    <p className="small muted">Nada registrado ainda.</p>}
                </Card>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
