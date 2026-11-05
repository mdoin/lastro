#!/bin/sh
# Sobe a área de trabalho do agente. Cada peça volta sozinha se cair (o dono pode fechar o Chrome pela tela).
set -u
mkdir -p "$HOME/Downloads" "$HOME/.config"
Xvfb :0 -screen 0 1366x800x24 -nolisten tcp &
sleep 1
openbox &
(while :; do tint2; sleep 1; done) &
(while :; do x11vnc -display :0 -localhost -rfbport 5900 -forever -shared -nopw -quiet -noxdamage; sleep 1; done) &
(while :; do navegador; sleep 2; done) &
wait
