# Política de segurança

## Como reportar uma vulnerabilidade
**Não abra issue pública.** Use o recurso "Report a vulnerability" (GitHub Security Advisories) deste repositório.
Inclua: versão, passos para reproduzir, impacto e, se possível, uma sugestão de correção. Respondemos em até 7 dias e
combinamos a divulgação depois da correção.

## Escopo
Interessa especialmente:
- vazamento de credenciais de IA para o navegador, logs, banco ou outro serviço;
- agente executando ferramenta fora da concessão do papel, ou alcançando arquivos, comandos ou rede não previstos;
- acesso ao banco a partir do worker, ou às credenciais a partir do web app;
- contorno da autenticação do Lastro, do token de instalação, do limitador de login ou da proteção CSRF;
- injeção de instruções por conteúdo de páginas, mensagens ou dados que leve a ações indevidas;
- qualquer caminho que execute operação financeira.

Fora do escopo: instâncias mal configuradas contra a documentação (por exemplo, publicadas sem HTTPS com
`LASTRO_COOKIE_SECURE=0`), ataques que exigem root no servidor e vulnerabilidades dos próprios provedores de IA.

## Versões suportadas
Só a versão mais recente recebe correções de segurança.

## Modelo de ameaças
Ver [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) e [docs/PROVIDERS.md](docs/PROVIDERS.md#segurança).
