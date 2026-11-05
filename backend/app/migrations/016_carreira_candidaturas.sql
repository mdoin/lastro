-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v16: Carreira, fases 2, 4 e 5 (docs/CARREIRA.md). Compatível: só tabelas novas.
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

-- Fase 5 (Treinador): entrevista simulada pelo WhatsApp, uma por vez; o histórico vai inteiro a cada resposta.
CREATE TABLE carreira_treinos (
    id               INTEGER PRIMARY KEY,
    vaga_id          TEXT NOT NULL REFERENCES carreira_vagas (id),
    status           TEXT NOT NULL CHECK (status IN ('ativo', 'encerrado')),
    transcript_json  TEXT NOT NULL,                 -- [{"de": "pessoa"|"treinador", "texto": "..."}]
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- Estado do serviço (ex.: até onde as mensagens do dono no WhatsApp já foram lidas).
CREATE TABLE carreira_estado (
    chave  TEXT PRIMARY KEY,
    valor  TEXT NOT NULL
);

-- Fase 4 (Carteiro): e-mails de vagas já lidos (só os que passaram no filtro de vagas; o corpo não é guardado).
CREATE TABLE carreira_emails (
    uid          TEXT PRIMARY KEY,                  -- "<uidvalidity>:<uid>" no INBOX
    received_at  TEXT,
    sender       TEXT NOT NULL,
    subject      TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    empresa      TEXT NOT NULL DEFAULT '',
    resumo       TEXT NOT NULL DEFAULT '',
    vaga_id      TEXT REFERENCES carreira_vagas (id),
    created_at   TEXT NOT NULL
);
