-- Bitcoin Health Scorecard Database Schema
-- SQLite3 compatible

-- Raw data tables (append-only)
-- These store raw API responses for audit trail and recomputation

-- Mempool snapshots (hourly)
CREATE TABLE IF NOT EXISTS raw_mempool_snapshot (
    ts INTEGER PRIMARY KEY,  -- Unix timestamp
    count INTEGER,           -- Number of transactions
    vsize INTEGER,           -- Virtual size in bytes
    total_fee INTEGER,       -- Total fees in satoshis
    fee_hist JSON           -- Fee histogram data
);

-- Difficulty adjustment estimates (hourly)
CREATE TABLE IF NOT EXISTS raw_difficulty_estimate (
    ts INTEGER PRIMARY KEY,
    progress REAL,          -- Progress percentage through epoch
    est_change REAL,        -- Estimated percentage change
    est_date TEXT          -- Estimated retarget date
);

-- Mining pool shares (daily)
CREATE TABLE IF NOT EXISTS raw_pool_shares (
    ts INTEGER,
    pool TEXT,
    share REAL,            -- Percentage share (0-100)
    blocks INTEGER,        -- Number of blocks mined
    PRIMARY KEY (ts, pool)
);

-- Block rewards tracking (daily)
CREATE TABLE IF NOT EXISTS raw_block_rewards (
    day TEXT PRIMARY KEY,   -- YYYY-MM-DD format
    fees_btc REAL,         -- Total fees in BTC
    subsidy_btc REAL,      -- Total subsidy in BTC
    blocks INTEGER,        -- Number of blocks
    avg_fee_per_block REAL
);

-- Bitnodes network snapshot (6-hourly due to rate limits)
CREATE TABLE IF NOT EXISTS raw_bitnodes_snapshot (
    ts INTEGER PRIMARY KEY,
    total_nodes INTEGER,
    user_agents JSON,      -- Client version distribution
    asn_counts JSON,       -- ASN distribution
    tor_nodes INTEGER,     -- Number of Tor nodes
    countries JSON         -- Country distribution
);

-- UTXO set size (daily)
CREATE TABLE IF NOT EXISTS raw_utxo_count (
    day TEXT PRIMARY KEY,
    utxos INTEGER,
    change_24h REAL,       -- Percentage change
    change_7d REAL
);

-- Bitcoin price (hourly)
CREATE TABLE IF NOT EXISTS raw_price (
    ts INTEGER PRIMARY KEY,
    price_usd REAL,
    volume_24h REAL,
    market_cap REAL
);

-- Stale block incidents from ForkMonitor
CREATE TABLE IF NOT EXISTS raw_stale_incidents (
    ts INTEGER PRIMARY KEY,
    height INTEGER,
    pool TEXT,
    hash TEXT,
    description TEXT
);

-- Lightning Network statistics (daily)
CREATE TABLE IF NOT EXISTS raw_ln_stats (
    day TEXT PRIMARY KEY,
    capacity_btc REAL,
    channels INTEGER,
    nodes INTEGER,
    avg_capacity REAL,     -- Average channel capacity
    avg_fee_rate REAL      -- Average fee rate
);

-- SegWit/Taproot adoption (daily)
CREATE TABLE IF NOT EXISTS raw_segwit_stats (
    day TEXT PRIMARY KEY,
    segwit_tx_count INTEGER,
    total_tx_count INTEGER,
    segwit_weight INTEGER,
    total_weight INTEGER,
    taproot_tx_count INTEGER
);

-- RBF replacement activity (hourly)
CREATE TABLE IF NOT EXISTS raw_rbf_stats (
    ts INTEGER PRIMARY KEY,
    replacements INTEGER,
    fullrbf_replacements INTEGER,
    total_tx INTEGER,
    rbf_share REAL
);

-- Computed metrics table (wide format)
CREATE TABLE IF NOT EXISTS metrics (
    metric_id TEXT,        -- e.g., 'security.hashprice', 'decent.pool_hhi'
    ts INTEGER,
    value REAL,
    unit TEXT,             -- Optional unit descriptor
    PRIMARY KEY(metric_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);
CREATE INDEX IF NOT EXISTS idx_metrics_id ON metrics(metric_id);

-- Rolling percentiles for normalization
CREATE TABLE IF NOT EXISTS percentiles (
    metric_id TEXT,
    window_days INTEGER,   -- 90, 365, etc.
    ts INTEGER,
    p10 REAL,
    p25 REAL,
    p50 REAL,
    p75 REAL,
    p90 REAL,
    min_val REAL,
    max_val REAL,
    PRIMARY KEY(metric_id, window_days, ts)
);

-- Computed scores
CREATE TABLE IF NOT EXISTS scores (
    kind TEXT,             -- 'metric' | 'pillar' | 'overall'
    id TEXT,               -- metric_id, pillar_id, or 'overall'
    ts INTEGER,
    score REAL,            -- 0-100
    trend_7d REAL,         -- Percentage change over 7 days
    trend_30d REAL,        -- Percentage change over 30 days
    PRIMARY KEY(kind, id, ts)
);
CREATE INDEX IF NOT EXISTS idx_scores_ts ON scores(ts);

-- Metadata and configuration
CREATE TABLE IF NOT EXISTS meta_config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER
);

-- Insert default configuration
INSERT OR IGNORE INTO meta_config (key, value, updated_at) VALUES
    ('version', '1.0.0', strftime('%s', 'now')),
    ('last_collection', NULL, NULL),
    ('last_computation', NULL, NULL);

-- Collection status tracking
CREATE TABLE IF NOT EXISTS collection_status (
    collector TEXT PRIMARY KEY,
    last_run INTEGER,
    last_success INTEGER,
    last_error TEXT,
    consecutive_failures INTEGER DEFAULT 0
);

-- Pillar definitions
CREATE TABLE IF NOT EXISTS pillar_definitions (
    pillar_id TEXT PRIMARY KEY,
    name TEXT,
    weight REAL,           -- Weight in overall score (0-1)
    description TEXT
);

INSERT OR REPLACE INTO pillar_definitions (pillar_id, name, weight, description) VALUES
    ('security', 'Security & Mining Economics', 0.30, 'Difficulty momentum, fee share, hashprice, stale blocks'),
    ('decent', 'Decentralization & Resilience', 0.25, 'Mining pool concentration, node diversity, client diversity'),
    ('throughput', 'Throughput & Mempool Dynamics', 0.15, 'Mempool backlog, fee market elasticity, confirmation times'),
    ('adoption', 'Adoption & Protocol Efficiency', 0.15, 'UTXO growth, SegWit/Taproot utilization, RBF activity'),
    ('lightning', 'Lightning Network Vitality', 0.15, 'Capacity growth, channel distribution, node concentration');

-- Metric definitions
CREATE TABLE IF NOT EXISTS metric_definitions (
    metric_id TEXT PRIMARY KEY,
    pillar_id TEXT,
    name TEXT,
    direction TEXT,        -- 'higher_better' | 'lower_better' | 'target_band'
    target_min REAL,       -- For target_band metrics
    target_max REAL,       -- For target_band metrics
    weight REAL,           -- Weight within pillar
    description TEXT,
    FOREIGN KEY (pillar_id) REFERENCES pillar_definitions(pillar_id)
);

-- Insert metric definitions
INSERT OR REPLACE INTO metric_definitions (metric_id, pillar_id, name, direction, target_min, target_max, weight, description) VALUES
    -- Security metrics
    ('security.difficulty_momentum', 'security', 'Difficulty Momentum', 'lower_better', NULL, NULL, 0.25, 'Stability of difficulty adjustments'),
    ('security.fee_share', 'security', 'Fee Share of Revenue', 'higher_better', NULL, NULL, 0.25, '30-day average fee percentage of miner revenue'),
    ('security.hashprice', 'security', 'Hashprice (USD/TH/day)', 'higher_better', NULL, NULL, 0.25, 'Mining profitability indicator'),
    ('security.stale_incidence', 'security', 'Stale Block Rate', 'lower_better', NULL, NULL, 0.25, 'Frequency of stale blocks and reorgs'),
    
    -- Decentralization metrics
    ('decent.pool_hhi', 'decent', 'Mining Pool HHI', 'lower_better', NULL, NULL, 0.35, 'Herfindahl-Hirschman Index of mining pools'),
    ('decent.node_asn_hhi', 'decent', 'Node ASN HHI', 'lower_better', NULL, NULL, 0.35, 'ASN concentration of nodes'),
    ('decent.client_entropy', 'decent', 'Client Version Entropy', 'higher_better', NULL, NULL, 0.30, 'Diversity of node implementations'),
    
    -- Throughput metrics
    ('throughput.mempool_pressure', 'throughput', 'Mempool Backlog', 'lower_better', NULL, NULL, 0.35, 'Virtual size of mempool backlog'),
    ('throughput.fee_elasticity', 'throughput', 'Fee Market Elasticity', 'higher_better', NULL, NULL, 0.35, 'Correlation between mempool size and fees'),
    ('throughput.confirm_latency', 'throughput', 'Confirmation Latency', 'lower_better', NULL, NULL, 0.30, 'Time to confirm at target fee rates'),
    
    -- Adoption metrics
    ('adoption.utxo_growth', 'adoption', 'UTXO Growth Pressure', 'lower_better', NULL, NULL, 0.30, 'Rate of UTXO set expansion'),
    ('adoption.segwit_usage', 'adoption', 'SegWit Utilization', 'higher_better', NULL, NULL, 0.35, 'Percentage of SegWit transactions'),
    ('adoption.rbf_activity', 'adoption', 'RBF Activity', 'target_band', 2, 15, 0.35, 'Replace-by-fee transaction percentage'),
    
    -- Lightning metrics
    ('lightning.capacity_growth', 'lightning', 'Capacity Growth', 'higher_better', NULL, NULL, 0.50, '30-day Lightning capacity change'),
    ('lightning.node_concentration', 'lightning', 'Node Concentration', 'lower_better', NULL, NULL, 0.50, 'Top node liquidity concentration');

-- Views for easier querying
CREATE VIEW IF NOT EXISTS latest_scores AS
SELECT 
    kind,
    id,
    score,
    trend_7d,
    trend_30d,
    ts
FROM scores
WHERE ts = (SELECT MAX(ts) FROM scores s2 WHERE s2.kind = scores.kind AND s2.id = scores.id);

CREATE VIEW IF NOT EXISTS latest_metrics AS
SELECT 
    metric_id,
    value,
    unit,
    ts
FROM metrics
WHERE ts = (SELECT MAX(ts) FROM metrics m2 WHERE m2.metric_id = metrics.metric_id);
