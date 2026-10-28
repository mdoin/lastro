// SPDX-License-Identifier: AGPL-3.0-or-later
import type { TeamAudit, TeamMessage } from "../api/types";

/** A mensagem traz conteúdo financeiro verificável (fontes, números conferidos, análise ou decisão)? */
export function substantive(m: TeamMessage): boolean {
  return m.kind === "analysis" || m.sources.length > 0 || (m.audit?.checked_numbers ?? 0) > 0
    || ["decisao", "analise"].includes(m.meta?.chat?.intent ?? "");
}

/** Selo de auditoria a mostrar: "PASSA" sem nada financeiro para conferir não vira selo (papo não é parecer);
 *  ressalva e reprovação aparecem sempre. A auditoria continua rodando no servidor de qualquer jeito. */
export function visibleAudit(m: TeamMessage): TeamAudit | null {
  if (!m.audit) return null;
  return m.audit.verdict === "PASSA" && (m.meta?.chat?.style === "conversa" || !substantive(m)) ? null : m.audit;
}

/** "Registrar no Diário" só para respostas com conteúdo financeiro, nunca para conversa. */
export function canRecord(m: TeamMessage): boolean {
  return m.role === "assistant" && m.kind === "message" && m.status === "ok" && m.agent_id !== "lastro"
    && m.meta?.chat?.style !== "conversa" && substantive(m);
}
