// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira (docs/CARREIRA.md): dados gravados pelos agentes e controle manual do navegador do aplicador. */
import { api } from "./client";

export interface BrowserFrame {
  ativo: boolean; imagem?: string; url?: string; titulo?: string; largura?: number; altura?: number; erro?: string;
}
export type BrowserKey = "Enter" | "Backspace" | "Tab" | "Escape" | "ArrowUp" | "ArrowDown" | "ArrowLeft" | "ArrowRight" | "Space";
export interface KeyFlags { ctrl?: boolean; alt?: boolean; shift?: boolean; meta?: boolean }
export type BrowserAction =
  | { acao: "iniciar" | "tela" | "voltar" | "encerrar" }
  | ({ acao: "clicar" | "duplo"; x: number; y: number })
  | { acao: "arrastar"; x: number; y: number; x2: number; y2: number }
  | { acao: "inserir" | "digitar"; texto: string }
  | ({ acao: "teclar"; key: string } & KeyFlags)
  | { acao: "tecla"; tecla: BrowserKey }
  | { acao: "abrir"; url: string }
  | { acao: "rolar"; dy: number };

export const getBrowserFrame = () => api.get<BrowserFrame>("/api/carreira/navegador");
export const browserAction = (body: BrowserAction) => api.post<BrowserFrame>("/api/carreira/navegador", body);

/** Estado do envio (o que o agente/dono fez) — nunca confundir com a etapa informada pela empresa. */
export type ApplicationStatus = "curriculo" | "precisa_de_voce" | "incerta" | "falhou" | "candidatada" | "encerrada" | "retirada";
export type Stage = "em_analise" | "teste" | "entrevista" | "proposta" | "recusada";
export type Column = "preparando" | "enviada" | "em_analise" | "entrevista" | "proposta" | "encerrada";
export type Verdict = "compativel" | "talvez" | "fora";
export type Workplace = "remoto" | "hibrido" | "presencial" | "desconhecido";
export type Seniority = "estagio" | "junior" | "pleno" | "senior" | "indefinida";

export interface Job {
  n: number; id: string; title: string; company: string; location: string; workplace: Workplace;
  salary_min: number | null; currency: string | null; source: string; url: string; first_seen: string;
  published_at: string | null; verdict: Verdict; score: number; reasons: string[]; senioridade: Seniority;
  contrato: string | null; aderencia: number | null; candidatura_status: ApplicationStatus | null; etapa: Stage | null;
  coluna?: Column | "sem_candidatura";
}

export interface CareerEvent {
  id: number; tipo: string; origem: string; detalhe: Record<string, unknown>; envio_id: number | null; created_at: string;
}
export interface FeedEvent extends CareerEvent { n: number; title: string; company: string; candidatura: boolean }

export interface AgentRun {
  id: number; tipo: "busca" | "curriculo" | "candidatura" | "perfil"; estado: "executando" | "concluida" | "falhou" | "interrompida";
  resultado: string; erro: string; started_at: string; updated_at: string; finished_at: string | null;
  n: number | null; title: string | null; company: string | null; travada: boolean;
}
export type AgentState = "ocioso" | "buscando" | "preparando_curriculo" | "preenchendo" | "atualizando_perfil" | "travado"
  | "aguardando_intervencao" | "erro" | "concluido";
export interface AgentInfo {
  estado: AgentState; atual: AgentRun | null; ultima: AgentRun | null; proximo_ciclo: string | null;
  proxima_fila: string | null; recentes: AgentRun[]; erros: AgentRun[];
  fila: {
    curriculos: { n: number; title: string; company: string; score: number }[];
    envios: { n: number; title: string; company: string; aderencia: number }[];
    envios_hoje: number; limite_diario: number; por_ciclo: number;
  };
}

export interface Metrics {
  total: number; compativeis: number; talvez: number; novas_7d: number; enviadas: number; aguardando: number;
  em_andamento: number; entrevistas: number; propostas: number; rejeicoes: number; falhas: number; incertas: number;
  intervencao: number; preparando: number; respondidas: number; taxa_resposta: number | null;
  hoje: DaySummary; na_fila: number; executando: number;
}
/** O que os agentes fizeram desde a meia-noite (horário de Brasília) e o que está parado esperando o dono. */
export interface DaySummary {
  encontradas: number; elegiveis: number; curriculos: number; tentativas: number; confirmadas: number; incertas: number;
  intervencoes: number; falhas: number; nao_aplicaveis: number; aguardando_voce: number; a_conferir: number;
}
export interface NextAction {
  tipo: "entrevista" | "teste" | "proposta" | "intervencao" | "verificar_envio" | "falha";
  n: number; title: string; company: string; motivo: string; url: string; prazo: string; desde: string;
}
export interface Summary { metricas: Metrics; agente: AgentInfo; proximas: NextAction[]; atividade: FeedEvent[] }

export interface Gap { requisito: string; dica: string }
export interface JobDetail extends Job {
  description: string;
  candidatura: null | {
    status: ApplicationStatus; etapa: Stage | null; coluna: Column; aderencia: number; resumo: string; lacunas: Gap[];
    curriculo_id: number | null; updated_at: string;
  };
  duplicatas: { n: number; title: string; source: string }[];
  eventos: CareerEvent[];
}

export interface Application extends Job {
  coluna: Column; criada_em: string; enviada_em: string | null; curriculo_id: number | null; atualizada_em: string;
  motivo: string;
}
export interface Attempt {
  id: number; status: "enviada" | "incerta" | "precisa_de_voce" | "nao_aplicavel" | "falhou"; motivo: string;
  url_final: string; evidencia: string; respostas: { pergunta: string; resposta: string }[];
  curriculo_id: number | null; execucao_id: number | null; agente: string; created_at: string;
}
export interface ApplicationDetail extends Job {
  status: ApplicationStatus; etapa: Stage | null; coluna: Column; resumo: string; lacunas: Gap[]; idioma: string;
  carta: string; curriculo_id: number | null; criada_em: string; atualizada_em: string; aderencia: number;
  envios: Attempt[]; eventos: CareerEvent[];
  emails: { received_at: string | null; subject: string; tipo: string; resumo: string; created_at: string }[];
}
export type ApplicationAction = { acao: "confirmar_envio" | "nao_enviada" | "retirar" } | { acao: "etapa"; etapa: Stage };

export interface ResumeItem {
  id: number; tipo: "base" | "vaga"; vigente: boolean; origem_id: number | null; alteracoes: string[]; created_at: string;
  tamanho: number; n: number | null; title: string | null; company: string | null;
  envios: { n: number; status: Attempt["status"]; created_at: string }[];
}
export interface Resume {
  id: number; tipo: "base" | "vaga"; origem_id: number | null; conteudo_md: string; origem_md: string | null;
  alteracoes: string[]; created_at: string; n: number | null; title: string | null; company: string | null;
}

export interface JobFilters {
  q?: string; empresa?: string; local?: string; modalidade?: string; senioridade?: string; compat?: string;
  fonte?: string; status?: string; salario_min?: string; aderencia_min?: string; desde?: string;
  ordem?: "relevancia" | "data"; limit?: number; offset?: number;
}

const qs = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") s.set(k, String(v));
  return s.toString();
};

export const getSummary = () => api.get<Summary>("/api/carreira/resumo");
export const getActivity = (limit = 100) => api.get<FeedEvent[]>(`/api/carreira/atividade?limit=${limit}`);
export const getAgent = () => api.get<AgentInfo>("/api/carreira/agente");
export const getJobs = (f: JobFilters) =>
  api.get<{ total: number; items: Job[]; fontes: string[] }>(`/api/carreira/vagas?${qs({ ...f })}`);
export const getJob = (n: number) => api.get<JobDetail>(`/api/carreira/vagas/${n}`);
export const getApplications = () => api.get<Application[]>("/api/carreira/candidaturas");
export const getApplication = (n: number) => api.get<ApplicationDetail>(`/api/carreira/candidaturas/${n}`);
export const applicationAction = (n: number, body: ApplicationAction) =>
  api.post<ApplicationDetail>(`/api/carreira/candidaturas/${n}/acao`, body);
export const getResumes = () => api.get<ResumeItem[]>("/api/carreira/curriculos");
export const getResume = (id: number) => api.get<Resume>(`/api/carreira/curriculos/${id}`);
export const resumeDocumentUrl = (id: number, formato: "html" | "md" = "html") =>
  `/api/carreira/curriculos/${id}/documento${formato === "md" ? "?formato=md" : ""}`;
