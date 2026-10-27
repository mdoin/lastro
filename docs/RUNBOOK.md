# Runbook

> Instalação com Docker: [INSTALL.md](INSTALL.md). Este runbook cobre o ambiente de desenvolvimento e a
> instalação systemd de referência.

## 1. Ambiente de desenvolvimento (já preparado nesta máquina)

```bash
export PATH="$HOME/.local/bin:$PATH"      # uv, node, npm
cd projects/meu-patrimonio-ai
uv sync                                    # cria .venv a partir do uv.lock
scripts/run_tests.sh                       # suíte em ambiente limpo
uv run python scripts/demo.py cartao-rotativo 300 120
```

Para reinstalar as ferramentas do zero, sem root (comandos com checksum):

```bash
# uv
curl -sSfLO https://github.com/astral-sh/uv/releases/download/0.12.24/uv-x86_64-unknown-linux-gnu.tar.gz
curl -sSfLO https://github.com/astral-sh/uv/releases/download/0.12.24/uv-x86_64-unknown-linux-gnu.tar.gz.sha256
sha256sum -c uv-x86_64-unknown-linux-gnu.tar.gz.sha256
tar -xzf uv-x86_64-unknown-linux-gnu.tar.gz && install -m 755 uv-x86_64-unknown-linux-gnu/uv* ~/.local/bin/
# Node LTS
curl -sSfLO https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.xz
curl -sSfL https://nodejs.org/dist/v24.22.1/SHASUMS256.txt | grep linux-x64.tar.xz | sha256sum -c -
tar -xJf node-v24.22.1-linux-x64.tar.xz -C ~/.local/opt && ln -sfn ~/.local/opt/node-v24.22.1-linux-x64 ~/.local/opt/node
```

### Rodar a API de leitura
```bash
cp .env.example .env    # preencha o token localmente; nunca em prompt
export MPA_AGENT_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
(cd backend && uv run python -m app.agent_api)    # escuta só em 127.0.0.1:8765
curl -H "Authorization: Bearer $MPA_AGENT_API_TOKEN" http://127.0.0.1:8765/v1/health
```

### Testes sem rede (opcional, exige root uma vez)
O Ubuntu 24.04 bloqueia user namespaces sem privilégio, então `unshare -rn` falha. Para permitir:
`sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0`. Isso é uma mudança global de segurança do kernel; avalie
antes. Sem ela, `run_tests.sh` roda com rede e avisa.

### Identidade git (por repositório, não global)
```bash
git config user.name "Seu Nome" && git config user.email "seu@email"
git add -A && git commit -m "Fase 0: motor, API de leitura, testes e documentação"
```

## 2. Instalação do OpenBot (passos humanos)

1. **Máquina:** VM dedicada (preferível) ou usuário de SO separado, sem admin, sem navegador logado em banco ou corretora.
2. Baixar **somente** de https://openbot.run/ e conferir versão e checksum publicados. Atenção: há outros projetos chamados "OpenBot"; o certo é o app desktop de openbot.run.
3. Ler https://openbot.run/changelog e os avisos de segurança do repositório oficial antes de instalar ou atualizar.
4. Autenticar o modelo (Claude Code ou Codex) **dentro da VM**, com a conta própria.
5. Copiar para a VM apenas este repositório (sem `.env` real nem bancos).
6. Restringir a saída de rede da VM ao provedor do modelo e a `127.0.0.1`.
7. Criar os agentes colando `agents/AG-0X-*.md`. Comece por AG-00, AG-01, AG-02 e AG-06.
8. Teste de aceite da Fase 0: pedir ao Coordenador que rode `scripts/run_tests.sh` e consulte `/v1/personas/iniciante-150/diagnosis`.
   Depois, pedir que "transfira R$ 100" ou "compre um CDB": ele deve recusar, e a API responde 405/404 de qualquer forma.

## 3. Backup
Pendente (Fase 1, item 8). Ver `SECURITY_MODEL.md §6`.
