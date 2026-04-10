-- V11: strategy_param_history — 파라미터 변경 이력

CREATE TABLE IF NOT EXISTS strategy_param_history (
    id              BIGSERIAL PRIMARY KEY,
    strategy        VARCHAR(30) NOT NULL,
    param_name      VARCHAR(50) NOT NULL,
    old_value       VARCHAR(100),
    new_value       VARCHAR(100) NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by      VARCHAR(50),
    reason          TEXT
);

CREATE INDEX IF NOT EXISTS idx_sph_strategy ON strategy_param_history(strategy, changed_at DESC);

-- 현재 임계값 초기 스냅샷 (changed_at 명시 — Hibernate DDL에 DB-level DEFAULT 없음)
INSERT INTO strategy_param_history (strategy, param_name, old_value, new_value, changed_by, reason, changed_at) VALUES
('S1_GAP_OPEN',        'threshold', NULL, '70',  'system', '초기 설정', NOW()),
('S2_VI_PULLBACK',     'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S3_INST_FOREIGN',    'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S4_BIG_CANDLE',      'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S5_PROGRAM_BUY',     'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S6_THEME',           'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S7_AUCTION',         'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S8_GOLDEN_CROSS',    'threshold', NULL, '60',  'system', '초기 설정', NOW()),
('S9_PULLBACK_SWING',  'threshold', NULL, '55',  'system', '초기 설정', NOW()),
('S10_NEW_HIGH',       'threshold', NULL, '58',  'system', '초기 설정', NOW()),
('S11_FRGN_CONT',      'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S12_CLOSING',        'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S13_BOX_BREAKOUT',   'threshold', NULL, '65',  'system', '초기 설정', NOW()),
('S14_OVERSOLD_BOUNCE','threshold', NULL, '60',  'system', '초기 설정', NOW()),
('S15_MOMENTUM_ALIGN', 'threshold', NULL, '65',  'system', '초기 설정', NOW());
