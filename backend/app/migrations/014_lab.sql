-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v14: Laboratório do Conselho (docs/LAB.md). Compatível: uma coluna e tabelas novas.
-- Bento sozinho × Conselho completo sobre o MESMO dossiê congelado, em conversas separadas; hipóteses conferidas
-- depois. Nada aqui é decisão da pessoa nem operação financeira.

-- Consumo e registro final de cada execução (chamadas, tokens, duração; no Conselho, o registro da reunião).
ALTER TABLE runs ADD COLUMN result_json TEXT;

CREATE TABLE lab_settings (
    user_id               TEXT PRIMARY KEY,
    automation            TEXT NOT NULL DEFAULT 'desligada' CHECK (automation IN ('desligada', 'propor', 'executar')),
    max_per_week          INTEGER NOT NULL DEFAULT 2 CHECK (max_per_week BETWEEN 0 AND 14),
    monthly_token_budget  INTEGER NOT NULL DEFAULT 0 CHECK (monthly_token_budget >= 0),  -- 0: sem teto de tokens
    repetitions           INTEGER NOT NULL DEFAULT 1 CHECK (repetitions BETWEEN 1 AND 5),
    updated_at            TEXT NOT NULL
);

CREATE TABLE lab_experiments (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    client_id          TEXT,
    dedupe_key         TEXT,
    origin             TEXT NOT NULL CHECK (origin IN ('pessoa', 'radar')),
    origin_ref         TEXT,
    category           TEXT NOT NULL,
    question           TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('proposto', 'executando', 'concluido', 'incompleto',
                                                       'cancelado', 'recusado')),
    as_of              TEXT NOT NULL,                 -- data de corte das informações (hoje ou data simulada)
    simulated          INTEGER NOT NULL DEFAULT 0,
    comparable         INTEGER NOT NULL,
    repetitions        INTEGER NOT NULL CHECK (repetitions BETWEEN 1 AND 5),
    research           INTEGER NOT NULL DEFAULT 0,
    followups_json     TEXT NOT NULL,                 -- dias de reavaliação (30/90/180/personalizado)
    snapshot_json      TEXT NOT NULL,                 -- controle experimental completo (dossiê, prompts, modelos…)
    snapshot_sha256    TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    started_at         TEXT,
    finished_at        TEXT
);
CREATE UNIQUE INDEX lab_experiments_client ON lab_experiments (user_id, client_id) WHERE client_id IS NOT NULL;
CREATE UNIQUE INDEX lab_experiments_dedupe ON lab_experiments (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX lab_experiments_by_user ON lab_experiments (user_id, created_at);
CREATE TRIGGER lab_experiments_frozen BEFORE UPDATE OF user_id, question, as_of, simulated, comparable, repetitions,
    research, snapshot_json, snapshot_sha256, created_at, origin, category ON lab_experiments
BEGIN SELECT RAISE(ABORT, 'o controle do experimento não muda depois de criado'); END;

-- Uma análise por modo e repetição; cada uma numa conversa própria (isolamento entre os modos).
CREATE TABLE lab_analyses (
    id               TEXT PRIMARY KEY,
    experiment_id    TEXT NOT NULL REFERENCES lab_experiments(id),
    user_id          TEXT NOT NULL,
    mode             TEXT NOT NULL CHECK (mode IN ('individual', 'conselho')),
    repetition       INTEGER NOT NULL,
    conversation_id  TEXT NOT NULL,
    run_id           TEXT,
    status           TEXT NOT NULL CHECK (status IN ('na_fila', 'executando', 'concluida', 'falhou', 'cancelada')),
    final_text       TEXT,
    record_json      TEXT,                            -- registro estruturado validado (ou nulo)
    record_status    TEXT CHECK (record_status IS NULL OR record_status IN ('ok', 'ausente', 'invalido')),
    evaluation_json  TEXT,                            -- avaliação determinística no fechamento
    usage_json       TEXT,
    created_at       TEXT NOT NULL,
    finished_at      TEXT,
    UNIQUE (experiment_id, mode, repetition)
);
CREATE INDEX lab_analyses_by_conversation ON lab_analyses (conversation_id);
CREATE INDEX lab_analyses_by_run ON lab_analyses (run_id);
CREATE TRIGGER lab_analyses_frozen BEFORE UPDATE OF final_text, record_json, record_status, evaluation_json ON lab_analyses
WHEN OLD.finished_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'análise fechada não muda'); END;

-- Hipóteses: o que foi dito não muda (mesma regra das Convicções); conferida uma vez, fica conferida.
CREATE TABLE lab_hypotheses (
    id             TEXT PRIMARY KEY,
    analysis_id    TEXT NOT NULL REFERENCES lab_analyses(id),
    experiment_id  TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    statement      TEXT NOT NULL,
    probability    TEXT,                              -- nula: hipótese sem probabilidade (fora do Brier)
    due_on         TEXT NOT NULL,
    check_json     TEXT,                              -- nula: conferência pela pessoa
    status         TEXT NOT NULL DEFAULT 'aberta'
                   CHECK (status IN ('aberta', 'aconteceu', 'nao_aconteceu', 'indeterminada')),
    observed_json  TEXT,
    resolved_by    TEXT CHECK (resolved_by IS NULL OR resolved_by IN ('dados', 'pessoa')),
    resolved_at    TEXT,
    note           TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (analysis_id, ordinal)
);
CREATE INDEX lab_hypotheses_due ON lab_hypotheses (status, due_on);
CREATE TRIGGER lab_hypotheses_frozen BEFORE UPDATE OF analysis_id, experiment_id, user_id, ordinal, statement,
    probability, due_on, check_json, created_at ON lab_hypotheses
BEGIN SELECT RAISE(ABORT, 'hipótese registrada não muda'); END;
CREATE TRIGGER lab_hypotheses_resolved_once BEFORE UPDATE OF status ON lab_hypotheses
WHEN OLD.status != 'aberta'
BEGIN SELECT RAISE(ABORT, 'hipótese já conferida'); END;

-- Reavaliações agendadas (30/90/180/personalizado): cada uma grava o retrato das métricas naquele dia.
CREATE TABLE lab_checkpoints (
    id               TEXT PRIMARY KEY,
    experiment_id    TEXT NOT NULL REFERENCES lab_experiments(id),
    user_id          TEXT NOT NULL,
    days             INTEGER NOT NULL,
    due_on           TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'agendada' CHECK (status IN ('agendada', 'pendente', 'feita')),
    evaluation_json  TEXT,
    done_at          TEXT,
    UNIQUE (experiment_id, days)
);
CREATE INDEX lab_checkpoints_due ON lab_checkpoints (status, due_on);

-- Avaliações de utilidade: IA às cegas (rótulos embaralhados) ou pessoa. Só acrescenta.
CREATE TABLE lab_reviews (
    id              TEXT PRIMARY KEY,
    experiment_id   TEXT NOT NULL REFERENCES lab_experiments(id),
    user_id         TEXT NOT NULL,
    repetition      INTEGER NOT NULL,
    reviewer        TEXT NOT NULL CHECK (reviewer IN ('ia', 'pessoa')),
    blind_json      TEXT,                            -- {"A": "conselho"|"individual", "B": ...} (só IA)
    scores_json     TEXT NOT NULL,
    usage_json      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX lab_reviews_by_experiment ON lab_reviews (experiment_id, created_at);
CREATE TRIGGER lab_reviews_no_update BEFORE UPDATE ON lab_reviews
BEGIN SELECT RAISE(ABORT, 'avaliação registrada não muda: registre outra'); END;
CREATE TRIGGER lab_reviews_no_delete BEFORE DELETE ON lab_reviews
BEGIN SELECT RAISE(ABORT, 'avaliação registrada não muda: registre outra'); END;

-- Diário do Laboratório: análises de IA e resultados observados (NÃO são decisões da pessoa). Encadeado (SHA-256).
CREATE TABLE lab_journal (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    experiment_id  TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('analise_ia', 'resultado_observado', 'decisao_vinculada')),
    ref            TEXT NOT NULL,                     -- idempotência: um registro por (experimento, evento)
    payload_json   TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    prev_sha256    TEXT,
    sha256         TEXT NOT NULL,
    UNIQUE (user_id, seq),
    UNIQUE (user_id, ref)
);
CREATE TRIGGER lab_journal_no_update BEFORE UPDATE ON lab_journal
BEGIN SELECT RAISE(ABORT, 'o Diário do Laboratório é append-only'); END;
CREATE TRIGGER lab_journal_no_delete BEFORE DELETE ON lab_journal
BEGIN SELECT RAISE(ABORT, 'o Diário do Laboratório é append-only'); END;
