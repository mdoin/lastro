-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v18: Carreira como módulo (docs/CARREIRA.md). Compatível: colunas e tabelas novas; dados antigos preservados.
-- Separa quatro coisas que antes dividiam o mesmo campo: estado do envio (carreira_candidaturas.status), etapa
-- informada pela empresa (carreira_candidaturas.etapa), execuções dos agentes (carreira_execucoes) e histórico
-- imutável (carreira_eventos).

-- 1. Vagas: URL canônica e chave empresa|cargo|local para achar a mesma vaga vinda de fontes diferentes.
--    O caçador preenche; as vagas antigas são preenchidas quando o serviço inicia.
ALTER TABLE carreira_vagas ADD COLUMN url_canonica TEXT;
ALTER TABLE carreira_vagas ADD COLUMN chave TEXT;
CREATE INDEX carreira_vagas_url_canonica ON carreira_vagas (url_canonica);
CREATE INDEX carreira_vagas_chave ON carreira_vagas (chave);
CREATE INDEX carreira_vagas_first_seen ON carreira_vagas (first_seen);

-- 2. Versões de currículo, imutáveis: a base (arquivo curriculo.md do dono) e as feitas pelo Alfaiate por vaga.
CREATE TABLE carreira_curriculos (
    id               INTEGER PRIMARY KEY,
    tipo             TEXT NOT NULL CHECK (tipo IN ('base', 'vaga')),
    vaga_id          TEXT REFERENCES carreira_vagas (id),
    origem_id        INTEGER REFERENCES carreira_curriculos (id),   -- base vigente quando a versão foi feita
    conteudo_md      TEXT NOT NULL,
    alteracoes_json  TEXT NOT NULL DEFAULT '[]',                     -- o que o Alfaiate diz ter mudado
    created_at       TEXT NOT NULL,
    CHECK ((tipo = 'base') = (vaga_id IS NULL))
);
CREATE INDEX carreira_curriculos_vaga ON carreira_curriculos (vaga_id);
CREATE TRIGGER carreira_curriculos_imutavel BEFORE UPDATE ON carreira_curriculos
BEGIN
    SELECT RAISE(ABORT, 'versão de currículo é imutável');
END;
INSERT INTO carreira_curriculos (tipo, vaga_id, conteudo_md, created_at)
    SELECT 'vaga', vaga_id, curriculo_md, created_at FROM carreira_candidaturas;

-- 3. Candidatura: etapa do processo seletivo separada do estado do envio.
--    status: curriculo (preparando) | precisa_de_voce | incerta (resultado desconhecido) | falhou | candidatada
--            | encerrada (não aplicável) | retirada
--    etapa:  NULL (sem retorno) | em_analise | teste | entrevista | proposta | recusada (rejeição confirmada)
ALTER TABLE carreira_candidaturas ADD COLUMN etapa TEXT
    CHECK (etapa IN ('em_analise', 'teste', 'entrevista', 'proposta', 'recusada'));
ALTER TABLE carreira_candidaturas ADD COLUMN curriculo_id INTEGER REFERENCES carreira_curriculos (id);
UPDATE carreira_candidaturas
    SET etapa = CASE status WHEN 'em_processo' THEN 'em_analise' ELSE status END, status = 'candidatada'
    WHERE status IN ('em_processo', 'teste', 'entrevista', 'proposta', 'recusada');
UPDATE carreira_candidaturas
    SET curriculo_id = (SELECT id FROM carreira_curriculos k WHERE k.vaga_id = carreira_candidaturas.vaga_id);

-- 4. Execuções dos agentes de carreira (estado operacional, nunca confundido com o da candidatura).
CREATE TABLE carreira_execucoes (
    id           INTEGER PRIMARY KEY,
    tipo         TEXT NOT NULL CHECK (tipo IN ('busca', 'curriculo', 'candidatura', 'perfil')),
    vaga_id      TEXT REFERENCES carreira_vagas (id),
    estado       TEXT NOT NULL CHECK (estado IN ('executando', 'concluida', 'falhou', 'interrompida')),
    resultado    TEXT NOT NULL DEFAULT '',
    erro         TEXT NOT NULL DEFAULT '',
    started_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    finished_at  TEXT
);
CREATE INDEX carreira_execucoes_estado ON carreira_execucoes (estado, started_at);
CREATE INDEX carreira_execucoes_vaga ON carreira_execucoes (vaga_id);

-- 5. Tentativas de envio: resultado desconhecido ("incerta"), evidência de sucesso e o currículo anexado.
--    SQLite não altera CHECK: a tabela é refeita com os mesmos dados.
CREATE TABLE carreira_envios_v18 (
    id              INTEGER PRIMARY KEY,
    vaga_id         TEXT NOT NULL REFERENCES carreira_vagas (id),
    status          TEXT NOT NULL CHECK (status IN ('enviada', 'incerta', 'precisa_de_voce', 'nao_aplicavel', 'falhou')),
    motivo          TEXT NOT NULL,
    url_final       TEXT NOT NULL DEFAULT '',
    respostas_json  TEXT NOT NULL DEFAULT '[]',
    evidencia       TEXT NOT NULL DEFAULT '',
    curriculo_id    INTEGER REFERENCES carreira_curriculos (id),
    execucao_id     INTEGER REFERENCES carreira_execucoes (id),
    created_at      TEXT NOT NULL
);
INSERT INTO carreira_envios_v18 (id, vaga_id, status, motivo, url_final, respostas_json, curriculo_id, created_at)
    SELECT e.id, e.vaga_id, e.status, e.motivo, e.url_final, e.respostas_json,
           (SELECT id FROM carreira_curriculos k WHERE k.vaga_id = e.vaga_id), e.created_at
    FROM carreira_envios e;
DROP TABLE carreira_envios;
ALTER TABLE carreira_envios_v18 RENAME TO carreira_envios;
CREATE INDEX carreira_envios_vaga ON carreira_envios (vaga_id, created_at);

-- 6. Histórico imutável por vaga/candidatura. origem = agente ou pessoa que causou o evento.
CREATE TABLE carreira_eventos (
    id            INTEGER PRIMARY KEY,
    vaga_id       TEXT NOT NULL REFERENCES carreira_vagas (id),
    tipo          TEXT NOT NULL,
    origem        TEXT NOT NULL CHECK (origem IN ('cacador', 'alfaiate', 'aplicador', 'carteiro', 'dono', 'sistema')),
    detalhe_json  TEXT NOT NULL DEFAULT '{}',
    envio_id      INTEGER REFERENCES carreira_envios (id),
    created_at    TEXT NOT NULL
);
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

-- Histórico reconstruído do que já estava gravado (marcado com "reconstruido": 1).
INSERT INTO carreira_eventos (vaga_id, tipo, origem, detalhe_json, created_at)
    SELECT id, 'descoberta', 'cacador',
           json_object('fonte', source, 'veredito', verdict, 'pontuacao', score, 'reconstruido', 1), first_seen
    FROM carreira_vagas;
INSERT INTO carreira_eventos (vaga_id, tipo, origem, detalhe_json, created_at)
    SELECT vaga_id, 'curriculo_preparado', 'alfaiate',
           json_object('aderencia', aderencia, 'curriculo_id', curriculo_id, 'reconstruido', 1), created_at
    FROM carreira_candidaturas;
INSERT INTO carreira_eventos (vaga_id, tipo, origem, detalhe_json, envio_id, created_at)
    SELECT vaga_id,
           CASE status WHEN 'enviada' THEN 'candidatura_enviada' WHEN 'precisa_de_voce' THEN 'intervencao_solicitada'
                       WHEN 'nao_aplicavel' THEN 'candidatura_nao_aplicavel' ELSE 'candidatura_falhou' END,
           'aplicador', json_object('motivo', motivo, 'reconstruido', 1), id, created_at
    FROM carreira_envios;
INSERT INTO carreira_eventos (vaga_id, tipo, origem, detalhe_json, created_at)
    SELECT vaga_id, 'resposta', 'carteiro', json_object('tipo', tipo, 'resumo', resumo, 'reconstruido', 1), created_at
    FROM carreira_emails WHERE vaga_id IS NOT NULL;
