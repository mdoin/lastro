# Carreira

Busca vagas que combinam com o perfil do dono, avisa no WhatsApp e, nas próximas fases, personaliza o currículo,
faz a candidatura, acompanha o processo e treina para a entrevista.

## Fases
| Fase | O que faz | Estado |
|---|---|---|
| 1. Caçador | Busca vagas públicas, avalia pelas regras e manda um resumo no WhatsApp | feito |
| 2. Alfaiate | Currículo por vaga a partir do currículo base, sem inventar experiência | feito |
| 3. Aplicador | Candidatura pelo navegador próprio do agente, com logins guardados em cofre | planejado |
| 4. Carteiro | Lê o e-mail de candidaturas, detecta avanços e testes e avisa | planejado |
| 5. Treinador | Entrevista simulada sobre a vaga que avançou | planejado |

As fases 3 e 4 guardam senhas e navegam em sites quaisquer com login: rodam num serviço e usuário próprios, sem
acesso aos dados financeiros, e só vão ao ar depois de uma nova auditoria de segurança.

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
