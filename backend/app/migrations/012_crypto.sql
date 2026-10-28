-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v12: inteligência de mercado cripto e central de notificações (docs/CRYPTO.md).
-- Compatível: só cria tabelas. Nada aqui compra, vende, custodia ou move ativos.

-- Cotações normalizadas (moeda de cotação explícita: USDT ≠ USD ≠ BRL) e velas por fonte.
CREATE TABLE crypto_quotes (
    source           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    stable_id        TEXT NOT NULL,
    quote_currency   TEXT NOT NULL CHECK (quote_currency IN ('USDT', 'USD', 'BRL')),
    price            TEXT NOT NULL,
    reference_time   TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    volume_24h       TEXT,
    quote_volume_24h TEXT,
    change_24h_pct   TEXT,
    market_cap       TEXT,
    status           TEXT NOT NULL,
    PRIMARY KEY (source, symbol, quote_currency, reference_time)
);
CREATE INDEX crypto_quotes_latest ON crypto_quotes (symbol, quote_currency, fetched_at);

CREATE TABLE crypto_candles (
    source        TEXT NOT NULL,
    pair          TEXT NOT NULL,
    interval      TEXT NOT NULL,
    open_time     TEXT NOT NULL,
    close_time    TEXT NOT NULL,
    open          TEXT NOT NULL,
    high          TEXT NOT NULL,
    low           TEXT NOT NULL,
    close         TEXT NOT NULL,
    volume        TEXT NOT NULL,
    quote_volume  TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (source, pair, interval, open_time)
);

-- TVL (DefiLlama): por rede ou protocolo, por dia.
CREATE TABLE crypto_tvl (
    source      TEXT NOT NULL,
    scope       TEXT NOT NULL CHECK (scope IN ('chain', 'protocol', 'total')),
    key         TEXT NOT NULL,
    day         TEXT NOT NULL,
    tvl         TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source, scope, key, day)
);

-- Estado de cada trabalho do coletor: retomada após reinício, saúde e trava (lease) para um só executor.
CREATE TABLE crypto_jobs (
    job            TEXT PRIMARY KEY,
    last_run_at    TEXT,
    last_ok_at     TEXT,
    last_error     TEXT,
    lease_owner    TEXT,
    lease_until    TEXT,
    runs           INTEGER NOT NULL DEFAULT 0,
    failures       INTEGER NOT NULL DEFAULT 0,
    latency_ms     INTEGER,
    health_json    TEXT NOT NULL DEFAULT '{}'
);

-- Consumo mensal por provedor (cota da CoinGecko Demo sobrevive a reinícios).
CREATE TABLE crypto_usage (
    provider  TEXT NOT NULL,
    month     TEXT NOT NULL,
    calls     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, month)
);

-- Preferências do monitoramento. Reuniões autônomas exigem opt-in explícito (autonomous = 1); padrão desligado.
CREATE TABLE crypto_prefs (
    user_id               TEXT PRIMARY KEY,
    watchlist_json        TEXT NOT NULL DEFAULT '["BTC","ETH","SOL"]',
    holdings_json         TEXT NOT NULL DEFAULT '{}',
    sensitivity           TEXT NOT NULL DEFAULT 'media' CHECK (sensitivity IN ('baixa', 'media', 'alta')),
    muted_json            TEXT NOT NULL DEFAULT '[]',
    concentration_limit   TEXT NOT NULL DEFAULT '0.25',
    autonomous            INTEGER NOT NULL DEFAULT 0,
    deliver               TEXT NOT NULL DEFAULT 'alertas' CHECK (deliver IN ('alertas', 'analises')),
    min_severity          TEXT NOT NULL DEFAULT 'conselho' CHECK (min_severity IN ('atencao', 'risco', 'conselho')),
    max_meetings_per_day  INTEGER NOT NULL DEFAULT 2,
    cooldown_hours        INTEGER NOT NULL DEFAULT 12,
    quiet_start           TEXT NOT NULL DEFAULT '22:00',
    quiet_end             TEXT NOT NULL DEFAULT '07:00',
    paused_until          TEXT,
    monthly_token_budget  INTEGER NOT NULL DEFAULT 0,
    updated_at            TEXT NOT NULL
);

-- Eventos detectados (sinais agrupados). Deduplicação por causa e janela; atualizações somam no mesmo evento.
CREATE TABLE crypto_events (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    dedup_key        TEXT NOT NULL,
    asset            TEXT NOT NULL,
    categories_json  TEXT NOT NULL,
    direction        TEXT NOT NULL,
    severity         TEXT NOT NULL,
    relevance        TEXT NOT NULL,
    data_quality     TEXT NOT NULL,
    hypothesis       TEXT NOT NULL,
    indicators_json  TEXT NOT NULL,
    evidence_json    TEXT NOT NULL,
    sources_json     TEXT NOT NULL,
    first_seen_at    TEXT NOT NULL,
    last_seen_at     TEXT NOT NULL,
    updates          INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL CHECK (status IN ('registrado', 'alerta', 'reuniao', 'pendente', 'descartado')),
    reason           TEXT NOT NULL DEFAULT '',
    conversation_id  TEXT,
    run_id           TEXT,
    UNIQUE (user_id, dedup_key)
);
CREATE INDEX crypto_events_by_user ON crypto_events (user_id, last_seen_at);

-- Central de notificações internas (sem serviço externo).
CREATE TABLE notifications (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    link        TEXT NOT NULL DEFAULT '',
    ref         TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'novo' CHECK (status IN ('novo', 'lido')),
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, kind, ref)
);
CREATE INDEX notifications_by_user ON notifications (user_id, status, created_at);
