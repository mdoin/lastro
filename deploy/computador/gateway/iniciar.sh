#!/bin/sh
# Firewall de saída antes do proxy subir: respostas aos computadores passam (conexões já estabelecidas);
# conexão NOVA só para endereço público. Sem as regras, o proxy não sobe (falha fechado).
set -eu
for t in iptables ip6tables; do
  $t -P OUTPUT ACCEPT
  $t -F OUTPUT
  $t -A OUTPUT -o lo -j ACCEPT
  $t -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
done
for net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 \
           192.168.0.0/16 198.18.0.0/15 224.0.0.0/3; do
  iptables -A OUTPUT -d "$net" -j REJECT
done
# DNS do Docker (127.0.0.11) é loopback e já passou acima. IPv6: só endereço global.
ip6tables -A OUTPUT ! -d 2000::/3 -j REJECT
# Só web (80/443): nada de e-mail, SSH ou varredura saindo com o nosso IP (que será o IP de casa do dono).
for t in iptables ip6tables; do
  $t -A OUTPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
  $t -A OUTPUT -j REJECT
done
exec tinyproxy -d -c /etc/tinyproxy/tinyproxy.conf
