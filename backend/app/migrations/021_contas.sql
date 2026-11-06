-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v21: Central de Contas e Acessos (docs/CONTAS.md). Compartilhada por Finanças e Carreira.
-- Só metadados: senha, token e cookie ficam no cofre cifrado do worker, nunca neste banco.

-- 1. Plataformas conhecidas e o estado do acesso de cada uma.
--    autenticacao: oauth (integração oficial) | sessao (login do dono no navegador do agente) | senha (cofre)
--    | env (configurada no servidor, fora da interface).
CREATE TABLE contas_plataformas (
    id                   TEXT PRIMARY KEY,
    nome                 TEXT NOT NULL,
    url_oficial          TEXT NOT NULL DEFAULT '',     -- vazio = plataforma vista pelo agente, endereço não verificado
    url_verificacao      TEXT NOT NULL DEFAULT '',     -- página que só abre com sessão ativa
    dominios_json        TEXT NOT NULL DEFAULT '[]',
    autenticacao         TEXT NOT NULL CHECK (autenticacao IN ('oauth', 'sessao', 'senha', 'env')),
    modulo               TEXT NOT NULL DEFAULT 'carreira' CHECK (modulo IN ('carreira', 'financas', 'sistema')),
    agentes_json         TEXT NOT NULL DEFAULT '["aplicador"]',
    estado               TEXT NOT NULL DEFAULT 'nao_configurada' CHECK (estado IN ('conectada', 'nao_configurada',
                         'sessao_expirada', 'aguardando_autenticacao', 'requer_verificacao', 'erro')),
    detalhe              TEXT NOT NULL DEFAULT '',
    tem_credencial       INTEGER NOT NULL DEFAULT 0,  -- espelho do cofre (sem o valor), atualizado pelo web app
    ultima_autenticacao  TEXT,                         -- última sessão confirmada
    ultima_verificacao   TEXT,
    updated_at           TEXT NOT NULL
);

-- 2. Pendências que os agentes abrem para o dono (login, cadastro, 2FA...). Uma aberta por (plataforma, tipo,
--    chave): o mesmo problema não duplica. chave = '' vale para a plataforma toda; = vaga_id quando é de uma vaga.
CREATE TABLE contas_pendencias (
    id           INTEGER PRIMARY KEY,
    plataforma   TEXT NOT NULL REFERENCES contas_plataformas (id),
    agente       TEXT NOT NULL,
    tipo         TEXT NOT NULL CHECK (tipo IN ('login', 'cadastro', 'sessao_expirada', 'verificacao_identidade',
                 'dois_fatores', 'confirmacao_email', 'informacao_ausente')),
    chave        TEXT NOT NULL DEFAULT '',
    motivo       TEXT NOT NULL,
    acao         TEXT NOT NULL,
    estado       TEXT NOT NULL DEFAULT 'aberta' CHECK (estado IN ('aberta', 'resolvida', 'descartada')),
    resolucao    TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    resolved_at  TEXT
);
CREATE UNIQUE INDEX contas_pendencias_uma_aberta ON contas_pendencias (plataforma, tipo, chave) WHERE estado = 'aberta';

-- 3. Candidatura em espera por acesso: status 'aguardando_acesso' + a pendência que a destrava.
ALTER TABLE carreira_candidaturas ADD COLUMN pendencia_id INTEGER REFERENCES contas_pendencias (id);
CREATE INDEX carreira_candidaturas_pendencia ON carreira_candidaturas (pendencia_id);

INSERT INTO contas_plataformas (id, nome, url_oficial, url_verificacao, dominios_json, autenticacao, modulo, agentes_json,
                                updated_at) VALUES
    ('gupy', 'Gupy', 'https://login.gupy.io/candidates/signin', 'https://login.gupy.io/candidates/applications',
     '["gupy.io"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('linkedin', 'LinkedIn', 'https://www.linkedin.com/login', 'https://www.linkedin.com/feed/',
     '["linkedin.com"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('catho', 'Catho', 'https://www.catho.com.br/', 'https://www.catho.com.br/area-candidato/',
     '["catho.com.br"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('indeed', 'Indeed', 'https://br.indeed.com/', 'https://myjobs.indeed.com/',
     '["indeed.com"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('programathor', 'ProgramaThor', 'https://programathor.com.br/', 'https://programathor.com.br/dashboard',
     '["programathor.com.br"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('infojobs', 'InfoJobs', 'https://www.infojobs.com.br/', 'https://www.infojobs.com.br/candidate/',
     '["infojobs.com.br"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('vagas', 'Vagas.com', 'https://www.vagas.com.br/', 'https://www.vagas.com.br/meu-perfil',
     '["vagas.com.br"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('google', 'Conta Google (Entrar com Google)', 'https://accounts.google.com/', 'https://myaccount.google.com/',
     '["google.com"]', 'sessao', 'carreira', '["aplicador"]', '2026-11-05T00:00:00+00:00'),
    ('gmail', 'Gmail (leitura de e-mails de vagas)', 'https://mail.google.com/', '',
     '["gmail.com","google.com"]', 'env', 'carreira', '["carteiro"]', '2026-11-05T00:00:00+00:00'),
    ('whatsapp', 'WhatsApp (Evolution API local)', '', '', '[]', 'env', 'sistema', '[]', '2026-11-05T00:00:00+00:00');
