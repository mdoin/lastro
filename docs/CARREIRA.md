# Carreira

Busca vagas que combinam com o perfil do dono, avisa no WhatsApp e, nas próximas fases, personaliza o currículo,
faz a candidatura, acompanha o processo e treina para a entrevista.

## Fases
| Fase | O que faz | Estado |
|---|---|---|
| 1. Caçador | Busca vagas públicas, avalia pelas regras e manda um resumo no WhatsApp | feito |
| 2. Alfaiate | Currículo por vaga a partir do currículo base, sem inventar experiência | feito |
| 3. Aplicador | Candidatura pelo navegador próprio do agente, com logins guardados em cofre | feito |
| 4. Carteiro | Lê o e-mail de candidaturas, detecta avanços e testes e avisa | feito |
| 5. Treinador | Entrevista simulada pelo WhatsApp sobre uma vaga | feito |

As fases 3 e 4 guardam senhas e usam contas do dono. Nenhuma das sessões delas tem ferramenta de dados financeiros;
a auditoria de segurança completa (run-2) continua pendente e deve cobrir a Carreira.

## Fase 1: caçador (`backend/carreira/`, serviço `lastro-carreira`)
- **Fontes, sem login:** Gupy, Catho e Programathor (páginas de busca), LinkedIn (busca pública, sem conta),
  RemoteOK e Remotive (APIs públicas). Indeed e Glassdoor recusam acesso automatizado (403) e ficaram de fora. Termos de
  busca em `match.py`. Um ciclo a cada 6 h (`CARREIRA_INTERVAL`).
- **Regras** (`match.py`, determinísticas, sem modelo):
  - remoto: Brasil ou internacional que aceite quem mora no Brasil;
  - híbrido só em Londrina/Cambé, presencial só em Londrina, e nesses casos salário ≥ R$ 5.000 ou empresa grande;
  - cargos de IA, software, Python, dados e automação; acima de júnior fica de fora, pleno vira "talvez";
  - TI geral (suporte, infraestrutura, sistemas, QA) só passa de "talvez" com salário publicado acima do piso.
- **Aviso:** até 8 compatíveis e 4 "vale conferir" por mensagem, só entre 8 h e 21 h (horário de Brasília). Cada
  vaga é avisada uma vez (`status` nova → avisada).
- **Tabela:** `carreira_vagas` (migração 015). Título e descrição são texto de terceiros: dado, nunca instrução.

### Configuração do WhatsApp
`/etc/meu-patrimonio/carreira.env` (0640 root:patrimonio, criado à mão):

```
CARREIRA_EVOLUTION_URL=https://evolution.seu-dominio
CARREIRA_EVOLUTION_KEY=...
CARREIRA_EVOLUTION_INSTANCE=...
CARREIRA_WHATSAPP_TO=5543988273960
```

A URL precisa ser HTTPS (a chave da Evolution não pode trafegar aberta), exceto `http://127.0.0.1` quando a Evolution
roda neste servidor. Na instância de referência ela fica em `/opt/evolution` (Docker Compose, v2.3.7, Postgres e
Redis, porta 8081 só no loopback) e o arquivo usa o token da instância `lastro`, não a chave global. Sem o arquivo, as vagas ficam guardadas e
saem no primeiro aviso possível.

## Fase 2: alfaiate (`backend/carreira/alfaiate.py`, agente interno `alfaiate`)
- A cada ciclo, até 3 vagas compatíveis sem candidatura vão para o agente `alfaiate` no worker do mentor (operação
  `ephemeral`, sem ferramentas, prompt próprio sem as regras financeiras do Lastro).
- Entrada: o perfil do dono (`/var/lib/patrimonio/carreira/perfil.md`, 0600, fora do repositório: a única fonte
  sobre a pessoa) e o texto da vaga marcado como dado não confiável.
- Saída conferida antes de gravar em `carreira_candidaturas` (migração 016): aderência 0–100, resumo, até 5
  lacunas com dica de estudo, idioma, currículo em Markdown e carta curta. Resposta inválida não grava e a vaga
  volta no próximo ciclo. O aviso no WhatsApp mostra a aderência das vagas já adaptadas.

## Fase 5: conversa e treinador (`backend/carreira/conversa.py`, agente interno `treinador`)
- O serviço consulta a Evolution a cada 20 s (sem webhook, sem porta aberta) e só processa mensagens recebidas do
  número do dono (aceita a forma sem o 9, comum em números antigos). Mensagens de outros contatos são ignoradas.
- Comandos: `vagas`, `cv N`, `treinar N`, `parar`, `ajuda`. `N` é o número `#N` que aparece no aviso.
- Treino: uma entrevista ativa por vez (`carreira_treinos`), histórico inteiro a cada resposta do agente
  `treinador` (sem ferramentas; perfil + vaga como dado não confiável + lacunas). `parar` pede o fechamento com
  nota, pontos fortes, pontos a melhorar e o que estudar.
- O cursor de leitura (`carreira_estado`) começa no momento da primeira execução e avança antes do envio: nenhuma
  mensagem antiga vira comando e nenhuma é respondida duas vezes.

## Fase 4: carteiro (`backend/carreira/carteiro.py`, agente interno `carteiro`)
- Gmail por IMAP com senha de app (`CARREIRA_GMAIL_USER`, `CARREIRA_GMAIL_APP_PASSWORD` no `carreira.env`), INBOX
  em modo leitura e `BODY.PEEK`: nada é marcado como lido, movido ou apagado. A cada 15 min, das 8 h às 21 h.
- Filtro determinístico antes da IA: remetente de plataforma de vagas ou recrutamento, termo de processo seletivo no
  assunto, ou empresa com candidatura; notificações sociais, newsletters e segurança de conta ficam de fora.
  Na caixa real (7 dias): 41 de 110 passam (alertas e mensagens do LinkedIn, Indeed, plataforma de recrutamento).
- O agente `carteiro` (sem ferramentas; e-mail como dado não confiável) classifica: convite para teste, entrevista,
  recusa, proposta, confirmação, andamento, alerta de vagas ou irrelevante. O corpo não é guardado; fica a
  classificação em `carreira_emails`.
- Convite, recusa, proposta e andamento: aviso imediato no WhatsApp (com `treinar N` quando é entrevista de uma
  candidatura conhecida) e o status da candidatura avança. Alertas (Indeed, LinkedIn...) viram vagas do caçador.
- Primeira execução: últimos 7 dias; depois, só o que chegou desde o cursor (UID). Até 20 e-mails por ciclo.

## Fase 3: aplicador (`backend/mentor/aplicador.py`, `backend/carreira/candidatura.py`, agente interno `aplicador`)
- Seleção (serviço `lastro-carreira`, das 8 h às 21 h): candidaturas com currículo pronto e aderência ≥ 60, até 3 por
  ciclo, 10 tentativas por dia e 2 por vaga. Cada tentativa fica em `carreira_envios` (migração 017).
- O worker abre uma sessão do agente `aplicador` (até 70 passos, prazo de 15 min) cujas ÚNICAS ferramentas são as do
  navegador do aplicador: abrir, clicar, digitar, rolar, ler, anexar currículo e login. `tools_for` recusa juntar esse
  navegador com dados do dono.
- Navegador: o mesmo Chrome do worker (sandbox e AppArmor aprovados), perfil persistente em
  `/var/lib/mentor/carreira/chrome` (logins das plataformas ficam salvos), uma candidatura por vez. Envia formulários;
  redes privadas seguem bloqueadas pelo systemd do worker.
- Cofre: `/var/lib/mentor/carreira/cofre.json` (0600 mentor), `{"gupy": {"usuario", "senha", "dominios"}}`. O modelo
  nunca vê a senha: `aplicador_login` digita usuário e senha no campo, só se o site aberto é um dos `dominios` daquela
  credencial e o campo indicado é mesmo de senha.
- Currículo: o Markdown do Alfaiate vira PDF A4 na hora (`markdown_html` + impressão do Chrome) e é anexado.
- Respostas de formulário: `/var/lib/patrimonio/carreira/respostas.md` (0600, fora do repositório), junto com o perfil.
  Questionários de autodeclaração (perfil comportamental, fit cultural) o agente responde, coerente com o perfil
  (decisão do dono). Teste que mede habilidade (lógica, técnico, inglês, código, case, vídeo), campo obrigatório sem
  resposta conhecida, CAPTCHA, código de verificação ou cadastro novo: o agente para com `precisa_de_voce` e o dono
  recebe o aviso no WhatsApp com o link.

## Navegador do agente (página `/navegador` do Lastro)
- O dono vê e controla o Chrome do aplicador (mesmo perfil persistente): toque para clicar, campo para digitar, teclas,
  endereço, voltar e rolar. Serve para entrar nas contas das plataformas, inclusive "Entrar com Google", e resolver
  CAPTCHA; o que for logado ali fica salvo para as candidaturas.
- Rotas `/api/carreira/navegador` (atrás do login e do CSRF do app) repassam ao worker (operação `navegador`). O texto
  digitado pode ser senha: não vai para log nem volta na resposta. Uma sessão manual por vez; fecha após 10 min sem uso.
- O aplicador usa o Chrome completo (`/usr/bin/google-chrome`, perfil AppArmor `chrome` com userns) para o perfil ser o
  mesmo da sessão manual. Nas candidaturas, com a conta Google do dono aberta no perfil, Gmail, Drive, Fotos, Agenda
  e configurações da conta ficam bloqueados para o agente; só a tela de login com Google funciona.

## Atualizar perfil nas plataformas
- WhatsApp: `atualizar perfil gupy` (linkedin, catho, indeed, programathor, infojobs, vagas). O aplicador roda no modo
  `carreira_perfil`: entra na conta, deixa as seções iguais ao perfil base sem inventar e anexa o currículo geral
  (`/var/lib/patrimonio/carreira/curriculo.md`). O resultado chega no WhatsApp com o que mudou.

## Compatibilidade do navegador (melhorias inspiradas no OpenBot)
- **Cookies de sessão persistem entre reinícios.** O `launch_persistent_context` já guarda perfil, localStorage,
  IndexedDB e cookies com validade; os cookies de sessão (sem expiração, usados por muitos logins) o Chromium
  descarta num fechamento limpo. O aplicador os salva em `chrome/session_cookies.json` (0600, dentro do próprio
  perfil) ao fechar e recoloca ao abrir — o login feito pela página "Navegador do agente" continua valendo depois.
- **Lista de elementos versionada.** Cada leitura numera a lista (`lista`); `aplicador_clicar`/`aplicador_digitar`
  aceitam esse número e recusam a ação (`lista_velha`) se a página mudou desde então, evitando clicar no elemento
  errado. Equivale ao `snapshotId` do OpenBot.
- **Fora do escopo (não implementado):** flags anti-detecção de automação (esconder do site que o navegador é
  controlado). Servem para burlar a verificação de robô dos próprios sites; ficam de fora por decisão de segurança.
