# Lastro — imagem única para os quatro serviços (web, mentor, agent-api, collector).
# Cada serviço roda com o próprio usuário sem privilégios (ver compose.yaml). Imagens base com versão explícita;
# numa release, fixe também os digests (docs/RELEASE.md).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:24-bookworm-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.24

FROM ${UV_IMAGE} AS uv

FROM ${NODE_IMAGE} AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime
# Executáveis oficiais opcionais. Não vêm por padrão: o Claude Code tem termos próprios da Anthropic e imagens
# publicadas não devem redistribuí-lo; o Codex é instalado do npm oficial na versão indicada.
ARG WITH_CLAUDE_CODE=0
ARG WITH_CODEX=0
ARG CODEX_VERSION=0.162.1
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/lastro/.venv \
    UV_LINK_MODE=copy \
    PATH=/opt/lastro/.venv/bin:$PATH \
    LASTRO_STATIC_DIR=/opt/lastro/frontend/dist \
    LASTRO_DB=/data/lastro.db \
    LASTRO_MENTOR_SOCKET=/run/lastro-mentor/mentor.sock

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /opt/lastro
COPY pyproject.toml uv.lock ./
RUN extras=""; \
    if [ "$WITH_CLAUDE_CODE" = "1" ]; then extras="--extra claude-code"; fi; \
    uv sync --frozen --no-dev --no-install-project $extras \
    && rm -rf /root/.cache
RUN if [ "$WITH_CODEX" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
      && npm install -g --no-audit --no-fund "@openai/codex@${CODEX_VERSION}" \
      && apt-get purge -y npm && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* /root/.npm; \
    fi

# Usuários fixos (os uids entram na conferência SO_PEERCRED do socket do mentor):
#   10001 lastro  — web, API de leitura e coletor (donos do banco)
#   10002 mentor  — worker dos agentes (dono das credenciais de IA; não vê o banco)
#   10010 lastro-sock — grupo do socket web ↔ mentor
RUN groupadd --gid 10010 lastro-sock \
    && groupadd --gid 10001 lastro && useradd --uid 10001 --gid 10001 --groups 10010 --no-create-home \
       --shell /usr/sbin/nologin lastro \
    && groupadd --gid 10002 mentor && useradd --uid 10002 --gid 10002 --groups 10010 --create-home \
       --home-dir /home/mentor --shell /usr/sbin/nologin mentor \
    && install -d -o 10001 -g 10001 -m 0700 /data \
    && install -d -o 10002 -g 10010 -m 0750 /run/lastro-mentor \
    && chmod 0700 /home/mentor

COPY backend/ /opt/lastro/backend/
COPY --from=frontend /src/frontend/dist/ /opt/lastro/frontend/dist/
RUN python -m compileall -q /opt/lastro/backend

WORKDIR /opt/lastro/backend
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "app.web"]
