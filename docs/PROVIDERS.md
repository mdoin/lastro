# Provedores de IA (AI Provider Runtime)

O núcleo do Lastro (motor financeiro, memória, agentes, conversas) não depende de nenhum modelo. Os provedores ficam
atrás de um contrato comum em `backend/providers/`:

| Peça | Arquivo |
|---|---|
| Contrato: provedor, sessão, capacidades, erros normalizados, consumo | `base.py` |
| Ferramentas neutras e a barreira que decide o que pode rodar | `toolspec.py` |
| Laço de ferramentas para APIs sem estado | `loop.py` |
| Conexões desta instalação (arquivo 0600 no worker) | `credentials.py` |
| Tipos disponíveis e escolha conexão → provedor | `registry.py` |

## Adaptadores

| Tipo | Autenticação | Ferramentas | Streaming | Cancelar | Retoma sessão nativa | Consumo | Observações |
|---|---|---|---|---|---|---|---|
| `anthropic` | API key (Claude Console) | sim | sim | sim | não (contexto do Lastro) | sim | Messages API; caminho recomendado pela Anthropic para produtos |
| `openai` | API key (OpenAI Platform) | sim | sim | sim | não | sim | Responses API com `store=false` |
| `claude_code` | login do CLI oficial **ou** API key | sim (MCP em processo) | sim | sim | sim | sim | executável oficial, sem modificação; ver termos |
| `codex` | login do CLI oficial (ChatGPT por device code) **ou** API key | sim (ferramentas dinâmicas) | sim | sim | não | sim | **experimental**; ferramentas nativas desligadas |
| `ollama` | nenhuma | configurável | sim | sim | não | não | local; capacidade depende do modelo |
| `openrouter` | API key | configurável | sim | sim | não | não | política de dados depende do modelo roteado |
| `gemini` | API key (Google AI Studio) | configurável | sim | sim | não | não | endpoint compatível com OpenAI documentado pelo Google |
| `openai_compatible` | opcional | configurável | sim | sim | não | não | LM Studio, vLLM, LiteLLM… |

"Configurável" = a conexão diz se o modelo suporta ferramentas (`tools`) e qual a janela de contexto
(`context_tokens`, que corta o histórico mais antigo). Modelos locais e pequenos **não** têm a mesma capacidade de
análise dos hospedados: sem ferramentas, o agente responde sem consultar os seus dados e o Auditor determinístico
continua conferindo números e promessas.

## Agentes e troca de provedor

- Cada agente (Mentor, Planejador, Analista, Economista, Riscos, Conselheiro, Auditor) pode usar uma conexão e um
  modelo diferentes (Configurações → Modelo de cada agente). Sem escolha, vale a conexão padrão.
- Identidade, instruções, ferramentas e limites do agente vêm do Lastro (`backend/team/agents.py` e
  `backend/mentor/prompts/`), não do provedor.
- Histórico, memória financeira, notas, relatórios e decisões ficam no banco do Lastro. Trocar o provedor não apaga
  nada: a próxima conversa recomeça no provedor novo com o resumo do histórico guardado.
- A sessão nativa do provedor é cache descartável. Só o Claude Code retoma sessão por id, e só na mesma conexão.
  Entre provedores diferentes, o contexto é sempre reconstruído (não há retomada nativa cruzada).

## Segurança

- Credenciais pertencem à instalação. O web app (que tem o banco) nunca recebe um segredo de volta: chaves aparecem
  como `…1234`. O worker (que tem as credenciais) nunca abre o banco.
- Mudar o `base_url` de uma conexão apaga a chave dela: um web app comprometido não consegue redirecionar uma chave
  existente para outro servidor.
- Toda chamada de ferramenta passa por `toolspec.run_tool`: nome fora da concessão do papel é recusado sem executar.
- Claude Code: `tools=[]`, `setting_sources=[]`, `strict_mcp_config`, `can_use_tool` com a mesma concessão.
- Codex: `shell_tool`, `unified_exec`, apps, plugins, imagens, subagentes e busca na web desligados; sandbox
  `read-only`; aprovações sempre recusadas; pedidos desconhecidos do servidor recebem erro; ambiente mínimo (sem tokens
  do Lastro).
- Limites de uso são por conexão: um provedor em pausa não segura os outros.

## Login com conta (assinatura)

O Lastro **não** implementa login próprio de Claude.ai nem de ChatGPT e **não** guarda tokens de assinatura. Seguindo
o desenho estudado no OpenBot, quem faz login é o executável oficial:

- **Claude Code**: `claude auth login --claudeai`. No servidor sem navegador, o worker roda o CLI num terminal virtual,
  mostra o link da página da Anthropic e escreve no CLI o código que a pessoa cola de volta. O código não é gravado,
  não vai para log e não volta em resposta. Alternativa sem intermediação: o terminal do servidor.
- **Codex**: `account/login/start` com `chatgptDeviceCode` no app-server oficial: a pessoa digita o código na página
  da OpenAI. A credencial fica no `CODEX_HOME` do worker.

Antes de usar uma assinatura, leia [PROVIDER_TERMS.md](PROVIDER_TERMS.md).

### Sign in with ChatGPT (token sharing) — não implementado

A OpenAI documenta um fluxo OAuth com PKCE para apps open source usarem o plano do ChatGPT na Responses API
(`dynamic_agent_client`, `ext_agent_host_id`, escopos `chatgpt.tokens.use.direct`). A página de pedido de client id diz
que o recurso é oferecido a parceiros selecionados. Até haver confirmação de elegibilidade do Lastro, ele **não** foi
implementado; o uso do plano do ChatGPT acontece pelo login oficial do Codex, acima.

## Adicionar um provedor

1. Crie `backend/providers/<nome>.py` com uma subclasse de `Provider` (declare `capabilities` com honestidade) e, se
   for uma API sem estado, uma sessão sobre `LoopSession`.
2. Registre em `registry.TYPES`.
3. Testes com transporte HTTP simulado em `tests/unit/test_providers.py` (nunca chame a API real nos testes).
4. Documente aqui a autenticação usada e o link da documentação oficial que a autoriza.
