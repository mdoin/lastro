-- Lastro — v5: equipe de agentes (conversas individuais, grupos, Conselho), fila persistente de execuções,
-- memória financeira com fonte e histórico, memória individual dos agentes e dados externos.
-- Compatível: só acrescenta colunas e tabelas; conversas antigas viram conversa individual com o Mentor.

ALTER TABLE conversations ADD COLUMN user_id TEXT NOT NULL DEFAULT 'owner';
ALTER TABLE conversations ADD COLUMN channel TEXT NOT NULL DEFAULT 'direct'
    CHECK (channel IN ('direct', 'group', 'council', 'routine'));
ALTER TABLE conversations ADD COLUMN agent_id TEXT;
UPDATE conversations SET channel = CASE kind WHEN 'panel' THEN 'council' WHEN 'routine' THEN 'routine' ELSE 'direct' END;
UPDATE conversations SET agent_id = 'mentor' WHERE channel = 'direct';
CREATE INDEX conversations_by_user ON conversations (user_id, updated_at);

CREATE TABLE conversation_participants (
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_id         TEXT NOT NULL,
    added_at         TEXT NOT NULL,
    PRIMARY KEY (conversation_id, agent_id)
);

ALTER TABLE messages ADD COLUMN agent_id TEXT;          -- autor (NULL = a pessoa)
ALTER TABLE messages ADD COLUMN run_id TEXT;
ALTER TABLE messages ADD COLUMN step_key TEXT;
ALTER TABLE messages ADD COLUMN client_id TEXT;         -- idempotência do envio pelo navegador
ALTER TABLE messages ADD COLUMN reply_to_id TEXT;
ALTER TABLE messages ADD COLUMN mentions_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE messages ADD COLUMN sources_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'message';  -- message | analysis | notice
UPDATE messages SET agent_id = 'mentor' WHERE role = 'assistant';
-- Retentativas nunca duplicam: cada etapa de uma execução publica no máximo uma mensagem.
CREATE UNIQUE INDEX messages_one_per_step ON messages (run_id, step_key) WHERE run_id IS NOT NULL;
CREATE UNIQUE INDEX messages_client_id ON messages (conversation_id, client_id) WHERE client_id IS NOT NULL;

-- Fila persistente: sobrevive ao fechamento da aba e ao reinício do serviço.
CREATE TABLE runs (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id          TEXT NOT NULL,
    message_id       TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('reply', 'council')),
    status           TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')),
    route_json       TEXT NOT NULL DEFAULT '{}',
    attempts         INTEGER NOT NULL DEFAULT 0,
    error            TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    UNIQUE (message_id, kind)
);
CREATE INDEX runs_by_status ON runs (status, created_at);
CREATE INDEX runs_by_conversation ON runs (conversation_id, created_at);

-- Cada passo é rastreável: quem, a pedido de quem (parent_key), em que profundidade, com que resultado.
-- Delegações são passos com parent_key; as recusadas (ciclo, limite, duplicata) ficam com status 'rejected'.
CREATE TABLE run_steps (
    run_id       TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_key     TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    kind         TEXT NOT NULL,
    parent_key   TEXT,
    depth        INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled', 'rejected')),
    task         TEXT NOT NULL DEFAULT '',
    output       TEXT NOT NULL DEFAULT '',
    tools_json   TEXT NOT NULL DEFAULT '[]',
    error        TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    PRIMARY KEY (run_id, step_key)
);

-- Memória financeira: fatos com fonte, data e histórico. Agentes só PROPÕEM; a pessoa confirma.
CREATE TABLE financial_facts (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL REFERENCES users(id),
    key            TEXT NOT NULL,
    value          TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('confirmed', 'proposed', 'rejected', 'superseded')),
    source         TEXT NOT NULL,      -- 'pessoa' | 'agente:<id>'
    source_ref     TEXT,               -- mensagem ou execução de origem
    note           TEXT NOT NULL DEFAULT '',
    as_of          TEXT NOT NULL,
    supersedes_id  TEXT REFERENCES financial_facts(id),
    created_at     TEXT NOT NULL,
    decided_at     TEXT
);
CREATE INDEX financial_facts_by_key ON financial_facts (user_id, key, created_at);
CREATE TRIGGER financial_facts_no_delete BEFORE DELETE ON financial_facts
BEGIN SELECT RAISE(ABORT, 'financial_facts guarda histórico: rejeite ou substitua'); END;

-- Memória individual: notas de um agente, valendo só onde nasceram (conversa individual dele ou aquele grupo).
CREATE TABLE agent_notes (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    agent_id         TEXT NOT NULL,
    scope            TEXT NOT NULL CHECK (scope IN ('private', 'conversation')),
    conversation_id  TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    content          TEXT NOT NULL,
    source_ref       TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX agent_notes_by_agent ON agent_notes (user_id, agent_id, scope, created_at);

-- Dados externos (coletor em integrations/): valor, unidade, data de referência e hora da coleta.
CREATE TABLE market_data (
    source          TEXT NOT NULL,
    series_id       TEXT NOT NULL,
    reference_date  TEXT NOT NULL,
    value           TEXT NOT NULL,
    unit            TEXT NOT NULL,
    label           TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (source, series_id, reference_date)
);
CREATE TABLE market_fetch_status (
    source      TEXT NOT NULL,
    series_id   TEXT NOT NULL,
    checked_at  TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    error       TEXT,
    PRIMARY KEY (source, series_id)
);
