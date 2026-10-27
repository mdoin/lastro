/** Radar e Diário de Oportunidades: tipos e chamadas (docs/WEB_API.md §Radar). Valores numéricos são strings decimais. */
import { api } from "./client";
import type { TeamConversation, UUID } from "./types";

const enc = encodeURIComponent;

export type Category = "renda_fixa" | "acoes" | "etf" | "fii" | "macro" | "patrimonio";
export type RuleKind = "limite" | "variacao" | "queda" | "reserva" | "dado_desatualizado";
export type OppState =
  | "detectada"
  | "em_analise"
  | "avaliada"
  | "alerta_emitido"
  | "em_acompanhamento"
  | "encerrada"
  | "invalidada"
  | "inconclusiva";
export type Verdict =
  | "confirmada"
  | "nao_confirmada"
  | "favoravel_por_outro_motivo"
  | "inconclusivo"
  | "invalidada"
  | "dados_insuficientes"
  | "sem_hipotese";
export type Decision = "analisei" | "ignorei" | "decidi_investir" | "decidi_nao_investir" | "acompanhar" | "outra";

export interface Rule {
  id: string;
  version: number;
  name: string;
  kind: RuleKind;
  category: Category;
  series_pattern: string;
  params: Record<string, string | number>;
  priority: number;
  interval_minutes: number;
  horizons: number[];
  benchmark: string;
  status: "ativa" | "pausada" | "arquivada";
  origin: "sistema" | "pessoa" | "proposta";
  note: string;
  created_at: string;
  state?: { last_evaluated_at: string | null; last_result: string | null } | null;
}

export type RuleInput = Pick<Rule, "name" | "kind" | "category" | "series_pattern" | "params" | "priority" | "interval_minutes" | "horizons" | "status" | "note">;

export interface Point {
  reference_date: string;
  value: string;
  observation_id: number;
  revision: number;
  fetched_at: string;
  quality: "ok" | "revisado" | "suspeito";
}

export interface SeriesItem {
  series_id: string;
  label: string;
  source: string;
  unit: string;
  category: Category;
  frequency: string;
  meta: Record<string, string>;
  last: Point | null;
  validity: "valido" | "desatualizado" | "indisponivel";
}

export interface Overview {
  series_by_source: Record<string, number>;
  source_names: Record<string, string>;
  sources: { source: string; checked_at: string; ok: number; error: string | null; next_at: string | null }[];
  series_status: { source: string; series_id: string; checked_at: string; ok: number; error: string | null }[];
  not_connected: string[];
  rules: number;
  unread_alerts: number;
  last_tick: Record<string, unknown> | null;
  prefs: Prefs;
  channels: Channel[];
  realtime: false;
}

export interface Prefs {
  min_priority: number;
  quiet_start: string;
  quiet_end: string;
  max_per_day: number;
  cooldown_hours: number;
  max_analyses_per_day: number;
}

export interface Channel {
  channel: "email" | "telegram" | "webpush";
  enabled: boolean;
  consent_at: string | null;
  transport_ready: boolean;
}

export interface Alert {
  id: UUID;
  opportunity_id: UUID;
  title: string;
  priority: number;
  status: "novo" | "visto" | "analisado" | "silenciado";
  occurrences: number;
  feedback: "util" | "irrelevante" | null;
  created_at: string;
  category: Category;
  asset_label: string;
  state: OppState;
  condition_text: string;
  reference_date: string;
  /** Especialistas escolhidos para analisar o sinal. */
  agents: string[];
}

export interface OutcomeBrief {
  horizon_days: number;
  status: string;
  verdict: Verdict | null;
}

export interface JournalItem {
  id: UUID;
  rule_id: string;
  category: Category;
  series_id: string | null;
  asset_label: string;
  classification: number;
  score: string | null;
  state: OppState;
  redundant_of: string | null;
  created_at: string;
  alert_id: string | null;
  alert_status: string | null;
  alert_feedback: string | null;
  condition_text: string;
  reference_date: string;
  verdicts: OutcomeBrief[];
  agents: string[];
}

export interface Snapshot {
  id: string;
  seq: number;
  kind: "deteccao" | "analise" | "correcao";
  sha256: string;
  prev_sha256: string | null;
  reason: string;
  created_at: string;
  // Conteúdo livre e versionado (registro do Diário); as telas leem os campos conhecidos.
  payload: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface Outcome {
  id: string;
  horizon_days: number;
  method: string;
  method_version: string;
  due_date: string;
  status: "pendente" | "calculado" | "dados_insuficientes";
  verdict: Verdict | null;
  result: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  attempts: number;
  last_error: string | null;
  computed_at: string | null;
}

export interface OpportunityDetail {
  opportunity: JournalItem & { analysis_run_id: string | null; state_changed_at: string };
  signal: { detected_at: string; reference_date: string; condition_text: string; rule_version: number };
  snapshots: Snapshot[];
  chain: { ok: boolean; registros: number; falhas: number[] };
  timeline: { at: string; kind: string; detail: Record<string, unknown> }[];
  outcomes: Outcome[];
  alert: (Alert & { deliveries: { channel: string; status: string; reason: string; at: string }[] }) | null;
  decisions: { id: string; decision: Decision; note: string; created_at: string }[];
  operations: { id: string; operation_date: string; direction: string; amount: string; unit_price: string | null; note: string }[];
  links: { conversation_id: string; purpose: string; created_at: string; title: string }[];
  evolution: Point[];
}

export interface Rate {
  valor: string | null;
  n: number;
  confiavel: boolean;
}

export interface Block {
  sinais: number;
  alertas: number;
  vereditos: Record<string, number>;
  precisao: Rate;
  favoravel_outro_motivo: Rate;
  invalidados: Rate;
  dados_insuficientes: Rate;
  redundantes: Rate;
  utilidade_informada: Rate;
  excesso_medio_vs_cdi_pp: string | null;
  n_excesso: number;
}

export interface Metrics {
  periodo: { de: string | null; ate: string | null };
  horizonte_dias: number;
  amostra_minima: number;
  totais: { sinais: number; alertas: number; estados: Record<string, number> };
  geral: Block;
  por_categoria: Record<string, Block>;
  por_regra: Record<string, Block & { nome: string }>;
  tendencia_mensal: (Block & { mes: string })[];
  latencia: Record<string, string | number | null>;
  limitacoes: string[];
}

export interface Proposal {
  id: string;
  rule_id: string;
  base_version: number;
  change: Record<string, unknown>;
  rationale: { motivo: string };
  backtest_id: string | null;
  status: string;
  created_at: string;
}

export interface BacktestBlock {
  sinais: number;
  avaliacoes: number;
  avaliaveis: number;
  confirmadas: number;
  taxa_confirmacao: string | null;
  excesso_medio_vs_cdi_pp: string | null;
}

export interface BacktestResult {
  id: string;
  tipo: "simulado";
  periodo: { de: string; ate: string };
  series: string[];
  dentro_da_amostra: BacktestBlock & { ate: string };
  fora_da_amostra: BacktestBlock & { de: string };
  segmentos: (BacktestBlock & { de: string; ate: string })[];
  limitacoes: string[];
}

export interface JournalFilters {
  category?: string;
  state?: string;
  rule_id?: string;
  asset?: string;
  since?: string;
  until?: string;
  min_class?: string;
  verdict?: string;
  agent?: string;
}

export const getOverview = () => api.get<Overview>("/api/radar/overview");
export const runTick = () => api.post<Record<string, unknown>>("/api/radar/tick");
export const getSeries = (category?: string) =>
  api.get<SeriesItem[]>(`/api/radar/series${category ? `?category=${enc(category)}` : ""}`);
export const getSeriesHistory = (id: string, days = 180) =>
  api.get<{ series: SeriesItem; points: Point[] }>(`/api/radar/series/${enc(id)}/history?days=${days}`);
export const addAsset = (ticker: string, kind: "acoes" | "etf" | "fii") => api.post("/api/radar/assets", { ticker, kind });
export const addAssetObservation = (id: string, body: { reference_date: string; value: string; kind: "preco" | "provento" }) =>
  api.post(`/api/radar/assets/${enc(id)}/observations`, body);
export const addCorporateEvent = (id: string, body: { ex_date: string; kind: string; factor: string }) =>
  api.post(`/api/radar/assets/${enc(id)}/events`, body);

export const getAlerts = (status?: string) => api.get<Alert[]>(`/api/radar/alerts${status ? `?status=${enc(status)}` : ""}`);
export const setAlertStatus = (id: UUID, status: "visto" | "analisado") =>
  api.post<Alert>(`/api/radar/alerts/${enc(id)}/status`, { status });
export const setAlertFeedback = (id: UUID, feedback: "util" | "irrelevante") =>
  api.post<Alert>(`/api/radar/alerts/${enc(id)}/feedback`, { feedback });
export const muteAlert = (id: UUID, days: number) => api.post(`/api/radar/alerts/${enc(id)}/mute`, { days });

export const getRules = () => api.get<Rule[]>("/api/radar/rules");
export const createRule = (r: RuleInput) => api.post<Rule>("/api/radar/rules", r);
export const updateRule = (id: string, r: RuleInput) => api.put<Rule>(`/api/radar/rules/${enc(id)}`, r);
export const setRuleStatus = (id: string, status: Rule["status"]) =>
  api.post<Rule>(`/api/radar/rules/${enc(id)}/status`, { status });
export const getRuleVersions = (id: string) =>
  api.get<{ versions: Rule[]; backtests: { id: string; created_at: string; result: BacktestResult }[] }>(
    `/api/radar/rules/${enc(id)}/versions`,
  );
export const backtestRule = (id: string) => api.post<BacktestResult>(`/api/radar/rules/${enc(id)}/backtest`, {});
export const getProposals = () => api.get<Proposal[]>("/api/radar/proposals");
export const decideProposal = (id: string, decision: "approve" | "reject") =>
  api.post(`/api/radar/proposals/${enc(id)}/${decision}`);

export const getPrefs = () => api.get<{ prefs: Prefs; channels: Channel[] }>("/api/radar/prefs");
export const savePrefs = (p: Partial<Prefs>) => api.put<Prefs>("/api/radar/prefs", p);
export const setChannel = (channel: string, enabled: boolean, consent: boolean) =>
  api.put<Channel[]>(`/api/radar/channels/${enc(channel)}`, { enabled, consent });

export const getJournal = (f: JournalFilters = {}) => {
  const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][]).toString();
  return api.get<JournalItem[]>(`/api/radar/journal${q ? `?${q}` : ""}`);
};
export const getOpportunity = (id: UUID) => api.get<OpportunityDetail>(`/api/radar/journal/${enc(id)}`);
export const addDecision = (id: UUID, decision: Decision, note: string) =>
  api.post(`/api/radar/journal/${enc(id)}/decisions`, { decision, note });
export const addOperation = (
  id: UUID,
  body: { operation_date: string; direction: "entrada" | "saida"; amount: string; unit_price?: string; note?: string },
) => api.post(`/api/radar/journal/${enc(id)}/operations`, body);
export const discuss = (id: UUID, target: "mentor" | "conselho") =>
  api.post<TeamConversation>(`/api/radar/journal/${enc(id)}/discuss`, { target });
export const getRadarLink = (conversationId: UUID) =>
  api.get<{ opportunity_id: string | null; asset_label: string | null }>(`/api/radar/links/${enc(conversationId)}`);
export const getMetrics = (days = 365, horizon = 90) =>
  api.get<Metrics>(`/api/radar/metrics?days=${days}&horizon=${horizon}`);

// Rótulos
export const PRIORITY: Record<number, { label: string; tone: "neutral" | "warning" | "gold" | "serious" | "critical" }> = {
  1: { label: "Informativo", tone: "neutral" },
  2: { label: "Em observação", tone: "neutral" },
  3: { label: "Potencialmente interessante", tone: "gold" },
  4: { label: "Alta prioridade para avaliação", tone: "serious" },
  5: { label: "Alerta de risco", tone: "critical" },
};
export const CATEGORY: Record<Category, string> = {
  renda_fixa: "Renda fixa",
  acoes: "Ações",
  etf: "ETFs",
  fii: "Fundos imobiliários",
  macro: "Macroeconomia",
  patrimonio: "Seu patrimônio",
};
export const STATE: Record<OppState, string> = {
  detectada: "Detectada",
  em_analise: "Em análise",
  avaliada: "Avaliada",
  alerta_emitido: "Alerta emitido",
  em_acompanhamento: "Em acompanhamento",
  encerrada: "Encerrada",
  invalidada: "Invalidada",
  inconclusiva: "Inconclusiva",
};
export const VERDICT: Record<Verdict, { label: string; tone: "good" | "warning" | "critical" | "neutral" | "gold" }> = {
  confirmada: { label: "Hipótese confirmada", tone: "good" },
  nao_confirmada: { label: "Não confirmada", tone: "critical" },
  favoravel_por_outro_motivo: { label: "Favorável por outro motivo", tone: "gold" },
  inconclusivo: { label: "Inconclusivo", tone: "neutral" },
  invalidada: { label: "Invalidada", tone: "warning" },
  dados_insuficientes: { label: "Dados insuficientes", tone: "neutral" },
  sem_hipotese: { label: "Informativo (sem hipótese)", tone: "neutral" },
};
export const DECISION_LABEL: Record<Decision, string> = {
  analisei: "Analisei",
  ignorei: "Ignorei",
  decidi_investir: "Decidi investir",
  decidi_nao_investir: "Decidi não investir",
  acompanhar: "Quero acompanhar",
  outra: "Registrei uma decisão diferente",
};
export const KIND_LABEL: Record<RuleKind, string> = {
  limite: "Limite",
  variacao: "Variação",
  queda: "Queda desde a máxima",
  reserva: "Reserva de emergência",
  dado_desatualizado: "Dado desatualizado",
};
