-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v16: Carreira, fase 2 (docs/CARREIRA.md). Compatível: só uma tabela nova.
-- Uma candidatura por vaga: currículo e carta feitos pelo Alfaiate a partir do perfil do dono (sem inventar).
-- As fases seguintes avançam o status (candidatura enviada, retorno da empresa, entrevista).

CREATE TABLE carreira_candidaturas (
    vaga_id       TEXT PRIMARY KEY REFERENCES carreira_vagas (id),
    status        TEXT NOT NULL DEFAULT 'curriculo',
    aderencia     INTEGER NOT NULL CHECK (aderencia BETWEEN 0 AND 100),
    resumo        TEXT NOT NULL,
    lacunas_json  TEXT NOT NULL,
    idioma        TEXT NOT NULL,
    curriculo_md  TEXT NOT NULL,
    carta         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
