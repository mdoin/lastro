// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Caixa de entrada financeira (Mila): enviar documentos, acompanhar a leitura, revisar pendências, resolver
 * duplicatas, corrigir categorias e ver a origem de cada lançamento. Nada aqui movimenta dinheiro.
 */
import { useCallback, useMemo, useRef, useState, type DragEvent } from "react";
import { ApiError } from "../api/client";
import {
  ACCEPT,
  DOC_LABEL,
  KIND_LABEL,
  approveDocument,
  deleteDocument,
  entryAction,
  getCategories,
  getConsents,
  getInbox,
  getLedger,
  interpretDocument,
  money,
  setConsent,
  uploadDocument,
  type EntryAction,
  type InboxDocument,
  type LedgerEntry,
} from "../api/ledger";
import { AgentAvatar } from "../components/AgentAvatar";
import { Icon } from "../components/Icon";
import { Badge, ErrorNotice, Loading, PageHeader, Segmented } from "../components/ui";
import { formatDate, formatDateTime } from "../lib/dates";
import { useAsync } from "../lib/useAsync";
import "../styles/inbox.css";

type Filter = "pendente" | "duplicada" | "registrado" | "todas";

const STATUS_TONE = { registrado: "good", pendente: "warning", duplicada: "neutral", desfeito: "neutral", descartado: "neutral" } as const;
const DOC_STATUS: Record<InboxDocument["status"], string> = {
  processado: "processado", revisao: "precisa de revisão", sem_leitura: "sem leitura", interpretando: "lendo com IA…",
  erro: "erro", excluido: "excluído",
};

export function InboxPage() {
  const inbox = useAsync(getInbox, []);
  const consents = useAsync(getConsents, []);
  const categories = useAsync(getCategories, []);
  const [filter, setFilter] = useState<Filter>("pendente");
  const ledger = useAsync(() => getLedger(filter === "todas" ? {} : { status: filter }), [filter]);
  const [busy, setBusy] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const docs = useMemo(() => Object.fromEntries((inbox.data?.documents ?? []).map((d) => [d.id, d])), [inbox.data]);

  const refresh = useCallback(() => { void inbox.reload(); void ledger.reload(); }, [inbox, ledger]);
  const fail = (e: unknown) => setError(e instanceof ApiError ? e.detail : "Não foi possível concluir.");

  async function send(files: FileList | File[]) {
    setError(null);
    setNotice(null);
    for (const file of Array.from(files)) {
      setBusy((b) => [...b, file.name]);
      try {
        const doc = await uploadDocument(file);
        setNotice(doc.repeated ? `“${file.name}” já tinha sido enviado; nada foi duplicado.`
          : `“${doc.original_name}”: ${doc.summary.identified ?? 0} movimentações identificadas, ${doc.summary.registered ?? 0} registradas, ${doc.summary.review ?? 0} para revisar, ${doc.summary.duplicates ?? 0} duplicadas.`);
      } catch (e) {
        fail(e);
      } finally {
        setBusy((b) => b.filter((n) => n !== file.name));
      }
    }
    refresh();
  }

  async function act(id: string, action: EntryAction, changes = {}) {
    try { await entryAction(id, action, changes); refresh(); } catch (e) { fail(e); }
  }

  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) void send(e.dataTransfer.files); };
  const auto = consents.data?.auto_register.granted ?? false;
  const ai = consents.data?.ai_documents.granted ?? false;

  return (
    <div className="inbox">
      <PageHeader eyebrow="Mila · Organizadora financeira" title="Caixa de entrada"
        lede="Envie extratos, faturas e comprovantes. A Mila lê, concilia e separa o que precisa da sua revisão. Ninguém aqui movimenta dinheiro." />

      <section className="inbox-top">
        <div className={`inbox-drop${over ? " is-over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)} onDrop={onDrop}>
          <AgentAvatar id="mila" size={56} decorative state={busy.length ? "thinking" : "idle"} />
          <div>
            <p className="inbox-drop-title">{busy.length ? `Lendo ${busy.join(", ")}…` : "Arraste arquivos para cá"}</p>
            <p className="small muted">PDF, PNG, JPG, CSV ou OFX · até 10 MB cada.
              {inbox.data && !inbox.data.ocr && " Imagens precisam de OCR no servidor (não instalado)."}
              {inbox.data && !inbox.data.pdf && " Leitura de PDF indisponível nesta instalação."}</p>
          </div>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => input.current?.click()}>
            <Icon name="plus" /> Escolher arquivos
          </button>
          <input ref={input} type="file" multiple accept={ACCEPT} className="visually-hidden" tabIndex={-1}
            onChange={(e) => { if (e.target.files?.length) void send(e.target.files); e.target.value = ""; }} />
        </div>

        <div className="inbox-prefs" role="group" aria-label="Preferências">
          <label className="team-check small">
            <input type="checkbox" role="switch" checked={auto} disabled={!consents.data}
              onChange={(e) => void setConsent("auto_register", e.target.checked).then(consents.setData).catch(fail)} />
            <span><strong>Registrar automaticamente</strong> o que estiver claro (valor, data e tipo) em documentos e no que você disser na conversa. Desligado, tudo fica para você aprovar.</span>
          </label>
          <label className="team-check small">
            <input type="checkbox" role="switch" checked={ai} disabled={!consents.data}
              onChange={(e) => void setConsent("ai_documents", e.target.checked).then(consents.setData).catch(fail)} />
            <span><strong>Permitir leitura por IA</strong> quando a leitura automática falhar: o <em>texto</em> do documento é enviado ao provedor de IA configurado para a Mila. Só acontece quando você pede, documento a documento.</span>
          </label>
          {inbox.data && <p className="tiny muted">Arquivos originais ficam {inbox.data.retention_days ? `${inbox.data.retention_days} dias` : "só durante a leitura"} em área privada do servidor; os lançamentos e a origem continuam depois.</p>}
        </div>
      </section>

      {error && <p className="inbox-alert" role="alert">{error}</p>}
      {notice && <p className="inbox-ok" role="status">{notice}</p>}

      <section className="inbox-docs" aria-labelledby="docs-title">
        <h2 id="docs-title" className="eyebrow">Documentos</h2>
        {inbox.loading && !inbox.data && <Loading />}
        <ErrorNotice error={inbox.error} onRetry={inbox.reload} />
        {inbox.data && !inbox.data.documents.length && <p className="small muted">Nenhum documento ainda.</p>}
        <ul className="inbox-doc-list">
          {(inbox.data?.documents ?? []).map((d) => (
            <li key={d.id} className="inbox-doc" data-status={d.status}>
              <span className="inbox-doc-icon" aria-hidden="true"><Icon name={d.source_format === "png" || d.source_format === "jpg" ? "copy" : "book"} /></span>
              <span className="inbox-doc-main">
                <strong>{d.original_name}</strong>
                <span className="tiny muted">{DOC_LABEL[d.doc_type]}{d.institution && ` · ${d.institution}`}{d.account && ` · final ${d.account}`} · {formatDateTime(d.created_at)}</span>
                <span className="small">
                  {d.status === "sem_leitura" ? d.summary.reason
                    : `${d.summary.identified ?? 0} identificadas · ${d.summary.registered ?? 0} registradas · ${d.summary.review ?? 0} para revisar · ${d.summary.duplicates ?? 0} duplicadas${d.summary.already ? ` · ${d.summary.already} já importadas` : ""}`}
                </span>
              </span>
              <span className="inbox-doc-actions">
                <Badge tone={d.status === "processado" ? "good" : d.status === "revisao" ? "warning" : "neutral"}>{DOC_STATUS[d.status]}</Badge>
                {d.status === "revisao" && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => void approveDocument(d.id).then(refresh).catch(fail)}>
                    Aprovar completas
                  </button>
                )}
                {ai && (d.status === "sem_leitura" || d.status === "revisao") && d.stored && d.source_format !== "csv" && d.source_format !== "ofx" && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => {
                    if (window.confirm("O texto deste documento será enviado ao provedor de IA configurado para a Mila. O resultado fica pendente para sua revisão. Continuar?"))
                      void interpretDocument(d.id).then(refresh).catch(fail);
                  }}>Ler com IA</button>
                )}
                <button type="button" className="icon-btn" aria-label={`Excluir ${d.original_name}`} onClick={() => {
                  const undo = window.confirm("Excluir o documento. Também desfazer os lançamentos que vieram dele?\n\nOK = excluir e desfazer · Cancelar = só excluir o arquivo");
                  void deleteDocument(d.id, undo).then(refresh).catch(fail);
                }}><Icon name="trash" /></button>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="inbox-entries" aria-labelledby="entries-title">
        <div className="row between">
          <h2 id="entries-title" className="eyebrow">Movimentações</h2>
          <Segmented label="Filtrar movimentações" value={filter} onChange={setFilter}
            options={[{ value: "pendente", label: "Pendências" }, { value: "duplicada", label: "Duplicadas" },
              { value: "registrado", label: "Registradas" }, { value: "todas", label: "Todas" }]} />
        </div>
        {ledger.loading && !ledger.data && <Loading />}
        <ErrorNotice error={ledger.error} onRetry={ledger.reload} />
        {ledger.data && !ledger.data.length && <p className="small muted">Nada aqui.</p>}
        <ul className="inbox-entry-list">
          {(ledger.data ?? []).map((e) => (
            <EntryRow key={e.id} e={e} doc={docs[e.source_ref]} categories={categories.data ?? []} onAct={act} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function EntryRow({ e, doc, categories, onAct }: {
  e: LedgerEntry; doc?: InboxDocument; categories: { key: string; label: string }[];
  onAct: (id: string, action: EntryAction, changes?: object) => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const origin = e.source_kind === "documento" || e.source_kind === "ia"
    ? `${doc?.original_name ?? "documento"}${e.source_detail ? ` · ${e.source_detail}` : ""}${e.source_kind === "ia" ? " · lido por IA" : ""}`
    : e.source_kind === "conversa" ? `você disse na conversa: “${e.source_detail}”` : "registro manual";
  const negative = (e.amount ?? "").startsWith("-");
  return (
    <li className="inbox-entry" data-status={e.status}>
      <span className="inbox-entry-main">
        <span className="inbox-entry-title">
          <strong>{e.counterparty || e.description || KIND_LABEL[e.kind]}</strong>
          <Badge tone={STATUS_TONE[e.status]}>{e.status}</Badge>
          {e.reconciliation === "possivel_duplicata" && <Badge tone="warning">possível duplicata</Badge>}
          {!e.settled && <Badge tone="neutral">lançamento futuro</Badge>}
          {e.installment && <span className="tag plain">parcela {e.installment}</span>}
        </span>
        <span className="tiny muted">{KIND_LABEL[e.kind]} · {e.occurred_on ? formatDate(e.occurred_on) : "sem data"} · confiança {e.confidence}</span>
        <span className="tiny muted inbox-origin">Origem: {origin}</span>
        {e.note && <span className="tiny muted">{e.note}</span>}
      </span>
      <span className={`inbox-entry-amount mono${negative ? " neg" : ""}`}>{e.amount ? money(e.amount) : "valor?"}</span>
      <span className="inbox-entry-actions">
        <label className="visually-hidden" htmlFor={`cat-${e.id}`}>Categoria</label>
        <select id={`cat-${e.id}`} className="select select-sm" value={e.category}
          onChange={(ev) => void onAct(e.id, "corrigir", { category: ev.target.value })}>
          {categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        {e.status === "pendente" && e.missing.includes("valor") && (
          <>
            <label className="visually-hidden" htmlFor={`amt-${e.id}`}>Valor</label>
            <input id={`amt-${e.id}`} className="input input-sm" inputMode="decimal" placeholder="valor (ex.: 120,50)"
              value={amount} onChange={(ev) => setAmount(ev.target.value)} />
          </>
        )}
        {(e.status === "pendente" || e.status === "duplicada") && (
          <button type="button" className="btn btn-primary btn-sm"
            onClick={() => void onAct(e.id, "confirmar", amount ? { amount } : {})}>Confirmar</button>
        )}
        {e.reconciliation === "possivel_duplicata" && e.status === "pendente" && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onAct(e.id, "e_duplicada")}>É duplicata</button>
        )}
        {(e.status === "duplicada" || e.reconciliation === "possivel_duplicata") && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onAct(e.id, "nao_e_duplicada")}>Não é duplicata</button>
        )}
        {(e.status === "pendente" || e.status === "duplicada") && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onAct(e.id, "descartar")}>Descartar</button>
        )}
        {e.status === "registrado" && <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onAct(e.id, "desfazer")}>Desfazer</button>}
        {e.status === "desfeito" && <button type="button" className="btn btn-ghost btn-sm" onClick={() => void onAct(e.id, "restaurar")}>Restaurar</button>}
      </span>
    </li>
  );
}
