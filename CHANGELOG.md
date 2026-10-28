# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões no padrão SemVer.

## [0.3.0] — não publicada

### Adicionado
- **AI Provider Runtime** (`backend/providers/`): contrato comum com capacidades declaradas, erros normalizados,
  streaming, ferramentas, cancelamento, limites de uso e consumo; adaptadores Anthropic (API key), OpenAI (API key),
  Claude Code (executável oficial), Codex (executável oficial, experimental), Ollama, OpenRouter, Gemini e endpoints
  compatíveis com OpenAI.
- Login com conta pelos executáveis oficiais (desenho estudado no OpenBot): Claude Code (`claude auth login`, com link
  e código em servidor sem navegador) e Codex (device code do ChatGPT). O Lastro não guarda tokens desses CLIs.
- Provedor e modelo por agente; trocar de provedor mantém histórico, memória, relatórios e decisões.
- Gerenciador de contas de IA nas Configurações e assistente inicial (`/instalar`) com token de instalação.
- Instalação self-hosted com Docker Compose, perfil HTTPS opcional, health checks e serviços sem privilégios.
- `lastro-admin backup` e `restore`; backup automático antes de qualquer migração.
- Fuso configurável (`LASTRO_TZ`).
- Documentação de instalação, atualização, backup, provedores, termos, fontes de dados, licença, testes e release;
  CI com testes em Linux, instalação limpa, gitleaks e auditoria de dependências.
- **Conselho com discordância verificável** (docs/MULTIAGENT.md): parecer estruturado com posição declarada e seções
  obrigatórias, rodada única de contestação entre posições opostas, mapa de posições determinístico e reprovação da
  síntese que omite quem segue discordando.
- Agente **Analista de Ativos Digitais** (`@cripto`): custódia, stablecoins e risco operacional; entra no Conselho
  quando a questão é sobre cripto.
- Cada mensagem de agente registra conexão, modelo e versão do agente (`meta`), preservados após troca de provedor.
- Nomes de exibição dos agentes (Bento, Lia, Caio, Vera, Rui, Nina, Téo, Cora, Mila); ids e @menções antigas continuam.
- **Sala do Conselho** visual: lugares com estado real, painel do participante, veredito com menções coloridas e
  modo apresentação com máscara de valores.
- **Livro de movimentações** e **memória financeira automática** a partir da conversa (consentimento, desfazer,
  pendências que pedem só o que falta) — docs/LEDGER.md.
- **Mila e Caixa de entrada**: importação de CSV, OFX, PDF (extra `documents`) e imagens (OCR local opcional), com
  conciliação, duplicatas, idempotência e leitura por IA opcional e sempre pendente.
- Licença **AGPL-3.0-or-later** (`LICENSE`), cabeçalhos SPDX nos arquivos-fonte, DCO nas contribuições (verificado no
  CI) e política de marca (`TRADEMARKS.md`); link do código-fonte no login e nas Configurações (AGPL §13,
  `LASTRO_SOURCE_URL`).

### Alterado
- O worker do mentor fala com qualquer provedor pelo runtime; o protocolo com o web app continua o mesmo.
- `claude-agent-sdk` e `playwright` viraram extras opcionais (`claude-code`, `browser`).
- Textos da interface deixaram de falar em "assinatura".

### Atualização
- Migração 008 (só acréscimos). Instalações com senha não passam pelo assistente.
- Migração 009 (só acrescenta `messages.meta_json`). Mensagens antigas ficam com `meta` vazio.
- Migração 010 (só cria tabelas do livro, documentos, capturas e consentimentos). Novo extra opcional `documents` (pypdf).
- systemd: a unidade `lastro-mentor` ganhou `LASTRO_IMPLICIT_CLAUDE_CODE=1` e `LASTRO_PROVIDERS_FILE`;
  `scripts/deploy.sh` instala os extras `claude-code` e `browser`.

## [0.2.0] — 2026-10-27
Radar e Diário de Oportunidades, Diário de Decisões assistido, equipe de agentes, mascotes.

## [0.1.0] — 2026-10-27
Primeira versão publicada na instância pessoal: motor financeiro, mentor e interface.
