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
  - cargos de IA, software, Python, dados e automação; acima de júnior fica de fora, pleno vira "talvez"; sem
    senioridade no título é compatível (júnior e habilidades só aumentam a prioridade). Até 2026-11-05 o código exigia
    "júnior" e habilidade no título para "compatível", mais estrito que a regra: quase tudo virava "talvez" e não
    entrava na fila. Ao iniciar, o serviço reaplica as regras a todas as vagas guardadas;
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

## Talent: recrutamento e estratégia (`backend/carreira/talent.py`, agente interno `talent`, migração 022)
Especialista em recrutamento que fica entre o Caçador e o Aplicador. Não é um chat: participa da fila e grava cada
decisão. Fluxo de cada vaga, numa volta da fila:

1. **Caçador** encontra e aplica as regras do dono (`match.py`): só "compatível" segue.
2. **Talent avalia** (`talent_avaliacao`, esforço baixo): extrai requisitos da vaga e liga cada um a um trecho
   literal do perfil. Trecho que não está no perfil derruba o requisito para "ausente". O código aplica os
   **filtros obrigatórios** (regras do dono e a mesma regra de senioridade lida na descrição — só a palavra
   escrita, júnior/pleno/sênior; "2+ anos" não vira "pleno", vai para o critério de experiência) e calcula a
   **rubrica**; o agente não dá nota. Elegível = todos os filtros ok e compatibilidade ≥ 60. Não elegível fica
   registrado com o motivo e não vai ao Alfaiate.
3. **Alfaiate** recebe a orientação do Talent (perfil de currículo, posicionamento, o que destacar e por quê,
   instruções específicas e requisitos que o perfil não comprova). A aderência da candidatura passa a ser a
   compatibilidade da rubrica.
4. **Talent revisa** cada versão do currículo antes do envio. Primeiro checagens sem IA: tecnologia ou número
   que não está no perfil nem no currículo-base, títulos de seção convencionais, tabela/imagem/HTML, tamanho e
   contato. Se o código já achou fato sem comprovação, a correção sai sem chamar o modelo. Senão, o agente revisa
   precisão factual, relevância, clareza, realizações, competências, estrutura e ATS. Resultado: aprovado,
   correções (devolvidas ao Alfaiate com instruções executáveis) ou bloqueado por inconsistência factual.
   Fato sem comprovação nunca é aprovado; problemas "menores" não seguram o envio, e da 2ª rodada em diante só
   problema bloqueante (factual) segura: no teste com dados reais (2026-11-05) o revisor achava um "importante"
   novo a cada rodada e chegou a bloquear um currículo que ele mesmo chamou de fiel ao perfil.
   **Limites:** até 3 revisões por vaga; a mesma afirmação sem comprovação repetida após a correção bloqueia na
   hora ("sem progresso"); 2 respostas inválidas do Talent ou do Alfaiate na mesma vaga bloqueiam. Bloqueada, a
   candidatura vira `falhou`, aparece em "Próximas ações" com o motivo e o dono recebe o aviso no WhatsApp.
5. **Aplicador** só recebe currículo cuja versão atual foi aprovada pelo Talent (`candidatura.pending`).
6. **Carteiro** registra as respostas; a cada 7 dias o Talent **analisa os resultados** sem IA.

### Rubrica (versão `2026-11-05.1`)
Filtros obrigatórios vêm antes e não são compensados por pontuação. A pontuação é compatibilidade segundo a rubrica,
não probabilidade de contratação.

| Critério | Peso | Como pontua |
|---|---|---|
| Requisitos técnicos obrigatórios | 40 | atendido 1, parcial 0,5, ausente 0; sem lista explícita: neutro (0,5) |
| Requisitos desejáveis | 10 | idem |
| Senioridade e experiência | 15 | até 1 ano ou não informado: total; 2 anos: 2/3; 3+: 1/3 |
| Formação e idiomas | 10 | cobertura das exigências; sem exigência: total |
| Local e modalidade | 10 | remoto: total; híbrido/presencial permitido: metade (depende de salário ou porte) |
| Tipo de contratação | 5 | CLT, estágio ou não informado: total; PJ: metade (o dono prefere CLT e aceita PJ) |
| Remuneração | 5 | publicada: total; não publicada: neutro |
| Área preferida | 5 | título com Python, IA, dados, automação etc.: total |

Cada avaliação guarda filtros, critérios com pontos e motivo, requisitos (atendidos, parciais, ausentes) com a
evidência, posicionamento, perfil de currículo (`backend`, `ia`, `junior`), destaques, orientações, justificativa,
versão da rubrica e data.

### Permissões (aplicadas em código)
- A sessão `talent` não tem ferramenta nenhuma (`Capabilities(data=False)`): sem navegador, sem dados financeiros,
  sem pesquisa, sem memória. Ela só recebe texto e devolve JSON, conferido por `talent.py`.
- As ferramentas do Talent são as funções de `talent.py` (consultar perfil, vagas, currículos e resultados;
  avaliar; revisar e pedir correção; registrar análises e propostas). Ele não lê o cofre (que pertence ao usuário
  `mentor`) nem `respostas.md`, não chama o Aplicador e não envia candidatura.
- Perfil e currículo-base não são alterados: o Talent registra **propostas** (`talent_propostas`), com a origem
  (trecho do perfil e contagem nas vagas). O dono aprova ou recusa uma vez na tela; aprovar só registra a decisão.

### Memória (`talent_avaliacoes`, `talent_revisoes`, `talent_analises`, `talent_propostas`)
Imutável (triggers impedem UPDATE/DELETE; proposta só muda na decisão do dono, uma vez). Responde: qual currículo
foi usado (`carreira_envios.curriculo_id`, sempre uma versão aprovada), por que a vaga foi compatível (filtros,
critérios, requisitos), por que um projeto foi destacado (`destaques`), que melhorias foram feitas (problemas da
revisão + `alteracoes` da versão corrigida), que vagas dão mais resultado (indicadores por plataforma, perfil de
currículo e versão da base) e qual a estratégia atual (rubrica, perfis em uso e última análise). Nada disso é fato
profissional: os fatos continuam só no perfil.

### Análise de resultados (semanal, sem IA)
Candidaturas, respostas, entrevistas, rejeições confirmadas, taxas, distribuição por plataforma e perfil de
currículo, requisitos recorrentes, motivos de descarte e rejeições conhecidas. Com menos de 10 envios (no total ou
no grupo), só observação descritiva; comparação entre grupos aparece como "associação, não causa". Os critérios do
dono nunca são alterados pela análise.

### Custo
Vaga que não passa nos filtros do Caçador não chega ao Talent. A avaliação usa esforço baixo e evita que o Alfaiate
(a chamada mais cara) escreva currículo para vaga pouco compatível. A revisão evita chamada quando o código já achou
o problema. Talent usa a conexão e o modelo escolhidos para ele em Configurações → Modelo de cada agente
(`store.ai_route`), como os demais agentes; sem escolha, vale a conexão padrão.

### Interface
Carreira → Talent (`/carreira/talent`): perfil (seções do perfil base, pontos fortes, lacunas, informações pendentes
e propostas), estratégia (critérios do dono, rubrica, perfis em uso, recomendações), avaliações, revisões e
resultados. Só mostra o que foi gravado; vazio aparece como vazio.

## Fila contínua (`hunter.fila_forever`)
- A busca roda a cada 6 h; a fila roda a cada 30 min (`CARREIRA_FILA_INTERVAL`), das 8 h às 21 h, sem depender da
  busca nem de conversa: currículo das compatíveis sem candidatura (Alfaiate, 3 por volta, maior pontuação primeiro) e
  candidaturas da fila (maior aderência primeiro). Antes, currículo e candidatura só rodavam dentro do ciclo de 6 h
  (2 a 3 voltas por dia) e só para vagas "compatíveis" pela regra estrita acima: por isso o Lastro só recomendava.
- Limites: `CARREIRA_LIMITE_DIA` (tentativas por dia, padrão 10) e `CARREIRA_POR_CICLO` (por volta, padrão 3), no
  `carreira.env`. Uma vaga bloqueada (`precisa_de_voce`) não para a fila: as outras seguem.
- Resumo diário no WhatsApp na primeira volta a partir das 20 h (`registro.resumo`); os mesmos números aparecem na
  visão geral (hoje, na fila, executando agora, aguardando você, próxima busca e próxima volta da fila).
- Operação manual com o mesmo código do serviço (como `patrimonio`, no grupo `lastro-sock`):
  `python -m carreira.hunter --fila` (uma volta agora) e `--perfil indeed` (atualiza o perfil e registra a execução).

### Estados (pedido do dono, reaproveitando o que existe)
| Estado | Onde |
|---|---|
| Elegível | vaga `compativel` sem candidatura (fila do Alfaiate) |
| Na fila | candidatura `curriculo`, aderência ≥ 60, menos de 2 tentativas |
| Preparando | execução `curriculo` em andamento |
| Preenchendo / enviando | execução `candidatura` em andamento (uma sessão do agente; não há sinal separado do clique final) |
| Enviada e confirmada | `candidatada` (só com `evidencia` da plataforma ou confirmação do dono/e-mail) |
| Resultado desconhecido | `incerta` (não é repetida; o dono confere) |
| Bloqueada por intervenção | `precisa_de_voce` ("não enviada" na tela devolve à fila depois de resolver) |
| Falha recuperável | envio `falhou` com tentativa restante (a candidatura continua `curriculo`) |
| Falha definitiva | `falhou` (2 tentativas) ou `encerrada` (não aplicável, duplicata) |

## Fase 3: aplicador (`backend/mentor/aplicador.py`, `backend/carreira/candidatura.py`, agente interno `aplicador`)
- Seleção (fila contínua, das 8 h às 21 h): candidaturas com currículo pronto e aderência ≥ 60, até 3 por
  volta, 10 tentativas por dia e 2 por vaga. Cada tentativa fica em `carreira_envios` (migração 017).
- Login: primeiro confere se a sessão salva já vale; senão senha do cofre; se a senha não anda e a página oferece
  "Entrar com Google", usa a conta Google já aberta no perfil (foi assim que a Gupy entrou em 2026-11-05; a senha
  parava na tela sem erro). Código por e-mail/SMS, CAPTCHA ou verificação do Google: `precisa_de_voce`.
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

### Falhas de ferramenta corrigidas em 2026-11-05 (por que as candidaturas não concluíam)
- `aplicador_ler` dava `TypeError` sempre (lambda que devolve None num `await`): em SPA como a Gupy o agente ficava
  com a lista de elementos da tela de carregamento e cada clique esperava 20 s por um elemento que não existia mais.
  Agora relê, a leitura espera a rede acalmar (até 3 s) e clique/digitação em elemento trocado respondem `lista_velha`.
- Radio/checkbox estilizados (input de 1 px, opacidade 0, dentro de `<label>`) eram descartados da lista: as perguntas
  Sim/Não da Gupy não apareciam. A visibilidade é medida pelo rótulo e cada radio traz `grupo` (o `name`).
- `aplicador_anexar_curriculo` aceita botão que abre o seletor de arquivos (Indeed "Substituir currículo").
- Worker fora do ar vinha como evento de erro (o `MentorClient` não lança) e virava `incerta`; agora não conta envio.
- `precisa_de_voce` não conta como tentativa (a vaga volta quando o dono resolve; antes esgotava as 2 tentativas).

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
  (`/var/lib/patrimonio/carreira/curriculo.md`). Não mexe em privacidade nem visibilidade do perfil. O resultado chega
  no WhatsApp com o que mudou e fica em `carreira_execucoes` (tipo `perfil`, data e resultado).

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

## Módulo Carreira na interface (migração 018)
- **Navegação:** seletor Finanças | Carreira no topo à esquerda (barra lateral; no celular, barra superior). Cada
  módulo tem a própria navegação; Computadores, Notificações e Configurações aparecem nos dois. Carreira vive em
  `/carreira/*`: visão geral, oportunidades (`/vagas`), candidaturas (Kanban e tabela), currículos, agente e
  navegador (`/navegador` redireciona). As telas recarregam a cada 10–60 s enquanto visíveis (sem streaming novo).
- **Quatro conceitos separados:** estado do envio (`carreira_candidaturas.status`: curriculo, precisa_de_voce,
  incerta, falhou, candidatada, encerrada, retirada); etapa informada pela empresa (`etapa`: em_analise, teste,
  entrevista, proposta, recusada); execuções dos agentes (`carreira_execucoes`); histórico imutável
  (`carreira_eventos`, triggers impedem UPDATE/DELETE). A migração reconstruiu o histórico do que já existia
  (marcado `reconstruido`).
- **Envio só com evidência:** o Aplicador devolve `evidencia` (texto de confirmação da plataforma). `enviada` sem
  evidência, agente que cai no meio ou resposta ilegível viram `incerta` (resultado desconhecido): não é repetida e
  aparece em "Próximas ações" para o dono confirmar ou negar. Só "worker nem atendeu" (socket ausente/recusado)
  conta como falha sem envio. Esgotadas as 2 tentativas, o status vira `falhou`. E-mail de confirmação do Carteiro
  promove `incerta` a `candidatada`.
- **Duplicatas:** `url_canonica` (sem rastreio; LinkedIn pelo id da vaga, o que junta busca e alerta de e-mail) e
  `chave` empresa|cargo|local normalizados (sem empresa, sem chave). Duplicata com candidatura não ganha currículo
  nem envio (evento `duplicata_bloqueada`). Vagas antigas recebem as chaves quando o serviço inicia.
- **Currículos:** `carreira_curriculos`, imutável. A base é o `curriculo.md` do dono (nova versão a cada mudança,
  gravada no ciclo); cada versão do Alfaiate guarda a base de origem e as `alteracoes` que ele diz ter feito; cada
  tentativa de envio guarda o currículo anexado. `/api/carreira/curriculos/{id}/documento` devolve o mesmo HTML A4
  que vira o PDF anexado (imprimir → PDF) ou o `.md`.
- **Execuções:** cada busca, currículo e candidatura grava início, fim, resultado e erro. Ao iniciar, o serviço marca
  como `interrompida` o que ficou "executando"; na tela, execução além do prazo do agente aparece como travada.
  O próximo ciclo fica em `carreira_estado.proximo_ciclo`.
- **Limites conhecidos:** requisitos e benefícios não são extraídos à parte (estão na descrição); tipo de contratação
  só quando o texto diz (CLT/PJ; estágio pelo título); o Carteiro não grava execuções (só eventos); as regras do
  caçador (`match.py`) seguem fixas no código — os filtros configuráveis são os da tela.

## Currículos: base estruturada, perfis e documentos (migração 020)
- **Fonte de verdade:** `carreira_base`, um JSON versionado e imutável (cada edição é uma versão nova). A primeira
  versão vem de `/var/lib/patrimonio/carreira/base.json` (0600, fora do repositório), importada pelo serviço ao
  iniciar quando a tabela está vazia. Cada fato (realização, projeto, competência, formação, curso, idioma) tem
  `status` e `fonte`: só `confirmado` entra num documento; `pendente` espera o dono; `inferido` nunca vira fato;
  `descartado` fica no histórico. Projeto corporativo só aparece como projeto com `divulgacao: autorizada`; até lá o
  conteúdo dele fica nas realizações da experiência, sem nome interno. Competência sem evidência fica `pendente`.
  `perguntas` guardam o que falta para quantificar resultados; a resposta é registrada e o dono edita a realização.
- **Perfis de apresentação** (`carreira/curriculo.py`, `PERFIS`): `backend` (Software Engineer / Backend), `ia`
  (AI Engineer / IA aplicada) e `junior` (Estágio / Júnior), com pesos por tag, ordem das categorias de competência e
  das seções (Júnior abre com a formação). Mesmo vocabulário do Talent (`perfil_curriculo`).
- **Por vaga:** o Talent avalia e indica o perfil → o Alfaiate (`prompts/alfaiate.md`) devolve só ids de fatos
  confirmados, o resumo e a carta → `alfaiate.parse_selecao` descarta id desconhecido e resumo/carta com tecnologia,
  número ou senioridade sem fonte (`curriculo.checar_resumo`) → `curriculo.montar` monta o documento (determinístico)
  → `documento.produzir` imprime, valida e, se a segunda página sobra quase vazia, tira o item menos relevante
  (projeto, realização, categoria, destaque; nunca diminui a fonte) → `documento.gravar` guarda PDF, DOCX, Markdown,
  seleção, análise, relatório e sha256 em `carreira_curriculos` (perfil, idioma, base_id). A revisão do Talent lê o
  `conteudo_md`; a correção pedida por ele é uma seleção nova. Sem `carreira_base`, vale o modo antigo (Markdown livre).
- **Layout** (`documento.CSS`): A4, uma coluna, fundo branco, texto grafite, Arial (no servidor, Liberation Sans:
  mesmas métricas, incorporada como TrueType com mapa Unicode), nome 22 pt, títulos 11,5 pt, corpo 10 pt com
  entrelinha 1,35, margens 13/15/12/15 mm, sem ícones, tabelas, colunas, imagens nem espaçamento entre letras. Palavra
  com hífen não quebra no hífen. O PDF sai do Chrome do worker (operação `pdf`: sem JavaScript, sem rede, PDF marcado)
  e ganha autor/assunto pelo pypdf. O DOCX é OOXML mínimo (biblioteca padrão) com estilos Título, Subtítulo,
  Cabeçalho 1/2 e Lista, data fixa no zip (mesmo documento, mesmo arquivo).
- **Validação de cada versão** (`documento.validar_pdf`/`validar_docx`): abre; nome, contatos e seções; todo trecho
  esperado no texto extraído (pypdf) e no DOCX; ordem de leitura; sem caractere corrompido nem campo de modelo;
  fontes incorporadas, sem Type3 e com ToUnicode; links mailto/LinkedIn/GitHub clicáveis; título e autor; título de
  seção isolado no fim da página; no máximo 2 páginas; e inspeção visual (pdftoppm em cinza): nada na faixa de 8 mm
  da borda, nenhuma página em branco e ocupação de cada página. Fato não confirmado ou tradução faltando reprova.
  Versão reprovada não é gravada. Passar na extração não garante compatibilidade com todo ATS.
- **Envio:** o Aplicador recebe o PDF/DOCX exatos da versão (`aplicacao.pdf_b64/docx_b64`) e anexa esse arquivo
  (`formato` docx só quando o site exige Word). O worker devolve o que foi de fato anexado e o envio grava em
  `carreira_envios.anexo` (`pdf`, `docx`, ou `plataforma: …` quando a plataforma usou o próprio currículo, como na
  candidatura fácil). `curriculo_id` do envio aponta para a versão imutável: nova versão nunca substitui a enviada.
  Candidatura que estava na fila com currículo do modo antigo (sem PDF) é refeita pela base antes de ir.
- **Liberação:** com a base estruturada, o Aplicador só envia depois que o dono clica em "Liberar envio" na tela
  Currículos (`carreira_estado.curriculo_liberado`), depois de conferir os três PDFs. Até lá o Alfaiate e o Talent
  seguem preparando e revisando.
- **Interface** (`/carreira/curriculos`): perfis com a página 1 do PDF exato, validação e downloads; liberação; versões
  por vaga com perfil e onde foram enviadas. `/carreira/curriculos/base`: o que espera validação (perguntas, fatos
  pendentes/inferidos, projetos corporativos), confirmar/pendente/descartar/editar cada fato e o histórico de versões.
  `/carreira/curriculos/:id`: páginas do PDF (PNG gerado do PDF guardado; o app proíbe frames), relatório de
  validação, escolhas do Alfaiate, lacunas, envios e comparação com qualquer outra versão.
- **Rotas:** `GET /api/carreira/base`, `POST /api/carreira/base/itens/{id}`, `POST /api/carreira/base/perguntas/{id}`,
  `POST /api/carreira/base/gerar`, `POST /api/carreira/base/liberar`, `GET /api/carreira/curriculos[/{id}]`,
  `GET /api/carreira/curriculos/{id}/documento?formato=pdf|docx|html|md` e `/pagina/{n}.png` (`app/curriculos_web.py`).
