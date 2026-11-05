// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira · currículos: a base do dono e as versões feitas pelo Alfaiate, com documento, uso e diferenças. */
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getResume, getResumes, resumeDocumentUrl, type ResumeItem } from "../api/carreira";
import { Skeleton } from "../components/Career";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader, Segmented } from "../components/ui";
import { lineDiff } from "../lib/career";
import { formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/carreira.css";

const USE: Record<string, string> = {
  enviada: "enviada", incerta: "envio incerto", precisa_de_voce: "parou para você", nao_aplicavel: "não aplicável",
  falhou: "falhou",
};

function DocLinks({ id }: { id: number }) {
  return (
    <span className="row">
      <a className="btn btn-secondary btn-sm" href={resumeDocumentUrl(id)} target="_blank" rel="noopener">
        <Icon name="download" /> Imprimir / PDF
      </a>
      <a className="btn btn-ghost btn-sm" href={resumeDocumentUrl(id, "md")}>Baixar .md</a>
    </span>
  );
}

function ResumeRow({ r }: { r: ResumeItem }) {
  return (
    <li>
      <Link to={`/carreira/curriculos/${r.id}`} className="career-job">
        <span className="career-job-main">
          <span className="career-job-title">
            {r.tipo === "base" ? "Currículo-base" : r.title}
            {" "}<span className="tag">v{r.id}</span>
          </span>
          <span className="small muted">
            {r.tipo === "base" ? "Fonte das versões adaptadas" : `${r.company || "Empresa não informada"} · vaga #${r.n}`}
            {r.origem_id ? ` · a partir da base v${r.origem_id}` : ""}
          </span>
          {r.alteracoes.length > 0 && <span className="small">{r.alteracoes.slice(0, 2).join(" · ")}{r.alteracoes.length > 2 ? "…" : ""}</span>}
        </span>
        <span className="career-job-side">
          {r.tipo === "base" && (r.vigente ? <Badge tone="good">Vigente</Badge> : <Badge tone="neutral">Anterior</Badge>)}
          {r.envios.length > 0 && (
            <span className="small">Usado em {r.envios.length} envio(s): {[...new Set(r.envios.map((e) => USE[e.status] ?? e.status))].join(", ")}</span>
          )}
          <span className="tiny muted">{formatDateTime(r.created_at)}</span>
        </span>
      </Link>
    </li>
  );
}

export function CareerResumesPage() {
  const { data, error, reload } = useAsync(getResumes, []);
  const bases = data?.filter((r) => r.tipo === "base") ?? [];
  const versions = data?.filter((r) => r.tipo === "vaga") ?? [];
  const current = bases.find((b) => b.vigente);

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Currículos"
        lede="O Alfaiate reorganiza e destaca o que está no seu perfil. Não inventa emprego, certificação, data, formação ou resultado." />
      <ErrorNotice error={error && !data ? error : null} onRetry={reload} />
      {!data && !error && <Skeleton rows={5} height={44} />}
      {data && (
        <>
          <Card title="Currículo-base" aside={current && <DocLinks id={current.id} />}>
            {bases.length === 0 ? (
              <p className="small muted">
                Nenhum currículo-base registrado. O serviço de carreira grava a versão do arquivo
                <code> curriculo.md </code> no início de cada ciclo; ele também é o currículo anexado ao atualizar perfis.
              </p>
            ) : <ul className="career-jobs">{bases.map((r) => <ResumeRow key={r.id} r={r} />)}</ul>}
          </Card>
          <Card title="Versões por vaga" aside={<span className="tag">{versions.length}</span>}>
            {versions.length === 0 ? (
              <EmptyState title="Nenhuma versão adaptada ainda" icon="book">
                Quando uma vaga compatível entra na fila, o Alfaiate prepara um currículo para ela e ele aparece aqui.
              </EmptyState>
            ) : <ul className="career-jobs">{versions.map((r) => <ResumeRow key={r.id} r={r} />)}</ul>}
          </Card>
        </>
      )}
    </div>
  );
}

export function CareerResumePage() {
  const id = Number(useParams().id);
  const { data, error, reload } = useAsync(() => getResume(id), [id]);
  const [tab, setTab] = useState<"documento" | "diferencas">("documento");
  const diff = useMemo(() => (data?.origem_md != null ? lineDiff(data.origem_md, data.conteudo_md) : null), [data]);

  if (error && !data) return <ErrorNotice error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={10} height={20} />;
  const changed = diff?.filter((l) => l.kind !== "same").length ?? 0;

  return (
    <div className="stack-lg">
      <nav aria-label="Trilha" className="small"><Link to="/carreira/curriculos" className="link-arrow">← Currículos</Link></nav>
      <PageHeader eyebrow={`Currículo v${data.id} · ${formatDateTime(data.created_at)}`}
        title={data.tipo === "base" ? "Currículo-base" : data.title ?? "Versão adaptada"}
        lede={data.tipo === "vaga" ? <>Para <Link to={`/carreira/vagas/${data.n}`}>{data.company || "vaga"} #{data.n}</Link>
          {data.origem_id ? <> · a partir da base <Link to={`/carreira/curriculos/${data.origem_id}`}>v{data.origem_id}</Link></> : " · base de origem não registrada (versão anterior ao histórico)"}</> : undefined}
        actions={<DocLinks id={data.id} />} />

      {data.alteracoes.length > 0 && (
        <Card title="Alterações informadas pelo Alfaiate">
          <ul className="bullets small">{data.alteracoes.map((a) => <li key={a}>{a}</li>)}</ul>
        </Card>
      )}

      {diff && (
        <Segmented label="Mostrar" value={tab} onChange={setTab}
          options={[{ value: "documento", label: "Documento" }, { value: "diferencas", label: `Diferenças da base (${changed})` }]} />
      )}
      {tab === "documento" || !diff ? (
        <article className="career-paper" aria-label="Currículo"><Markdown text={data.conteudo_md} /></article>
      ) : (
        <pre className="career-diff" aria-label="Diferenças linha a linha">
          {diff.map((l, i) => (
            <div key={i} className={`career-diff-${l.kind}`}>
              <span aria-hidden="true">{l.kind === "add" ? "+" : l.kind === "del" ? "−" : " "}</span>
              <span className="visually-hidden">{l.kind === "add" ? "adicionado: " : l.kind === "del" ? "removido: " : ""}</span>
              {l.text || " "}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}
