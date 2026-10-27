#!/usr/bin/env bash
# Roda a suíte com ambiente limpo (sem variáveis/credenciais herdadas) e, quando
# o kernel permite, sem acesso à rede — prova de que nada depende de saída externa.
set -euo pipefail
cd "$(dirname "$0")/.."
UV="${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
"$UV" sync --frozen --quiet
RUN=(env -i HOME="$PWD/.venv/.home" PATH="$PWD/.venv/bin:/usr/bin:/bin" "$PWD/.venv/bin/python" -m pytest "$@")
mkdir -p .venv/.home
if unshare -rn true 2>/dev/null; then
  echo "» rodando testes SEM rede (unshare -rn)"
  exec unshare -rn "${RUN[@]}"
fi
echo "» unshare indisponível: rodando testes com rede"
exec "${RUN[@]}"
