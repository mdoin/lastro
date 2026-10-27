import type {
  AuditVerdict,
  GoalStatus,
  GuidanceStage,
  Liquidity,
  PanelRole,
  RunStatus,
  Schedule,
  ScheduleKind,
} from "../api/types";
import { formatDate } from "./dates";

export type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "gold";

export const STAGE_LABEL: Record<GuidanceStage, string> = {
  sem_recurso_disponivel: "Sem recurso disponível este mês",
  organizar_orcamento: "Organizar o orçamento",
  priorizar_divida: "Priorizar dívidas",
  construir_reserva: "Construir a reserva",
  investir_para_metas: "Investir para metas",
};

export const STAGE_ORDER: GuidanceStage[] = [
  "sem_recurso_disponivel",
  "organizar_orcamento",
  "priorizar_divida",
  "construir_reserva",
  "investir_para_metas",
];

export const GOAL_STATUS: Record<GoalStatus, { label: string; tone: Tone }> = {
  no_rumo: { label: "No rumo", tone: "good" },
  atencao: { label: "Atenção", tone: "warning" },
  revisar: { label: "Revisar", tone: "serious" },
};

export const LIQUIDITY_LABEL: Record<Liquidity, string> = {
  diaria: "Diária",
  curto_prazo: "Curto prazo",
  longo_prazo: "Longo prazo",
};

export const RUN_STATUS: Record<RunStatus, { label: string; tone: Tone }> = {
  queued: { label: "Na fila", tone: "neutral" },
  running: { label: "Rodando", tone: "gold" },
  succeeded: { label: "Concluída", tone: "good" },
  quiet: { label: "Sem novidades", tone: "neutral" },
  failed: { label: "Falhou", tone: "critical" },
  skipped: { label: "Pulada", tone: "neutral" },
  missed: { label: "Perdida", tone: "warning" },
};

export const AUDIT_VERDICT: Record<AuditVerdict, { label: string; tone: Tone; help: string }> = {
  PASSA: { label: "PASSA", tone: "good", help: "O Auditor não encontrou problemas na resposta." },
  REVISAR: { label: "REVISAR", tone: "warning", help: "O Auditor recomenda revisar pontos antes de agir." },
  BLOQUEAR: { label: "BLOQUEAR", tone: "critical", help: "O Auditor bloqueou a resposta. Não aja com base nela." },
};

export const PANEL_ROLE_LABEL: Record<PanelRole, string> = {
  diagnostico: "Diagnóstico",
  simulacao: "Simulação",
  riscos: "Riscos",
  educacao: "Educação",
  pesquisa: "Pesquisa",
};

export const WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];

export const SCHEDULE_KIND_LABEL: Record<ScheduleKind, string> = {
  daily: "Diária",
  weekly: "Semanal",
  monthly: "Mensal",
  once: "Uma vez",
};

export function describeSchedule(s: Schedule): string {
  switch (s.kind) {
    case "daily":
      return `Todos os dias às ${s.time}`;
    case "weekly":
      return `Toda ${WEEKDAYS[s.weekday ?? 0] ?? "semana"} às ${s.time}`;
    case "monthly":
      return `Todo dia ${s.day ?? 1} às ${s.time}`;
    case "once":
      return `Em ${formatDate(s.date)} às ${s.time}`;
    default:
      return s.time;
  }
}

/** Nome técnico da ferramenta → frase curta para o chip ("Consultou diagnóstico"). */
const TOOL_LABEL: Record<string, string> = {
  diagnostico: "Consultou diagnóstico",
  diagnosis: "Consultou diagnóstico",
  projecao: "Simulou projeção",
  projection: "Simulou projeção",
  listar_personas: "Consultou perfis de exemplo",
  snapshot: "Consultou retrato financeiro",
  metas: "Consultou metas",
  goals: "Consultou metas",
  premissas: "Consultou premissas",
  assumptions: "Consultou premissas",
  decisoes: "Consultou diário de decisões",
  WebSearch: "Pesquisou na web",
  WebFetch: "Leu uma página da web",
};

export function toolLabel(name: string): string {
  if (name.startsWith("painel:")) {
    const role = name.slice("painel:".length) as PanelRole;
    return `Especialista: ${PANEL_ROLE_LABEL[role] ?? role}`;
  }
  const short = name.includes("__") ? (name.split("__").pop() ?? name) : name;
  return TOOL_LABEL[short] ?? `Usou ferramenta: ${short.replace(/_/g, " ")}`;
}
