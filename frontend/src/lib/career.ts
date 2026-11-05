// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira: rótulos, módulo ativo, diferença entre currículos e atualização periódica das telas. */
import { useEffect } from "react";
import type { AgentRun, AgentState, ApplicationStatus, Column, FeedEvent, Seniority, Stage, Verdict, Workplace } from "../api/carreira";
import type { Tone } from "./labels";

export type Module = "financas" | "carreira";

/** Telas globais (sem módulo próprio): mantêm o módulo de onde se veio. */
export const SHARED_PATHS = ["/computadores", "/notificacoes", "/configuracoes"];

export function moduleOf(pathname: string, previous: Module): Module {
  if (pathname === "/carreira" || pathname.startsWith("/carreira/")) return "carreira";
  return SHARED_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ? previous : "financas";
}

export const COLUMNS: { key: Column; label: string; hint: string }[] = [
  { key: "preparando", label: "Preparando", hint: "Currículo pronto, envio pendente, incerto ou com falha" },
  { key: "enviada", label: "Enviada", hint: "Envio confirmado, sem retorno da empresa" },
  { key: "em_analise", label: "Em análise", hint: "A empresa deu andamento ou pediu teste" },
  { key: "entrevista", label: "Entrevista", hint: "Convite para entrevista" },
  { key: "proposta", label: "Proposta", hint: "Proposta recebida" },
  { key: "encerrada", label: "Encerrada", hint: "Recusa, retirada ou vaga não aplicável" },
];

export const STATUS: Record<ApplicationStatus, { label: string; tone: Tone }> = {
  curriculo: { label: "Currículo pronto", tone: "neutral" },
  precisa_de_voce: { label: "Aguardando você", tone: "warning" },
  incerta: { label: "Envio não confirmado", tone: "serious" },
  falhou: { label: "Falhou", tone: "critical" },
  candidatada: { label: "Enviada", tone: "good" },
  encerrada: { label: "Não aplicável", tone: "neutral" },
  retirada: { label: "Retirada", tone: "neutral" },
};

export const STAGE: Record<Stage, { label: string; tone: Tone }> = {
  em_analise: { label: "Em análise", tone: "gold" },
  teste: { label: "Teste", tone: "gold" },
  entrevista: { label: "Entrevista", tone: "good" },
  proposta: { label: "Proposta", tone: "good" },
  recusada: { label: "Recusada", tone: "critical" },
};

export const VERDICT: Record<Verdict, { label: string; tone: Tone }> = {
  compativel: { label: "Compatível", tone: "good" },
  talvez: { label: "Vale conferir", tone: "gold" },
  fora: { label: "Fora do perfil", tone: "neutral" },
};

export const WORKPLACE: Record<Workplace, string> = {
  remoto: "Remoto", hibrido: "Híbrido", presencial: "Presencial", desconhecido: "Não informado",
};

export const SENIORITY: Record<Seniority, string> = {
  estagio: "Estágio", junior: "Júnior", pleno: "Pleno", senior: "Sênior+", indefinida: "Não informada",
};

export const SOURCE_LABEL: Record<string, string> = {
  gupy: "Gupy", catho: "Catho", linkedin: "LinkedIn", programathor: "Programathor", remoteok: "RemoteOK",
  remotive: "Remotive", "email-linkedin": "LinkedIn (e-mail)", "email-indeed": "Indeed (e-mail)",
};
export const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s.replace(/^email-/, "e-mail · ");

export const AGENT_STATE: Record<AgentState, { label: string; tone: Tone; live?: boolean }> = {
  ocioso: { label: "Ocioso", tone: "neutral" },
  buscando: { label: "Buscando oportunidades", tone: "gold", live: true },
  preparando_curriculo: { label: "Preparando currículo", tone: "gold", live: true },
  preenchendo: { label: "Preenchendo candidatura", tone: "gold", live: true },
  atualizando_perfil: { label: "Atualizando perfil", tone: "gold", live: true },
  avaliando_vaga: { label: "Talent avaliando vaga", tone: "gold", live: true },
  revisando_curriculo: { label: "Talent revisando currículo", tone: "gold", live: true },
  analisando_resultados: { label: "Talent analisando resultados", tone: "gold", live: true },
  travado: { label: "Sem resposta além do prazo", tone: "critical" },
  aguardando_intervencao: { label: "Aguardando intervenção", tone: "warning" },
  erro: { label: "Erro na última execução", tone: "critical" },
  concluido: { label: "Concluído", tone: "good" },
};

export const RUN_KIND: Record<AgentRun["tipo"], string> = {
  busca: "Busca de vagas", curriculo: "Currículo sob medida", candidatura: "Candidatura", perfil: "Perfil na plataforma",
  avaliacao: "Avaliação da vaga (Talent)", revisao: "Revisão do currículo (Talent)", analise: "Análise de resultados (Talent)",
};
export const RUN_STATE: Record<AgentRun["estado"], { label: string; tone: Tone }> = {
  executando: { label: "Em execução", tone: "gold" },
  concluida: { label: "Concluída", tone: "good" },
  falhou: { label: "Falhou", tone: "critical" },
  interrompida: { label: "Interrompida", tone: "serious" },
};

export const ORIGIN: Record<string, string> = {
  cacador: "Caçador", alfaiate: "Alfaiate", aplicador: "Aplicador", carteiro: "Carteiro", talent: "Talent", dono: "Você",
  sistema: "Lastro",
};

const RESPONSE: Record<string, string> = {
  convite_teste: "convite para teste", convite_entrevista: "convite para entrevista", recusa: "retorno negativo",
  proposta: "proposta", confirmacao: "confirmação de candidatura", andamento: "andamento do processo",
};

/** Frase de um evento do histórico. Só usa o que o evento traz. */
export function eventText(e: { tipo: string; detalhe: Record<string, unknown> }): string {
  const d = e.detalhe;
  switch (e.tipo) {
    case "descoberta": return `Vaga encontrada${d.fonte ? ` em ${sourceLabel(String(d.fonte))}` : ""}${
      d.veredito ? ` · ${VERDICT[d.veredito as Verdict]?.label ?? d.veredito}` : ""}`;
    case "avaliada": return `Avaliada pelo Alfaiate: aderência ${d.aderencia}%`;
    case "curriculo_preparado": return "Currículo sob medida preparado";
    case "avaliada_talent": return d.elegivel ? `Talent: elegível, compatibilidade ${d.pontuacao}` : `Talent: não elegível — ${d.motivo}`;
    case "revisao_aprovado": return "Talent aprovou o currículo para envio";
    case "revisao_correcoes": return `Talent pediu correções ao Alfaiate (rodada ${d.rodada})`;
    case "revisao_bloqueado": return "Talent bloqueou: inconsistência factual";
    case "revisao_bloqueada": return `Currículo bloqueado pelo Talent: ${d.motivo}`;
    case "curriculo_corrigido": return "Alfaiate corrigiu o currículo";
    case "candidatura_iniciada": return "Candidatura iniciada pelo Aplicador";
    case "candidatura_enviada": return "Candidatura enviada, com confirmação da plataforma";
    case "resultado_desconhecido": return "Resultado do envio desconhecido — precisa de verificação";
    case "intervencao_solicitada": return "Intervenção solicitada";
    case "candidatura_nao_aplicavel": return "Candidatura não aplicável";
    case "candidatura_falhou": return "Falha durante o preenchimento";
    case "duplicata_bloqueada": return `Envio bloqueado: mesma vaga já tratada (#${d.vaga_n})`;
    case "resposta": return `Resposta recebida: ${RESPONSE[String(d.tipo)] ?? d.tipo}`;
    case "etapa_atualizada": return `Etapa: ${STAGE[d.etapa as Stage]?.label ?? d.etapa}`;
    case "envio_confirmado": return "Envio confirmado";
    case "envio_negado": return "Marcada como não enviada";
    case "retirada": return "Candidatura retirada";
    default: return e.tipo.replace(/_/g, " ");
  }
}

export function eventTone(tipo: string): Tone {
  if (["candidatura_falhou", "resultado_desconhecido"].includes(tipo)) return "serious";
  if (["intervencao_solicitada", "duplicata_bloqueada", "revisao_correcoes"].includes(tipo)) return "warning";
  if (["revisao_bloqueado", "revisao_bloqueada"].includes(tipo)) return "serious";
  if (tipo === "revisao_aprovado") return "good";
  if (["candidatura_enviada", "envio_confirmado"].includes(tipo)) return "good";
  if (["resposta", "etapa_atualizada"].includes(tipo)) return "gold";
  return "neutral";
}

/** Para onde um evento leva: a candidatura, quando existe; senão, a vaga. */
export const eventHref = (e: FeedEvent) => (e.candidatura ? `/carreira/candidaturas/${e.n}` : `/carreira/vagas/${e.n}`);

export type DiffLine = { kind: "same" | "add" | "del"; text: string };

/** Diferença linha a linha (LCS). Currículos têm dezenas de linhas: O(n·m) basta. */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  const w = b.length + 1;
  const lcs = new Int32Array((a.length + 1) * w);  // lcs[i*w + j]: maior subsequência comum de a[i:] e b[j:]
  const at = (i: number, j: number) => lcs[i * w + j]!;
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i * w + j] = a[i] === b[j] ? at(i + 1, j + 1) + 1 : Math.max(at(i + 1, j), at(i, j + 1));
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i]! });
      i++;
      j++;
    } else if (at(i + 1, j) >= at(i, j + 1)) out.push({ kind: "del", text: a[i++]! });
    else out.push({ kind: "add", text: b[j++]! });
  }
  while (i < a.length) out.push({ kind: "del", text: a[i++]! });
  while (j < b.length) out.push({ kind: "add", text: b[j++]! });
  return out;
}

/** Recarrega a tela a cada `ms` enquanto a aba está visível (os agentes gravam no backend; sem streaming novo). */
export function usePolling(reload: () => unknown, ms = 15_000) {
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload();
    }, ms);
    const onVisible = () => document.visibilityState === "visible" && void reload();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [reload, ms]);
}

export function formatSalary(value: number | null, currency: string | null): string {
  if (value == null) return "";
  const cur = currency || "BRL";
  try {
    return new Intl.NumberFormat("pt-BR", { style: "currency", currency: cur, maximumFractionDigits: 0 }).format(value);
  } catch {
    return `${cur} ${value}`;
  }
}

export const percent = (x: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);
