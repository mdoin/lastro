/** Funções tipadas, uma por rota de `docs/WEB_API.md`. */
import { api } from "./client";
import type {
  Agent,
  Fact,
  SubmitResult,
  TeamConversation,
  TeamMemory,
  TeamMessage,
  TeamRun,
  AppStatus,
  AssumptionsResponse,
  AuthState,
  Decision,
  DecisionInput,
  Diagnosis,
  Goal,
  GoalInput,
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

// Equipe
export const getAgents = () => api.get<Agent[]>("/api/agents");
export const getTeamConversations = () => api.get<TeamConversation[]>("/api/team/conversations");
export const createTeamConversation = (body: {
  channel: "direct" | "group" | "council";
  agent_id?: string;
  title?: string;
  participants?: string[];
}) => api.post<TeamConversation>("/api/team/conversations", body);
export const getTeamConversation = (id: UUID) => api.get<TeamConversation>(`/api/team/conversations/${enc(id)}`);
export const renameTeamConversation = (id: UUID, title: string) =>
  api.put<TeamConversation>(`/api/team/conversations/${enc(id)}`, { title });
export const deleteTeamConversation = (id: UUID) => api.del(`/api/team/conversations/${enc(id)}`);
export const addParticipant = (id: UUID, agent_id: string) =>
  api.post<TeamConversation>(`/api/team/conversations/${enc(id)}/participants`, { agent_id });
export const removeParticipant = (id: UUID, agent_id: string) =>
  api.del<TeamConversation>(`/api/team/conversations/${enc(id)}/participants/${enc(agent_id)}`);
export const getTeamMessages = (id: UUID) => api.get<TeamMessage[]>(`/api/team/conversations/${enc(id)}/messages`);
export const sendTeamMessage = (id: UUID, body: { text: string; client_id: string; reply_to_id?: string }) =>
  api.post<SubmitResult>(`/api/team/conversations/${enc(id)}/messages`, body);
export const getTeamRuns = (id: UUID) => api.get<TeamRun[]>(`/api/team/conversations/${enc(id)}/runs`);
export const cancelRun = (runId: UUID) => api.post<TeamRun>(`/api/team/runs/${enc(runId)}/cancel`);
export const teamStreamUrl = (id: UUID) => `/api/team/conversations/${enc(id)}/stream`;
export const getTeamMemory = () => api.get<TeamMemory>("/api/team/memory");
export const addFact = (body: { key: string; value: string; note?: string }) => api.post<Fact>("/api/team/facts", body);
export const decideFact = (id: UUID, decision: "confirm" | "reject") =>
  api.post<Fact>(`/api/team/facts/${enc(id)}/${decision}`);
export const deleteNote = (id: UUID) => api.del(`/api/team/notes/${enc(id)}`);
