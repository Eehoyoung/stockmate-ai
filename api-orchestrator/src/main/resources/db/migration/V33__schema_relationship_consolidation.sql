-- V33: 스키마 관계 재정비 및 정합성 강화
-- 목적:
--   1. kiwoom_token → kiwoom_tokens 테이블명 통일 (엔티티 기준)
--   2. vi_events 누락 컬럼 추가 (ViEvent 엔티티 기준)
--   3. ws_tick_data 누락 컬럼 추가 (WsTickData 엔티티 기준)
--   4. overnight_evaluations.position_id FK 제거 (open_positions가 V30에서 뷰로 전환됨)
--   5. trading_signals → stock_master FK 추가
--   6. signal_score_components → trading_signals FK 확인 (V3에서 이미 정의됨)
--   7. candidate_pool_history → stock_master FK 추가
--   8. daily_indicators → stock_master FK 추가
--   9. human_confirm_requests.signal_id → trading_signals FK 추가
--  10. ai_cancel_signal / rule_cancel_signal FK 확인
--  11. trading_signals 레거시 컬럼(legacy_open_position_id) 정리
--  12. 누락 인덱스 보완

-- ============================================================
-- STEP 1. kiwoom_token → kiwoom_tokens 테이블명 통일
-- JPA 엔티티 @Table(name = "kiwoom_tokens") 기준으로 테이블명 정합.
-- V1 baseline이 "kiwoom_token" 으로 생성했으나 엔티티는 "kiwoom_tokens" 참조.
-- ddl-auto:update 환경에서는 자동 생성됐으나 신규 DB에서는 두 테이블이 공존할 위험.
-- ============================================================

DO $$
BEGIN
    -- kiwoom_token 이 존재하고 kiwoom_tokens 가 없는 경우: RENAME
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'kiwoom_token'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'kiwoom_tokens'
    ) THEN
        ALTER TABLE kiwoom_token RENAME TO kiwoom_tokens;
    END IF;

    -- kiwoom_token 과 kiwoom_tokens 가 모두 존재하는 경우:
    -- kiwoom_tokens 에 더 최신 토큰이 있다고 가정하고 kiwoom_token 제거.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'kiwoom_token'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'kiwoom_tokens'
    ) THEN
        DROP TABLE kiwoom_token;
    END IF;
END
$$;

-- kiwoom_tokens 누락 컬럼 추가 (엔티티: is_active, updated_at)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'kiwoom_tokens'
          AND column_name = 'is_active'
    ) THEN
        ALTER TABLE kiwoom_tokens ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'kiwoom_tokens'
          AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE kiwoom_tokens ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END
$$;

-- access_token 길이 확장 (엔티티 length=2000, V1은 TEXT — 이미 충분하지만 타입 통일)
-- TEXT는 이미 무제한이므로 별도 ALTER 불필요.

-- ============================================================
-- STEP 2. vi_events 누락 컬럼 추가
-- V1 baseline: trigger_price, reference_price, vi_type 만 존재.
-- ViEvent 엔티티 기준 누락 컬럼: stk_nm, vi_status, vi_price, acc_volume,
--   ref_price, upper_limit, lower_limit, market_type, released_at
-- V32에서 occurred_at → created_at 이미 처리됨.
-- ============================================================


DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'stk_nm') THEN
        ALTER TABLE vi_events ADD COLUMN stk_nm VARCHAR(40);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'vi_status') THEN
        ALTER TABLE vi_events ADD COLUMN vi_status VARCHAR(2);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'vi_price') THEN
        ALTER TABLE vi_events ADD COLUMN vi_price FLOAT8;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'acc_volume') THEN
        ALTER TABLE vi_events ADD COLUMN acc_volume BIGINT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'ref_price') THEN
        ALTER TABLE vi_events ADD COLUMN ref_price FLOAT8;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'upper_limit') THEN
        ALTER TABLE vi_events ADD COLUMN upper_limit FLOAT8;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'lower_limit') THEN
        ALTER TABLE vi_events ADD COLUMN lower_limit FLOAT8;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'market_type') THEN
        ALTER TABLE vi_events ADD COLUMN market_type VARCHAR(10);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vi_events' AND column_name = 'released_at') THEN
        ALTER TABLE vi_events ADD COLUMN released_at TIMESTAMPTZ;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'vi_events'
          AND column_name = 'created_at'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'vi_events'
          AND column_name = 'occurred_at'
    ) THEN
        ALTER TABLE vi_events RENAME COLUMN occurred_at TO created_at;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'vi_events'
          AND column_name = 'created_at'
    ) THEN
        ALTER TABLE vi_events ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END
$$;

-- STEP 2b. vi_events 레거시 컬럼 마이그레이션
-- trigger_price  → vi_price 로 이관 (엔티티 필드명 기준)
-- reference_price → ref_price 로 이관
-- 이관 후 레거시 컬럼 제거.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'vi_events'
          AND column_name = 'trigger_price'
    ) THEN
        EXECUTE '
            UPDATE vi_events
            SET vi_price = COALESCE(vi_price, trigger_price)
            WHERE trigger_price IS NOT NULL
        ';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'vi_events'
          AND column_name = 'reference_price'
    ) THEN
        EXECUTE '
            UPDATE vi_events
            SET ref_price = COALESCE(ref_price, reference_price)
            WHERE reference_price IS NOT NULL
        ';
    END IF;
END
$$;

ALTER TABLE vi_events
    DROP COLUMN IF EXISTS trigger_price,
    DROP COLUMN IF EXISTS reference_price;

-- vi_events 인덱스 보완 (엔티티 @Index 기준)
CREATE INDEX IF NOT EXISTS idx_vi_stk_cd     ON vi_events(stk_cd);
CREATE INDEX IF NOT EXISTS idx_vi_created_at ON vi_events(created_at);

-- ============================================================
-- STEP 3. ws_tick_data 누락 컬럼 추가
-- V1 baseline: stk_cd, cur_prc, flu_rt, cntr_qty 만 존재.
-- WsTickData 엔티티 기준 누락 컬럼:
--   pred_pre, acc_trde_qty, acc_trde_prica, cntr_str,
--   total_bid_qty, total_ask_qty, bid_ask_ratio, tick_type
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'pred_pre') THEN
        ALTER TABLE ws_tick_data ADD COLUMN pred_pre FLOAT8;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'acc_trde_qty') THEN
        ALTER TABLE ws_tick_data ADD COLUMN acc_trde_qty BIGINT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'acc_trde_prica') THEN
        ALTER TABLE ws_tick_data ADD COLUMN acc_trde_prica BIGINT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'cntr_str') THEN
        ALTER TABLE ws_tick_data ADD COLUMN cntr_str FLOAT8;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'total_bid_qty') THEN
        ALTER TABLE ws_tick_data ADD COLUMN total_bid_qty BIGINT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'total_ask_qty') THEN
        ALTER TABLE ws_tick_data ADD COLUMN total_ask_qty BIGINT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'bid_ask_ratio') THEN
        ALTER TABLE ws_tick_data ADD COLUMN bid_ask_ratio FLOAT8;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'ws_tick_data' AND column_name = 'tick_type') THEN
        ALTER TABLE ws_tick_data ADD COLUMN tick_type VARCHAR(4);
    END IF;
END
$$;

-- cntr_qty → V1에서 BIGINT로 생성됐으나 엔티티에는 없는 컬럼.
--   데이터 이관 후 제거.
-- ============================================================


-- cntr_qty 이관: acc_trde_qty 와 역할이 다르므로 별도 보존 불필요.
-- V1의 cntr_qty(건별 체결량)는 현재 시스템에서 사용하지 않으므로 DROP.
ALTER TABLE ws_tick_data
    DROP COLUMN IF EXISTS cntr_qty;

-- ws_tick_data 인덱스 보완 (엔티티 @Index 기준)
CREATE INDEX IF NOT EXISTS idx_tick_stk_cd_created ON ws_tick_data(stk_cd, created_at);

-- ============================================================
-- STEP 4. overnight_evaluations.position_id FK 제거
-- V25 + V30 에서 open_positions 테이블이 open_positions_legacy 로 RENAME 되고
-- 뷰(VIEW)로 재생성됐으므로, position_id → open_positions 실제 테이블 참조가
-- 더 이상 유효하지 않음. FK 제약을 해제하고 컬럼은 이력 목적으로 유지.
-- ============================================================

DO $$
DECLARE
    fk_name TEXT;
BEGIN
    -- position_id 컬럼에 걸린 FK 이름을 동적으로 찾아 DROP
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'overnight_evaluations'::regclass
      AND contype   = 'f'
      AND conkey    @> ARRAY[(
          SELECT attnum FROM pg_attribute
          WHERE attrelid = 'overnight_evaluations'::regclass
            AND attname  = 'position_id'
      )]::smallint[];

    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE overnight_evaluations DROP CONSTRAINT %I', fk_name);
    END IF;
END
$$;

-- signal_id FK 확인: V7에서 ON DELETE SET NULL으로 이미 정의됨.
-- signal_id → trading_signals FK 유효성 재확인 후 없으면 추가.
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'overnight_evaluations'::regclass
      AND contype   = 'f'
      AND conkey    @> ARRAY[(
          SELECT attnum FROM pg_attribute
          WHERE attrelid = 'overnight_evaluations'::regclass
            AND attname  = 'signal_id'
      )]::smallint[];

    IF fk_name IS NULL THEN
        ALTER TABLE overnight_evaluations
            ADD CONSTRAINT fk_oe_signal_id
            FOREIGN KEY (signal_id)
            REFERENCES trading_signals(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

-- ============================================================
-- STEP 5. trading_signals → stock_master FK 추가
-- 신호 생성 시 stock_master 에 없는 종목 코드가 들어올 수 있으므로
-- ON DELETE SET NULL 정책 사용. 또한 stock_master 갱신 주기(주 1회)와
-- 신호 생성 주기가 달라 정합성보다 유연성 우선.
-- stock_master.stk_cd 가 PK(VARCHAR(20)) 이므로 FK 참조 가능.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading_signals'::regclass
          AND contype   = 'f'
          AND conname   = 'fk_ts_stk_cd'
    ) THEN
        -- 고아 stk_cd 를 NULL로 처리하지 않고 FK 추가 가능하도록
        -- stock_master 에 없는 stk_cd 행은 FK 위반이므로 먼저 확인.
        -- 운영 DB에서 stock_master 없이 신호가 있을 수 있으므로 DEFERRABLE 사용.
        ALTER TABLE trading_signals
            ADD CONSTRAINT fk_ts_stk_cd
            FOREIGN KEY (stk_cd)
            REFERENCES stock_master(stk_cd)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
EXCEPTION
    WHEN foreign_key_violation THEN
        -- stock_master에 없는 stk_cd가 존재하면 FK 추가를 건너뜀
        -- 운영팀이 stock_master 정합성 확보 후 수동으로 재실행 필요
        RAISE WARNING 'fk_ts_stk_cd 추가 실패: trading_signals 에 stock_master 미등록 stk_cd 존재. stock_master 갱신 후 재실행 필요.';
END
$$;

-- ============================================================
-- STEP 6. candidate_pool_history → stock_master FK 추가
-- 후보 풀은 stock_master 에 등록된 종목만 대상으로 하므로
-- ON DELETE CASCADE (종목 삭제 시 이력도 함께 제거).
-- 단, stock_master 에 없는 종목이 있을 경우 DEFERRABLE 사용.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'candidate_pool_history'::regclass
          AND contype   = 'f'
          AND conname   = 'fk_cph_stk_cd'
    ) THEN
        ALTER TABLE candidate_pool_history
            ADD CONSTRAINT fk_cph_stk_cd
            FOREIGN KEY (stk_cd)
            REFERENCES stock_master(stk_cd)
            ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
EXCEPTION
    WHEN foreign_key_violation THEN
        RAISE WARNING 'fk_cph_stk_cd 추가 실패: candidate_pool_history 에 stock_master 미등록 stk_cd 존재.';
END
$$;

-- ============================================================
-- STEP 7. daily_indicators → stock_master FK 추가
-- 기술지표 캐시는 stock_master 에 등록된 종목만 대상으로 하므로
-- ON DELETE CASCADE.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'daily_indicators'::regclass
          AND contype   = 'f'
          AND conname   = 'fk_di_stk_cd'
    ) THEN
        ALTER TABLE daily_indicators
            ADD CONSTRAINT fk_di_stk_cd
            FOREIGN KEY (stk_cd)
            REFERENCES stock_master(stk_cd)
            ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
EXCEPTION
    WHEN foreign_key_violation THEN
        RAISE WARNING 'fk_di_stk_cd 추가 실패: daily_indicators 에 stock_master 미등록 stk_cd 존재.';
END
$$;

-- ============================================================
-- STEP 8. human_confirm_requests.signal_id → trading_signals FK 추가
-- V23 생성 시 FK 제약이 누락됨.
-- 신호 삭제 시 확인 요청도 의미 없으므로 ON DELETE CASCADE.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'human_confirm_requests'::regclass
          AND contype   = 'f'
          AND conname   = 'fk_hcr_signal_id'
    ) THEN
        ALTER TABLE human_confirm_requests
            ADD CONSTRAINT fk_hcr_signal_id
            FOREIGN KEY (signal_id)
            REFERENCES trading_signals(id)
            ON DELETE CASCADE;
    END IF;
EXCEPTION
    WHEN foreign_key_violation THEN
        RAISE WARNING 'fk_hcr_signal_id 추가 실패: human_confirm_requests 에 존재하지 않는 signal_id 있음.';
END
$$;

-- ============================================================
-- STEP 9. trading_signals 레거시 컬럼 정리
-- legacy_open_position_id: V30에서 데이터 이관 목적으로 추가됐으나
--   이관 완료 후 더 이상 사용하지 않음. JPA 엔티티에도 없음.
--   이력 조회 필요 없으므로 DROP.
-- ============================================================

-- Keep legacy_open_position_id because the V30 open_positions compatibility view
-- depends on it. Extra database columns do not affect the JPA entity mapping.

-- ============================================================
-- STEP 10. trading_signals 컬럼 타입 보완
-- created_at: 엔티티는 LocalDateTime (TIMESTAMP without timezone) 을 사용하나
--   V32에서 이미 TIMESTAMPTZ로 변환됨.
--   closed_at, executed_at도 동일하게 V32에서 처리됨.
-- signal_status DEFAULT 추가 (엔티티 기본값 PENDING)
-- ============================================================

ALTER TABLE trading_signals
    ALTER COLUMN signal_status SET DEFAULT 'PENDING';

-- ============================================================
-- STEP 11. vi_events 레거시 시퀀스 정리
-- V20에서 vi_events_id_seq, V26에서 vi_events_seq 두 시퀀스가 공존.
-- V28에서 vi_events_id_seq를 컬럼 소유로 확정함.
-- vi_events_seq (V26용)가 남아있으면 혼선이 생기므로 삭제.
-- ============================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_sequences
        WHERE schemaname = 'public' AND sequencename = 'vi_events_seq'
    ) THEN
        -- vi_events_seq 가 vi_events.id 에 OWNED BY 되어 있지 않으면 DROP
        IF NOT EXISTS (
            SELECT 1 FROM pg_depend d
            JOIN pg_class c ON c.oid = d.refobjid
            JOIN pg_sequences s ON s.sequencename = 'vi_events_seq'
            WHERE d.deptype = 'a' AND c.relname = 'vi_events'
        ) THEN
            DROP SEQUENCE IF EXISTS vi_events_seq;
        END IF;
    END IF;
END
$$;

-- ============================================================
-- STEP 12. economic_events 구형 컬럼 제거
-- V1 baseline에서 생성된 title, importance, country 컬럼은
-- EconomicEvent 엔티티에 없음 (V22에서 신규 컬럼만 추가됨).
-- 운영 DB에서 V22 이후 새 컬럼으로 마이그레이션됐으므로 구형 컬럼 제거.
-- ============================================================

ALTER TABLE economic_events
    DROP COLUMN IF EXISTS title,
    DROP COLUMN IF EXISTS importance,
    DROP COLUMN IF EXISTS country;

-- ============================================================
-- STEP 13. news_analysis 구형 컬럼 제거
-- V1 baseline에서 생성된 headline, sector 컬럼은
-- NewsAnalysis 엔티티에 없음 (V22에서 신규 컬럼만 추가됨).
-- headline → summary 로 역할 이관됐으므로 이관 후 DROP.
-- ============================================================

-- headline → summary 이관 (summary 가 비어있는 행에만 적용)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'news_analysis'
          AND column_name = 'headline'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'news_analysis'
          AND column_name = 'summary'
    ) THEN
        EXECUTE '
            UPDATE news_analysis
            SET summary = COALESCE(summary, headline)
            WHERE headline IS NOT NULL AND summary IS NULL
        ';
    END IF;
END
$$;

ALTER TABLE news_analysis
    DROP COLUMN IF EXISTS headline,
    DROP COLUMN IF EXISTS sector;

-- ============================================================
-- STEP 14. risk_events → stock_master FK 추가
-- stk_cd가 NULL인 리스크 이벤트(포트폴리오 레벨 이벤트)가 존재하므로
-- ON DELETE SET NULL 정책 사용.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'risk_events'::regclass
          AND contype   = 'f'
          AND conname   = 'fk_re_stk_cd'
    ) THEN
        ALTER TABLE risk_events
            ADD CONSTRAINT fk_re_stk_cd
            FOREIGN KEY (stk_cd)
            REFERENCES stock_master(stk_cd)
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
EXCEPTION
    WHEN foreign_key_violation THEN
        RAISE WARNING 'fk_re_stk_cd 추가 실패: risk_events 에 stock_master 미등록 stk_cd 존재.';
END
$$;

-- ============================================================
-- STEP 15. 뷰 재생성
-- STEP 1에서 kiwoom_token → kiwoom_tokens rename 이후
-- 뷰는 kiwoom_token을 참조하지 않으므로 영향 없음.
-- vi_events 컬럼 변경(trigger_price → vi_price)이 뷰에 영향 없음.
-- v_active_positions, v_portfolio_risk_snapshot, v_strategy_performance_30d,
-- v_score_outcome_correlation 은 V30에서 최종 재작성됨 — 추가 변경 없음.
-- ============================================================

-- open_positions 뷰를 V30에서 생성한 그대로 두되, vi_price 노출 여부만 확인.
-- 뷰 내용에 vi_events 참조 없으므로 재생성 불필요.

-- ============================================================
-- STEP 16. 누락 인덱스 추가
-- ============================================================

-- vi_events: vi_status, market_type 조회 최적화
CREATE INDEX IF NOT EXISTS idx_vi_status_cd
    ON vi_events(vi_status, stk_cd)
    WHERE vi_status = '1';  -- 발동 중인 VI만 인덱싱

-- ws_tick_data: tick_type 별 조회 최적화
CREATE INDEX IF NOT EXISTS idx_tick_type_created
    ON ws_tick_data(tick_type, created_at DESC)
    WHERE tick_type IS NOT NULL;

-- human_confirm_requests: 이미 V23에서 인덱스 생성됨 — 중복 없음.

-- candidate_pool_history: signal_id 인덱스 (V13에 없음)
CREATE INDEX IF NOT EXISTS idx_cph_signal_id
    ON candidate_pool_history(signal_id)
    WHERE signal_id IS NOT NULL;

-- overnight_evaluations: position_id 인덱스는 V7에서 생성됨 (컬럼 유지, FK만 제거).

-- ============================================================
-- STEP 17. 코멘트 정비
-- ============================================================

COMMENT ON TABLE kiwoom_tokens IS 'Kiwoom REST API 인증 토큰 원장';
COMMENT ON COLUMN kiwoom_tokens.is_active IS '현재 유효한 토큰 여부 (TokenRefreshScheduler 갱신 시 이전 토큰 FALSE)';

COMMENT ON COLUMN vi_events.vi_price IS 'VI 발동 가격 (구 trigger_price)';
COMMENT ON COLUMN vi_events.ref_price IS '기준 가격 (구 reference_price)';
COMMENT ON COLUMN vi_events.vi_status IS '1=발동, 2=해제';
COMMENT ON COLUMN vi_events.released_at IS 'VI 해제 시각 (vi_status=2 시 채워짐)';

COMMENT ON COLUMN ws_tick_data.tick_type IS '0B=체결, 0D=호가, 0H=예상체결';
COMMENT ON COLUMN ws_tick_data.cntr_str IS '체결강도 (매수체결량/매도체결량 × 100)';

COMMENT ON COLUMN overnight_evaluations.position_id IS 'Legacy open_positions.id reference retained without FK';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading_signals'::regclass
          AND conname = 'fk_ts_stk_cd'
    ) THEN
        COMMENT ON CONSTRAINT fk_ts_stk_cd ON trading_signals IS 'DEFERRABLE: stock_master validation is deferred until transaction end';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'candidate_pool_history'::regclass
          AND conname = 'fk_cph_stk_cd'
    ) THEN
        COMMENT ON CONSTRAINT fk_cph_stk_cd ON candidate_pool_history IS 'DEFERRABLE: stock_master validation is deferred until transaction end';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'daily_indicators'::regclass
          AND conname = 'fk_di_stk_cd'
    ) THEN
        COMMENT ON CONSTRAINT fk_di_stk_cd ON daily_indicators IS 'DEFERRABLE: stock_master validation is deferred until transaction end';
    END IF;
END
$$;
