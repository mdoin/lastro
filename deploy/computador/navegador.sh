#!/bin/sh
# Chrome do agente. O container é a caixa de areia (sem rede própria, sem capabilities), por isso --no-sandbox.
# --test-type só esconde a faixa de aviso do --no-sandbox.
# WebRTC só pelo proxy: sem UDP direto, o IP visto pelos sites é sempre o da saída.
exec chromium --no-sandbox --test-type --no-first-run --no-default-browser-check --disable-dev-shm-usage \
  --user-data-dir="$HOME/.config/chromium" --lang=pt-BR --start-maximized \
  --proxy-server=http://saida:8888 \
  --force-webrtc-ip-handling-policy=disable_non_proxied_udp --webrtc-ip-handling-policy=disable_non_proxied_udp \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 "$@"
