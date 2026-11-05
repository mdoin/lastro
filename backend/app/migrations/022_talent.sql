-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v22: Talent, especialista em recrutamento da Carreira (docs/CARREIRA.md, seção Talent).
-- Memória do Talent: avaliações de vaga, revisões de currículo, análises de resultado e propostas ao dono.
-- Avaliações, revisões e análises são imutáveis (versão nova em vez de UPDATE); numa proposta só muda a decisão
-- do dono, uma vez. Nada aqui é fato profissional: os fatos continuam só no perfil do dono.

CREATE TABLE talent_avaliacoes (
    id                INTEGER PRIMARY KEY,
    vaga_id           TEXT NOT NULL REFERENCES carreira_vagas (id),
    entrada_sha       TEXT NOT NULL,                -- sha256 de perfil + vaga + rubrica: a mesma entrada não é reavaliada
    rubrica           TEXT NOT NULL,                -- versão da rubrica (carreira/talent.py RUBRICA)
    elegivel          INTEGER NOT NULL CHECK (elegivel IN (0, 1)),
    pontuacao         INTEGER NOT NULL CHECK (pontuacao BETWEEN 0 AND 100),  -- compatibilidade pela rubrica, não chance
    filtros_json      TEXT NOT NULL,                -- [{"filtro", "ok", "motivo"}] obrigatórios, antes da pontuação
    criterios_json    TEXT NOT NULL,                -- [{"criterio", "peso", "pontos", "motivo"}]
    requisitos_json   TEXT NOT NULL,                -- [{"texto", "tipo", "categoria", "situacao", "evidencia"}]
    posicionamento    TEXT NOT NULL,
    perfil_curriculo  TEXT NOT NULL,                -- backend | ia | junior
    destaques_json    TEXT NOT NULL,                -- [{"item", "motivo"}]
    orientacoes_json  TEXT NOT NULL,                -- instruções ao Alfaiate
    justificativa     TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    UNIQUE (vaga_id, entrada_sha)
);
CREATE INDEX talent_avaliacoes_vaga ON talent_avaliacoes (vaga_id, id);

CREATE TABLE talent_revisoes (
    id              INTEGER PRIMARY KEY,
    vaga_id         TEXT NOT NULL REFERENCES carreira_vagas (id),
    curriculo_id    INTEGER NOT NULL UNIQUE REFERENCES carreira_curriculos (id),  -- uma revisão por versão
    avaliacao_id    INTEGER REFERENCES talent_avaliacoes (id),
    rodada          INTEGER NOT NULL,
    resultado       TEXT NOT NULL CHECK (resultado IN ('aprovado', 'correcoes', 'bloqueado')),
    checagens_json  TEXT NOT NULL,                  -- determinísticas: [{"criterio", "ok", "detalhe"}]
    problemas_json  TEXT NOT NULL,                  -- [{"criterio", "gravidade", "trecho", "correcao"}]
    resumo          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX talent_revisoes_vaga ON talent_revisoes (vaga_id, id);

CREATE TABLE talent_analises (
    id                  INTEGER PRIMARY KEY,
    indicadores_json    TEXT NOT NULL,
    recomendacoes_json  TEXT NOT NULL,              -- [{"texto", "base", "forca": "descritiva" | "indicativa"}]
    created_at          TEXT NOT NULL
);

CREATE TABLE talent_propostas (
    id          INTEGER PRIMARY KEY,
    alvo        TEXT NOT NULL CHECK (alvo IN ('perfil', 'curriculo_base')),
    proposta    TEXT NOT NULL,
    origem      TEXT NOT NULL,                      -- de onde veio: trecho do perfil e/ou contagem nas vagas
    chave       TEXT NOT NULL UNIQUE,               -- a mesma proposta não é repetida
    status      TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'aprovada', 'recusada')),
    created_at  TEXT NOT NULL,
    decidida_em TEXT
);

CREATE TRIGGER talent_avaliacoes_imutavel BEFORE UPDATE ON talent_avaliacoes
BEGIN
    SELECT RAISE(ABORT, 'avaliação do Talent é imutável');
END;
CREATE TRIGGER talent_avaliacoes_sem_delete BEFORE DELETE ON talent_avaliacoes
BEGIN
    SELECT RAISE(ABORT, 'avaliação do Talent é imutável');
END;
CREATE TRIGGER talent_revisoes_imutavel BEFORE UPDATE ON talent_revisoes
BEGIN
    SELECT RAISE(ABORT, 'revisão do Talent é imutável');
END;
CREATE TRIGGER talent_revisoes_sem_delete BEFORE DELETE ON talent_revisoes
BEGIN
    SELECT RAISE(ABORT, 'revisão do Talent é imutável');
END;
CREATE TRIGGER talent_analises_imutavel BEFORE UPDATE ON talent_analises
BEGIN
    SELECT RAISE(ABORT, 'análise do Talent é imutável');
END;
CREATE TRIGGER talent_propostas_decisao_unica BEFORE UPDATE ON talent_propostas
WHEN OLD.status != 'pendente' OR NEW.proposta != OLD.proposta OR NEW.origem != OLD.origem
BEGIN
    SELECT RAISE(ABORT, 'proposta já decidida ou alteração fora da decisão');
END;

-- 'talent' passa a ser origem válida do histórico e avaliação/revisão/análise tipos de execução. SQLite não altera
-- CHECK: as tabelas são recriadas com os mesmos dados (DROP TABLE não dispara os triggers de DELETE).
CREATE TABLE carreira_eventos_v22 (
    id            INTEGER PRIMARY KEY,
    vaga_id       TEXT NOT NULL REFERENCES carreira_vagas (id),
    tipo          TEXT NOT NULL,
    origem        TEXT NOT NULL CHECK (origem IN ('cacador', 'alfaiate', 'aplicador', 'carteiro', 'talent', 'dono', 'sistema')),
    detalhe_json  TEXT NOT NULL DEFAULT '{}',
    envio_id      INTEGER REFERENCES carreira_envios (id),
    created_at    TEXT NOT NULL
);
INSERT INTO carreira_eventos_v22 SELECT id, vaga_id, tipo, origem, detalhe_json, envio_id, created_at FROM carreira_eventos;
DROP TABLE carreira_eventos;
ALTER TABLE carreira_eventos_v22 RENAME TO carreira_eventos;
CREATE INDEX carreira_eventos_vaga ON carreira_eventos (vaga_id, created_at);
CREATE INDEX carreira_eventos_data ON carreira_eventos (created_at);
CREATE TRIGGER carreira_eventos_sem_update BEFORE UPDATE ON carreira_eventos
BEGIN
    SELECT RAISE(ABORT, 'histórico da carreira é imutável');
END;
CREATE TRIGGER carreira_eventos_sem_delete BEFORE DELETE ON carreira_eventos
BEGIN
    SELECT RAISE(ABORT, 'histórico da carreira é imutável');
END;

-- carreira_envios.execucao_id aponta para carreira_execucoes, e com foreign_keys ligado o DROP da tabela-mãe falha
-- (e PRAGMA foreign_keys não muda dentro da transação): os vínculos saem antes e voltam com os mesmos ids.
CREATE TEMP TABLE talent_v22_vinculos AS SELECT id, execucao_id FROM carreira_envios WHERE execucao_id IS NOT NULL;
UPDATE carreira_envios SET execucao_id = NULL WHERE execucao_id IS NOT NULL;
CREATE TABLE carreira_execucoes_v22 (
    id           INTEGER PRIMARY KEY,
    tipo         TEXT NOT NULL CHECK (tipo IN ('busca', 'curriculo', 'candidatura', 'perfil', 'avaliacao', 'revisao',
                                               'analise')),
    vaga_id      TEXT REFERENCES carreira_vagas (id),
    estado       TEXT NOT NULL CHECK (estado IN ('executando', 'concluida', 'falhou', 'interrompida')),
    resultado    TEXT NOT NULL DEFAULT '',
    erro         TEXT NOT NULL DEFAULT '',
    started_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    finished_at  TEXT
);
INSERT INTO carreira_execucoes_v22 SELECT * FROM carreira_execucoes;
DROP TABLE carreira_execucoes;
ALTER TABLE carreira_execucoes_v22 RENAME TO carreira_execucoes;
CREATE INDEX carreira_execucoes_estado ON carreira_execucoes (estado, started_at);
CREATE INDEX carreira_execucoes_vaga ON carreira_execucoes (vaga_id);
UPDATE carreira_envios SET execucao_id = (SELECT t.execucao_id FROM talent_v22_vinculos t WHERE t.id = carreira_envios.id)
    WHERE id IN (SELECT id FROM talent_v22_vinculos);
DROP TABLE talent_v22_vinculos;
