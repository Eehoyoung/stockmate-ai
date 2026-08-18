CREATE TABLE ai_api_usage (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(20) NOT NULL,
    purpose VARCHAR(40) NOT NULL,
    model VARCHAR(80) NOT NULL,
    request_id VARCHAR(100),
    status VARCHAR(10) NOT NULL CHECK (status IN ('SUCCESS', 'ERROR')),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_write_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
    cache_read_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cost_usd NUMERIC(14, 8) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_type VARCHAR(120),
    error_message VARCHAR(1000)
);

CREATE INDEX idx_ai_api_usage_created_at ON ai_api_usage (created_at DESC);
CREATE INDEX idx_ai_api_usage_purpose_created_at ON ai_api_usage (purpose, created_at DESC);

COMMENT ON TABLE ai_api_usage IS 'Claude call usage audit; ai-engine retains at least 90 days.';
