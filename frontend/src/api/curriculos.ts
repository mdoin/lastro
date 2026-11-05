// SPDX-License-Identifier: AGPL-3.0-or-later
/** Currículos (docs/CARREIRA.md, "Currículos"): base estruturada, perfis, versões e documentos exatos. */
import { api } from "./client";

export type FactStatus = "confirmado" | "pendente" | "inferido" | "descartado";
export type ProfileId = "backend" | "ia" | "junior";
export type Lang = "pt" | "en";
type Text2 = { pt: string; en?: string };

export interface Fact { id: string; status: FactStatus; fonte?: string }
export interface Achievement extends Fact, Text2 { tags?: string[]; grupo?: string }
export interface Experience extends Fact {
  empresa: string; local?: string; area?: string; descricao?: Text2;
  cargos: (Text2 & { inicio: string; fim: string | null })[]; realizacoes: Achievement[];
}
export interface Project extends Fact {
  nome: string; descricao: Text2; tecnologias?: string[]; situacao?: string; corporativo?: boolean;
  divulgacao?: string; link?: string; destaques?: Text2[];
}
export interface Skill extends Fact { categoria: string; nome: string; evidencias?: string[] }
export interface Education extends Fact { curso: Text2; instituicao: string; situacao?: string; conclusao?: string }
export interface Course extends Fact { nome: string; instituicao: string; data?: string; tipo?: string }
export interface Language extends Fact, Text2 {}
export interface Question { id: string; alvo: string; pergunta: string; resposta: string; status: "aberta" | "respondida" | "descartada"; respondida_em?: string }

export interface BaseDoc {
  pessoa: Record<string, string>;
  titulos: Record<ProfileId, Text2>; resumos: Record<ProfileId, Text2>;
  experiencias: Experience[]; projetos: Project[]; competencias: Skill[]; formacao: Education[];
  cursos: Course[]; idiomas: Language[]; perguntas: Question[];
}
export interface Validation { ok: boolean | null; paginas: number | null; erros: number; avisos: number }
export interface ProfileVersion {
  perfil: ProfileId; nome: string; descricao: string; curriculo_id: number | null; created_at: string | null;
  validacao: Validation | null;
}
export interface BaseView {
  versao: { id: number; origem: string; nota: string; created_at: string };
  base: BaseDoc;
  pendencias: { itens: { id: string; tipo: string; status: string; texto: string }[]; perguntas: Question[] };
  perfis: ProfileVersion[];
  historico: { id: number; origem: string; nota: string; created_at: string }[];
  liberado_em: string | null;
}

export interface ResumeUse { n: number; status: string; anexo: string; created_at: string }
export interface ResumeItem {
  id: number; tipo: "base" | "vaga"; vigente: boolean; origem_id: number | null; alteracoes: string[]; created_at: string;
  tamanho: number; perfil: ProfileId | null; idioma: Lang | null; base_id: number | null; tem_pdf: boolean;
  validacao: Validation | null; n: number | null; title: string | null; company: string | null; envios: ResumeUse[];
}
export interface FullValidation {
  ok: boolean; erros: string[]; avisos: string[]; paginas: number; ocupacao?: number[]; fontes?: string[];
  links?: string[]; caracteres?: number; verificado_em?: string; docx?: { ok: boolean; erros: string[]; paragrafos?: number };
}
export interface Resume {
  id: number; tipo: "base" | "vaga"; origem_id: number | null; conteudo_md: string; origem_md: string | null;
  alteracoes: string[]; created_at: string; n: number | null; title: string | null; company: string | null;
  perfil: ProfileId | null; idioma: Lang | null; base_id: number | null; sha256: string | null;
  tem_pdf: boolean; tem_docx: boolean; paginas: number | null; validacao: FullValidation | null;
  analise: { perfil_fonte?: string; aderencia?: number; lacunas?: { requisito: string; dica: string }[] } | null;
  envios: { id: number; status: string; anexo: string; created_at: string; n: number; title: string; company: string }[];
}

export const PROFILE_LABEL: Record<ProfileId, string> = {
  backend: "Software Engineer / Backend", ia: "AI Engineer / IA aplicada", junior: "Estágio / Júnior",
};

export const getBase = () => api.get<BaseView>("/api/carreira/base");
export const editFact = (id: string, body: { status?: FactStatus; pt?: string; en?: string }) =>
  api.post<{ id: number }>(`/api/carreira/base/itens/${encodeURIComponent(id)}`, body);
export const answerQuestion = (id: string, resposta: string, descartar = false) =>
  api.post<{ id: number }>(`/api/carreira/base/perguntas/${encodeURIComponent(id)}`, { resposta, descartar });
export const generateProfiles = () => api.post<{ criados: number[] }>("/api/carreira/base/gerar");
export const setRelease = (liberar: boolean) => api.post<{ liberado_em: string | null }>("/api/carreira/base/liberar", { liberar });
export const getResumes = () => api.get<ResumeItem[]>("/api/carreira/curriculos");
export const getResume = (id: number) => api.get<Resume>(`/api/carreira/curriculos/${id}`);
export const resumeFileUrl = (id: number, formato: "html" | "md" | "pdf" | "docx", download = false) =>
  `/api/carreira/curriculos/${id}/documento?formato=${formato}${download ? "&download=1" : ""}`;
export const resumePageUrl = (id: number, page: number) => `/api/carreira/curriculos/${id}/pagina/${page}.png`;
