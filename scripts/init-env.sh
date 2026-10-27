#!/usr/bin/env sh
# Cria o .env a partir do .env.example, com segredos aleatórios. Não sobrescreve um .env existente.
set -eu
cd "$(dirname "$0")/.."

if [ -e .env ]; then
  echo ".env já existe; nada foi alterado." >&2
  exit 0
fi

token=$(od -An -N48 -tx1 /dev/urandom | tr -d ' \n')
umask 077
sed "s/^LASTRO_AGENT_API_TOKEN=.*/LASTRO_AGENT_API_TOKEN=${token}/" .env.example > .env
echo ".env criado (permissão 0600). Revise LASTRO_BIND, LASTRO_DOMAIN e LASTRO_TZ antes de subir."
