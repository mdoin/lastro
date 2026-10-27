/**
 * Tipos do contrato `docs/WEB_API.md` (v1). Fonte única de verdade: o documento.
 * `Dec` = string decimal com ponto ("1234.56"). Nunca number.
 */

export type Dec = string;
export type ISODate = string; // AAAA-MM-DD
export type ISODateTime = string; // ISO 8601 com fuso
export type UUID = string;

// --- Autenticação -----------------------------------------------------------
export interface AuthState {
  authenticated: boolean;
  setup_required: boolean;
}

// --- Snapshots ----------------------------------------------------------------
export interface Debt {
  name: string;
  balance: Dec;
  monthly_rate: Dec;
  monthly_payment: Dec;
}

export interface Snapshot {
  id: UUID;
  as_of: ISODate;
  net_monthly_income: Dec;
  essential_expenses: Dec;
  variable_expenses: Dec;
  liquid_reserve: Dec;
  available_this_month: Dec;
  debts: Debt[];
  created_at: ISODateTime;
}

export type SnapshotInput = Omit<Snapshot, "id" | "created_at">;

export interface SnapshotHistoryItem {
  id: UUID;
  as_of: ISODate;
  net_monthly_income: Dec;
  liquid_reserve: Dec;
  total_debt: Dec;
  free_cash_flow: Dec;
}

// --- Diagnóstico --------------------------------------------------------------
export type GuidanceStage =
  | "sem_recurso_disponivel"
  | "organizar_orcamento"
  | "priorizar_divida"
  | "construir_reserva"
  | "investir_para_metas";

export interface Allocation {
  purpose: string;
  amount: Dec;
  percent: Dec;
  rationale: string;
}

export interface Guidance {
  stage: GuidanceStage;
  next_step: string;
  situation: string[];
  allocation: Allocation[];
  comparisons: string[];
  premises: string[];
  missing_information: string[];
  checklist: string[];
  follow_up: string;
  disclaimer: string;
  notes: string[];
}

export interface Diagnosis {
  as_of: ISODate;
  free_cash_flow: Dec;
  debt_commitment_ratio: Dec | null;
  total_debt: Dec;
  reserve: {
    target_months: number;
    target_amount: Dec;
    current: Dec;
    gap: Dec;
    coverage_months: Dec | null;
    complete: boolean;
  };
  guidance: Guidance;
}

// --- Premissas e projeção -----------------------------------------------------
export interface Scenario {
  name: string;
  annual_return: Dec;
  annual_inflation: Dec;
  annual_fee: Dec;
  note: string;
}

export interface AssumptionsResponse {
  scenarios: Scenario[];
  is_default: boolean;
  note: string;
}

export interface ProjectionRequest {
  initial: Dec;
  contribution: Dec;
  months: number;
  contribution_annual_increase?: Dec;
  paused_months?: number[];
  include_path?: boolean;
}

/** Espelha `Plan.as_dict()` do motor (o contrato só diz `{...}`). */
export interface ProjectionPlan {
  initial?: Dec;
  monthly_contribution?: Dec;
  months?: number;
  contribution_annual_increase?: Dec;
  paused_months?: number[];
  withdrawals?: [number, Dec][];
  [key: string]: unknown;
}

export interface Projection {
  scenario: string;
  engine_version: string;
  inputs_fingerprint: string;
  final_nominal: Dec;
  final_real_todays_money: Dec;
  total_contributed: Dec;
  total_withdrawn: Dec;
  market_result: Dec;
  plan: ProjectionPlan;
  assumptions: Scenario;
  limitations: string[];
  /** [mês, nominal, real] — valores como string decimal (como `Projection.as_dict`). */
  path?: [number, Dec, Dec][];
}

export interface ProjectionResponse {
  projections: Projection[];
}

// --- Metas ----------------------------------------------------------------------
export type Liquidity = "diaria" | "curto_prazo" | "longo_prazo";
export type GoalStatus = "no_rumo" | "atencao" | "revisar";

export interface Goal {
  id: UUID;
  name: string;
  target_real_value: Dec;
  base_date: ISODate;
  deadline: ISODate;
  priority: number;
  liquidity: Liquidity;
  current_amount: Dec;
  required_monthly: Record<string, Dec>;
  months_left: number;
  status: GoalStatus;
}

export interface GoalInput {
  name: string;
  target_real_value: Dec;
  deadline: ISODate;
  priority: number;
  liquidity: Liquidity;
  current_amount: Dec;
}

// --- Mentor -----------------------------------------------------------------------
export type ConversationKind = "chat" | "routine" | "panel";

export interface Conversation {
  id: UUID;
  title: string;
  kind: ConversationKind;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ToolUse {
  name: string;
  input: Record<string, unknown>;
}

export type MessageStatus = "ok" | "error" | "interrupted";

export interface Message {
  id: UUID;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  tools: ToolUse[];
  created_at: ISODateTime;
}

export type StreamErrorKind = "auth" | "rate_limit" | "network" | "timeout" | "internal";

export type ChatEvent =
  | { event: "queued"; data: { position: number } }
  | { event: "waiting_limit"; data: { retry_at: ISODateTime | null; message: string } }
  | { event: "tool"; data: ToolUse }
  | { event: "delta"; data: { text: string } }
  | { event: "done"; data: { message: Message } }
  | { event: "error"; data: { kind: StreamErrorKind; message: string } };

export type PanelRole = "diagnostico" | "simulacao" | "riscos" | "educacao" | "pesquisa";
export type AuditVerdict = "PASSA" | "REVISAR" | "BLOQUEAR";

/**
 * Quadro do "navegador de pesquisa" (futuro). Nome dos campos ainda não está no contrato:
 * aceitamos `image`, `jpeg_base64` ou `data` para o JPEG em base64.
 */
export interface BrowserFrame {
  role?: string;
  url: string;
  image?: string;
  jpeg_base64?: string;
  data?: string;
}

export type PanelEvent =
  | { event: "plan"; data: { agents: { role: PanelRole; label: string }[] } }
  | { event: "agent_start"; data: { role: PanelRole } }
  | { event: "agent_tool"; data: { role: PanelRole; name: string; input: Record<string, unknown> } }
  | { event: "agent_delta"; data: { role: PanelRole; text: string } }
  | { event: "agent_done"; data: { role: PanelRole; text: string; status: string } }
  | { event: "synthesis_delta"; data: { text: string } }
  | { event: "audit"; data: { verdict: AuditVerdict; reasons: string[] } }
  | { event: "done"; data: { message: Message; conversation_id: UUID } }
  | { event: "error"; data: { kind: StreamErrorKind; message: string } }
  | { event: "queued"; data: { position: number } }
  | { event: "waiting_limit"; data: { retry_at: ISODateTime | null; message: string } }
  | { event: "browser_frame"; data: BrowserFrame };

// --- Rotinas -------------------------------------------------------------------
export type ScheduleKind = "daily" | "weekly" | "monthly" | "once";

export interface Schedule {
  kind: ScheduleKind;
  time: string; // HH:MM
  weekday?: number; // 0 = segunda
  day?: number; // 1-28
  date?: ISODate;
}

export type RunStatus = "queued" | "running" | "succeeded" | "quiet" | "failed" | "skipped" | "missed";

export interface RoutineRun {
  id: UUID;
  routine_id: UUID;
  scheduled_for: ISODateTime | null;
  started_at: ISODateTime | null;
  finished_at: ISODateTime | null;
  status: RunStatus;
  summary: string | null;
  conversation_id: UUID | null;
  read: boolean;
}

export type MissedPolicy = "skip" | "run_once";

export interface Routine {
  id: UUID;
  name: string;
  instruction: string;
  schedule: Schedule;
  timezone: string;
  active: boolean;
  missed_policy: MissedPolicy;
  use_panel: boolean;
  next_run_at: ISODateTime | null;
  last_run: RoutineRun | null;
}

export type RoutineInput = Pick<
  Routine,
  "name" | "instruction" | "schedule" | "timezone" | "active" | "missed_policy" | "use_panel"
>;

// --- Diário de decisões ---------------------------------------------------------
export interface Decision {
  id: UUID;
  date: ISODate;
  question: string;
  alternatives: string[];
  information: string;
  risk_accepted: string;
  user_choice: string;
  planned_amount: Dec | null;
  confirmed: boolean;
  review_of_id: UUID | null;
}

export type DecisionInput = Omit<Decision, "id">;

// --- Estado ---------------------------------------------------------------------
export interface AppStatus {
  app_version: string;
  engine_version: string;
  mentor: {
    available: boolean;
    logged_in: boolean | null;
    subscription: string | null;
    busy: number;
    queued: number;
    limit_until: ISODateTime | null;
  };
  data: {
    latest_snapshot_as_of: ISODate | null;
    stale: boolean;
  };
}

// ---------- Equipe: Mentor, especialistas, grupos e Conselho ----------

export type AgentId = "mentor" | "planejador" | "analista" | "economista" | "riscos" | "comportamental";
export type Channel = "direct" | "group" | "council" | "routine";
export type TeamVerdict = "PASSA" | "PASSA COM RESSALVAS" | "REPROVA";

export interface Agent {
  id: AgentId;
  name: string;
  handle: string;
  title: string;
  kind: "coordinator" | "specialist";
  icon: string;
  color: string;
  summary: string;
  examples: string[];
  tools: string[];
  version: string;
}

export interface TeamConversation {
  id: UUID;
  kind: string;
  channel: Channel;
  agent_id: AgentId | null;
  title: string;
  participants: AgentId[];
  created_at: ISODateTime;
  updated_at: ISODateTime;
  last_message?: string;
  last_agent_id?: string | null;
}

export interface Source {
  kind: "dados" | "memoria" | "motor" | "pagina" | "mercado" | "especialista";
  label: string;
  url?: string;
  source?: string;
  reference_date?: string;
  fetched_at?: string;
  validity?: "valido" | "desatualizado" | "indisponivel";
}

export interface TeamAudit {
  verdict: TeamVerdict | AuditVerdict;
  reasons: string[];
  checked_numbers?: number;
}

export interface TeamMessage {
  id: UUID;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  tools: ToolUse[];
  audit: TeamAudit | null;
  created_at: ISODateTime;
  agent_id: string | null;
  run_id: UUID | null;
  step_key: string | null;
  client_id: string | null;
  reply_to_id: UUID | null;
  mentions: string[];
  sources: Source[];
  kind: "message" | "analysis" | "notice";
}

export type RunState = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";
export type StepState = "running" | "succeeded" | "failed" | "cancelled" | "rejected" | "retrying";

export interface RunStep {
  step_key: string;
  agent_id: string;
  kind: string;
  parent_key: string | null;
  depth: number;
  status: StepState;
  output?: string;
  error: string | null;
  attempts?: number;
}

export interface TeamRun {
  id: UUID;
  conversation_id: UUID;
  message_id: UUID;
  kind: "reply" | "council";
  status: RunState;
  route: { agents?: string[]; via_router?: boolean; reason?: string };
  error: string | null;
  created_at: ISODateTime;
  steps?: RunStep[];
}

export interface SubmitResult {
  message: TeamMessage;
  run: TeamRun | null;
  notices: TeamMessage[];
}

export interface Fact {
  id: UUID;
  key: string;
  value: string;
  status: "confirmed" | "proposed" | "rejected" | "superseded";
  source: string;
  note: string;
  as_of: string;
  created_at: ISODateTime;
}

export interface AgentNote {
  id: UUID;
  agent_id: string;
  scope: "private" | "conversation";
  conversation_id: UUID | null;
  content: string;
  created_at: ISODateTime;
}

export interface MarketSeries {
  series_id: string;
  label: string;
  source: string;
  unit: string;
  value: string | null;
  reference_date: string | null;
  fetched_at: string | null;
  validity: "valido" | "desatualizado" | "indisponivel";
  url: string;
}

export interface TeamMemory {
  facts: Fact[];
  notes: AgentNote[];
  market: MarketSeries[];
  not_connected: string[];
}

/** Eventos ao vivo do GET /api/team/conversations/{id}/stream. */
export type TeamEvent =
  | { type: "snapshot"; runs: TeamRun[]; partials: Record<string, Record<string, { agent_id: string; text: string }>> }
  | { type: "message"; message: TeamMessage }
  | { type: "run"; run: TeamRun }
  | { type: "step"; run_id: UUID; step_key: string; agent_id: string; status: StepState; kind?: string; parent_key?: string | null; error?: string }
  | { type: "delta"; run_id: UUID; step_key: string; agent_id: string; text: string }
  | { type: "tool"; run_id: UUID; step_key: string; agent_id: string; name: string }
  | { type: "wait"; run_id: UUID; step_key: string; agent_id: string; kind: "queued" | "waiting_limit"; message?: string }
  | { type: "fact_proposed"; run_id: UUID; agent_id: string; key: string }
  | { type: "ping" };
