// SPDX-License-Identifier: AGPL-3.0-or-later
/** Central de Contas e Acessos (docs/CONTAS.md). Senhas vão direto ao backend e nunca voltam: nada aqui guarda segredo. */
import { api } from "./client";

export type AccountState = "conectada" | "nao_configurada" | "sessao_expirada" | "aguardando_autenticacao" | "requer_verificacao" | "erro";
export type AuthKind = "oauth" | "sessao" | "senha" | "env";
export type PendingKind = "login" | "cadastro" | "sessao_expirada" | "verificacao_identidade" | "dois_fatores" | "confirmacao_email" | "informacao_ausente";

export interface Platform {
  id: string; nome: string; url_oficial: string; url_verificacao: string; dominios: string[]; autenticacao: AuthKind;
  modulo: "carreira" | "financas" | "sistema"; agentes: string[]; estado: AccountState; detalhe: string; tem_credencial: boolean;
  ultima_autenticacao: string | null; ultima_verificacao: string | null; updated_at: string;
  credencial?: { usuario_dica: string; agentes: string[]; dominios: string[]; atualizado_em: string | null } | null;
}
export interface PendingTask { n: number; title: string; company: string; status: string }
export interface Pending {
  id: number; plataforma: string; plataforma_nome: string; url_oficial: string; agente: string; tipo: PendingKind;
  motivo: string; acao: string; estado: "aberta" | "resolvida" | "descartada"; resolucao: string; created_at: string;
  resolved_at: string | null; tarefas: PendingTask[];
}
export interface AccountsOverview { plataformas: Platform[]; pendencias: Pending[]; cofre: { disponivel: boolean | null } }

export const getAccounts = () => api.get<AccountsOverview>("/api/contas");
export const verifyAccount = (id: string) => api.post<{ estado: AccountState; retomadas: number }>(`/api/contas/${encodeURIComponent(id)}/verificar`);
export const saveCredential = (id: string, body: { usuario: string; senha: string; senha_dono: string }) =>
  api.put(`/api/contas/${encodeURIComponent(id)}/credencial`, body);
export const revokeCredential = (id: string, senha_dono: string) => api.post(`/api/contas/${encodeURIComponent(id)}/revogar`, { senha_dono });
export const disconnectAccount = (id: string, senha_dono: string) => api.post(`/api/contas/${encodeURIComponent(id)}/desconectar`, { senha_dono });
export const resolvePending = (id: number, acao: "verificar" | "concluir" | "descartar") =>
  api.post<{ retomadas?: number; estado?: AccountState }>(`/api/contas/pendencias/${id}/resolver`, { acao });
