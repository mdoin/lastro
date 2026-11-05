# SPDX-License-Identifier: AGPL-3.0-or-later
# Gateway de saída dos computadores dos agentes: proxy HTTP (tinyproxy) que só alcança a internet pública.
# Redes privadas, loopback do host, CGNAT e metadados da nuvem ficam bloqueados por iptables (vale para DNS rebinding
# e IP literal, porque o filtro é no pacote, não no nome).
FROM alpine:3.22
RUN apk add --no-cache tinyproxy iptables ip6tables curl
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY iniciar.sh /usr/local/bin/iniciar
CMD ["/usr/local/bin/iniciar"]
