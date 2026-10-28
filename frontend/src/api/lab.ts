// SPDX-License-Identifier: AGPL-3.0-or-later
/** Laboratório do Conselho: Bento sozinho × Conselho completo sobre o mesmo dossiê (backend/lab/, docs/LAB.md). */
import { api } from "./client";

const enc = encodeURIComponent;

export type LabMode = "individual" | "conselho";
export type LabStatus = "proposto" | "executando" | "concluido" | "incompleto" | "cancelado" | "recusado";
export type PairOutcome = "conselho" | "individual" | "empate" | "sem_avaliacao" | "nao_comparavel";
export type Criterion = "alternativas" | "restricoes" | "consequencias" | "clareza";

export interface LabRecord {
  cenario: string | null;
  horizonte_dias: number | null;
  hipotese: string | null;
  resultado_esperado: string | null;
  metricas_observaveis: string[];
  riscos_identificados: string[];
  premissas: string[];
  fontes: string[];
  nivel_confianca: "baixa" | "media" | "alta" | null;
  condicoes_invalidacao: string[];
  conclusao: string | null;
  dados_insuficientes: boolean;
  sem_hipotese_motivo: string | null;
  hipoteses: { afirmacao: string; probabilidade: string | null; data: string; check: unknown }[];
}

export interface Debate {
  falas: number;
  mudancas_de_posicao: string[];
  contestacoes: number;
  revisoes_declaradas: number;
  divergencias_finais: string[];
  devolucoes_da_auditoria: number;
  correcoes_apos_auditor: number;
  falas_repetitivas: number;
  limites_atingidos: string[];
}

export interface LabEvaluation {
  registro: { status: "ok" | "ausente" | "invalido"; problemas: string[] };
  factual: { veredito: string | null; numeros_conferidos: number; ressalvas: string[] };
  riscos: { categorias: string[]; itens: number };
  consistencia: { problemas: string[] };
  debate: Debate | null;
  fontes: { label?: string; url?: string; kind?: string }[];
}

export interface LabAnalysis {
  id: string;
  mode: LabMode;
  repetition: number;
  conversation_id: string;
  status: "na_fila" | "executando" | "concluida" | "falhou" | "cancelada";
  record_status: "ok" | "ausente" | "invalido" | null;
  text: string | null;
  record: LabRecord | null;
  evaluation: LabEvaluation | null;
  usage: { chamadas?: number; tokens?: number; segundos?: number } | null;
  created_at: string;
  finished_at: string | null;
}

export interface LabHypothesis {
  id: string;
  analysis_id: string;
  mode: LabMode;
  repetition: number;
  statement: string;
  probability: string | null;
  due_on: string;
  check: { kind: string; series_id?: string; symbol?: string; op: string; value: string } | null;
  status: "aberta" | "aconteceu" | "nao_aconteceu" | "indeterminada";
  observed: { value: string; reference_date: string; unit: string; label: string; source: string } | null;
  resolved_by: "dados" | "pessoa" | null;
  note: string | null;
  brier: string | null;
}

export interface BrierSummary { n: number; brier: string | null; ic95: [string, string] | null; amostra_pequena: boolean; referencia_50pct: string }

export interface LabPair {
  repeticao: number;
  calibracao: PairOutcome;
  brier: Record<LabMode, BrierSummary>;
  utilidade_ia?: LabMode | "empate";
  utilidade_pessoa?: LabMode | "empate";
}

export interface UtilityScore {
  criterios: Partial<Record<Criterion, { nota: number; trecho?: string }>>;
  descartados: Criterion[];
  total: number;
  max: number;
}

export interface LabReview {
  id: string;
  repetition: number;
  reviewer: "ia" | "pessoa";
  created_at: string;
  blind: Record<"A" | "B", LabMode> | null;
  scores: { por_modo: Record<LabMode, UtilityScore>; observacao?: string; sem_resposta_valida?: boolean };
}

export interface LabJournalEntry {
  id: string;
  seq: number;
  experiment_id: string;
  kind: "analise_ia" | "resultado_observado" | "decisao_vinculada";
  created_at: string;
  sha256: string;
  payload: Record<string, unknown> & { aviso?: string };
}

export interface LabSnapshot {
  dossie_sha256: string;
  prompts_sha256: string;
  data_de_corte: string;
  simulado: boolean;
  avisos: string[];
  fontes: { serie: string; fonte: string; data_referencia: string; coletado_em: string }[];
  comparabilidade: { comparavel: boolean; motivos: string[] };
  modelos: Record<string, Record<string, string>>;
  agentes: { individual: string[]; conselho: string[] };
  ferramentas: { todos_os_agentes: string[]; leitura_ao_vivo: string };
  motor_financeiro: string;
  versao_lastro: string;
  amostragem: string;
  parametros: { repeticoes: number; pesquisa_web: boolean; reavaliacoes_dias: number[] };
}

export interface LabExperimentSummary {
  id: string;
  origin: "pessoa" | "radar";
  category: string;
  question: string;
  status: LabStatus;
  as_of: string;
  repetitions: number;
  created_at: string;
  finished_at: string | null;
  simulated: boolean;
  comparable: boolean;
  hypotheses: Partial<Record<LabHypothesis["status"], number>>;
  pairs: LabPair[];
}

export interface LabExperiment extends LabExperimentSummary {
  origin_ref: string | null;
  started_at: string | null;
  research: boolean;
  followups: number[];
  snapshot: LabSnapshot;
  snapshot_sha256: string;
  analyses: LabAnalysis[];
  checkpoints: { id: string; days: number; due_on: string; status: "agendada" | "pendente" | "feita"; done_at: string | null }[];
  reviews: LabReview[];
  journal: LabJournalEntry[];
}

/** O backend devolve `hypotheses` como lista no detalhe e como contagem na listagem. */
export type LabExperimentDetail = Omit<LabExperiment, "hypotheses"> & { hypotheses: LabHypothesis[] };

export interface Proportion { k: number; n: number; pct: number | null; ic95: [number, number] | null; amostra_pequena: boolean }
export interface Verdict { conselho: number; individual: number; empates: number; decisivos: number; p_valor: number | null; vencedor: LabMode | null; texto: string }

export interface ModeMetrics {
  analises: number;
  factual_sem_ressalva: Proportion;
  registro_valido: Proportion;
  calibracao: BrierSummary;
  categorias_de_risco_media: number | null;
  problemas_de_consistencia: number;
  erros_apontados_pelo_auditor: number;
  tokens_medio: number | null;
  tokens_amostra: number;
  segundos_medio: number | null;
  hipoteses: number;
}

export interface LabDashboard {
  experimentos: number;
  concluidos: number;
  incompletos: number;
  em_execucao: number;
  propostos: number;
  nao_comparaveis: number;
  avaliaveis: number;
  pendentes: number;
  por_modo: Record<LabMode, ModeMetrics>;
  calibracao: Verdict;
  utilidade: Record<"ia" | "pessoa", Verdict>;
  por_categoria: Record<string, { conselho: number; individual: number; empate: number; sem_avaliacao: number }>;
  debate: { reunioes: number; com_mudanca_de_posicao: number; com_correcao_apos_auditor: number; com_divergencia_preservada: number; falas_repetitivas: number };
  evolucao: { data: string; modo: LabMode; individual: string | null; conselho: string | null; n_individual: number; n_conselho: number }[];
}

export interface LabSettings { automation: "desligada" | "propor" | "executar"; max_per_week: number; monthly_token_budget: number; repetitions: number }

export interface LabOverview {
  experiments: LabExperimentSummary[];
  dashboard: LabDashboard;
  categories: Record<string, string>;
  settings: LabSettings;
}

export interface NewExperiment {
  question: string;
  category: string;
  repetitions: number;
  research: boolean;
  as_of?: string | null;
  followups: number[];
  client_id: string;
}

export const getLab = (filters: { category?: string; since?: string } = {}) => {
  const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]).toString();
  return api.get<LabOverview>(`/api/lab${q ? `?${q}` : ""}`);
};
export const getExperiment = (id: string) => api.get<LabExperimentDetail>(`/api/lab/${enc(id)}`);
export const createExperiment = (body: NewExperiment) => api.post<LabExperimentDetail>("/api/lab", body);
export const startExperiment = (id: string) => api.post<LabExperimentDetail>(`/api/lab/${enc(id)}/start`);
export const refuseExperiment = (id: string) => api.post<LabExperimentDetail>(`/api/lab/${enc(id)}/refuse`);
export const cancelExperiment = (id: string) => api.post<LabExperimentDetail>(`/api/lab/${enc(id)}/cancel`);
export const judgeExperiment = (id: string, repetition: number) =>
  api.post<LabExperimentDetail>(`/api/lab/${enc(id)}/judge`, { repetition });
export const reviewExperiment = (id: string, repetition: number, scores: Record<LabMode, Partial<Record<Criterion, number>>>, note = "") =>
  api.post<LabExperimentDetail>(`/api/lab/${enc(id)}/review`, { repetition, scores, note });
export const resolveHypothesis = (id: string, outcome: "aconteceu" | "nao_aconteceu" | "indeterminada", note = "") =>
  api.post<LabHypothesis>(`/api/lab/hypotheses/${enc(id)}/resolve`, { outcome, note });
export const linkDecision = (id: string, decision_id: string) =>
  api.post<LabExperimentDetail>(`/api/lab/${enc(id)}/decision`, { decision_id });
export const putLabSettings = (body: Partial<LabSettings>) => api.put<LabSettings>("/api/lab/settings", body);
export const getLabJournal = () => api.get<LabJournalEntry[]>("/api/lab/journal");

export const CRITERIA: Record<Criterion, string> = {
  alternativas: "Alternativas", restricoes: "Restrições", consequencias: "Consequências", clareza: "Clareza",
};
export const RISK_LABELS: Record<string, string> = {
  juros: "Juros", inflacao: "Inflação", liquidez: "Liquidez", credito: "Crédito", mercado: "Preço/volatilidade",
  cambio: "Câmbio", concentracao: "Concentração", tributacao: "Tributação", prazo: "Prazo", divida: "Dívida",
  comportamental: "Comportamento", dados: "Qualidade dos dados",
};
