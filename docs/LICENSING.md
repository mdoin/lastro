# Licença

**Decisão (2026-10-27): AGPL-3.0-or-later**, com DCO nas contribuições e política de marca separada
([TRADEMARKS.md](../TRADEMARKS.md)). Abaixo, a análise que fundamentou a escolha.

## Compatibilidade das dependências
Todas as dependências distribuídas são permissivas (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0 só em dados de
certificados e ferramenta de build; OFL-1.1 nas fontes). Elas são compatíveis tanto com Apache-2.0 quanto com
AGPL-3.0. Pontos de atenção que valem para as duas:

- **Claude Code** (dentro do wheel `claude-agent-sdk`): regido pelos termos comerciais da Anthropic. É opcional e não
  entra nas imagens por padrão; imagens publicadas pelo projeto não devem incluí-lo.
- **Codex** (Apache-2.0): chamado como programa externo; opcional na imagem.
- **OpenBot** (PolyForm Noncommercial 1.0.0): incompatível com ambas para incorporação de código. Usado só como
  referência de conceitos; nenhum código foi copiado. Manter assim.
- **Marca**: nome "Lastro", logotipos (`docs/brand/`) e mascotes ficam fora da licença do código, com uma política de
  marca própria, para que forks não se apresentem como o projeto oficial.

## Comparação

| Critério | Apache-2.0 | AGPL-3.0-or-later |
|---|---|---|
| Fork hospedado como serviço fechado | permitido, sem devolver código | quem oferece pela rede precisa publicar as mudanças |
| Adoção por empresas e integração em produtos | máxima | menor (muitas empresas evitam AGPL) |
| Proteção de patentes | concessão explícita | concessão implícita (GPLv3) |
| Contribuições de volta à comunidade | voluntárias | obrigatórias para quem distribui ou hospeda versão modificada |
| Combinação com código GPL/AGPL de terceiros | só em uma direção | sim |
| Coerência com "self-hosted, dados do operador" | neutra | reforça: impede um "Lastro na nuvem" fechado com dados de terceiros |

## Recomendação
**AGPL-3.0-or-later** para o código, com **DCO** (`Signed-off-by`) nas contribuições e política de marca separada.

Motivos: o Lastro lida com dados financeiros e foi desenhado para cada pessoa rodar a própria instância. A AGPL
impede que alguém pegue o projeto, adicione coleta de dados e ofereça um serviço fechado sem que a comunidade veja o
que mudou, e mantém as melhorias voltando para o projeto brasileiro. O custo é menor adoção corporativa; se a
prioridade for virar componente de produtos de terceiros, a escolha muda para **Apache-2.0**.

Observação regulatória (independe da licença): oferecer o Lastro como serviço a terceiros pode exigir análise à luz das
normas da CVM sobre consultoria e análise de valores mobiliários (ver `docs/PENDING.md`, item 17). A distribuição
self-hosted, em que cada pessoa opera a própria instância, é o modelo assumido nesta versão.

## Como foi aplicada
1. `LICENSE` com o texto oficial da FSF (https://www.gnu.org/licenses/agpl-3.0.txt, 661 linhas, SHA-256
   `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`).
2. `SPDX-License-Identifier: AGPL-3.0-or-later` no topo dos arquivos-fonte (Python, TypeScript, CSS, SQL, shell,
   Dockerfile, compose); o teste `test_source_files_declare_the_license` cobra os arquivos novos.
3. `license` em `pyproject.toml` e `frontend/package.json`.
4. `DCO` (texto oficial 1.1) e verificação de `Signed-off-by` nos pull requests (CI).
5. Elementos de marca fora da AGPL, com política própria ([TRADEMARKS.md](../TRADEMARKS.md)).
6. AGPL §13: o link do código-fonte aparece no login e nas Configurações (`LASTRO_SOURCE_URL`). Quem roda uma versão
   modificada para outras pessoas deve apontá-lo para o próprio código.
