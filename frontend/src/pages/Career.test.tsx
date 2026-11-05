// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { AgentInfo, Application, Metrics, Summary } from "../api/carreira";
import { Timeline } from "../components/Career";
import { Layout } from "../components/Layout";
import { AppProvider } from "../lib/appContext";
import { eventHref, eventText, lineDiff, moduleOf } from "../lib/career";
import { Board, nextStep, Table } from "./CareerApplications";
import { Overview } from "./CareerOverview";

const at = (path: string, el: ReactElement) =>
  renderToStaticMarkup(<MemoryRouter initialEntries={[path]}>{el}</MemoryRouter>);

const idle: AgentInfo = {
  estado: "ocioso", atual: null, ultima: null, proximo_ciclo: null, recentes: [], erros: [],
  fila: { curriculos: [], envios: [], envios_hoje: 0, limite_diario: 10, por_ciclo: 3 },
};
const zero: Metrics = {
  total: 0, compativeis: 0, talvez: 0, novas_7d: 0, enviadas: 0, aguardando: 0, em_andamento: 0, entrevistas: 0,
  propostas: 0, rejeicoes: 0, falhas: 0, incertas: 0, intervencao: 0, preparando: 0, respondidas: 0, taxa_resposta: null,
};
const app = (n: number, over: Partial<Application>): Application => ({
  n, id: `gupy:${n}`, title: `Vaga ${n}`, company: "ACME", location: "", workplace: "remoto", salary_min: null,
  currency: null, source: "gupy", url: "https://x", first_seen: "2026-11-01T00:00:00Z", published_at: null,
  verdict: "compativel", score: 80, reasons: [], senioridade: "junior", contrato: null, aderencia: 80,
  candidatura_status: "curriculo", etapa: null, coluna: "preparando", criada_em: "2026-11-01T00:00:00Z",
  enviada_em: null, curriculo_id: 1, atualizada_em: "2026-11-02T00:00:00Z", motivo: "", ...over,
});

describe("módulos e navegação", () => {
  it("o caminho decide o módulo; telas globais mantêm o anterior", () => {
    expect(moduleOf("/carreira/vagas/3", "financas")).toBe("carreira");
    expect(moduleOf("/vida-financeira", "carreira")).toBe("financas");
    expect(moduleOf("/configuracoes", "carreira")).toBe("carreira");
    expect(moduleOf("/configuracoes", "financas")).toBe("financas");
    expect(moduleOf("/carreirasx", "carreira")).toBe("financas");
  });

  it("Carreira mostra só a navegação dela e as ferramentas globais", () => {
    const html = at("/carreira/vagas", <AppProvider><Layout /></AppProvider>);
    for (const label of ["Oportunidades", "Candidaturas", "Currículos", "Agente de carreira", "Navegador do agente",
      "Configurações e auditoria", "Computadores"]) expect(html).toContain(label);
    expect(html).not.toContain("Minha vida financeira");
    expect(html).toMatch(/aria-current="true"[^>]*>Carreira</);
  });

  it("Finanças preserva todas as seções financeiras", () => {
    const html = at("/", <AppProvider><Layout /></AppProvider>);
    for (const label of ["Minha vida financeira", "Meu futuro", "Metas", "Caixa de entrada", "Mentor e especialistas",
      "Rotinas", "Diário de decisões", "Convicções", "Laboratório do Conselho", "Radar", "Diário de oportunidades",
      "Radar cripto", "Configurações e auditoria"]) expect(html).toContain(label);
    expect(html).not.toContain("Agente de carreira");
    expect(html).toMatch(/aria-current="true"[^>]*>Finanças</);
  });
});

describe("visão geral", () => {
  it("sem dados: zeros reais, taxa sem valor e estados vazios — nada inventado", () => {
    const html = at("/carreira", <Overview data={{ metricas: zero, agente: idle, proximas: [], atividade: [] } satisfies Summary} />);
    expect(html).toContain("Nenhuma atividade ainda");
    expect(html).toContain("nenhuma enviada ainda");
    expect(html).toContain("Ocioso");
    expect(html).toContain("Nada esperando por você agora");
    expect(html).not.toContain("running");  // sem indicador de atividade falso
  });

  it("mostra os números recebidos e liga eventos aos objetos", () => {
    const data: Summary = {
      metricas: { ...zero, total: 499, compativeis: 7, enviadas: 4, respondidas: 1, taxa_resposta: 0.25, rejeicoes: 1 },
      agente: { ...idle, estado: "preenchendo", atual: { id: 1, tipo: "candidatura", estado: "executando", resultado: "",
        erro: "", started_at: "2026-11-05T12:00:00Z", updated_at: "x", finished_at: null, n: 9, title: "Dev Jr",
        company: "ACME", travada: false } },
      proximas: [{ tipo: "verificar_envio", n: 9, title: "Dev Jr", company: "ACME", motivo: "sem confirmação", url: "", prazo: "", desde: "x" }],
      atividade: [{ id: 1, tipo: "resposta", origem: "carteiro", detalhe: { tipo: "recusa" }, envio_id: null,
        created_at: "2026-11-05T12:00:00Z", n: 9, title: "Dev Jr", company: "ACME", candidatura: true }],
    };
    const html = at("/carreira", <Overview data={data} />);
    expect(html).toContain(">499<");
    expect(html).toContain("25%");
    expect(html).toContain("Preenchendo candidatura");
    expect(html).toContain("status-dot running");
    expect(html).toContain('href="/carreira/candidaturas/9"');
    expect(html).toContain("Resposta recebida: retorno negativo");
  });
});

describe("candidaturas", () => {
  const items = [
    app(1, {}),
    app(2, { candidatura_status: "candidatada", coluna: "enviada", enviada_em: "2026-11-03T00:00:00Z" }),
    app(3, { candidatura_status: "candidatada", etapa: "recusada", coluna: "encerrada" }),
    app(4, { candidatura_status: "incerta", coluna: "preparando" }),
  ];

  it("Kanban põe cada uma na coluna da etapa e mostra o estado do envio à parte", () => {
    const html = at("/carreira/candidaturas", <Board items={items} />);
    const col = (id: string) => html.split(`id="col-${id}"`)[1]!.split("</section>")[0]!;
    expect(col("preparando")).toContain("Vaga 1");
    expect(col("preparando")).toContain("Envio não confirmado");
    expect(col("enviada")).toContain("Vaga 2");
    expect(col("encerrada")).toContain("Recusada");
    expect(col("entrevista")).not.toContain("Vaga");
  });

  it("tabela traz data de envio e próxima ação", () => {
    const html = at("/carreira/candidaturas", <Table items={items} />);
    expect(html).toContain("03/11/2026");
    expect(html).toContain("Verificar se o envio aconteceu");
    expect(nextStep(items[1]!)).toBe("Aguardar retorno");
  });
});

describe("histórico e currículos", () => {
  it("cada tipo de evento tem frase própria e leva ao objeto", () => {
    for (const tipo of ["descoberta", "avaliada", "curriculo_preparado", "candidatura_iniciada", "candidatura_enviada",
      "resultado_desconhecido", "intervencao_solicitada", "candidatura_falhou", "resposta", "etapa_atualizada",
      "envio_confirmado", "retirada", "duplicata_bloqueada"])
      expect(eventText({ tipo, detalhe: {} })).not.toBe(tipo.replace(/_/g, " "));
    expect(eventHref({ n: 3, candidatura: false } as never)).toBe("/carreira/vagas/3");
    const html = renderToStaticMarkup(<Timeline events={[{ id: 1, tipo: "descoberta", origem: "cacador",
      detalhe: { fonte: "gupy", reconstruido: 1 }, envio_id: null, created_at: "2026-11-01T00:00:00Z" }]} />);
    expect(html).toContain("Vaga encontrada em Gupy");
    expect(html).toContain("reconstruído");
  });

  it("diferença linha a linha entre a base e a versão", () => {
    expect(lineDiff("# Ana\nPython\nSQL", "# Ana\nPython e LLM\nSQL")).toEqual([
      { kind: "same", text: "# Ana" }, { kind: "del", text: "Python" }, { kind: "add", text: "Python e LLM" },
      { kind: "same", text: "SQL" },
    ]);
  });
});
