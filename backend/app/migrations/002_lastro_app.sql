-- Lastro — esquema v2: autenticação, snapshots, chat, rotinas.
-- Mesmas convenções da v1: UUID em TEXT, datas ISO 8601, valores Decimal em TEXT.

-- Dono único do app (uso pessoal).
INSERT INTO users (id, created_at, preferences) VALUES ('owner', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), '{}');

CREATE TABLE credentials (
    user_id        TEXT PRIMARY KEY REFERENCES users(id),
    password_hash  TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE auth_sessions (
    token_hash    TEXT PRIMARY KEY,      -- sha256 do token; o token em si nunca é guardado
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);

CREATE TABLE login_attempts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    success  INTEGER NOT NULL
);

-- Fotografia financeira do mês. Append-only: editar = criar outra.
CREATE TABLE financial_snapshots (
    id                    TEXT PRIMARY KEY,
    user_id               TEXT NOT NULL REFERENCES users(id),
    as_of                 TEXT NOT NULL,
    net_monthly_income    TEXT NOT NULL,
    essential_expenses    TEXT NOT NULL,
    variable_expenses     TEXT NOT NULL,
    liquid_reserve        TEXT NOT NULL,
    available_this_month  TEXT NOT NULL,
    created_at            TEXT NOT NULL
);
CREATE INDEX financial_snapshots_by_date ON financial_snapshots (user_id, as_of, created_at);
CREATE TRIGGER financial_snapshots_no_update BEFORE UPDATE ON financial_snapshots
BEGIN SELECT RAISE(ABORT, 'financial_snapshots é append-only'); END;
CREATE TRIGGER financial_snapshots_no_delete BEFORE DELETE ON financial_snapshots
BEGIN SELECT RAISE(ABORT, 'financial_snapshots é append-only'); END;

ALTER TABLE liabilities ADD COLUMN snapshot_id TEXT REFERENCES financial_snapshots(id);
CREATE INDEX liabilities_by_snapshot ON liabilities (snapshot_id);

ALTER TABLE goals ADD COLUMN current_amount TEXT NOT NULL DEFAULT '0';
ALTER TABLE goals ADD COLUMN created_at TEXT;
ALTER TABLE goals ADD COLUMN updated_at TEXT;

CREATE TABLE user_assumptions (
    user_id         TEXT PRIMARY KEY REFERENCES users(id),
    scenarios_json  TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE conversations (
    id                 TEXT PRIMARY KEY,
    kind               TEXT NOT NULL CHECK (kind IN ('chat', 'routine', 'panel')),
    title              TEXT NOT NULL,
    claude_session_id  TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error', 'interrupted')),
    tools_json       TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
);
CREATE INDEX messages_by_conversation ON messages (conversation_id, created_at);

CREATE TABLE routines (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    instruction    TEXT NOT NULL,
    schedule_json  TEXT NOT NULL,
    timezone       TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
    active         INTEGER NOT NULL DEFAULT 1,
    missed_policy  TEXT NOT NULL DEFAULT 'skip' CHECK (missed_policy IN ('skip', 'run_once')),
    use_panel      INTEGER NOT NULL DEFAULT 0,
    next_run_at    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE routine_runs (
    id               TEXT PRIMARY KEY,
    routine_id       TEXT NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    scheduled_for    TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    status           TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'quiet', 'failed', 'skipped', 'missed')),
    summary          TEXT,
    conversation_id  TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    read             INTEGER NOT NULL DEFAULT 0,
    UNIQUE (routine_id, scheduled_for)     -- idempotência: uma execução por ocorrência
);
CREATE INDEX routine_runs_inbox ON routine_runs (read, finished_at);
