-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v10: livro de movimentações, registro a partir da conversa e caixa de entrada de documentos
-- (docs/LEDGER.md). Compatível: só cria tabelas; retratos financeiros (financial_snapshots) não mudam.

-- Consentimentos explícitos por pessoa e escopo (registro automático; envio de documento a provedor de IA).
CREATE TABLE consents (
    user_id     TEXT NOT NULL,
    scope       TEXT NOT NULL CHECK (scope IN ('auto_register', 'ai_documents')),
    granted     INTEGER NOT NULL CHECK (granted IN (0, 1)),
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, scope)
);

-- Documento enviado. O arquivo fica fora da área pública, com nome gerado pelo servidor (storage_name); depois da
-- retenção, o arquivo some e os metadados ficam (storage_name NULL).
CREATE TABLE documents (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    sha256           TEXT NOT NULL,
    original_name    TEXT NOT NULL,
    media_type       TEXT NOT NULL,
    size             INTEGER NOT NULL,
    storage_name     TEXT,
    status           TEXT NOT NULL CHECK (status IN ('processado', 'revisao', 'sem_leitura', 'interpretando', 'erro',
                                                     'excluido')),
    doc_type         TEXT NOT NULL DEFAULT 'desconhecido',
    source_format    TEXT NOT NULL DEFAULT '',
    institution      TEXT NOT NULL DEFAULT '',
    account          TEXT NOT NULL DEFAULT '',
    summary_json     TEXT NOT NULL DEFAULT '{}',
    warnings_json    TEXT NOT NULL DEFAULT '[]',
    conversation_id  TEXT,
    created_at       TEXT NOT NULL,
    processed_at     TEXT,
    deleted_at       TEXT,
    UNIQUE (user_id, sha256)
);
CREATE INDEX documents_by_user ON documents (user_id, created_at);

-- Livro de movimentações. Valores em texto decimal (nunca float). Só conta nos totais o que está 'registrado' e
-- efetivado (settled = 1); transferências, pagamento de fatura e saldos não são receita nem despesa.
CREATE TABLE ledger_entries (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('despesa', 'receita', 'transferencia', 'pagamento_fatura', 'estorno',
                                                  'reembolso')),
    status          TEXT NOT NULL CHECK (status IN ('registrado', 'pendente', 'duplicada', 'desfeito', 'descartado')),
    occurred_on     TEXT,
    accrual_on      TEXT,
    amount          TEXT,
    currency        TEXT NOT NULL DEFAULT 'BRL',
    description     TEXT NOT NULL DEFAULT '',
    counterparty    TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT 'outros',
    institution     TEXT NOT NULL DEFAULT '',
    account         TEXT NOT NULL DEFAULT '',
    external_id     TEXT NOT NULL DEFAULT '',
    fingerprint     TEXT,
    installment     TEXT NOT NULL DEFAULT '',
    settled         INTEGER NOT NULL DEFAULT 1 CHECK (settled IN (0, 1)),
    reconciliation  TEXT NOT NULL DEFAULT 'nao_conciliado'
                    CHECK (reconciliation IN ('nao_conciliado', 'conciliado', 'possivel_duplicata')),
    matched_id      TEXT,
    confidence      TEXT NOT NULL CHECK (confidence IN ('alta', 'media', 'baixa')),
    source_kind     TEXT NOT NULL CHECK (source_kind IN ('conversa', 'documento', 'manual', 'ia')),
    source_ref      TEXT NOT NULL,
    source_detail   TEXT NOT NULL DEFAULT '',
    missing_json    TEXT NOT NULL DEFAULT '[]',
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
-- Idempotência: a mesma movimentação importada duas vezes tem a mesma impressão digital.
CREATE UNIQUE INDEX ledger_fingerprint ON ledger_entries (user_id, fingerprint) WHERE fingerprint IS NOT NULL;
CREATE INDEX ledger_by_user_date ON ledger_entries (user_id, occurred_on);
CREATE INDEX ledger_by_source ON ledger_entries (user_id, source_kind, source_ref);

-- Trilha de auditoria das movimentações: append-only.
CREATE TABLE ledger_events (
    id          TEXT PRIMARY KEY,
    entry_id    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    action      TEXT NOT NULL,
    before_json TEXT,
    after_json  TEXT,
    actor       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX ledger_events_by_entry ON ledger_events (entry_id, created_at);
CREATE TRIGGER ledger_events_no_update BEFORE UPDATE ON ledger_events
BEGIN SELECT RAISE(ABORT, 'ledger_events é append-only'); END;
CREATE TRIGGER ledger_events_no_delete BEFORE DELETE ON ledger_events
BEGIN SELECT RAISE(ABORT, 'ledger_events é append-only'); END;

-- Saldos informados por extratos: observação datada, nunca receita.
CREATE TABLE account_balances (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    document_id  TEXT NOT NULL,
    institution  TEXT NOT NULL DEFAULT '',
    account      TEXT NOT NULL DEFAULT '',
    as_of        TEXT NOT NULL,
    amount       TEXT NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'BRL',
    created_at   TEXT NOT NULL,
    UNIQUE (user_id, document_id, account, as_of)
);

-- O que o Lastro reconheceu numa mensagem da pessoa e o que fez com isso (origem de cada registro automático).
CREATE TABLE captures (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    message_id       TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    span             TEXT NOT NULL,
    classification   TEXT NOT NULL,
    fields_json      TEXT NOT NULL,
    missing_json     TEXT NOT NULL DEFAULT '[]',
    status           TEXT NOT NULL CHECK (status IN ('registrado', 'pendente', 'informativo', 'desfeito', 'descartado')),
    target_kind      TEXT,
    target_id        TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (message_id, span)
);
CREATE INDEX captures_by_user ON captures (user_id, status, created_at);
