// SPDX-License-Identifier: AGPL-3.0-or-later
/** Carreira: controle manual do navegador do aplicador (docs/CARREIRA.md). */
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
