# Termos dos provedores

O Lastro não vende, revende nem paga uso de modelos. Cada instalação conecta as próprias contas e chaves, e o acordo
de quem conectou com o provedor vale para todo o uso. O Lastro não verifica se o seu uso respeita os termos de cada
provedor, e um provedor pode limitar ou encerrar uma conta que os descumpra. **Isto não é aconselhamento jurídico.**

## Claude (Anthropic)

### Como o Lastro roda o Claude
- `anthropic`: Messages API com a **sua** API key da Claude Console.
- `claude_code`: o Claude Agent SDK inicia o executável oficial `claude`, sem modificação, com o autoatualizador
  desligado. O executável vem do pacote `claude-agent-sdk` (hash conferido pelo `uv.lock`) ou de `LASTRO_CLAUDE_PATH`.
  O login é feito pelo próprio CLI (`claude auth login --claudeai`), que guarda a credencial; o Lastro só consulta
  `claude auth status`. Uma API key configurada na conexão tem precedência sobre o login.
- Em servidor sem navegador, a interface pode levar até o CLI o código que a página da Anthropic mostra (ver
  [PROVIDERS.md](PROVIDERS.md)). Isso é uma intermediação do código de login.

### O que a Anthropic publica
Página [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), lida em 2026-10-27, em resumo:
- a autenticação OAuth (planos Free, Pro, Max, Team, Enterprise) é para o uso comum do Claude Code e de aplicativos
  nativos da Anthropic;
- quem constrói produtos ou serviços sobre o Claude, inclusive com o Agent SDK, deve usar autenticação por API key
  (Claude Console ou provedor de nuvem suportado);
- terceiros não podem oferecer login do Claude.ai nos próprios aplicativos, nem encaminhar requisições por credenciais
  de planos Free/Pro/Max em nome de usuários, nem coletar, guardar ou intermediar credenciais ou tokens de sessão do
  Claude.ai;
- isso não impede o usuário final de entrar com a própria assinatura no executável oficial e não modificado do
  Claude Code, inclusive quando uma plataforma hospeda o Claude Code;
- os limites anunciados dos planos Pro e Max pressupõem uso individual e comum do Claude Code e do Agent SDK;
- a Anthropic pode aplicar essas restrições sem aviso prévio.

### Risco por uso (avaliação do projeto, não da Anthropic)
| Uso | Risco com assinatura Claude |
|---|---|
| Sua instalação, só você, login pelo terminal do servidor | Não está claro. Você entra no CLI oficial pela página da Anthropic; mas o Lastro é um produto sobre o Agent SDK, e rotinas automáticas podem ir além do "uso individual e comum". |
| Login pela interface do Lastro (código colado) | Maior: o Lastro leva o código da sua tela até o CLI. |
| Outras pessoas usando a sua instalação | Alto: pedidos de outras pessoas consomem o plano de uma só. |

**Recomendação:** use a API key (`anthropic`, ou `claude_code` com API key). Para o seu caso específico, a Anthropic
indica [falar com vendas](https://www.anthropic.com/contact-sales).

## OpenAI / ChatGPT

- `openai`: Responses API com a **sua** API key da OpenAI Platform; `store=false` (a OpenAI não guarda a conversa
  para recuperação; políticas de retenção da API continuam valendo).
- `codex`: executável oficial `codex app-server`. O login com a conta do ChatGPT é o device code oficial do próprio
  Codex, e a credencial fica com o Codex. Verifique se o seu plano permite o uso do Codex desta forma.
- **Sign in with ChatGPT para apps open source** (token sharing): documentado pela OpenAI em
  <https://developers.openai.com/siwc/token-sharing-open-source>, oferecido a parceiros selecionados. **Não
  implementado** até confirmação de elegibilidade.

## Google (Gemini), OpenRouter e endpoints compatíveis
Só API key do próprio operador, pelos endpoints documentados por cada serviço. Leia as políticas de dados de cada um:
no OpenRouter, a política depende do provedor final de cada modelo.

## Modelos locais (Ollama, LM Studio, vLLM)
Nenhum dado sai da sua máquina. Respeite a licença de cada modelo baixado.

## Dados financeiros
Provedores externos recebem o contexto necessário para responder: a pergunta, o histórico resumido da conversa e o
resultado das ferramentas que o agente chamou (por exemplo, seu retrato financeiro). Escolha o provedor de cada
agente sabendo disso; o Economista, que lê páginas da web, nunca vê seus dados.
