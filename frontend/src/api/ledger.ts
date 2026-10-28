// SPDX-License-Identifier: AGPL-3.0-or-later
/** Livro de movimentações, registros reconhecidos na conversa e Caixa de entrada (docs/LEDGER.md).
 * Valores são strings decimais com o sinal do fluxo de dinheiro (negativo = saiu). */
import { formatBRL } from "../lib/money";
import { api, uploadBinary } from "./client";
import type { ISODate, ISODateTime, UUID } from "./types";

const enc = encodeURIComponent;

export type EntryKind = "despesa" | "receita" | "transferencia" | "pagamento_fatura" | "estorno" | "reembolso";
export type EntryStatus = "registrado" | "pendente" | "duplicada" | "desfeito" | "descartado";
export type EntryAction = "confirmar" | "descartar" | "desfazer" | "restaurar" | "corrigir" | "e_duplicada" | "nao_e_duplicada";

export interface LedgerEntry {
  id: UUID;
  kind: EntryKind;
  status: EntryStatus;
  occurred_on: ISODate | null;
  accrual_on: ISODate | null;
  amount: string | null;
  currency: string;
  description: string;
  counterparty: string;
  category: string;
  category_label: string;
  institution: string;
  account: string;
  external_id: string;
  installment: string;
  settled: boolean;
  reconciliation: "nao_conciliado" | "conciliado" | "possivel_duplicata";
  matched_id: UUID | null;
  confidence: "alta" | "media" | "baixa";
  source_kind: "conversa" | "documento" | "manual" | "ia";
  source_ref: string;
  source_detail: string;
  missing: string[];
  note: string;
  created_at: ISODateTime;
}

export interface LedgerSummary {
  period: { start: ISODate; end: ISODate };
  income: string;
  expenses: string;
  refunds: string;
  neutral_moves: string;
  by_category: { category: string; label: string; amount: string }[];
  counts: { registrado: number; pendente: number; duplicada: number; futuro: number };
  pending_total: number;
  basis: string;
}

export interface Capture {
  id: UUID;
  classification: string;
  label: string;
  status: "registrado" | "pendente" | "informativo" | "desfeito" | "descartado";
  missing: string[];
  target_kind: "ledger" | "fato" | "diario" | null;
  target_id: string | null;
  amount?: string | null;
  occurred_on?: ISODate | null;
  date_assumed?: boolean;
}

export interface DocSummary {
  identified?: number;
  registered?: number;
  review?: number;
  duplicates?: number;
  already?: number;
  balances?: number;
  reason?: string;
  ai_items?: number;
  ai_rejected?: number;
}

export interface InboxDocument {
  id: UUID;
  original_name: string;
  media_type: string;
  size: number;
  status: "processado" | "revisao" | "sem_leitura" | "interpretando" | "erro" | "excluido";
  doc_type: "extrato" | "fatura_cartao" | "comprovante" | "recibo" | "desconhecido";
  source_format: "csv" | "ofx" | "pdf" | "png" | "jpg";
  institution: string;
  account: string;
  summary: DocSummary;
  warnings: string[];
  conversation_id: UUID | null;
  created_at: ISODateTime;
  stored: boolean;
  repeated?: boolean;
}

export interface InboxOverview {
  documents: InboxDocument[];
  ocr: boolean;
  pdf: boolean;
  limits: { max_bytes: number; formats: string[] };
  retention_days: number;
}

export type ConsentScope = "auto_register" | "ai_documents";
export type Consents = Record<ConsentScope, { granted: boolean; updated_at: ISODateTime | null }>;

export interface EntryChanges {
  kind?: EntryKind;
  category?: string;
  amount?: string;
  occurred_on?: ISODate;
  description?: string;
}

export const getConsents = () => api.get<Consents>("/api/consents");
export const setConsent = (scope: ConsentScope, granted: boolean) => api.put<Consents>(`/api/consents/${scope}`, { granted });

export const getLedger = (params: { status?: EntryStatus; document_id?: string } = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
  return api.get<LedgerEntry[]>(`/api/ledger${q ? `?${q}` : ""}`);
};
export const getLedgerSummary = (month = "") => api.get<LedgerSummary>(`/api/ledger/summary${month ? `?month=${enc(month)}` : ""}`);
export const getCategories = () => api.get<{ key: string; label: string }[]>("/api/ledger/categories");
export const entryAction = (id: string, action: EntryAction, changes: EntryChanges = {}) =>
  api.post<LedgerEntry>(`/api/ledger/${enc(id)}/${action}`, { changes });

export const captureAction = (id: string, action: "desfazer" | "confirmar" | "descartar", changes: EntryChanges = {}) =>
  api.post<Capture>(`/api/captures/${enc(id)}/${action}`, { changes });

export const getInbox = () => api.get<InboxOverview>("/api/documents");
export const getDocument = (id: string) => api.get<InboxDocument & { entries: LedgerEntry[]; summary_text: string }>(`/api/documents/${enc(id)}`);
export const uploadDocument = (file: File, conversationId?: string) =>
  uploadBinary<InboxDocument>(`/api/documents${conversationId ? `?conversation_id=${enc(conversationId)}` : ""}`, file, file.name);
export const approveDocument = (id: string) => api.post<{ approved: number; document: InboxDocument }>(`/api/documents/${enc(id)}/approve`);
export const deleteDocument = (id: string, undoEntries: boolean) =>
  api.del<{ id: string; undone: number }>(`/api/documents/${enc(id)}?entries=${undoEntries ? "true" : "false"}`);
export const interpretDocument = (id: string) => api.post<InboxDocument>(`/api/documents/${enc(id)}/interpret`, { confirm: true });

export const ACCEPT = ".pdf,.png,.jpg,.jpeg,.csv,.ofx,application/pdf,image/png,image/jpeg,text/csv";

export const money = formatBRL;

export const KIND_LABEL: Record<EntryKind, string> = {
  despesa: "Despesa", receita: "Receita", transferencia: "Transferência", pagamento_fatura: "Pagamento de fatura",
  estorno: "Estorno", reembolso: "Reembolso",
};
export const DOC_LABEL: Record<InboxDocument["doc_type"], string> = {
  extrato: "Extrato", fatura_cartao: "Fatura do cartão", comprovante: "Comprovante", recibo: "Recibo", desconhecido: "Documento",
};
