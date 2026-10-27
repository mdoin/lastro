import type {
  GoalStatus,
  GuidanceStage,
  Liquidity,
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
