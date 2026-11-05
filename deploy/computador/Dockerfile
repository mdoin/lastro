# SPDX-License-Identifier: AGPL-3.0-or-later
# Computador de um agente (docs/COMPUTADORES.md): tela virtual, barra de tarefas, Chrome, terminal e arquivos.
# Sem rede própria: só alcança o gateway de saída (proxy HTTP). VNC e DevTools escutam só no loopback do container;
# o controlador do host chega neles por `docker exec socat`.
FROM debian:trixie-slim

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      xvfb x11vnc openbox tint2 xterm pcmanfm chromium chromium-l10n socat ca-certificates curl wget git python3 \
      fonts-noto-core fonts-noto-color-emoji locales tzdata procps less nano \
    && sed -i 's/^# *pt_BR.UTF-8/pt_BR.UTF-8/' /etc/locale.gen && locale-gen \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash agente

COPY tint2rc /etc/xdg/tint2/tint2rc
COPY iniciar.sh /usr/local/bin/iniciar
COPY navegador.sh /usr/local/bin/navegador

ENV LANG=pt_BR.UTF-8 LC_ALL=pt_BR.UTF-8 TZ=America/Sao_Paulo DISPLAY=:0 \
    http_proxy=http://saida:8888 https_proxy=http://saida:8888 \
    HTTP_PROXY=http://saida:8888 HTTPS_PROXY=http://saida:8888 no_proxy=localhost,127.0.0.1
USER agente
WORKDIR /home/agente
CMD ["/usr/local/bin/iniciar"]
