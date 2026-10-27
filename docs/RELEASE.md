# Preparação de release e publicação

Publicar o repositório ou uma imagem é decisão da autora. Este checklist precisa estar todo marcado antes.

## Bloqueadores (resolver antes de tornar público)
- [x] Licença escolhida e aplicada: AGPL-3.0-or-later, DCO, política de marca ([LICENSING.md](LICENSING.md)).
- [ ] `LASTRO_SOURCE_URL` padrão (`backend/app/web.py`) aponta para o repositório público definitivo.
- [ ] Decisão sobre o histórico Git ([OPEN_SOURCE_AUDIT.md](OPEN_SOURCE_AUDIT.md) §8): o histórico contém o e-mail
      pessoal da autora em um commit e o domínio/IP da instância pessoal. Recomendado: publicar um repositório novo a
      partir de um commit limpo, mantendo o histórico atual privado.
- [ ] Gitleaks sem achados no histórico que será publicado (job `secrets` do CI).
- [ ] Nenhuma credencial exposta: se algo aparecer, revogar/rotacionar **antes** de publicar.

## Verificações técnicas
- [ ] CI verde (backend, frontend, instalação limpa, segredos, dependências).
- [ ] `pip-audit` e `npm audit --omit=dev` sem vulnerabilidades conhecidas abertas (ou justificadas).
- [ ] Imagens base fixadas por digest no `Dockerfile` (`python`, `node`, `uv`) e no `compose.yaml` (`caddy`).
- [ ] Teste manual com cada provedor suportado que você usa: conectar, testar, conversar, trocar de provedor,
      desconectar.
- [ ] Instalação seguindo só o [INSTALL.md](INSTALL.md), numa máquina limpa, por alguém que não desenvolveu o projeto.
- [ ] Atualização a partir da versão anterior com dados ([UPGRADE.md](UPGRADE.md)) e restauração de backup.
- [ ] Logs revisados: nenhum conteúdo de conversa, chave, cookie ou código de login.

## Revisão de conteúdo
- [ ] `tests/fixtures_synthetic/` e capturas em `docs/screenshots/` só com dados fictícios.
- [ ] `docs/PENDING.md` e `docs/DECISIONS.md` sem detalhes operacionais da instância pessoal.
- [x] Marca e mascotes com política de uso publicada ([TRADEMARKS.md](../TRADEMARKS.md)).
- [ ] `CHANGELOG.md` com a versão e notas de atualização.

## Não fazer sem autorização explícita
Push, tornar o repositório público, publicar imagens, criar tags de release, deploy em produção, reescrever histórico.
