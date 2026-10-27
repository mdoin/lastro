-- Meu Patrimônio AI — esquema SQLite do MVP (versão 1).
-- Convenções: ids são UUID em TEXT; datas/horas em ISO 8601 com fuso;
-- valores monetários, quantidades e taxas em TEXT com Decimal serializado
-- (nunca REAL/float). Ver docs/DATA_DICTIONARY.md.

PRAGMA foreign_keys = ON;

CREATE TABLE schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
INSERT INTO schema_version (version, applied_at) VALUES (1, '2026-10-26T00:00:00-03:00');

CREATE TABLE users (
    id           TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    preferences  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE financial_profiles (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id),
    version          INTEGER NOT NULL,
    assessed_at      TEXT NOT NULL,
    horizon_months   INTEGER,
    liquidity_needs  TEXT,
    loss_tolerance   TEXT,
    experience       TEXT,
    rationale        TEXT NOT NULL,
    UNIQUE (user_id, version)
);

CREATE TABLE accounts (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES users(id),
    institution_alias  TEXT NOT NULL,          -- apelido; nunca agência/conta completas
    type               TEXT NOT NULL,
    currency           TEXT NOT NULL DEFAULT 'BRL'
);

CREATE TABLE assets (
    id              TEXT PRIMARY KEY,
    ticker_or_code  TEXT,
    name            TEXT NOT NULL,
    asset_class     TEXT NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'BRL',
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE transactions (
    id                     TEXT PRIMARY KEY,
    account_id             TEXT NOT NULL REFERENCES accounts(id),
    asset_id               TEXT REFERENCES assets(id),
    type                   TEXT NOT NULL CHECK (type IN
                              ('aplicacao','resgate','compra','venda','provento','taxa','imposto','ajuste')),
    date                   TEXT NOT NULL,
    quantity               TEXT,
    gross_amount           TEXT NOT NULL,
    fees                   TEXT NOT NULL DEFAULT '0',
    taxes                  TEXT NOT NULL DEFAULT '0',
    currency               TEXT NOT NULL DEFAULT 'BRL',
    import_hash            TEXT NOT NULL UNIQUE,   -- garante importação idempotente
    reconciliation_status  TEXT NOT NULL DEFAULT 'pendente'
                              CHECK (reconciliation_status IN ('pendente','conciliado','retificado')),
    supersedes_id          TEXT REFERENCES transactions(id),  -- retificação sem apagar o original
    created_at             TEXT NOT NULL
);

CREATE TABLE prices (
    asset_id        TEXT NOT NULL REFERENCES assets(id),
    price           TEXT NOT NULL,
    currency        TEXT NOT NULL,
    reference_date  TEXT NOT NULL,
    source          TEXT NOT NULL,
    retrieved_at    TEXT NOT NULL,
    is_estimate     INTEGER NOT NULL DEFAULT 0,
    license         TEXT,
    PRIMARY KEY (asset_id, reference_date, source)
);

CREATE TABLE positions_snapshots (
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    asset_id    TEXT NOT NULL REFERENCES assets(id),
    quantity    TEXT NOT NULL,
    value       TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    PRIMARY KEY (account_id, asset_id, as_of)
);

CREATE TABLE liabilities (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL REFERENCES users(id),
    name              TEXT NOT NULL,
    balance           TEXT NOT NULL,
    monthly_rate      TEXT,
    cet_annual        TEXT,
    due_date          TEXT,
    monthly_payment   TEXT,
    as_of             TEXT NOT NULL
);

CREATE TABLE budgets (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL REFERENCES users(id),
    period    TEXT NOT NULL,              -- AAAA-MM
    category  TEXT NOT NULL,              -- receita | essencial | variavel | extraordinaria
    amount    TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'planejado' CHECK (status IN ('planejado','realizado'))
);

CREATE TABLE goals (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES users(id),
    name               TEXT NOT NULL,
    target_real_value  TEXT NOT NULL,     -- em poder de compra da data base
    base_date          TEXT NOT NULL,
    deadline           TEXT NOT NULL,
    priority           INTEGER NOT NULL,
    liquidity          TEXT
);

CREATE TABLE assumptions (
    id                TEXT PRIMARY KEY,
    scenario          TEXT NOT NULL,
    annual_return     TEXT NOT NULL,
    inflation_rate    TEXT NOT NULL,
    fees              TEXT NOT NULL DEFAULT '0',
    taxes_note        TEXT,
    created_at        TEXT NOT NULL
);

-- Simulações, pareceres, decisões e auditoria são append-only:
-- projeções passadas não são reescritas para parecer que o agente acertou.
CREATE TABLE simulations (
    id                  TEXT PRIMARY KEY,
    assumptions_id      TEXT NOT NULL REFERENCES assumptions(id),
    engine_version      TEXT NOT NULL,
    inputs_fingerprint  TEXT NOT NULL,
    results_json        TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE research_reports (
    id             TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL,
    question       TEXT NOT NULL,
    sources_json   TEXT NOT NULL,
    as_of          TEXT NOT NULL,
    review_status  TEXT NOT NULL CHECK (review_status IN ('PASSA','REVISAR','BLOQUEAR','pendente')),
    created_at     TEXT NOT NULL
);

CREATE TABLE decision_log (
    id              TEXT PRIMARY KEY,
    date            TEXT NOT NULL,
    question        TEXT NOT NULL,
    alternatives    TEXT NOT NULL,
    information     TEXT,
    risk_accepted   TEXT,
    user_choice     TEXT NOT NULL,
    planned_amount  TEXT,
    confirmed       INTEGER NOT NULL DEFAULT 0,   -- plano ≠ aporte confirmado pelo usuário
    review_of_id    TEXT REFERENCES decision_log(id)  -- revisão posterior é novo registro
);

CREATE TABLE audit_log (
    id         TEXT PRIMARY KEY,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    resource   TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    outcome    TEXT NOT NULL
);

CREATE TRIGGER simulations_no_update BEFORE UPDATE ON simulations
BEGIN SELECT RAISE(ABORT, 'simulations é append-only'); END;
CREATE TRIGGER simulations_no_delete BEFORE DELETE ON simulations
BEGIN SELECT RAISE(ABORT, 'simulations é append-only'); END;
CREATE TRIGGER decision_log_no_update BEFORE UPDATE ON decision_log
BEGIN SELECT RAISE(ABORT, 'decision_log é append-only; registre uma revisão'); END;
CREATE TRIGGER decision_log_no_delete BEFORE DELETE ON decision_log
BEGIN SELECT RAISE(ABORT, 'decision_log é append-only; registre uma revisão'); END;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log é append-only'); END;
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log é append-only'); END;
CREATE TRIGGER transactions_reconciled_no_delete BEFORE DELETE ON transactions
WHEN OLD.reconciliation_status = 'conciliado'
BEGIN SELECT RAISE(ABORT, 'transação conciliada não pode ser apagada; use retificação'); END;
