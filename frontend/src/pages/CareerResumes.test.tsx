// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppProvider } from "../lib/appContext";
import { FactRow, ProfileCard } from "./CareerResumes";

const html = (el: ReactElement) => renderToStaticMarkup(<MemoryRouter><AppProvider>{el}</AppProvider></MemoryRouter>);

describe("currículos", () => {
  it("perfil mostra a página do PDF exato, a validação e os arquivos", () => {
    const out = html(<ProfileCard p={{ perfil: "backend", nome: "Software Engineer / Backend", descricao: "Python e APIs",
      curriculo_id: 7, created_at: "2026-11-05T12:00:00Z", validacao: { ok: true, paginas: 1, erros: 0, avisos: 0 } }} />);
    expect(out).toContain("/api/carreira/curriculos/7/pagina/1.png");
    expect(out).toContain("Validado · 1 pág.");
    expect(out).toContain("formato=pdf");
    expect(out).toContain("formato=docx");
  });

  it("perfil ainda não gerado não inventa documento", () => {
    const out = html(<ProfileCard p={{ perfil: "ia", nome: "AI Engineer", descricao: "LLMs", curriculo_id: null,
      created_at: null, validacao: null }} />);
    expect(out).toContain("Ainda não gerado");
    expect(out).not.toContain("formato=pdf");
  });

  it("fato pendente pede confirmação; confirmado oferece voltar a pendente", () => {
    const pend = html(<FactRow id="sk-x" status="pendente" text="WebSocket" source="sem evidência" onSaved={() => {}} />);
    expect(pend).toContain("Pendente");
    expect(pend).toContain(">Confirmar<");
    const ok = html(<FactRow id="sk-y" status="confirmado" text="Python" onSaved={() => {}} />);
    expect(ok).not.toContain(">Confirmar<");
    expect(ok).toContain("Confirmado");
  });
});
