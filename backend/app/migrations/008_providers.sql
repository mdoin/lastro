-- Lastro — v8: provedor de IA e modelo por agente; sessão nativa marcada com a conexão que a criou;
-- configurações da instalação (assistente inicial). Compatível: só acrescenta tabelas e uma coluna.
-- As conexões e seus segredos ficam no worker (providers.json), nunca neste banco.

CREATE TABLE agent_models (
    agent_id       TEXT PRIMARY KEY,
    connection_id  TEXT NOT NULL,
    model          TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL
);

-- `claude_session_id` passa a guardar o id da sessão nativa de qualquer provedor; esta coluna diz de qual conexão.
-- NULL = sessão criada antes da v8 (Claude Code implícito).
ALTER TABLE conversations ADD COLUMN session_connection TEXT;

CREATE TABLE app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Instalações que já tinham senha não passam pelo assistente inicial.
INSERT INTO app_settings (key, value, updated_at)
SELECT 'onboarding_done', '1', strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') WHERE EXISTS (SELECT 1 FROM credentials);
