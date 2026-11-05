-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v15: Carreira, fase 1 (docs/CARREIRA.md). Compatível: só uma tabela nova.
-- Vagas públicas encontradas pelo caçador (serviço lastro-carreira), já avaliadas pelas regras do dono.
-- Texto de terceiros (título, descrição): dado não confiável, nunca instrução.

CREATE TABLE carreira_vagas (
    id            TEXT PRIMARY KEY,                -- "<fonte>:<id na fonte>"
    source        TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL DEFAULT '',
    location      TEXT NOT NULL DEFAULT '',
    workplace     TEXT NOT NULL CHECK (workplace IN ('remoto', 'hibrido', 'presencial', 'desconhecido')),
    salary_min    REAL,
    currency      TEXT,
    description   TEXT NOT NULL DEFAULT '',
    published_at  TEXT,
    verdict       TEXT NOT NULL CHECK (verdict IN ('compativel', 'talvez', 'fora')),
    score         INTEGER NOT NULL,
    reasons_json  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'nova',    -- nova → avisada; as próximas fases acrescentam estados
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);
CREATE INDEX carreira_vagas_aviso ON carreira_vagas (status, verdict, score);
