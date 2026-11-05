-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v20: currículo-base estruturado e documentos (PDF/DOCX) guardados por versão (docs/CARREIRA.md).
-- Compatível: só tabela e colunas novas; as versões antigas (só Markdown) continuam legíveis.

-- 1. Currículo-base estruturado, versionado e imutável: a fonte de verdade dos documentos. Cada fato traz
--    status (confirmado | pendente | inferido | descartado) e fonte; só "confirmado" entra num documento.
CREATE TABLE carreira_base (
    id             INTEGER PRIMARY KEY,
    conteudo_json  TEXT NOT NULL,
    origem         TEXT NOT NULL CHECK (origem IN ('importacao', 'dono')),
    nota           TEXT NOT NULL DEFAULT '',          -- o que mudou nesta versão
    created_at     TEXT NOT NULL
);
CREATE TRIGGER carreira_base_imutavel BEFORE UPDATE ON carreira_base
BEGIN
    SELECT RAISE(ABORT, 'versão do currículo-base é imutável');
END;

-- 2. Versões de currículo com o documento exato: perfil de apresentação (backend | ai | junior), idioma, base de
--    origem, a seleção montada, os arquivos gerados e o relatório de validação. tipo 'base' + perfil = versão
--    geral de um perfil; tipo 'vaga' = versão personalizada.
ALTER TABLE carreira_curriculos ADD COLUMN perfil TEXT;
ALTER TABLE carreira_curriculos ADD COLUMN idioma TEXT;
ALTER TABLE carreira_curriculos ADD COLUMN base_id INTEGER REFERENCES carreira_base (id);
ALTER TABLE carreira_curriculos ADD COLUMN documento_json TEXT;
ALTER TABLE carreira_curriculos ADD COLUMN pdf BLOB;
ALTER TABLE carreira_curriculos ADD COLUMN docx BLOB;
ALTER TABLE carreira_curriculos ADD COLUMN validacao_json TEXT;
ALTER TABLE carreira_curriculos ADD COLUMN sha256 TEXT;          -- do PDF, para conferir o arquivo enviado
CREATE INDEX carreira_curriculos_base ON carreira_curriculos (base_id, perfil);

-- 3. O que foi de fato anexado em cada tentativa: 'pdf', 'docx', ou a descrição do documento da própria
--    plataforma quando ela não aceita currículo personalizado (ex.: candidatura fácil com o CV do perfil).
ALTER TABLE carreira_envios ADD COLUMN anexo TEXT NOT NULL DEFAULT '';
