# Computadores dos agentes

**Cada agente da equipe (Bento, Lia, Caio, Vera, Rui, Nina, Téo, Mila e Cora) tem o próprio computador: uma área de
trabalho Linux com Chrome, terminal e arquivos.** O agente usa esse computador nas sessões de pesquisa
(docs/PESQUISA.md), e o dono acompanha ao vivo na página **Computadores**, onde pode assumir o controle.

Código: `deploy/computador/` (imagens e controlador), `backend/mentor/computador.py` (aba e terminal do agente),
`backend/app/computador_web.py` (rotas e tela), `frontend/src/pages/Computadores.tsx`.

## Peças
| Peça | O que é |
|---|---|
| `lastro-computador:1` | Debian com Xvfb, openbox, tint2 (barra com Chrome, arquivos e terminal), x11vnc e Chromium. Usuário `agente`, pasta pessoal num volume próprio (`lastro-pc-<agente>`), guardada entre pesquisas |
| `lastro-saida:1` (container `lastro-saida`) | Gateway de saída: proxy HTTP (tinyproxy) com firewall que só deixa abrir conexão para endereço público |
| `lastro-computadores.service` | Controlador (root, só biblioteca padrão). Liga e desliga containers, roda comandos e faz a ponte da tela e do DevTools. Socket `/run/lastro-computadores/controle.sock` 0660 root:lastro-sock |

## Isolamento
- **Rede:** cada computador fica numa rede Docker `--internal` só sua (`lastro-pc-<agente>`), onde só existe ele e o
  gateway. Não há rota para a internet nem para outro computador. O Chrome e o terminal (`http_proxy`) saem pelo
  gateway, que recusa redes privadas, loopback, CGNAT, link-local (metadados da nuvem) e multicast por iptables. Como
  a regra vale para o pacote, também cobre IP literal e DNS rebinding. WebRTC só pelo proxy
  (`disable_non_proxied_udp`): o IP que os sites veem é sempre o da saída.
- **Container:** `--cap-drop ALL`, `no-new-privileges`, 1,2 GB de memória, 512 processos, sem montagem do host. O
  Chrome roda com `--no-sandbox` porque o container é a caixa de areia.
- **Acesso:** VNC (5900) e DevTools (9222) escutam só no loopback do container. Só o controlador chega neles
  (`docker exec … socat`), e só a web e o worker do mentor falam com o controlador.
- **Dados:** o computador só é usado pela sessão de pesquisa, que não tem dados do dono (`tools_for`). Nada da
  pessoa vai para lá. O que o agente baixa fica no volume dele.
- **Recursos:** até 3 ligados ao mesmo tempo (`LASTRO_PC_MAX`). Um computador parado há 15 min (`LASTRO_PC_IDLE`) e
  sem ninguém olhando a tela é desligado; ao precisar de vaga, desliga o ocioso mais antigo.

## Ferramentas do agente (sessão de pesquisa)
- `navegador_*`: as mesmas de antes, mas numa aba nova do Chrome visível do computador (fechada ao fim da pesquisa).
- `computador_terminal`: um comando bash como `agente` (prazo de até 300 s, saída de até 20 mil caracteres).
- Quando o dono assumiu o controle, as ações do agente voltam `aguardando` até ele devolver.

## Interface
`/computadores` lista os computadores (desligado, ligado, usando agora). Ao abrir um deles:
- a tela liga o computador e mostra ao vivo, só para ver;
- **Assumir** libera mouse e teclado para o dono, e o agente espera. **Devolver** (ou fechar) devolve;
- o rodapé mostra o **IP de saída**.
A tela vem por WebSocket (`/api/computadores/<agente>/tela`, com login conferido e origem igual ao host) e usa o
cliente noVNC (`@novnc/novnc`, MPL-2.0).

## IP residencial: saída pela casa do dono (Raspberry Pi)
Hoje o gateway sai pelo IP da VPS, que é de datacenter, e alguns sites bloqueiam ou mostram CAPTCHA. O próximo
passo é sair pela internet de casa, com um Raspberry Pi servindo de nó de saída do Tailscale:
1. No Pi (Raspberry Pi OS Lite, de preferência no cabo): `curl -fsSL https://tailscale.com/install.sh | sh` e depois
   `sudo tailscale up --advertise-exit-node`.
2. No painel do Tailscale: aprovar o Pi como exit node e, nas ACLs, liberar para a VPS só `autogroup:internet`. Assim a
   VPS sai pela internet de casa, mas não enxerga a rede local (roteador, outros aparelhos).
3. O gateway entra na tailnet e passa a usar o Pi como saída. Se o Pi cair, o gateway fica sem saída em vez de voltar
   para o IP da VPS.
Fuso e idioma continuam `America/Sao_Paulo` e `pt-BR`, coerentes com um IP de casa no Brasil.

## Operação
- Imagens: `scripts/deploy.sh` reconstrói as duas. Um computador ligado continua na imagem antiga até desligar.
  Para trocar o gateway: `docker rm -f lastro-saida` (o controlador sobe de novo no próximo uso).
- Apagar o que um agente guardou: desligar e `docker volume rm lastro-pc-<agente>`.
- Testes: `tests/unit/test_computador.py` (controlador com Docker simulado).
