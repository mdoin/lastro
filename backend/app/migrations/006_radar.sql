-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v6: Radar (observações versionadas, regras, sinais, alertas) e Diário de Oportunidades.
-- Compatível: só acrescenta tabelas. Fatos históricos são append-only (triggers); estado operacional
-- (estado da oportunidade, status do alerta) muda, mas cada mudança fica na linha do tempo (radar_events).

-- Metadados de cada série observada (catálogo fixo, títulos do Tesouro e ativos informados pela pessoa).
CREATE TABLE market_series (
    series_id      TEXT PRIMARY KEY,
    source         TEXT NOT NULL,          -- bcb_sgs | fred | ibge_sidra | tesouro_direto | pessoa
    label          TEXT NOT NULL,
    unit           TEXT NOT NULL,
    currency       TEXT,
    frequency      TEXT NOT NULL,          -- diaria | mensal | eventual
    category       TEXT NOT NULL,          -- macro | renda_fixa | acoes | etf | fii
    max_age_days   INTEGER NOT NULL,
    url            TEXT NOT NULL DEFAULT '',
    meta_json      TEXT NOT NULL DEFAULT '{}',
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL
);

-- Observações: revisão de um valor nunca sobrescreve a anterior (nova linha, revision+1, supersedes_id).
CREATE TABLE market_observations (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,
    series_id       TEXT NOT NULL REFERENCES market_series(series_id),
    reference_date  TEXT NOT NULL,
    value           TEXT NOT NULL,
    unit            TEXT NOT NULL,
    currency        TEXT,
    frequency       TEXT NOT NULL,
    revision        INTEGER NOT NULL,
    supersedes_id   INTEGER REFERENCES market_observations(id),
    fetched_at      TEXT NOT NULL,
    quality         TEXT NOT NULL DEFAULT 'ok' CHECK (quality IN ('ok', 'revisado', 'suspeito')),
    quality_json    TEXT NOT NULL DEFAULT '{}',
    UNIQUE (series_id, reference_date, revision)
);
CREATE INDEX market_observations_by_series ON market_observations (series_id, reference_date, revision);
CREATE TRIGGER market_observations_no_update BEFORE UPDATE ON market_observations
BEGIN SELECT RAISE(ABORT, 'observações são imutáveis: registre uma revisão'); END;

-- Estado de cada fonte (última verificação, erro, próxima tentativa respeitando limite do fornecedor).
CREATE TABLE market_source_status (
    source        TEXT PRIMARY KEY,
    checked_at    TEXT NOT NULL,
    ok            INTEGER NOT NULL,
    error         TEXT,
    next_at       TEXT,
    etag          TEXT,
    modified      TEXT
);

-- Regras: cada alteração é uma nova versão; a vigente é a de maior versão.
CREATE TABLE radar_rules (
    id               TEXT NOT NULL,
    version          INTEGER NOT NULL,
    user_id          TEXT NOT NULL,
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('limite', 'variacao', 'queda', 'reserva', 'dado_desatualizado')),
    category         TEXT NOT NULL CHECK (category IN ('renda_fixa', 'acoes', 'etf', 'fii', 'macro', 'patrimonio')),
    series_pattern   TEXT NOT NULL DEFAULT '',
    params_json      TEXT NOT NULL,
    priority         INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    interval_minutes INTEGER NOT NULL CHECK (interval_minutes >= 5),
    horizons_json    TEXT NOT NULL,
    benchmark        TEXT NOT NULL DEFAULT 'cdi',
    status           TEXT NOT NULL CHECK (status IN ('ativa', 'pausada', 'arquivada')),
    origin           TEXT NOT NULL CHECK (origin IN ('sistema', 'pessoa', 'proposta')),
    note             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    PRIMARY KEY (id, version)
);
CREATE TRIGGER radar_rules_immutable BEFORE UPDATE ON radar_rules
BEGIN SELECT RAISE(ABORT, 'versão de regra é imutável: crie uma nova versão'); END;
CREATE TRIGGER radar_rules_no_delete BEFORE DELETE ON radar_rules
BEGIN SELECT RAISE(ABORT, 'regras guardam histórico: arquive'); END;

CREATE TABLE radar_rule_state (
    rule_id            TEXT PRIMARY KEY,
    last_evaluated_at  TEXT,
    last_result        TEXT
);

-- Propostas de ajuste geradas pelos resultados: nunca entram em vigor sem a pessoa aprovar.
CREATE TABLE radar_rule_proposals (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    rule_id        TEXT NOT NULL,
    base_version   INTEGER NOT NULL,
    change_json    TEXT NOT NULL,
    rationale_json TEXT NOT NULL,
    backtest_id    TEXT,
    status         TEXT NOT NULL CHECK (status IN ('pendente', 'aprovada', 'recusada', 'obsoleta')),
    created_at     TEXT NOT NULL,
    decided_at     TEXT,
    FOREIGN KEY (rule_id, base_version) REFERENCES radar_rules(id, version)
);

CREATE TABLE radar_signals (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    rule_version    INTEGER NOT NULL,
    series_id       TEXT,
    observation_id  INTEGER REFERENCES market_observations(id),
    reference_date  TEXT NOT NULL,
    detected_at     TEXT NOT NULL,
    fingerprint     TEXT NOT NULL UNIQUE,
    condition_text  TEXT NOT NULL,
    values_json     TEXT NOT NULL,
    FOREIGN KEY (rule_id, rule_version) REFERENCES radar_rules(id, version)
);
CREATE INDEX radar_signals_by_rule ON radar_signals (rule_id, detected_at);
CREATE TRIGGER radar_signals_immutable BEFORE UPDATE ON radar_signals
BEGIN SELECT RAISE(ABORT, 'sinal é imutável'); END;
CREATE TRIGGER radar_signals_no_delete BEFORE DELETE ON radar_signals
BEGIN SELECT RAISE(ABORT, 'sinal é imutável'); END;
CREATE TRIGGER market_observations_keep_used BEFORE DELETE ON market_observations
WHEN EXISTS (SELECT 1 FROM radar_signals WHERE observation_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'observação usada por um sinal do Diário não pode ser apagada'); END;

-- Diário: uma oportunidade por sinal avaliado (inclusive as que não viraram alerta).
CREATE TABLE radar_opportunities (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    signal_id        TEXT NOT NULL UNIQUE REFERENCES radar_signals(id),
    rule_id          TEXT NOT NULL,
    category         TEXT NOT NULL,
    series_id        TEXT,
    asset_label      TEXT NOT NULL,
    classification   INTEGER NOT NULL CHECK (classification BETWEEN 1 AND 5),
    score            TEXT,
    state            TEXT NOT NULL CHECK (state IN ('detectada', 'em_analise', 'avaliada', 'alerta_emitido',
                                                    'em_acompanhamento', 'encerrada', 'invalidada', 'inconclusiva')),
    redundant_of     TEXT REFERENCES radar_opportunities(id),
    analysis_run_id  TEXT,
    created_at       TEXT NOT NULL,
    state_changed_at TEXT NOT NULL
);
CREATE INDEX radar_opportunities_by_user ON radar_opportunities (user_id, created_at);
CREATE INDEX radar_opportunities_by_state ON radar_opportunities (state);
CREATE TRIGGER radar_opportunities_no_delete BEFORE DELETE ON radar_opportunities
BEGIN SELECT RAISE(ABORT, 'o Diário não apaga oportunidades'); END;
-- Classificação original não muda depois de registrada.
CREATE TRIGGER radar_opportunities_keep_original BEFORE UPDATE OF classification, score, signal_id, created_at
ON radar_opportunities
BEGIN SELECT RAISE(ABORT, 'classificação original é imutável: registre uma correção'); END;

-- Registros imutáveis encadeados por hash: detecção, análise e correções versionadas.
CREATE TABLE radar_snapshots (
    id              TEXT PRIMARY KEY,
    opportunity_id  TEXT NOT NULL REFERENCES radar_opportunities(id),
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('deteccao', 'analise', 'correcao')),
    payload_json    TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    prev_sha256     TEXT,
    reason          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    UNIQUE (opportunity_id, seq)
);
CREATE TRIGGER radar_snapshots_immutable BEFORE UPDATE ON radar_snapshots
BEGIN SELECT RAISE(ABORT, 'registro do Diário é imutável: registre uma correção'); END;
CREATE TRIGGER radar_snapshots_no_delete BEFORE DELETE ON radar_snapshots
BEGIN SELECT RAISE(ABORT, 'registro do Diário é imutável'); END;

CREATE TABLE radar_events (
    id              TEXT PRIMARY KEY,
    opportunity_id  TEXT NOT NULL REFERENCES radar_opportunities(id),
    at              TEXT NOT NULL,
    kind            TEXT NOT NULL,
    detail_json     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX radar_events_by_opportunity ON radar_events (opportunity_id, at);
CREATE TRIGGER radar_events_immutable BEFORE UPDATE ON radar_events
BEGIN SELECT RAISE(ABORT, 'linha do tempo é append-only'); END;
CREATE TRIGGER radar_events_no_delete BEFORE DELETE ON radar_events
BEGIN SELECT RAISE(ABORT, 'linha do tempo é append-only'); END;

-- Avaliações posteriores: uma por horizonte e versão de método; recalcular = nova versão de método.
CREATE TABLE radar_outcomes (
    id              TEXT PRIMARY KEY,
    opportunity_id  TEXT NOT NULL REFERENCES radar_opportunities(id),
    horizon_days    INTEGER NOT NULL,
    method          TEXT NOT NULL,
    method_version  TEXT NOT NULL,
    due_date        TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('pendente', 'calculado', 'dados_insuficientes')),
    verdict         TEXT,
    result_json     TEXT NOT NULL DEFAULT '{}',
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    computed_at     TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (opportunity_id, horizon_days, method_version)
);
CREATE INDEX radar_outcomes_due ON radar_outcomes (status, due_date);
CREATE TRIGGER radar_outcomes_final BEFORE UPDATE ON radar_outcomes
WHEN OLD.status = 'calculado'
BEGIN SELECT RAISE(ABORT, 'avaliação calculada é imutável: recalcule com nova versão de método'); END;
CREATE TRIGGER radar_outcomes_no_delete BEFORE DELETE ON radar_outcomes
BEGIN SELECT RAISE(ABORT, 'avaliações guardam histórico'); END;

-- Alertas (estado operacional) e entregas (histórico).
CREATE TABLE radar_alerts (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL,
    opportunity_id     TEXT NOT NULL UNIQUE REFERENCES radar_opportunities(id),
    group_key          TEXT NOT NULL,
    title              TEXT NOT NULL,
    priority           INTEGER NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('novo', 'visto', 'analisado', 'silenciado')),
    occurrences        INTEGER NOT NULL DEFAULT 1,
    last_occurrence_at TEXT NOT NULL,
    feedback           TEXT CHECK (feedback IN ('util', 'irrelevante')),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX radar_alerts_by_user ON radar_alerts (user_id, status, created_at);
CREATE INDEX radar_alerts_by_group ON radar_alerts (group_key, created_at);

CREATE TABLE radar_deliveries (
    id         TEXT PRIMARY KEY,
    alert_id   TEXT NOT NULL REFERENCES radar_alerts(id),
    channel    TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('entregue', 'adiado', 'suprimido', 'nao_configurado', 'falhou')),
    reason     TEXT NOT NULL DEFAULT '',
    at         TEXT NOT NULL
);
CREATE INDEX radar_deliveries_by_alert ON radar_deliveries (alert_id, at);

CREATE TABLE radar_prefs (
    user_id               TEXT PRIMARY KEY,
    min_priority          INTEGER NOT NULL DEFAULT 3,
    quiet_start           TEXT NOT NULL DEFAULT '22:00',
    quiet_end             TEXT NOT NULL DEFAULT '07:00',
    max_per_day           INTEGER NOT NULL DEFAULT 5,
    cooldown_hours        INTEGER NOT NULL DEFAULT 72,
    max_analyses_per_day  INTEGER NOT NULL DEFAULT 4,
    updated_at            TEXT NOT NULL
);

-- Canais externos: exigem configuração e consentimento explícito; sem isso, a entrega fica "não configurado".
CREATE TABLE radar_channels (
    user_id     TEXT NOT NULL,
    channel     TEXT NOT NULL CHECK (channel IN ('email', 'telegram', 'webpush')),
    enabled     INTEGER NOT NULL DEFAULT 0,
    consent_at  TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, channel)
);

CREATE TABLE radar_mutes (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    group_key   TEXT NOT NULL,
    until       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Decisões da pessoa (append-only) e operações reais informadas por ela, separadas do desempenho hipotético.
CREATE TABLE radar_decisions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    opportunity_id  TEXT NOT NULL REFERENCES radar_opportunities(id),
    decision        TEXT NOT NULL CHECK (decision IN ('analisei', 'ignorei', 'decidi_investir', 'decidi_nao_investir',
                                                      'acompanhar', 'outra')),
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE TRIGGER radar_decisions_immutable BEFORE UPDATE ON radar_decisions
BEGIN SELECT RAISE(ABORT, 'decisões são append-only'); END;
CREATE TRIGGER radar_decisions_no_delete BEFORE DELETE ON radar_decisions
BEGIN SELECT RAISE(ABORT, 'decisões são append-only'); END;

CREATE TABLE radar_user_operations (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    opportunity_id  TEXT NOT NULL REFERENCES radar_opportunities(id),
    operation_date  TEXT NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('entrada', 'saida')),
    amount          TEXT NOT NULL,
    unit_price      TEXT,
    note            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE TRIGGER radar_user_operations_immutable BEFORE UPDATE ON radar_user_operations
BEGIN SELECT RAISE(ABORT, 'operações informadas são append-only'); END;
CREATE TRIGGER radar_user_operations_no_delete BEFORE DELETE ON radar_user_operations
BEGIN SELECT RAISE(ABORT, 'operações informadas são append-only'); END;

-- Eventos corporativos informados (desdobramento/grupamento/bonificação) para ajustar preços de ativos.
CREATE TABLE radar_corporate_events (
    id          TEXT PRIMARY KEY,
    series_id   TEXT NOT NULL REFERENCES market_series(series_id),
    ex_date     TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('desdobramento', 'grupamento', 'bonificacao')),
    factor      TEXT NOT NULL,          -- ações após / ações antes (2 = desdobramento 1:2)
    source      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (series_id, ex_date, kind)
);

-- Backtests: resultados simulados, guardados à parte (nunca entram nas métricas de alertas reais).
CREATE TABLE radar_backtests (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    rule_id       TEXT NOT NULL,
    rule_version  INTEGER NOT NULL,
    params_json   TEXT NOT NULL,
    result_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- Conversas abertas a partir de uma oportunidade (análise do Radar, Mentor, Conselho): o vínculo não se perde.
CREATE TABLE radar_links (
    opportunity_id   TEXT NOT NULL REFERENCES radar_opportunities(id),
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    purpose          TEXT NOT NULL CHECK (purpose IN ('analise', 'mentor', 'conselho')),
    created_at       TEXT NOT NULL,
    PRIMARY KEY (opportunity_id, conversation_id)
);
CREATE INDEX radar_links_by_conversation ON radar_links (conversation_id);
