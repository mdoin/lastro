/** Funções tipadas, uma por rota de `docs/WEB_API.md`. */
import { api, postStream } from "./client";
import type {
  AppStatus,
  AssumptionsResponse,
  AuthState,
  ChatEvent,
  Conversation,
  Decision,
  DecisionInput,
  Diagnosis,
  Goal,
  GoalInput,
  Message,
  PanelEvent,
  ProjectionRequest,
  ProjectionResponse,
  Routine,
  RoutineInput,
  RoutineRun,
  Scenario,
  Snapshot,
  SnapshotHistoryItem,
  SnapshotInput,
  UUID,
} from "./types";

const enc = encodeURIComponent;

// Autenticação
export const getAuthState = () => api.get<AuthState>("/api/auth/state", { noAuthRedirect: true });
export const login = (password: string) =>
  api.post<void>("/api/auth/login", { password }, { noAuthRedirect: true });
export const logout = () => api.post<void>("/api/auth/logout", undefined, { noAuthRedirect: true });

// Snapshots
export const getLatestSnapshot = () => api.get<Snapshot | null>("/api/snapshot/latest");
export const createSnapshot = (s: SnapshotInput) => api.post<Snapshot>("/api/snapshot", s);
export const getSnapshotHistory = () => api.get<SnapshotHistoryItem[]>("/api/snapshot/history");

// Diagnóstico (404 = ainda não há snapshot)
export const getDiagnosis = (params?: { reserve_months?: number; reference_annual_return?: string }) => {
  const q = new URLSearchParams();
  if (params?.reserve_months !== undefined) q.set("reserve_months", String(params.reserve_months));
  if (params?.reference_annual_return !== undefined) q.set("reference_annual_return", params.reference_annual_return);
  const qs = q.toString();
  return api.get<Diagnosis>(`/api/diagnosis${qs ? `?${qs}` : ""}`);
};

// Premissas e projeção
export const getAssumptions = () => api.get<AssumptionsResponse>("/api/assumptions");
export const putAssumptions = (scenarios: Scenario[]) =>
  api.put<AssumptionsResponse>("/api/assumptions", { scenarios });
export const postProjection = (body: ProjectionRequest) => api.post<ProjectionResponse>("/api/projection", body);

// Metas
export const getGoals = () => api.get<Goal[]>("/api/goals");
export const createGoal = (g: GoalInput) => api.post<Goal>("/api/goals", g);
export const updateGoal = (id: UUID, g: GoalInput) => api.put<Goal>(`/api/goals/${enc(id)}`, g);
export const deleteGoal = (id: UUID) => api.del(`/api/goals/${enc(id)}`);

// Mentor
export const getConversations = () => api.get<Conversation[]>("/api/conversations");
export const createConversation = (title?: string) =>
  api.post<Conversation>("/api/conversations", title ? { title } : {});
export const deleteConversation = (id: UUID) => api.del(`/api/conversations/${enc(id)}`);
export const getMessages = (id: UUID) => api.get<Message[]>(`/api/conversations/${enc(id)}/messages`);
export const interruptConversation = (id: UUID) => api.post<void>(`/api/conversations/${enc(id)}/interrupt`);
export const streamMessage = (id: UUID, text: string, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) =>
  postStream<ChatEvent>(`/api/conversations/${enc(id)}/messages`, { text }, onEvent, signal);
export const streamPanel = (
  question: string,
  conversationId: UUID | null,
  onEvent: (e: PanelEvent) => void,
  signal?: AbortSignal,
) =>
  postStream<PanelEvent>(
    "/api/panels",
    conversationId ? { question, conversation_id: conversationId } : { question },
    onEvent,
    signal,
  );

// Rotinas e caixa de entrada
export const getRoutines = () => api.get<Routine[]>("/api/routines");
export const createRoutine = (r: RoutineInput) => api.post<Routine>("/api/routines", r);
export const updateRoutine = (id: UUID, r: RoutineInput) => api.put<Routine>(`/api/routines/${enc(id)}`, r);
export const deleteRoutine = (id: UUID) => api.del(`/api/routines/${enc(id)}`);
export const runRoutine = (id: UUID) => api.post<RoutineRun>(`/api/routines/${enc(id)}/run`);
export const getRoutineRuns = (id: UUID) => api.get<RoutineRun[]>(`/api/routines/${enc(id)}/runs`);
export const getInbox = () => api.get<RoutineRun[]>("/api/inbox");
export const markInboxRead = (runId: UUID) => api.post<void>(`/api/inbox/${enc(runId)}/read`);

// Diário de decisões
export const getDecisions = () => api.get<Decision[]>("/api/decisions");
export const createDecision = (d: DecisionInput) => api.post<Decision>("/api/decisions", d);

// Estado e dados
export const getStatus = () => api.get<AppStatus>("/api/status");
export const EXPORT_URL = "/api/export";
