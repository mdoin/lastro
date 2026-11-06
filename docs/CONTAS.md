# Central de Contas e Acessos

Serviço compartilhado pelos módulos Finanças e Carreira: plataformas que os agentes usam, o estado de cada acesso,
o cofre de credenciais e as pendências que os agentes abrem para o dono. Tela: **Configurações → Contas e acessos**
(`/configuracoes/contas`), também no menu "Sistema" dos dois módulos.

## Peças

| Peça | Papel |
|---|---|
| `backend/mentor/cofre.py` | cofre cifrado (só no worker) e operação `contas` do socket |
| `backend/mentor/aplicador.py` | `load_vault()` lê do cofre só o que o `aplicador` pode usar; `sessao()` verifica/desconecta sessões no perfil do Chrome do agente |
| `backend/app/contas.py` | plataformas, pendências (sem duplicar), notificação e retomada das tarefas |
| `backend/app/contas_web.py` | rotas `/api/contas/*` |
| `backend/carreira/candidatura.py` | resultado `sem_acesso` do Aplicador → pendência; a vaga espera, as outras plataformas seguem |
| `backend/carreira/hunter.py` | `esperar_fila`: o sinal `retomar` acorda a fila em até 1 min |
| `migrations/021_contas.sql` | `contas_plataformas`, `contas_pendencias`, `carreira_candidaturas.pendencia_id` |
| `frontend/src/pages/Accounts.tsx` | a tela |

## Estratégias de autenticação (nesta ordem)

1. **OAuth / integração oficial** — tipo `oauth` reservado. Hoje nenhuma das plataformas de vaga oferece integração
   oficial que sirva para candidatura; o Gmail tem OAuth, mas exige um app registrado no Google Cloud (fica como
   próximo passo, ver migração do `.env`).
2. **Sessão no Chromium persistente** (`sessao`, padrão): o dono entra pela tela **Navegador do agente**
   (`Conectar`/`Reconectar` abrem lá com o endereço oficial preenchido). O agente reutiliza a sessão sem conhecer a
   senha. **Verificar sessão** abre a página de verificação da plataforma (só existe logado) numa aba à parte e
   decide pelo endereço final: fora dos domínios, caminho de login/checkpoint ou campo de senha visível = não logado.
   Só volta host e caminho, nunca a URL inteira.
3. **Senha no cofre** (`senha`): o dono guarda usuário e senha pela tela. O agente nunca recebe o valor: a ferramenta
   `aplicador_login` digita no campo, e só se a página aberta for de um dos domínios da credencial.

Não existe ferramenta que crie conta. O prompt do Aplicador manda parar com `sem_acesso`/`cadastro` só quando a
plataforma disser claramente que a conta não existe; login que falhou é `login`. E o backend confere de novo: se a
plataforma já tem credencial ou sessão confirmada, um pedido de `cadastro` vira `login`.

## Pendências e retomada

O Aplicador devolve `{"status": "sem_acesso", "plataforma": "gupy", "acesso": "login|cadastro|sessao_expirada|
dois_fatores|verificacao_identidade|confirmacao_email", "motivo": ...}`. Então:

1. abre (ou reaproveita) a pendência `(plataforma, tipo)` — uma aberta por problema (índice único parcial);
2. a candidatura fica `aguardando_acesso`, ligada à pendência (`pendencia_id`); **nenhum envio é gravado e nenhuma
   tentativa é gasta**;
3. as demais vagas daquela plataforma ficam fora da fila enquanto a pendência estiver aberta; as das outras seguem;
4. só na criação: notificação interna (`acesso_pendente`, link para a Central) e um aviso no WhatsApp.

Campo obrigatório sem resposta (`precisa_de_voce` + `tipo: informacao_ausente`) também vira pendência, por vaga
(chave = id da vaga), com o comportamento antigo de envio/tentativa.

Resolver: **Já entrei — verificar** (confirma a sessão; fecha todas as pendências de acesso da plataforma),
**Marcar como resolvida** ou **Descartar** (as tarefas presas são encerradas). Resolvida, a candidatura volta para
`curriculo` com evento `retomada`, e a tabela `carreira_estado` recebe `retomar`: o `lastro-carreira` confere esse
sinal a cada minuto e roda a fila sem esperar a volta de 30 min (dentro do horário de avisos, 8 h–21 h).

## Segurança

| Requisito | Como |
|---|---|
| Criptografia autenticada em repouso | AES-256-GCM (`cryptography`), nonce aleatório por gravação, AAD fixo; arquivo adulterado ou chave errada = erro (`InvalidTag`), nunca dado parcial |
| Chave separada dos dados | `LoadCredentialEncrypted=lastro-cofre` (systemd 255): a chave fica em `/etc/credstore.encrypted/lastro-cofre` (root, 0600), cifrada pela chave do host `/var/lib/systemd/credential.secret`; o worker a vê só em `$CREDENTIALS_DIRECTORY`. Dados em `/var/lib/mentor/carreira/cofre.enc` (0600, mentor) |
| Sem chave | cofre indisponível; não há plano B em texto puro |
| Permissões | gravação atômica `0600` (mesmo padrão de `providers/credentials.py`); `UMask=0077` no serviço |
| HTTPS | Caddy na frente; cookie `Secure`, `SameSite=Strict`, `HttpOnly` |
| Autenticação | todas as rotas exigem sessão; gravar, revogar e desconectar pedem a senha do Lastro de novo, no mesmo limitador do login (bloqueio por cliente) |
| CSRF / XSS | `X-Lastro: 1` + mesma origem em toda escrita; CSP do app; React escapa texto; endereço de plataforma vindo de página nunca vira link "oficial" |
| Validação | plataforma `^[a-z0-9][a-z0-9_-]{1,39}$`; domínios só nomes (sem IP, sem esquema); usuário/senha sem caracteres de controle e com teto; 422 sem ecoar o valor enviado (handler global) |
| Isolamento por agente | cada credencial lista `agentes`; só `aplicador` tem ferramenta de login (`cofre.AGENTES`). Agentes de Finanças e o Carteiro não recebem nada |
| Domínio | senha digitada só no domínio da credencial; trocar os domínios sem reenviar a senha é recusado (o segredo não segue para outro site) |
| Sem segredo em log, resposta ou modelo | logs só com o nome da plataforma; `public()` devolve dica do usuário (`ma…@x.com`) e `tem_senha`; o modelo só vê o resultado da ferramenta; auditoria (`audit_log`) só com ação e plataforma |
| Frontend | senha só no estado do formulário aberto, limpa no envio; nada em `localStorage`/`sessionStorage`; nunca em URL |
| Cofre não é API genérica | a operação `contas` só existe no socket do worker (SO_PEERCRED = usuário do web app) e não tem ação de leitura de segredo |

Testes: `tests/integration/test_contas.py` (cofre, adulteração, isolamento, domínio, log, migração, pendências,
retomada, rotas, reautenticação, limite) e `frontend/src/pages/Accounts.test.tsx`.

## Migração do cofre antigo e dos `.env`

**Cofre antigo** (`/var/lib/mentor/carreira/cofre.json`, texto puro 0600, 7 plataformas): na primeira leitura com
chave, o worker cifra tudo em `cofre.enc` (autorizando só o `aplicador`) e renomeia o original para
`cofre.json.importado`. Depois de uma candidatura conferida com login por senha, apague-o:
`sudo shred -u /var/lib/mentor/carreira/cofre.json.importado`.

**Variáveis de ambiente** (inventário de 2026-11-05; valores não lidos nem registrados):

| Arquivo / variável | Tipo | Já no cofre? | Proposta |
|---|---|---|---|
| `carreira.env` `CARREIRA_GMAIL_USER` + `CARREIRA_GMAIL_APP_PASSWORD` | credencial de plataforma (Gmail IMAP, usada pelo Carteiro no `lastro-carreira`) | não | **compatível, próxima etapa**: o Carteiro roda como `patrimonio`, que não abre o cofre do worker. Migrar = mover a leitura IMAP para o worker (capacidade restrita "ler e-mails de vagas", como o login do Aplicador) ou trocar por OAuth do Gmail. Até lá aparece na Central como "Configurada no servidor" |
| `carreira.env` `CARREIRA_EVOLUTION_KEY` | segredo de infraestrutura (API local da Evolution, 127.0.0.1) | não | manter no `.env`: não é conta do dono numa plataforma |
| `carreira.env` `CARREIRA_EVOLUTION_URL`, `_INSTANCE`, `CARREIRA_WHATSAPP_TO` | configuração operacional | — | manter |
| `agent-api.env` `MPA_AGENT_API_TOKEN`, `mentor-token` | segredo de infraestrutura (API de leitura interna) | — | manter (systemd) |
| `/opt/evolution/.env` (`AUTHENTICATION_API_KEY`, `POSTGRES_PASSWORD`, URIs) | infraestrutura da Evolution (Docker) | — | manter |
| `pesquisa.env` (`LASTRO_BRAVE_API_KEY_FILE`, `LASTRO_SEARXNG_URL`) | chave de serviço / configuração | — | manter (já é arquivo à parte) |
| Chaves de IA | credencial de serviço | já pela tela (Configurações → Provedores) | — |

Nenhum `.env` foi removido. Contas de plataforma de vaga deixam de exigir SSH: conectar, guardar senha, revogar e
desconectar são pela tela.

## Restauração

O cofre depende de três arquivos: `cofre.enc` (dados), `/etc/credstore.encrypted/lastro-cofre` (chave cifrada) e
`/var/lib/systemd/credential.secret` (chave do host). Sem os dois últimos, recadastre as senhas pela tela (as sessões
do navegador continuam no perfil do Chrome).
