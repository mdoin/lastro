-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Convicções: previsões declaradas pelos agentes no Conselho e conferidas depois (app/convictions.py).
CREATE TABLE predictions (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id),
    agent_id         TEXT NOT NULL,
    conversation_id  TEXT,
    run_id           TEXT,
    message_id       TEXT NOT NULL,
    ordinal          INTEGER NOT NULL,
    statement        TEXT NOT NULL,
    probability      TEXT NOT NULL,
    due_on           TEXT NOT NULL,
    check_json       TEXT,
    status           TEXT NOT NULL DEFAULT 'aberta'
                     CHECK (status IN ('aberta', 'aconteceu', 'nao_aconteceu', 'anulada', 'indeterminada')),
    observed_json    TEXT,
    resolved_by      TEXT CHECK (resolved_by IS NULL OR resolved_by IN ('dados', 'pessoa')),
    resolved_at      TEXT,
    note             TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE (message_id, ordinal)
);
CREATE INDEX predictions_due ON predictions (status, due_on);
CREATE INDEX predictions_agent ON predictions (user_id, agent_id);

-- O que o agente disse não muda depois (nem a probabilidade, nem a data, nem a condição).
CREATE TRIGGER predictions_frozen BEFORE UPDATE OF user_id, agent_id, message_id, ordinal, statement, probability,
    due_on, check_json, created_at ON predictions
BEGIN
    SELECT RAISE(ABORT, 'previsão registrada não muda');
END;

-- Conferida uma vez, fica conferida.
CREATE TRIGGER predictions_resolved_once BEFORE UPDATE OF status ON predictions
WHEN OLD.status != 'aberta'
BEGIN
    SELECT RAISE(ABORT, 'previsão já conferida');
END;
