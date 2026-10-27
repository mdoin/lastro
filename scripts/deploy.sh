#!/usr/bin/env bash
# Implanta o Lastro neste servidor. Rode com sudo, a partir de qualquer pasta:
#   sudo scripts/deploy.sh
# O frontend precisa estar compilado antes (frontend/dist), com o usuário normal:
#   (cd frontend && npm ci && npm run build)
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
DEST=/opt/meu-patrimonio
UNITS=(patrimonio-agent-api.service lastro-mentor.service lastro-web.service)

[ "$(id -u)" -eq 0 ] || { echo "Rode com sudo." >&2; exit 1; }

# Usuários e grupo do socket (idempotente).
for u in patrimonio mentor; do
  id "$u" >/dev/null 2>&1 || useradd --system --create-home --home-dir "/var/lib/$u" --shell /usr/sbin/nologin "$u"
done
chmod 0750 /var/lib/patrimonio /var/lib/mentor
groupadd --system -f lastro-sock

# Código: cópia limpa só do que roda (lista explícita), preservando o venv. Segredos e dados nunca vão junto,
# mesmo que alguém deixe um .env.local ou um .db esquecido dentro dessas pastas.
[ -f "$SRC/frontend/dist/index.html" ] || { echo "Compile o frontend antes (frontend/dist)." >&2; exit 1; }
SHIP=(backend deploy pyproject.toml uv.lock README.md frontend/dist)
install -d -m 0755 "$DEST"
find "$DEST" -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +
tar -C "$SRC" --exclude=__pycache__ --exclude='.env*' --exclude='*.db' --exclude='*.db-*' --exclude='*.sqlite*' \
    --exclude='*.ofx' --exclude='*.csv' --exclude='*.xlsx' --exclude='*.pdf' --exclude='*.pem' --exclude='*.key' \
    -cf - "${SHIP[@]}" | tar -xf - -C "$DEST" --no-same-owner
cd "$DEST"
UV_CACHE_DIR=/var/cache/uv-meu-patrimonio UV_PYTHON=/usr/bin/python3.12 /usr/local/bin/uv sync --frozen --no-dev --quiet
chown -R root:root "$DEST"
chmod -R go-w "$DEST"

# Segredos (criados à mão uma vez; ver docs/RUNBOOK.md): confere dono e modo a cada implantação.
install -d -m 0755 -o root -g root /etc/meu-patrimonio
[ -f /etc/meu-patrimonio/agent-api.env ] && chown root:patrimonio /etc/meu-patrimonio/agent-api.env \
  && chmod 0640 /etc/meu-patrimonio/agent-api.env
[ -f /etc/meu-patrimonio/mentor-token ] && chown root:mentor /etc/meu-patrimonio/mentor-token \
  && chmod 0640 /etc/meu-patrimonio/mentor-token

# Banco: aplica migrações como o dono do banco.
sudo -u patrimonio env LASTRO_DB=/var/lib/patrimonio/lastro.db sh -c \
  "cd $DEST/backend && $DEST/.venv/bin/python -m app.admin migrate"

# Perfil AppArmor do Chrome do navegador de pesquisa (aprovado pelo dono em 2026-10-26).
if [ -d /sys/kernel/security/apparmor ]; then
  install -m 0644 "$DEST/deploy/apparmor/lastro-chrome" /etc/apparmor.d/lastro-chrome
  apparmor_parser -r /etc/apparmor.d/lastro-chrome
fi

# Comando de administração e unidades systemd.
install -m 0755 "$DEST/deploy/lastro-admin" /usr/local/bin/lastro-admin
for unit in "${UNITS[@]}"; do install -m 0644 "$DEST/deploy/systemd/$unit" "/etc/systemd/system/$unit"; done
systemctl daemon-reload
for unit in "${UNITS[@]}"; do systemctl enable --quiet "$unit"; systemctl restart "$unit"; done
sleep 3
for unit in "${UNITS[@]}"; do printf '%-32s %s\n' "$unit" "$(systemctl is-active "$unit")"; done
