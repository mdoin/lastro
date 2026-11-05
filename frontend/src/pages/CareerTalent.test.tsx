// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { TalentEvaluation, TalentReview } from "../api/carreira";
import { Layout } from "../components/Layout";
import { AppProvider } from "../lib/appContext";
import { eventText } from "../lib/career";
import { Evaluation, Review } from "./CareerTalent";

const at = (el: ReactElement, path = "/carreira/talent") =>
  renderToStaticMarkup(<MemoryRouter initialEntries={[path]}>{el}</MemoryRouter>);

// Dados de teste fictícios ([TESTE]); a página só mostra o que o Talent gravou.
const avaliacao: TalentEvaluation = {
  id: 1, n: 7, title: "[TESTE] Dev Python Júnior", company: "ACME Teste", elegivel: false, pontuacao: 88, rubrica: "r1",
  filtros: [{ filtro: "Senioridade pedida na descrição", ok: false, motivo: "a descrição pede pleno" }],
  criterios: [{ criterio: "Requisitos técnicos obrigatórios", peso: 40, pontos: 40, motivo: "2 atendido(s)" }],
  requisitos: [{ texto: "Kubernetes", tipo: "obrigatorio", categoria: "tecnico", situacao: "ausente", evidencia: "", evidencia_recusada: true }],
  posicionamento: "Backend Python júnior", perfil_curriculo: "backend", destaques: [], orientacoes: ["Destacar FastAPI e PostgreSQL."],
  justificativa: "Pontua bem, mas pede pleno.", created_at: "2026-11-05T12:00:00Z",
};
const revisao: TalentReview = {
  id: 1, n: 7, title: "[TESTE] Dev Python Júnior", company: "ACME Teste", curriculo_id: 3, rodada: 1, resultado: "correcoes",
  resumo: "Afirmação sem comprovação.", created_at: "2026-11-05T12:00:00Z",
  checagens: [{ criterio: "precisao_factual", ok: false, detalhe: "tecnologias fora do perfil: kubernetes" }],
  problemas: [{ criterio: "precisao_factual", gravidade: "bloqueante", trecho: "kubernetes", correcao: "Remover kubernetes: não aparece no perfil." }],
};

describe("Talent", () => {
  it("aparece na navegação da Carreira", () => {
    expect(at(<AppProvider><Layout /></AppProvider>)).toContain("Talent");
  });

  it("avaliação mostra filtro que barra, evidência recusada, rubrica e que a nota não é chance de contratação", () => {
    const html = at(<Evaluation a={avaliacao} />);
    for (const text of ["Não elegível", "a descrição pede pleno", "evidência citada não está no perfil", "40 / 40",
      "não chance de contratação", "Destacar FastAPI"]) expect(html).toContain(text);
  });

  it("revisão mostra resultado, correção executável e checagem", () => {
    const html = at(<Review r={revisao} />);
    for (const text of ["Correções necessárias", "Remover kubernetes", "tecnologias fora do perfil", "/carreira/curriculos/3"])
      expect(html).toContain(text);
  });

  it("eventos do Talent têm frase própria", () => {
    expect(eventText({ tipo: "avaliada_talent", detalhe: { elegivel: true, pontuacao: 72 } })).toBe("Talent: elegível, compatibilidade 72");
    expect(eventText({ tipo: "revisao_bloqueada", detalhe: { motivo: "sem progresso" } })).toContain("sem progresso");
  });
});
