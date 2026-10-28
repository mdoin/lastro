-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v11: Conselho deliberativo (docs/COUNCIL.md). Compatível: uma coluna e uma tabela novas.

-- A pessoa pode pedir para encerrar a deliberação: o orquestrador termina a fala em curso e vai para o veredito.
ALTER TABLE runs ADD COLUMN close_requested INTEGER NOT NULL DEFAULT 0;

-- Registro estruturado de cada reunião concluída (histórico da deliberação, NÃO decisão da pessoa).
CREATE TABLE council_records (
    run_id           TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    mode             TEXT NOT NULL,
    topic            TEXT NOT NULL,
    record_json      TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX council_records_by_user ON council_records (user_id, created_at);
