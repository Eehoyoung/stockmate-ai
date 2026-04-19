CREATE TABLE IF NOT EXISTS human_confirm_requests (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(80) NOT NULL UNIQUE,
    signal_id BIGINT NULL,
    stk_cd VARCHAR(16) NOT NULL,
    stk_nm VARCHAR(120),
    strategy VARCHAR(64) NOT NULL,
    rule_score NUMERIC(6, 2),
    rr_ratio NUMERIC(8, 2),
    status VARCHAR(24) NOT NULL DEFAULT 'PENDING',
    payload JSONB NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ NULL,
    decision_chat_id BIGINT NULL,
    decision_message_id BIGINT NULL,
    last_sent_at TIMESTAMPTZ NULL,
    last_enqueued_at TIMESTAMPTZ NULL,
    ai_score NUMERIC(6, 2) NULL,
    ai_action VARCHAR(24) NULL,
    ai_confidence VARCHAR(24) NULL,
    ai_reason TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_human_confirm_requests_status_expires
    ON human_confirm_requests (status, expires_at);

CREATE INDEX IF NOT EXISTS idx_human_confirm_requests_signal_id
    ON human_confirm_requests (signal_id);
