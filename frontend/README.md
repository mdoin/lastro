# Lastro — frontend web

SPA em Vite + React + TypeScript (strict), interface 100% em português do Brasil.
Contrato com o backend: [`../docs/WEB_API.md`](../docs/WEB_API.md) (fonte única de verdade).

## Comandos

```bash
export PATH="$HOME/.local/bin:$PATH"     # Node 24 / npm 11
npm ci                                    # instala exatamente o package-lock.json
npm run dev                               # http://127.0.0.1:5173, proxy /api → http://127.0.0.1:8080
npm run typecheck                         # tsc --noEmit
npm test                                  # vitest (dinheiro e parser SSE)
npm run build                             # typecheck + build em dist/ (servido pelo FastAPI em "/")
```

Para adicionar dependências: `npm install --before=<hoje - 14 dias> <pacote>` (versões exatas via `.npmrc`
`save-exact=true`) e versione o `package-lock.json`.

O FastAPI deve servir `dist/` em `/` com fallback de SPA para `index.html` (rotas como `/metas`, `/mentor/<id>`).

## Segurança e CSP

- O bundle não faz requisições a terceiros: sem CDN, sem analytics. As fontes (Inter e Geist Mono, SIL OFL) são
  **auto-hospedadas** — vêm dos pacotes `@fontsource-variable/*` e são empacotadas em `dist/assets` (só os recortes
  latino e latino estendido, ver `src/styles/fonts.css`), compatíveis com `font-src 'self'`.
- Compatível com `Content-Security-Policy: default-src 'self'`: nenhum script ou `<style>` inline no build; estilos dinâmicos
  usam CSSOM (props `style` do React), que a CSP não bloqueia.
- Markdown do mentor: `react-markdown` + `remark-gfm`, sem HTML bruto (`skipHtml`) e sem imagens.
- O quadro futuro do "navegador de pesquisa" (`browser_frame`) é desenhado em `<canvas>` via `createImageBitmap`,
  sem URLs `data:`/`blob:` — funciona sem afrouxar `img-src`.

## Arquitetura

```
src/
  api/
    types.ts        tipos do contrato (dinheiro = string decimal)
    client.ts       fetch same-origin, X-Lastro: 1 em POST/PUT/DELETE, ApiError, 401 → /login, postStream (SSE)
    sse.ts          parser SSE (event:/data:, CRLF, pedaços partidos) + leitor de ReadableStream
    endpoints.ts    uma função tipada por rota
  lib/
    money.ts        formatação/parse pt-BR sem float (formatBRL, formatPct, parseBRL, parsePercent, soma exata)
    dates.ts        datas pt-BR sem deslocamento de fuso
    labels.ts       rótulos de estágio, status, agenda, ferramentas
    appContext.tsx  status, aviso legal (guidance.disclaimer), não lidos, toast
    useAsync.ts     carregamento simples com recarga
  components/       Layout (barra lateral / barra de abas flutuante), ui (painel aninhado, campos, selos, anel de
                    progresso), LineChart e FlowDiagram (SVG), RollingNumber (saldo que rola), Markdown (sob demanda),
                    BrowserView (placeholder do navegador de pesquisa), Icon (ícones + símbolo BrandMark)
  pages/            Login, Overview, Finances, Future, Goals, Mentor, Routines, Decisions, Settings
  styles/fonts.css  @font-face das fontes auto-hospedadas
  styles/global.css sistema visual "Bloco": tokens claro/escuro (aparelho ou escolha em lib/theme.ts), layout e componentes
```

### Dinheiro

`src/lib/money.ts` espelha `backend/financial_engine/money.py`:

- Exibição: `formatBRL("1234.5")` → `R$ 1.234,50` (espaço não separável), `formatPct("0.12")` → `12,00%`,
  arredondamento `ROUND_HALF_UP` feito em string/BigInt — o valor nunca passa por float.
- Entrada: `parseBRL("1.234,56")` → `"1234.56"`; aceita `150`, `0,5`, `R$ 10,00`, `(10,00)`; **recusa** `10.50`
  (ambíguo) com mensagem explicativa. `parsePercent("2,5")` → `"0.025"`.
- `toChartNumber` é a única conversão para float, só para geometria de gráficos e medidores.

### Gráficos

SVG escrito à mão (`components/LineChart.tsx`, `components/FlowDiagram.tsx`), sem biblioteca. Paletas validadas com o
script da skill de dataviz, claro (sobre `#ffffff`) e escuro (sobre `#1c1c1a`):

- linhas (`--pairs all`): `--series-1` azul `#2a78d6`/`#3987e5`, `--series-2` dourado `#b07d1e`/`#b38a35`,
  `--series-3` verde-água `#1f8f7a`/`#24977e`;
- fluxo do mês (pares adjacentes, nesta ordem): essenciais azul, parcelas laranja `#eb6834`/`#d95926`,
  variáveis violeta `#6250d6`/`#9085e9`, livre verde-água `#1baf7a`/`#199e70` (déficit usa a cor de status crítico).

Uma escala Y, legenda sempre presente, crosshair + tooltip no hover e no teclado (setas/Home/End), tabela ou lista
equivalente em cada gráfico; texto sempre na cor de tinta (a cor fica no marcador ao lado).

### Sistema visual

Inspirado em referências de produto (Plasma, Project card, Model router, Agent handoff): base monocromática, painéis
aninhados (casca cinza `.panel` + folha branca `.panel-body` + rodapé `.panel-foot` — o `Card` com título já renderiza
assim), rótulos em mono maiúsculo (`.eyebrow`, `.tag`), botões em pílula, números grandes e o dourado do lastro só onde
há significado. Marca e ícones: [`../docs/brand`](../docs/brand/README.md).

Controles de formulário no estilo do sistema: `DateInput` (data dd/mm/aaaa com calendário próprio), listas com
`appearance: base-select`, checkbox/radio/interruptor (`role="switch"`) e slider estilizados no CSS global; o campo de hora
é digitado (o seletor nativo ficou oculto no desktop). Tema: Automático/Claro/Escuro (`ThemeSwitch`, `lib/theme.ts`;
`public/theme-init.js` aplica a escolha antes da primeira pintura).

Movimento (saldo que rola, partículas do fluxo, entrada de painéis, notificação "ilha") respeita
`prefers-reduced-motion`. O checklist do mês guarda as marcações só no `localStorage` do navegador.

### Streams

`postStream` faz POST e lê `text/event-stream` com `fetch` + `ReadableStream`. No chat, se a conexão cair antes de
`done`, a tela recarrega `GET /api/conversations/{id}/messages` (o turno continua no servidor).
