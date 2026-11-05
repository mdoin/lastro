// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira · currículos: currículo-base estruturado (fonte de verdade), perfis de apresentação, versões por vaga,
 *  o documento exato enviado em cada candidatura e o que ainda precisa da sua validação. */
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  PROFILE_LABEL, answerQuestion, editFact, generateProfiles, getBase, getResume, getResumes, resumeFileUrl,
  resumePageUrl, setRelease, type BaseView, type FactStatus, type ProfileId, type Question, type ResumeItem,
  type Validation,
} from "../api/curriculos";
import { Skeleton } from "../components/Career";
import { Icon } from "../components/Icon";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader, Segmented } from "../components/ui";
import { useApp } from "../lib/appContext";
import { lineDiff } from "../lib/career";
import { formatDateTime } from "../lib/dates";
import { errorMessage, useAsync } from "../lib/useAsync";
import "../styles/carreira.css";

const USE: Record<string, string> = {
  enviada: "enviada", incerta: "envio incerto", precisa_de_voce: "parou para você", nao_aplicavel: "não aplicável",
  falhou: "falhou",
};
const STATUS: Record<FactStatus, { label: string; tone: "good" | "warning" | "neutral" | "gold" }> = {
  confirmado: { label: "Confirmado", tone: "good" }, pendente: { label: "Pendente", tone: "warning" },
  inferido: { label: "Inferência", tone: "gold" }, descartado: { label: "Descartado", tone: "neutral" },
};

function ValidationBadge({ v }: { v: Validation | null }) {
  if (!v) return <Badge tone="neutral">Só texto (versão antiga)</Badge>;
  return v.ok
    ? <Badge tone="good">Validado · {v.paginas} pág.</Badge>
    : <Badge tone="critical">{v.erros} erro(s) na validação</Badge>;
}

function Files({ id, pdf = true }: { id: number; pdf?: boolean }) {
  return (
    <span className="row career-files">
      {pdf && <a className="btn btn-secondary btn-sm" href={resumeFileUrl(id, "pdf")} target="_blank" rel="noopener">
        <Icon name="download" /> PDF</a>}
      {pdf && <a className="btn btn-ghost btn-sm" href={resumeFileUrl(id, "docx")}>DOCX</a>}
      {!pdf && <a className="btn btn-secondary btn-sm" href={resumeFileUrl(id, "html")} target="_blank" rel="noopener">
        <Icon name="download" /> Imprimir</a>}
      <a className="btn btn-ghost btn-sm" href={resumeFileUrl(id, "md")}>.md</a>
    </span>
  );
}

export function ProfileCard({ p }: { p: BaseView["perfis"][number] }) {
  return (
    <article className="career-profile">
      {p.curriculo_id ? (
        <Link to={`/carreira/curriculos/${p.curriculo_id}`} className="career-sheet" aria-label={`Abrir ${p.nome}`}>
          <img src={resumePageUrl(p.curriculo_id, 1)} alt={`Primeira página do currículo ${p.nome}`} loading="lazy" />
        </Link>
      ) : <div className="career-sheet career-sheet-empty small muted">Ainda não gerado</div>}
      <div className="career-profile-body">
        <strong>{p.nome}</strong>
        <span className="small muted">Prioriza {p.descricao}.</span>
        <span className="row career-badges">{p.curriculo_id && <ValidationBadge v={p.validacao} />}</span>
        {p.curriculo_id && <Files id={p.curriculo_id} />}
      </div>
    </article>
  );
}

function ResumeRow({ r }: { r: ResumeItem }) {
  return (
    <li>
      <Link to={`/carreira/curriculos/${r.id}`} className="career-job">
        <span className="career-job-main">
          <span className="career-job-title">
            {r.tipo === "base" ? (r.perfil ? `Geral · ${PROFILE_LABEL[r.perfil]}` : "Currículo-base (texto)") : r.title}
            {" "}<span className="tag">v{r.id}</span>
          </span>
          <span className="small muted">
            {r.tipo === "vaga" ? `${r.company || "Empresa não informada"} · vaga #${r.n}` : "Versão geral do perfil"}
            {r.perfil && r.tipo === "vaga" ? ` · perfil ${PROFILE_LABEL[r.perfil]}` : ""}
            {r.idioma === "en" ? " · inglês" : ""}
          </span>
          {r.alteracoes.length > 0 && <span className="small">{r.alteracoes.slice(0, 2).join(" · ")}{r.alteracoes.length > 2 ? "…" : ""}</span>}
        </span>
        <span className="career-job-side">
          <ValidationBadge v={r.validacao} />
          {r.envios.length > 0 && (
            <span className="small">Enviado em {r.envios.length} candidatura(s): {[...new Set(r.envios.map((e) => USE[e.status] ?? e.status))].join(", ")}</span>
          )}
          <span className="tiny muted">{formatDateTime(r.created_at)}</span>
        </span>
      </Link>
    </li>
  );
}

function ReleaseCard({ data, reload }: { data: BaseView; reload: () => void }) {
  const { toast } = useApp();
  const [busy, setBusy] = useState(false);
  const ready = data.perfis.every((p) => p.curriculo_id && p.validacao?.ok);
  async function act(fn: () => Promise<unknown>, done: string) {
    setBusy(true);
    try { await fn(); toast(done); reload(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <Card title="Envio automático com o gerador novo" aside={data.liberado_em
      ? <Badge tone="good">Liberado</Badge> : <Badge tone="warning">Aguardando você</Badge>}>
      <p className="small">
        {data.liberado_em
          ? <>Liberado em {formatDateTime(data.liberado_em)}. Cada candidatura guarda o PDF exato enviado.</>
          : <>Confira os três PDFs acima. Até você liberar, o Alfaiate prepara as versões por vaga, mas o Aplicador não
            envia nenhuma candidatura.</>}
      </p>
      <span className="row">
        {!data.liberado_em && <button className="btn btn-primary btn-sm" disabled={busy || !ready}
          onClick={() => act(() => setRelease(true), "Gerador liberado para as candidaturas.")}>Liberar envio</button>}
        {data.liberado_em && <button className="btn btn-ghost btn-sm" disabled={busy}
          onClick={() => act(() => setRelease(false), "Envio pausado.")}>Pausar envio</button>}
        <button className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => act(generateProfiles, "Versões dos perfis conferidas.")}>
          <Icon name="refresh" /> Gerar versões dos perfis</button>
      </span>
    </Card>
  );
}

export function CareerResumesPage() {
  const base = useAsync(getBase, []);
  const list = useAsync(getResumes, []);
  const versions = list.data?.filter((r) => r.tipo === "vaga") ?? [];
  const pend = base.data ? base.data.pendencias.itens.length + base.data.pendencias.perguntas.length : 0;

  return (
    <div className="stack-lg">
      <PageHeader eyebrow="Carreira" title="Currículos"
        lede="Um currículo-base com fatos confirmados por você; três perfis de apresentação; uma versão por vaga, montada só com esses fatos e validada antes de sair." />
      <ErrorNotice error={list.error && !list.data ? list.error : null} onRetry={list.reload} />
      {(!base.data && !base.error) && <Skeleton rows={4} height={60} />}
      {base.error && !base.data && (
        <Card title="Currículo-base">
          <p className="small muted">Ainda não há currículo-base estruturado. O serviço de carreira importa o arquivo
            <code> base.json </code> do servidor na primeira vez; até lá vale o modo antigo (texto).</p>
        </Card>
      )}
      {base.data && (
        <>
          <Card title="Currículo-base" aside={<Link className="btn btn-secondary btn-sm" to="/carreira/curriculos/base">Ver e validar</Link>}>
            <div className="career-facts-row">
              <span><strong>v{base.data.versao.id}</strong> <span className="small muted">· {formatDateTime(base.data.versao.created_at)}</span></span>
              <span className="small">{base.data.versao.nota}</span>
              {pend > 0
                ? <Badge tone="warning">{pend} item(ns) esperando sua validação</Badge>
                : <Badge tone="good">Nada pendente</Badge>}
            </div>
          </Card>
          <section aria-labelledby="perfis-h" className="stack">
            <h2 id="perfis-h" className="section-title">Perfis de apresentação</h2>
            <div className="career-profiles">{base.data.perfis.map((p) => <ProfileCard key={p.perfil} p={p} />)}</div>
          </section>
          <ReleaseCard data={base.data} reload={base.reload} />
        </>
      )}
      {list.data && (
        <Card title="Versões por vaga" aside={<span className="tag">{versions.length}</span>}>
          {versions.length === 0 ? (
            <EmptyState title="Nenhuma versão por vaga ainda" icon="book">
              Quando uma vaga elegível entra na fila, o Alfaiate escolhe o perfil e os fatos mais relevantes e a versão aparece aqui.
            </EmptyState>
          ) : <ul className="career-jobs">{versions.map((r) => <ResumeRow key={r.id} r={r} />)}</ul>}
        </Card>
      )}
      {list.data && list.data.some((r) => r.tipo === "base") && (
        <details className="panel career-older">
          <summary>Versões gerais anteriores ({list.data.filter((r) => r.tipo === "base").length})</summary>
          <ul className="career-jobs">{list.data.filter((r) => r.tipo === "base").map((r) => <ResumeRow key={r.id} r={r} />)}</ul>
        </details>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------- versão (documento)

export function CareerResumePage() {
  const id = Number(useParams().id);
  const { data, error, reload } = useAsync(() => getResume(id), [id]);
  const all = useAsync(getResumes, []);
  const [tab, setTab] = useState<"documento" | "validacao" | "comparar">("documento");
  const [other, setOther] = useState<number | null>(null);
  const otherData = useAsync(() => (other ? getResume(other) : Promise.resolve(null)), [other]);
  const against = other ? otherData.data?.conteudo_md ?? null : data?.origem_md ?? null;
  const diff = useMemo(() => (data && against != null ? lineDiff(against, data.conteudo_md) : null), [data, against]);

  if (error && !data) return <ErrorNotice error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={10} height={20} />;
  const pages = Array.from({ length: data.paginas ?? 0 }, (_, i) => i + 1);
  const v = data.validacao;

  return (
    <div className="stack-lg">
      <nav aria-label="Trilha" className="small"><Link to="/carreira/curriculos" className="link-arrow">← Currículos</Link></nav>
      <PageHeader eyebrow={`Currículo v${data.id} · ${formatDateTime(data.created_at)}`}
        title={data.tipo === "base" ? (data.perfil ? `Geral · ${PROFILE_LABEL[data.perfil]}` : "Currículo-base (texto)") : data.title ?? "Versão por vaga"}
        lede={data.tipo === "vaga" ? <>Para <Link to={`/carreira/vagas/${data.n}`}>{data.company || "vaga"} #{data.n}</Link>
          {data.perfil ? ` · perfil ${PROFILE_LABEL[data.perfil]}` : ""}
          {data.analise?.perfil_fonte ? ` (escolhido pelo ${data.analise.perfil_fonte === "talent" ? "Talent" : data.analise.perfil_fonte === "alfaiate" ? "Alfaiate" : "título da vaga"})` : ""}</> : undefined}
        actions={<Files id={data.id} pdf={data.tem_pdf} />} />

      <Segmented label="Mostrar" value={tab} onChange={setTab} options={[
        { value: "documento", label: "Documento" }, { value: "validacao", label: v ? (v.ok ? "Validação ✓" : "Validação ✗") : "Validação" },
        { value: "comparar", label: "Comparar" }]} />

      {tab === "documento" && (data.tem_pdf ? (
        <div className="career-pages">
          {pages.map((p) => <img key={p} src={resumePageUrl(data.id, p)} alt={`Página ${p} do currículo (PDF exato)`} className="career-page" />)}
        </div>
      ) : <article className="career-paper" aria-label="Currículo"><pre className="career-md">{data.conteudo_md}</pre></article>)}

      {tab === "validacao" && (
        <div className="career-split">
          <Card title="Validação do documento">
            {!v ? <p className="small muted">Versão anterior ao gerador novo: sem PDF guardado nem validação.</p> : (
              <dl className="career-facts">
                <div><dt>Resultado</dt><dd>{v.ok ? "aprovado" : "reprovado"}</dd></div>
                <div><dt>Páginas</dt><dd>{v.paginas}{v.ocupacao ? ` (ocupação da última: ${Math.round((v.ocupacao.at(-1) ?? 0) * 100)}%)` : ""}</dd></div>
                <div><dt>Fontes incorporadas</dt><dd>{v.fontes?.join(", ") || "—"}</dd></div>
                <div><dt>Links clicáveis</dt><dd>{v.links?.join(" · ") || "—"}</dd></div>
                <div><dt>Texto extraído</dt><dd>{v.caracteres} caracteres, conferidos com o conteúdo</dd></div>
                <div><dt>DOCX</dt><dd>{v.docx ? (v.docx.ok ? "aprovado" : v.docx.erros.join("; ")) : "—"}</dd></div>
                <div><dt>SHA-256 do PDF</dt><dd className="mono tiny">{data.sha256}</dd></div>
                <div><dt>Conferido em</dt><dd>{v.verificado_em ? formatDateTime(v.verificado_em) : "—"}</dd></div>
              </dl>
            )}
            {v && v.erros.length > 0 && <ul className="bullets small career-error-list">{v.erros.map((e) => <li key={e}>{e}</li>)}</ul>}
            {v && v.avisos.length > 0 && <ul className="bullets small muted">{v.avisos.map((e) => <li key={e}>{e}</li>)}</ul>}
            <p className="tiny muted">A extração de texto confirma que o conteúdo está inteiro e na ordem certa; não garante
              compatibilidade com todo sistema de recrutamento.</p>
          </Card>
          <div className="stack">
            {data.alteracoes.length > 0 && (
              <Card title="Escolhas do Alfaiate"><ul className="bullets small">{data.alteracoes.map((a) => <li key={a}>{a}</li>)}</ul></Card>
            )}
            {(data.analise?.lacunas?.length ?? 0) > 0 && (
              <Card title="Lacunas (não entram no currículo)">
                <ul className="bullets small">{data.analise!.lacunas!.map((g) => <li key={g.requisito}><strong>{g.requisito}:</strong> {g.dica}</li>)}</ul>
              </Card>
            )}
            <Card title="Onde esta versão foi enviada">
              {data.envios.length === 0 ? <p className="small muted">Ainda não foi anexada a nenhuma candidatura.</p> : (
                <ul className="bullets small">{data.envios.map((e) => (
                  <li key={e.id}><Link to={`/carreira/candidaturas/${e.n}`}>{e.company} · #{e.n}</Link> — {USE[e.status] ?? e.status}
                    {e.anexo ? ` · anexo: ${e.anexo}` : ""} · {formatDateTime(e.created_at)}</li>))}</ul>
              )}
            </Card>
          </div>
        </div>
      )}

      {tab === "comparar" && (
        <div className="stack">
          <label className="field">
            <span className="small">Comparar com</span>
            <select className="input" value={other ?? ""} onChange={(e) => setOther(e.target.value ? Number(e.target.value) : null)}>
              <option value="">{data.origem_id ? `Versão de origem (v${data.origem_id})` : "Sem versão de origem"}</option>
              {all.data?.filter((r) => r.id !== data.id).map((r) => (
                <option key={r.id} value={r.id}>v{r.id} · {r.tipo === "base" ? (r.perfil ? `geral ${PROFILE_LABEL[r.perfil]}` : "base (texto)") : `${r.company} #${r.n}`}</option>
              ))}
            </select>
          </label>
          {diff ? (
            <pre className="career-diff" aria-label="Diferenças linha a linha">
              {diff.map((l, i) => (
                <div key={i} className={`career-diff-${l.kind}`}>
                  <span aria-hidden="true">{l.kind === "add" ? "+" : l.kind === "del" ? "−" : " "}</span>
                  <span className="visually-hidden">{l.kind === "add" ? "adicionado: " : l.kind === "del" ? "removido: " : ""}</span>
                  {l.text || " "}
                </div>
              ))}
            </pre>
          ) : <p className="small muted">Escolha uma versão para comparar.</p>}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------- base (validação)

export function FactRow({ id, status, text, en, source, label, onSaved }: {
  id: string; status: FactStatus; text: string; en?: string; source?: string; label?: string; onSaved: () => void;
}) {
  const { toast } = useApp();
  const [editing, setEditing] = useState(false);
  const [pt, setPt] = useState(text);
  const [enText, setEn] = useState(en ?? "");
  const [busy, setBusy] = useState(false);
  async function save(body: Parameters<typeof editFact>[1], done: string) {
    setBusy(true);
    try { await editFact(id, body); toast(done); setEditing(false); onSaved(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  const s = STATUS[status];
  return (
    <li className={`career-fact${status === "descartado" ? " is-muted" : ""}`}>
      <div className="career-fact-main">
        {editing ? (
          <div className="stack">
            <textarea className="input" rows={3} value={pt} onChange={(e) => setPt(e.target.value)} aria-label="Texto em português" />
            {en !== undefined && <textarea className="input" rows={3} value={enText} onChange={(e) => setEn(e.target.value)} aria-label="Texto em inglês" />}
          </div>
        ) : <span>{label && <strong>{label} — </strong>}{text}</span>}
        {source && !editing && <span className="tiny muted">Fonte: {source}</span>}
      </div>
      <div className="career-fact-side">
        <Badge tone={s.tone}>{s.label}</Badge>
        <span className="row">
          {editing ? (
            <>
              <button className="btn btn-primary btn-sm" disabled={busy || pt.trim().length < 2}
                onClick={() => save({ pt, ...(en !== undefined ? { en: enText } : {}), status: "confirmado" }, "Texto salvo e confirmado.")}>Salvar</button>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancelar</button>
            </>
          ) : (
            <>
              {status !== "confirmado" && <button className="btn btn-secondary btn-sm" disabled={busy}
                onClick={() => save({ status: "confirmado" }, "Confirmado: pode aparecer nos currículos.")}>Confirmar</button>}
              {status === "confirmado" && <button className="btn btn-ghost btn-sm" disabled={busy}
                onClick={() => save({ status: "pendente" }, "Marcado como pendente: sai dos currículos.")}>Pendente</button>}
              {status !== "descartado" && <button className="btn btn-ghost btn-sm" disabled={busy}
                onClick={() => save({ status: "descartado" }, "Descartado.")}>Descartar</button>}
              <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)} aria-label="Editar texto"><Icon name="edit" /></button>
            </>
          )}
        </span>
      </div>
    </li>
  );
}

function QuestionRow({ q, onSaved }: { q: Question; onSaved: () => void }) {
  const { toast } = useApp();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  async function send(descartar: boolean) {
    setBusy(true);
    try { await answerQuestion(q.id, text, descartar); toast(descartar ? "Pergunta descartada." : "Resposta registrada."); onSaved(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <li className="career-question">
      <p>{q.pergunta}</p>
      <textarea className="input" rows={2} value={text} onChange={(e) => setText(e.target.value)} aria-label={q.pergunta}
        placeholder="Sua resposta (pode ser aproximada; diga quando for estimativa)" />
      <span className="row">
        <button className="btn btn-primary btn-sm" disabled={busy || text.trim().length < 2} onClick={() => send(false)}>Responder</button>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => send(true)}>Não se aplica</button>
      </span>
    </li>
  );
}

export function CareerResumeBasePage() {
  const { data, error, reload } = useAsync(getBase, []);
  const [view, setView] = useState<"pendencias" | "tudo" | "historico">("pendencias");
  if (error && !data) return <ErrorNotice error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={10} height={24} />;
  const b = data.base;
  const answered = b.perguntas.filter((q) => q.status === "respondida");
  const pendIds = new Set(data.pendencias.itens.map((i) => i.id));
  const facts = (filter: (status: FactStatus, id: string) => boolean) => ({
    exp: b.experiencias.map((e) => ({ e, rs: e.realizacoes.filter((r) => filter(r.status, r.id)) })).filter((x) => x.rs.length),
    proj: b.projetos.filter((p) => filter(p.status, p.id)),
    skills: b.competencias.filter((s) => filter(s.status, s.id)),
    courses: b.cursos.filter((c) => filter(c.status, c.id)),
  });
  const shown = facts(view === "pendencias" ? (_s, id) => pendIds.has(id) : () => true);

  return (
    <div className="stack-lg">
      <nav aria-label="Trilha" className="small"><Link to="/carreira/curriculos" className="link-arrow">← Currículos</Link></nav>
      <PageHeader eyebrow={`Currículo-base · v${data.versao.id}`} title={b.pessoa.nome ?? "Currículo-base"}
        lede="Fonte de verdade de todos os currículos. Só o que está confirmado entra em um documento; pendências e inferências ficam aqui até você decidir." />
      <Segmented label="Mostrar" value={view} onChange={setView} options={[
        { value: "pendencias", label: `Para validar (${data.pendencias.itens.length + data.pendencias.perguntas.length})` },
        { value: "tudo", label: "Tudo" }, { value: "historico", label: `Histórico (${data.historico.length})` }]} />

      {view === "historico" ? (
        <Card title="Versões do currículo-base">
          <ul className="bullets small">{data.historico.map((h) => (
            <li key={h.id}><strong>v{h.id}</strong> · {formatDateTime(h.created_at)} · {h.origem === "dono" ? "você" : "importação"} — {h.nota}</li>))}</ul>
        </Card>
      ) : (
        <>
          {data.pendencias.perguntas.length > 0 && (
            <Card title="Perguntas para enriquecer o currículo" aside={<span className="tag">{data.pendencias.perguntas.length}</span>}>
              <p className="small muted">Números e resultados só entram depois de você responder. Com a resposta, edite a
                realização correspondente para incluir o dado.</p>
              <ul className="career-questions">{data.pendencias.perguntas.map((q) => <QuestionRow key={q.id} q={q} onSaved={reload} />)}</ul>
            </Card>
          )}
          {view === "tudo" && (
            <Card title="Dados pessoais e títulos">
              <dl className="career-facts">
                <div><dt>Contato</dt><dd>{b.pessoa.cidade}, {b.pessoa.uf} · {b.pessoa.telefone} · {b.pessoa.email}</dd></div>
                <div><dt>Links</dt><dd>{b.pessoa.linkedin} · {b.pessoa.github}</dd></div>
                {(Object.keys(b.titulos) as ProfileId[]).map((p) => (
                  <div key={p}><dt>{PROFILE_LABEL[p]}</dt><dd><strong>{b.titulos[p].pt}</strong><br /><span className="small">{b.resumos[p].pt}</span></dd></div>
                ))}
              </dl>
            </Card>
          )}
          {shown.exp.map(({ e, rs }) => (
            <Card key={e.id} title={e.empresa} eyebrow="Experiência"
              aside={<span className="small muted">{e.cargos.map((c) => c.pt).join(" ← ")}</span>}>
              <ul className="career-facts-list">{rs.map((r) => (
                <FactRow key={r.id} id={r.id} status={r.status} text={r.pt} en={r.en ?? ""} source={r.fonte} onSaved={reload} />))}</ul>
            </Card>
          ))}
          {shown.proj.length > 0 && (
            <Card title="Projetos" eyebrow="Portfólio">
              <ul className="career-facts-list">{shown.proj.map((p) => (
                <FactRow key={p.id} id={p.id} status={p.status} source={p.fonte} onSaved={reload} text={p.descricao.pt}
                  en={p.descricao.en ?? ""}
                  label={`${p.nome}${p.corporativo ? (p.divulgacao === "autorizada" ? " (corporativo, autorizado)" : " (corporativo: só aparece como realização até você autorizar)") : ""}`} />))}</ul>
            </Card>
          )}
          {shown.skills.length > 0 && (
            <Card title="Competências" eyebrow="Só com evidência em experiência ou projeto">
              <ul className="career-facts-list">{shown.skills.map((s) => (
                <FactRow key={s.id} id={s.id} status={s.status} text={s.nome} source={s.fonte} onSaved={reload} />))}</ul>
            </Card>
          )}
          {view === "tudo" && shown.courses.length > 0 && (
            <Card title="Cursos e formação" eyebrow="Cursos livres não aparecem como certificação">
              <ul className="career-facts-list">
                {b.formacao.map((f) => <FactRow key={f.id} id={f.id} status={f.status} onSaved={reload}
                  text={`${f.curso.pt} — ${f.instituicao} · ${f.situacao === "em_andamento" ? `em andamento, conclusão prevista em ${f.conclusao}` : f.conclusao ?? ""}`} />)}
                {shown.courses.map((c) => <FactRow key={c.id} id={c.id} status={c.status} source={c.fonte} onSaved={reload}
                  text={`${c.nome} — ${c.instituicao}${c.data ? ` · ${c.data}` : ""}`} />)}
              </ul>
            </Card>
          )}
          {view === "pendencias" && data.pendencias.itens.length === 0 && data.pendencias.perguntas.length === 0 && (
            <EmptyState title="Nada esperando validação" icon="check">Tudo o que está no currículo-base foi confirmado por você.</EmptyState>
          )}
          {answered.length > 0 && view === "tudo" && (
            <Card title="Respostas já dadas">
              <ul className="bullets small">{answered.map((q) => <li key={q.id}><strong>{q.pergunta}</strong> {q.resposta}</li>)}</ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
