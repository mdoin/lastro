-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v7: Diário de Decisões assistido por agentes (docs/DIARIO.md).
-- Proposta (rascunho preparado pelos agentes) ≠ decisão (confirmada pela pessoa).
-- Compatível: só acrescenta tabelas. `decision_log` fica como está (append-only) e é importada pelo web app.

-- Rascunhos: o conteúdo é dos agentes e não muda; só o estado muda, e nunca depois de confirmado ou descartado.
CREATE TABLE decision_drafts (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    author           TEXT NOT NULL CHECK (author LIKE 'agente:%'),
    requested_by     TEXT NOT NULL CHECK (requested_by IN ('agente', 'pessoa')),
    status           TEXT NOT NULL CHECK (status IN ('pendente', 'adiado', 'confirmado', 'descartado')),
    message_id       TEXT NOT NULL UNIQUE,         -- mensagem de origem: um rascunho por mensagem (idempotência)
    conversation_id  TEXT,                         -- sem FK: apagar a conversa não apaga o registro
    run_id           TEXT,
    opportunity_id   TEXT,
    review_of_id     TEXT,                         -- a decisão que esta conversa revisa (se aberta a partir dela)
    content_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    status_note      TEXT NOT NULL DEFAULT '',
    remind_on        TEXT,
    decided_at       TEXT,
    decision_id      TEXT
);
CREATE INDEX decision_drafts_by_user ON decision_drafts (user_id, status, created_at);
CREATE TRIGGER decision_drafts_no_delete BEFORE DELETE ON decision_drafts
BEGIN SELECT RAISE(ABORT, 'rascunhos ficam no histórico: descarte em vez de apagar'); END;
CREATE TRIGGER decision_drafts_content_fixed BEFORE UPDATE ON decision_drafts
WHEN NEW.content_json IS NOT OLD.content_json OR NEW.author IS NOT OLD.author OR NEW.user_id IS NOT OLD.user_id
  OR NEW.message_id IS NOT OLD.message_id OR NEW.created_at IS NOT OLD.created_at
  OR NEW.opportunity_id IS NOT OLD.opportunity_id OR NEW.review_of_id IS NOT OLD.review_of_id
  OR OLD.status IN ('confirmado', 'descartado')
BEGIN SELECT RAISE(ABORT, 'rascunho fixo: correções da pessoa vão no registro da decisão'); END;

-- Decisões, revisões e resultados observados: só por ação autenticada da pessoa; append-only e encadeados (SHA-256).
CREATE TABLE diary_entries (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('decisao', 'revisao', 'resultado')),
    decision_id     TEXT NOT NULL,                 -- a decisão original (numa 'decisao', o próprio id)
    version         INTEGER NOT NULL,              -- versão vigente da decisão depois deste registro
    draft_id        TEXT REFERENCES decision_drafts(id),
    opportunity_id  TEXT,
    client_id       TEXT,
    payload_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    prev_sha256     TEXT,
    sha256          TEXT NOT NULL,
    UNIQUE (user_id, seq),
    UNIQUE (user_id, client_id)
);
CREATE INDEX diary_entries_by_decision ON diary_entries (decision_id, seq);
CREATE TRIGGER diary_entries_no_update BEFORE UPDATE ON diary_entries
BEGIN SELECT RAISE(ABORT, 'o Diário é append-only: registre uma revisão'); END;
CREATE TRIGGER diary_entries_no_delete BEFORE DELETE ON diary_entries
BEGIN SELECT RAISE(ABORT, 'o Diário é append-only: registre uma revisão'); END;

-- Revisão periódica (configuração, não registro: pode mudar).
CREATE TABLE decision_review_plans (
    decision_id   TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    every_months  INTEGER NOT NULL CHECK (every_months BETWEEN 1 AND 24),
    next_on       TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Conversa aberta para revisar uma decisão: rascunhos nascidos nela viram revisão daquela decisão.
CREATE TABLE decision_links (
    conversation_id  TEXT PRIMARY KEY,
    decision_id      TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
