-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v17: Carreira, fase 3 (docs/CARREIRA.md). Compatível: só uma tabela nova.
-- Cada tentativa de candidatura feita pelo agente aplicador, com o resultado e as respostas dadas no formulário.

CREATE TABLE carreira_envios (
    id              INTEGER PRIMARY KEY,
    vaga_id         TEXT NOT NULL REFERENCES carreira_vagas (id),
    status          TEXT NOT NULL CHECK (status IN ('enviada', 'precisa_de_voce', 'nao_aplicavel', 'falhou')),
    motivo          TEXT NOT NULL,
    url_final       TEXT NOT NULL DEFAULT '',
    respostas_json  TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL
);
CREATE INDEX carreira_envios_vaga ON carreira_envios (vaga_id, created_at);
