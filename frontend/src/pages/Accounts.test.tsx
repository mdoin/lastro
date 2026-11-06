// SPDX-License-Identifier: AGPL-3.0-or-later
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Platform } from "../api/contas";
import { PlatformCard } from "./Accounts";

const base: Platform = {
  id: "gupy", nome: "Gupy", url_oficial: "https://login.gupy.io/candidates/signin", url_verificacao: "https://login.gupy.io/x",
  dominios: ["gupy.io"], autenticacao: "sessao", modulo: "carreira", agentes: ["aplicador"], estado: "sessao_expirada",
  detalhe: "", tem_credencial: true, ultima_autenticacao: null, ultima_verificacao: null, updated_at: "2026-11-05T00:00:00Z",
  credencial: { usuario_dica: "ma…@x.example", agentes: ["aplicador"], dominios: ["gupy.io"], atualizado_em: null },
};
const card = (p: Partial<Platform>, sensitive: "credencial" | null = null) => renderToStaticMarkup(
  <MemoryRouter><PlatformCard p={{ ...base, ...p }} busy={null} vaultReady sensitive={sensitive} setSensitive={() => undefined}
    onVerify={() => undefined} onSensitive={async () => undefined} /></MemoryRouter>);

describe("Contas e acessos", () => {
  it("mostra estado, permissões e ações sem nenhum valor de segredo", () => {
    const html = card({});
    expect(html).toContain("Sessão expirada");
    expect(html).toContain("digitar a senha do cofre só em gupy.io");
    expect(html).toContain("Conectar");
    expect(html).toContain("/carreira/navegador?abrir=https%3A%2F%2Flogin.gupy.io");
    expect(html).toContain("Revogar acesso");
    expect(html).not.toMatch(/type="password"/);
  });

  it("plataforma vista pelo agente não ganha endereço oficial; a do servidor não se desconecta pela tela", () => {
    expect(card({ url_oficial: "" })).toContain("não verificado");
    const env = card({ autenticacao: "env", tem_credencial: false, credencial: null });
    expect(env).not.toContain("Desconectar");
    expect(env).not.toContain("Guardar senha");
  });

  it("formulário de credencial pede a senha do Lastro e não sugere preenchimento automático", () => {
    const html = card({}, "credencial");
    expect(html).toContain("Sua senha do Lastro (confirmação)");
    expect(html).toContain('"new-password"');
  });
});
