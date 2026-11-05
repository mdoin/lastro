// SPDX-License-Identifier: AGPL-3.0-or-later
/** Computadores dos agentes (docs/COMPUTADORES.md). */
import { api } from "./client";

export interface Computador {
  id: string; nome: string; titulo: string; ligado: boolean; controle: "agente" | "dono"; agente_ativo: boolean;
}
export interface Computadores { ip_saida: string; limite: number; agentes: Computador[] }

export const getComputadores = () => api.get<Computadores>("/api/computadores");
export const ligarComputador = (id: string) => api.post<{ ok: boolean }>(`/api/computadores/${id}/ligar`);
export const desligarComputador = (id: string) => api.post<{ ok: boolean }>(`/api/computadores/${id}/desligar`);
export const controlarComputador = (id: string, dono: boolean) =>
  api.post<{ ok: boolean }>(`/api/computadores/${id}/controle`, { dono });
export const telaUrl = (id: string) =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/computadores/${id}/tela`;
