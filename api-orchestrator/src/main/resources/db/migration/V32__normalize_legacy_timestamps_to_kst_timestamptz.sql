ALTER TABLE kiwoom_token
    ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING CASE
        WHEN expires_at IS NULL THEN NULL
        ELSE expires_at AT TIME ZONE 'Asia/Seoul'
    END,
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING CASE
        WHEN created_at IS NULL THEN NULL
        ELSE created_at AT TIME ZONE 'Asia/Seoul'
    END;

ALTER TABLE trading_signals
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING CASE
        WHEN created_at IS NULL THEN NULL
        ELSE created_at AT TIME ZONE 'UTC'
    END,
    ALTER COLUMN executed_at TYPE TIMESTAMPTZ USING CASE
        WHEN executed_at IS NULL THEN NULL
        ELSE executed_at AT TIME ZONE 'UTC'
    END,
    ALTER COLUMN closed_at TYPE TIMESTAMPTZ USING CASE
        WHEN closed_at IS NULL THEN NULL
        ELSE closed_at AT TIME ZONE 'UTC'
    END;

ALTER TABLE vi_events
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING CASE
        WHEN created_at IS NULL THEN NULL
        ELSE created_at AT TIME ZONE 'Asia/Seoul'
    END,
    ALTER COLUMN released_at TYPE TIMESTAMPTZ USING CASE
        WHEN released_at IS NULL THEN NULL
        ELSE released_at AT TIME ZONE 'Asia/Seoul'
    END;

ALTER TABLE ws_tick_data
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING CASE
        WHEN created_at IS NULL THEN NULL
        ELSE created_at AT TIME ZONE 'Asia/Seoul'
    END;

ALTER TABLE economic_events
    ALTER COLUMN created_at TYPE TIMESTAMPTZ USING CASE
        WHEN created_at IS NULL THEN NULL
        ELSE created_at AT TIME ZONE 'Asia/Seoul'
    END;

ALTER TABLE news_analysis
    ALTER COLUMN analyzed_at TYPE TIMESTAMPTZ USING CASE
        WHEN analyzed_at IS NULL THEN NULL
        ELSE analyzed_at AT TIME ZONE 'Asia/Seoul'
    END;

ALTER TABLE kiwoom_token
    ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE trading_signals
    ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE vi_events
    ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE ws_tick_data
    ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE economic_events
    ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE news_analysis
    ALTER COLUMN analyzed_at SET DEFAULT NOW();
