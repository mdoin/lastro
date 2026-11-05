// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira · oportunidades: vagas encontradas pelos agentes, com filtros na URL e detalhe com a análise. */
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { getJob, getJobs, type Job, type JobFilters } from "../api/carreira";
import { ApplicationBadges, Skeleton, Timeline } from "../components/Career";
import { Icon } from "../components/Icon";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader } from "../components/ui";
import {
  COLUMNS, SENIORITY, VERDICT, WORKPLACE, formatSalary, sourceLabel, usePolling,
} from "../lib/career";
import { formatDate, formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/carreira.css";

const PAGE = 50;
const COMPAT: Record<string, { label: string; api: string }> = {
  "": { label: "Compatíveis e para conferir", api: "compativel,talvez" },
  compativel: { label: "Só compatíveis", api: "compativel" },
  talvez: { label: "Para conferir", api: "talvez" },
  fora: { label: "Fora do perfil", api: "fora" },
  todas: { label: "Todas", api: "compativel,talvez,fora" },
};
const TEXT_FILTERS = ["q", "empresa", "local", "salario_min", "aderencia_min"] as const;

function JobMeta({ job }: { job: Job }) {
  const salary = formatSalary(job.salary_min, job.currency);
  const parts = [job.location || null, WORKPLACE[job.workplace], job.contrato, salary ? `a partir de ${salary}` : null];
  return <span className="small muted">{parts.filter(Boolean).join(" · ")}</span>;
}

export function CareerJobsPage() {
  const [params, setParams] = useSearchParams();
  const [limit, setLimit] = useState(PAGE);
  const [draft, setDraft] = useState(() => Object.fromEntries(TEXT_FILTERS.map((k) => [k, params.get(k) ?? ""])));
  const get = (k: string) => params.get(k) ?? "";

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
    setLimit(PAGE);
  };

  // Texto: aplica 300 ms depois da última tecla (sem uma requisição por letra).
  useEffect(() => {
    const t = window.setTimeout(() => {
      const next = new URLSearchParams(params);
      let changed = false;
      for (const k of TEXT_FILTERS) {
        if ((params.get(k) ?? "") !== draft[k]) {
          changed = true;
          if (draft[k]) next.set(k, draft[k]);
          else next.delete(k);
        }
      }
      if (changed) {
        setParams(next, { replace: true });
        setLimit(PAGE);
      }
    }, 300);
    return () => window.clearTimeout(t);
  }, [draft, params, setParams]);

  const filters: JobFilters = {
    q: get("q"), empresa: get("empresa"), local: get("local"), modalidade: get("modalidade"),
    senioridade: get("senioridade"), compat: (COMPAT[get("compat")] ?? COMPAT[""]!).api, fonte: get("fonte"),
    status: get("status"), salario_min: get("salario_min"), aderencia_min: get("aderencia_min"), desde: get("desde"),
    ordem: get("ordem") === "data" ? "data" : "relevancia", limit,
  };
  const key = JSON.stringify(filters);
  const { data, error, reload, loading } = useAsync(() => getJobs(filters), [key]);
  usePolling(reload, 60_000);
  const active = [...params.keys()].filter((k) => k !== "ordem").length;
  const secondary = [...params.keys()].filter((k) => !["ordem", "q", "compat"].includes(k)).length;
  // No celular os filtros secundários começam recolhidos; no desktop, ou com algum ativo, abertos.
  const [moreOpen, setMoreOpen] = useState(() => secondary > 0 || (typeof window !== "undefined" && window.matchMedia("(min-width: 720px)").matches));

  const select = (k: string, label: string, options: [string, string][]) => (
    <label className="career-filter">
      <span>{label}</span>
      <select className="select" value={get(k)} onChange={(e) => set(k, e.target.value)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
  const text = (k: (typeof TEXT_FILTERS)[number], label: string, extra: Record<string, string> = {}) => (
    <label className="career-filter">
      <span>{label}</span>
      <input className="input" value={draft[k]} onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))} {...extra} />
    </label>
  );

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Oportunidades"
        lede="Vagas encontradas pelo caçador e pelos alertas de e-mail, avaliadas pelas suas regras e pelo Alfaiate." />

      <form className="career-filters" role="search" aria-label="Filtrar oportunidades" onSubmit={(e) => e.preventDefault()}>
        <label className="career-filter career-filter-wide">
          <span>Buscar</span>
          <input className="input" type="search" placeholder="Cargo, empresa, tecnologia…" value={draft.q}
            onChange={(e) => setDraft((d) => ({ ...d, q: e.target.value }))} />
        </label>
        {select("compat", "Compatibilidade", Object.entries(COMPAT).map(([v, o]) => [v, o.label]))}
        <details className="career-more-filters" open={moreOpen} onToggle={(e) => setMoreOpen(e.currentTarget.open)}>
          <summary>Mais filtros{secondary ? ` (${secondary} ativo${secondary > 1 ? "s" : ""})` : ""}</summary>
          <div className="career-filters-grid">
        {select("modalidade", "Modalidade", [["", "Todas"], ...Object.entries(WORKPLACE)])}
        {select("senioridade", "Senioridade", [["", "Todas"], ...Object.entries(SENIORITY)])}
        {select("status", "Candidatura", [["", "Todas"], ["sem_candidatura", "Sem candidatura"],
          ...COLUMNS.map((c): [string, string] => [c.key, c.label])])}
        {select("fonte", "Plataforma", [["", "Todas"], ...(data?.fontes ?? []).map((f): [string, string] => [f, sourceLabel(f)])])}
        {text("empresa", "Empresa")}
        {text("local", "Localização")}
        {text("salario_min", "Salário mínimo", { inputMode: "numeric", placeholder: "R$" })}
        {text("aderencia_min", "Aderência mínima", { inputMode: "numeric", placeholder: "0–100" })}
        <label className="career-filter">
          <span>Descoberta desde</span>
          <input className="input" type="date" value={get("desde")} onChange={(e) => set("desde", e.target.value)} />
        </label>
          </div>
        </details>
        {select("ordem", "Ordenar por", [["", "Relevância"], ["data", "Mais recentes"]])}
        {active > 0 && (
          <button type="button" className="btn btn-ghost btn-sm career-filter-clear"
            onClick={() => { setParams(new URLSearchParams(), { replace: true }); setDraft(Object.fromEntries(TEXT_FILTERS.map((k) => [k, ""]))); }}>
            Limpar filtros
          </button>
        )}
      </form>

      <ErrorNotice error={error && !data ? error : null} onRetry={reload} />
      {!data && !error && <Skeleton rows={8} height={44} />}
      {data && (
        <section aria-label="Resultados" aria-busy={loading} className="stack-sm">
          <div className="tiny muted mono" aria-live="polite">{data.total} vaga(s)</div>
          {data.items.length === 0 ? (
            <EmptyState title={active ? "Nenhuma vaga com esses filtros" : "Nenhuma oportunidade descoberta ainda"} icon="search">
              {active ? "Afrouxe um filtro ou limpe todos." :
                "O caçador busca a cada 6 horas em Gupy, LinkedIn, Catho, Programathor, RemoteOK e Remotive."}
            </EmptyState>
          ) : (
            <ul className="career-jobs">
              {data.items.map((job) => (
                <li key={job.id}>
                  <Link to={`/carreira/vagas/${job.n}`} className="career-job">
                    <span className="career-job-main">
                      <span className="career-job-title">{job.title}</span>
                      <span className="career-job-company">{job.company || "Empresa não informada"}</span>
                      <JobMeta job={job} />
                    </span>
                    <span className="career-job-side">
                      <span className="row">
                        <Badge tone={VERDICT[job.verdict].tone}>{VERDICT[job.verdict].label}</Badge>
                        {job.aderencia != null && <span className="tag" title="Aderência calculada pelo Alfaiate">{job.aderencia}%</span>}
                      </span>
                      {job.candidatura_status && <ApplicationBadges status={job.candidatura_status} etapa={job.etapa} />}
                      <span className="tiny muted">
                        {sourceLabel(job.source)} · encontrada {formatDate(job.first_seen)}
                        {job.published_at ? ` · publicada ${formatDate(job.published_at)}` : ""}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {data.items.length < data.total && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setLimit((l) => l + PAGE)}>
              Mostrar mais ({data.total - data.items.length} restantes)
            </button>
          )}
        </section>
      )}
    </div>
  );
}

export function CareerJobPage() {
  const n = Number(useParams().n);
  const { data, error, reload } = useAsync(() => getJob(n), [n]);
  usePolling(reload, 30_000);

  if (error && !data) return <ErrorNotice error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={8} height={24} />;
  const c = data.candidatura;
  return (
    <div className="stack-lg">
      <nav aria-label="Trilha" className="small"><Link to="/carreira/vagas" className="link-arrow">← Oportunidades</Link></nav>
      <PageHeader eyebrow={`Vaga #${data.n} · ${sourceLabel(data.source)}`} title={data.title}
        lede={data.company || "Empresa não informada"}
        actions={<>
          <a className="btn btn-secondary btn-sm" href={data.url} target="_blank" rel="noopener noreferrer">
            <Icon name="globe" /> Abrir vaga original
          </a>
          {c && <Link className="btn btn-primary btn-sm" to={`/carreira/candidaturas/${data.n}`}>Ver candidatura</Link>}
        </>} />

      <div className="career-split">
        <Card title="Dados da vaga">
          <dl className="career-facts">
            <div><dt>Localização</dt><dd>{data.location || "Não informada"}</dd></div>
            <div><dt>Modalidade</dt><dd>{WORKPLACE[data.workplace]}</dd></div>
            <div><dt>Contratação</dt><dd>{data.contrato ?? "Não informada"}</dd></div>
            <div><dt>Senioridade</dt><dd>{SENIORITY[data.senioridade]}</dd></div>
            <div><dt>Salário</dt><dd>{data.salary_min != null ? `a partir de ${formatSalary(data.salary_min, data.currency)}` : "Não informado"}</dd></div>
            <div><dt>Encontrada</dt><dd>{formatDateTime(data.first_seen)}</dd></div>
            <div><dt>Publicada</dt><dd>{data.published_at ? formatDate(data.published_at) : "Não informada"}</dd></div>
          </dl>
        </Card>

        <Card title="Compatibilidade" aside={<Badge tone={VERDICT[data.verdict].tone}>{VERDICT[data.verdict].label}</Badge>}>
          <div className="stack-sm">
            <div>
              <div className="eyebrow">Regras do seu perfil</div>
              <ul className="bullets small">{data.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
            {c ? (
              <div className="stack-sm">
                <div className="eyebrow">Análise do Alfaiate · aderência {c.aderencia}%</div>
                <p className="small">{c.resumo}</p>
                {c.lacunas.length > 0 && (
                  <div>
                    <div className="small muted">Requisitos que o perfil não cobre</div>
                    <ul className="bullets small">
                      {c.lacunas.map((g) => <li key={g.requisito}><strong>{g.requisito}</strong>{g.dica ? ` — ${g.dica}` : ""}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="small muted">
                {data.verdict === "compativel" ? "Ainda sem análise do Alfaiate: ela entra na fila do próximo ciclo."
                  : "O Alfaiate só analisa vagas compatíveis com as regras."}
              </p>
            )}
          </div>
        </Card>
      </div>

      {data.duplicatas.length > 0 && (
        <Card title="Possíveis duplicatas">
          <ul className="career-list">
            {data.duplicatas.map((d) => (
              <li key={d.n}><Link to={`/carreira/vagas/${d.n}`} className="career-list-link">
                <span className="tag">#{d.n}</span><span className="career-list-main">{d.title} · {sourceLabel(d.source)}</span>
              </Link></li>
            ))}
          </ul>
          <p className="tiny muted">Mesma URL ou mesma empresa, cargo e local. O Aplicador não envia duas vezes para a mesma vaga.</p>
        </Card>
      )}

      <div className="career-split">
        <Card title="Descrição" eyebrow="Texto da plataforma">
          {data.description ? <div className="career-description">{data.description}</div>
            : <p className="small muted">A fonte não trouxe descrição. Abra a vaga original para ver requisitos e benefícios.</p>}
        </Card>
        <Card title="Histórico">
          <Timeline events={data.eventos} />
        </Card>
      </div>
    </div>
  );
}
