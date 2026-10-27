# Como contribuir

Obrigado pelo interesse no Lastro. Antes de abrir uma contribuição, leia o [Código de Conduta](CODE_OF_CONDUCT.md).

## Princípios que não mudam
1. **Nenhuma operação financeira.** Não aceitamos código que ordene, transfira, pague, resgate ou se conecte com
   credenciais a bancos e corretoras. Os testes em `tests/security/` garantem isso.
2. **Número vem do motor.** Toda conta com dinheiro, taxa ou prazo passa por `backend/financial_engine` (Decimal);
   a IA interpreta e explica.
3. **Independência de provedor.** Núcleo, memória e agentes não importam SDK de provedor; integração nova vai em
   `backend/providers/` com capacidades declaradas e só por fluxos de autenticação documentados oficialmente.
4. **Dados da pessoa ficam na instalação.** Sem telemetria, sem chamadas a servidores do projeto.
5. **Sem dados reais.** Testes, exemplos e capturas usam só dados fictícios.

## Fluxo
1. Abra uma issue descrevendo o problema ou a proposta (para mudanças grandes, antes de codar).
2. Crie um branch, faça commits pequenos no padrão [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`…), em português.
3. Rode localmente:
   ```bash
   uv run pytest -q
   (cd frontend && npm run typecheck && npm test)
   ```
4. Abra o pull request explicando o quê, por quê e como testou. Mudanças de interface com captura de tela.

## Padrões
- Python 3.12, async no web app, sem dependências novas sem justificativa (licença, manutenção, tamanho).
- Dependências respeitam a janela de 2 semanas (`exclude-newer` no `pyproject.toml`, versões fixas no `package.json`).
- Mensagens para a pessoa em português do Brasil, claras e sem jargão.
- Teste para todo comportamento novo; testes de segurança para qualquer coisa que toque credenciais, ferramentas dos
  agentes ou dados financeiros.

## Licença das contribuições
A licença do projeto ainda está em definição ([docs/LICENSING.md](docs/LICENSING.md)). Contribuições externas só
serão aceitas depois dela, com `Signed-off-by` (DCO) em cada commit.
