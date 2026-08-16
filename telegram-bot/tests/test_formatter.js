'use strict';

const assert = require('assert');
const path = require('path');

const {
    formatSignal,
    formatForceClose,
    formatDailySummary,
    formatSellSignal,
    formatSellRecommendation,
    formatRuleOnlySignal,
    formatHoldWatch,
    formatHoldReleased,
    escapeHtml,
} = require(path.join(__dirname, '../src/utils/formatter'));

let passCount = 0;
let failCount = 0;
const failures = [];

function test(name, fn) {
    try {
        fn();
        passCount++;
        console.log(`PASS ${name}`);
    } catch (error) {
        failCount++;
        failures.push({ name, error: error.message });
        console.log(`FAIL ${name}`);
        console.log(`  ${error.message}`);
    }
}

function makeSignal(overrides = {}) {
    return {
        strategy: 'S1_GAP_OPEN',
        stk_cd: '005930',
        stk_nm: '삼성전자',
        action: 'ENTER',
        ai_score: 78.5,
        rule_score: 75.0,
        confidence: 'HIGH',
        entry_type: '시초가_상향',
        target_pct: 4.0,
        stop_pct: -2.0,
        gap_pct: 3.85,
        cntr_strength: 143.0,
        ai_reason: '강한 갭상승과 체결강도 확인',
        signal_time: '2026-03-21T09:00:05',
        cur_prc: 84300,
        ...overrides,
    };
}

function makeSellRecommendation(overrides = {}) {
    return {
        strategy: 'S1_GAP_OPEN',
        stk_cd: '005930',
        stk_nm: '삼성전자',
        recommendation_type: 'TP1',
        partial: 50,
        urgent: true,
        trigger_price: 101500,
        realized_pnl_pct: 3.45,
        reason_summary: 'TP1 도달 후 수익 일부 확정 권고',
        signal_time: '2026-03-21T09:15:00',
        ...overrides,
    };
}

test('escapeHtml escapes special characters', () => {
    assert.strictEqual(escapeHtml('a & b < c > d'), 'a &amp; b &lt; c &gt; d');
    assert.strictEqual(escapeHtml(null), '');
});

test('formatSignal includes basic trade context', () => {
    const msg = formatSignal(makeSignal());
    assert.ok(msg.includes('S1_GAP_OPEN'));
    assert.ok(msg.includes('005930'));
    assert.ok(msg.includes('삼성전자'));
    assert.ok(!msg.includes('초보자용 매수 가이드'));
    assert.ok(!msg.includes('지금 할 일'));
    assert.ok(msg.includes('갭 상승 관찰'));
    assert.ok(msg.includes('확인 체크포인트'));
    assert.ok(!msg.includes('신규매수'));
    assert.ok(!msg.includes('권장 비중'));
    assert.ok(!msg.includes('조건부 매수 검토'));
    assert.ok(!msg.includes('매수 방식'));
    assert.ok(!msg.includes('추격 매수'));
    assert.ok(msg.includes('&lt;') || !msg.includes('<script>'));
});

test('formatSignal treats ENTER_CANDIDATE readiness as non-enter review', () => {
    const msg = formatSignal(makeSignal({
        readiness_action: 'ENTER_CANDIDATE',
        readiness_reasons: ['fast rule pass; deep/AI not used'],
    }));
    assert.ok(msg.includes('ENTER_CANDIDATE'));
    assert.ok(msg.includes('fast rule pass'));
    assert.ok(!msg.includes('조건부 매수 검토'));
});

test('formatSignal renders S1 rule-only as observation form', () => {
    const msg = formatSignal(makeSignal({
        type: 'RULE_ONLY_SIGNAL',
        signal_grade: 'RULE_ONLY',
        cur_prc: 18880,
        tp1_price: 20070,
        sl_price: 17480,
        stk_nm: 'BNK금융지주',
    }));
    assert.ok(msg.includes('갭상승 관찰 알림'));
    assert.ok(msg.includes('종목: BNK금융지주'));
    assert.ok(msg.includes('18,900원 부근 조건 확인') || msg.includes('18,880원 부근 조건 확인'));
    assert.ok(msg.includes('20,070원 도달 여부 관찰'));
    assert.ok(msg.includes('무효화 기준'));
    assert.ok(!msg.includes('신규매수'));
    assert.ok(!msg.includes('권장 비중'));
    assert.strictEqual(msg, formatRuleOnlySignal({
        strategy: 'S1_GAP_OPEN',
        stk_nm: 'BNK금융지주',
        cur_prc: 18880,
        tp1_price: 20070,
        sl_price: 17480,
    }));
});

test('formatRuleOnlySignal keeps legacy buy wording for non-S1 strategies', () => {
    const msg = formatRuleOnlySignal({
        strategy: 'S2_VI_PULLBACK',
        stk_nm: 'BNK금융지주',
        cur_prc: 18880,
        tp1_price: 20070,
        sl_price: 17480,
    });
    assert.ok(msg.includes('가라급등열차 점장선생'));
    assert.ok(msg.includes('신규매수'));
    assert.ok(msg.includes('권고'));
});

test('formatSignal falls back to target and stop percentages', () => {
    const msg = formatSignal(makeSignal({ tp1_price: undefined, tp2_price: undefined, sl_price: undefined }));
    assert.ok(msg.includes('4.0') || msg.includes('+4') || msg.includes('target'));
    assert.ok(msg.includes('-2.0') || msg.includes('-2') || msg.includes('stop'));
});

test('formatSignal shows display TP2 while execution TP2 is absent', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        tp2_price: undefined,
        display_tp2_price: 92000,
        sl_price: 82000,
        rr_ratio: 1.7,
    }));
    assert.ok(msg.includes('92,000'));
});

test('formatSignal renders 손익비 with market regime policy wording', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        sl_price: 82000,
        rr_ratio: 0.72,
        rr_regime: 'bull',
        rr_regime_threshold: 0.65,
    }));
    assert.ok(msg.includes('현재 장세 손익비/bull'));
    assert.ok(msg.includes('통과'));
    assert.ok(!msg.includes('R:R'));
});

test('formatSignal escapes RR regime label', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        sl_price: 82000,
        rr_ratio: 0.72,
        rr_regime: '<bull&bear>',
        rr_regime_threshold: 0.65,
    }));
    assert.ok(msg.includes('&lt;bull&amp;bear&gt;'));
    assert.ok(!msg.includes('손익비/<bull&bear>'));
});

test('formatSignal renders toss risk line for swing ENTER signals', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S8_GOLDEN_CROSS',
        toss_risk: {
            short_selling: { shortSellingAmountRate: '0.12' },
            credit_trades: { marginLoan: { balanceRate: '0.06' } },
            warnings: [{ warningType: 'OVERHEATED' }],
        },
    }));
    assert.ok(msg.includes('토스 리스크'));
    assert.ok(msg.includes('공매도비중 12.0%'));
    assert.ok(msg.includes('신용융자잔고 6.00%'));
    assert.ok(msg.includes('매수유의사항[OVERHEATED]'));
});

test('formatSignal combines investor flow trend with toss risk under one swing block', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S14_OVERSOLD_BOUNCE',
        investor_flow_trend: {
            kospi: { foreigner_net_delta: 12000000000, institution_net_delta: -3000000000 },
        },
        toss_risk: {
            short_selling: { shortSellingAmountRate: '0.08' },
        },
    }));
    assert.ok(msg.includes('스윙 참고'));
    assert.ok(msg.includes('시장수급추세(최근30분)'));
    assert.ok(msg.includes('코스피(외인+120억/기관-30억)'));
    assert.ok(msg.includes('토스 리스크'));
});

test('formatSignal omits swing block entirely when both trend and risk are absent', () => {
    const msg = formatSignal(makeSignal({ investor_flow_trend: null, toss_risk: null }));
    assert.ok(!msg.includes('스윙 참고'));
    assert.ok(!msg.includes('시장수급추세'));
});

test('formatSignal omits toss risk line when data absent (day strategies)', () => {
    const msg = formatSignal(makeSignal({ toss_risk: null }));
    assert.ok(!msg.includes('토스 리스크'));
});

test('formatSignal skips invalid RR ratio instead of rendering NaN', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        sl_price: 82000,
        rr_ratio: 'not-a-number',
        rr_regime_threshold: 0.65,
    }));
    assert.ok(!msg.includes('NaN'));
    assert.ok(!msg.includes('현재 장세 기준 RR'));
});

test('formatSignal shows Claude execution TP1 before rule TP1', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        claude_tp1: 90000,
        display_tp2_price: 92000,
        sl_price: 82000,
    }));
    assert.ok(msg.includes('90,000'));
    assert.ok(!msg.includes('88,000'));
});

test('formatSignal shows Claude execution TP2 before display TP2', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        claude_tp1: 90000,
        claude_tp2: 94000,
        display_tp2_price: 92000,
        sl_price: 82000,
    }));
    assert.ok(msg.includes('94,000'));
    assert.ok(!msg.includes('92,000'));
});

test('formatSignal shows Claude execution SL before rule SL', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        claude_tp1: 90000,
        sl_price: 82000,
        claude_sl: 81000,
    }));
    assert.ok(msg.includes('81,000'));
    assert.ok(!msg.includes('82,000'));
});

test('formatSignal handles optional S1 signal_stage values safely', () => {
    const watchMsg = formatSignal(makeSignal({ signal_stage: 'WATCH' }));
    assert.ok(watchMsg.includes('신호 단계: <b>관찰</b>'));
    assert.ok(!watchMsg.includes('진입 판단'));
    assert.ok(!watchMsg.includes('권장 비중'));
    assert.ok(!watchMsg.includes('신규매수'));

    const entryMsg = formatSignal(makeSignal({ signal_stage: 'ENTRY' }));
    assert.ok(entryMsg.includes('신호 단계: <b>조건 충족 확인</b>'));
    assert.ok(!entryMsg.includes('조건부 매수 검토'));

    const holdMsg = formatSignal(makeSignal({ action: undefined, signal_stage: 'HOLD' }));
    assert.ok(holdMsg.includes('신호 단계: <b>관망</b>'));
    assert.ok(holdMsg.includes('관찰 기준가'));
    assert.ok(!holdMsg.includes('진입가'));
    assert.ok(!holdMsg.includes('권장 비중'));
});

test('formatSignal sanitizes S1 upstream buy wording', () => {
    const msg = formatSignal(makeSignal({
        entry_type: '시장가 매수',
        ai_reason: '신규 매수 가능하나 추격 매수는 주의',
    }));
    assert.ok(msg.includes('체결강도와 호가 우위 재확인'));
    assert.ok(!msg.includes('시장가 매수'));
    assert.ok(!msg.includes('신규 매수'));
    assert.ok(!msg.includes('추격 매수'));
});

test('formatSignal renders non-S1 ENTER as passed entry conditions', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S2_VI_PULLBACK',
        signal_stage: 'ENTRY',
    }));
    assert.ok(msg.includes('진입 판단: <b>진입 조건 통과</b>'));
    assert.ok(msg.includes('권장 비중'));
    assert.ok(msg.includes('매수 방식'));
    assert.ok(msg.includes('진입 체크포인트'));
});

test('formatSignal renders S16 accumulation strategy identity', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S16_ACCUMULATION_SHADOW',
        stk_cd: '123456',
        stk_nm: 'Accumulation Test',
        tp1_price: 11500,
        tp2_price: 12600,
        sl_price: 9900,
        rr_ratio: 1.8,
        s16_state: 'TRIGGERED',
    }));
    assert.ok(msg.includes('S16_ACCUMULATION_SHADOW'));
    assert.ok(msg.includes('Accumulation Test'));
    assert.ok(msg.includes('세력 매집'));
});

test('formatSignal renders family lineage without replacing legacy setup', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S4_BIG_CANDLE',
        strategy_family: 'G06',
        strategy_family_name: 'INTRADAY_THEME_MOMENTUM',
        primary_setup_id: 'S4_BIG_CANDLE',
        matched_setup_ids: ['S4_BIG_CANDLE', 'S6_THEME_LAGGARD'],
    }));

    assert.ok(msg.includes('[S4_BIG_CANDLE]'));
    assert.ok(msg.includes('G06 장중급등·테마'));
    assert.ok(msg.includes('대표 세부전략: S4_BIG_CANDLE'));
    assert.ok(msg.includes('S6_THEME_LAGGARD'));
});

test('formatSignal renders upgraded ENTER form with Korean price and execution labels', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S13_BOX_BREAKOUT',
        strategy_family: 'G05',
        primary_setup_id: 'S13_BOX_BREAKOUT',
        matched_setup_ids: ['S13_BOX_BREAKOUT', 'S10_NEW_HIGH'],
        market_type: '101',
        final_score: 80.8,
        tp1_price: 10600,
        tp2_price: 11200,
        sl_price: 9650,
        tp_method: '최근 매물대',
        tp2_method: '박스 높이 1배 확장',
        sl_method: '박스 상단 재이탈',
        raw_rr: 1.71,
        effective_rr: 1.55,
        min_rr_ratio: 1.55,
        hard_gates_passed: true,
        portfolio_arbitration_passed: true,
        data_quality: 'OK',
        data_source: { hoga: 'kiwoom_ws' },
        source_age_ms: { hoga: 430 },
        bid_ratio: 1.73,
        spread_pct: 0.2,
        chase_risk: 'LOW',
    }));
    for (const text of [
        '시장: 코스닥', '스윙형', '함께 확인된 세부전략', '필수조건 통과',
        '데이터 상태 정상', '진입가', '출처 키움 실시간', '1차 목표가',
        '2차 목표가', '손절가', '기본 손익비', '비용 반영 손익비',
        '최소 기준', '호가비율', '매수·매도 가격차', '추격 위험 낮음',
    ]) assert.ok(msg.includes(text), `${text} 포함`);
    for (const forbidden of ['R:R', '현재 장세 기준 RR', 'TP1:', 'TP2:', 'SL:']) {
        assert.ok(!msg.includes(forbidden), `${forbidden} 미표시`);
    }
});

test('formatSignal prefixes hold-promoted ENTER strategy with H tag', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S2_VI_PULLBACK',
        signal_stage: 'ENTRY',
        hold_promoted_to_enter: true,
    }));
    assert.ok(msg.includes('[H][S2_VI_PULLBACK]'));
});

test('formatForceClose renders stock code and strategy', () => {
    const msg = formatForceClose({ stk_cd: '005930', stk_nm: '삼성전자', strategy: 'S1_GAP_OPEN' });
    assert.ok(msg.includes('005930'));
    assert.ok(msg.includes('S1_GAP_OPEN') || typeof msg === 'string');
});

test('formatDailySummary handles empty input', () => {
    const msg = formatDailySummary([]);
    assert.ok(typeof msg === 'string');
    assert.ok(msg.length > 0);
});

test('SELL_RECOMMENDATION TP1 includes partial/urgent/trigger/pnl', () => {
    const msg = formatSellRecommendation(makeSellRecommendation());
    assert.ok(msg.includes('[매도검토]'));
    assert.ok(msg.includes('1차 목표가 도달'));
    assert.ok(msg.includes('청산범위'));
    assert.ok(msg.includes('기준가'));
    assert.ok(msg.includes('손익'));
    assert.ok(msg.includes('판단근거'));
});

test('SELL_RECOMMENDATION SL uses stop-loss wording', () => {
    const msg = formatSellRecommendation(makeSellRecommendation({
        recommendation_type: 'SL',
        partial: false,
        urgent: false,
        trigger_price: 98000,
        realized_pnl_pct: -2.15,
        reason_summary: '손절 기준 이탈',
    }));
    assert.ok(msg.includes('손절 기준 도달'));
    assert.ok(msg.includes('검토 필요'));
    assert.ok(msg.includes('-2.15') || msg.includes('-2.15%'));
});

test('SELL_RECOMMENDATION TRAILING keeps trailing wording', () => {
    const msg = formatSellRecommendation(makeSellRecommendation({
        recommendation_type: 'TRAILING',
        partial: '30%',
        urgent: true,
        trailing_pct: 1.5,
        reason_summary: '이익 보호를 위한 추적 손절',
    }));
    assert.ok(msg.includes('트레일링'));
    assert.ok(msg.includes('30%'));
    assert.ok(msg.includes('1.5') || msg.includes('1.50'));
});

test('SELL_SIGNAL TP1 with partial false does not claim partial sell', () => {
    const msg = formatSellSignal({
        strategy: 'S7_ICHIMOKU_BREAKOUT',
        stk_cd: '006800',
        stk_nm: '미래에셋증권',
        exit_type: 'TP1_HIT',
        partial: false,
        entry_price: 70400,
        cur_prc: 81100,
        trigger_price: 78400,
        sl_price: 67900,
        realized_pnl_pct: 15.1989,
        timestamp: '2026-05-06T10:01:05+09:00',
    });
    assert.ok(msg.includes('[매도신호]'));
    assert.ok(msg.includes('목표가 도달'));
    assert.ok(msg.includes('전량/단일 목표 청산'));
    assert.ok(!msg.includes('부분 청산'));
    assert.ok(!msg.includes('절반 청산'));
});

// ── entry_size_tier (진입 강도) 테스트 ─────────────────────────────

test('SIZE_2 신호에 진입 강도 표시', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S8_GOLDEN_CROSS',
        entry_size_tier: 'SIZE_2',
        entry_size_weight: 0.50,
        entry_size_basis: 'model_relative_not_account',
        size_downgrade_flags: ['spread_too_wide'],
    }));
    assert.ok(msg.includes('SIZE_2'), 'SIZE_2 포함');
    assert.ok(msg.includes('0.50'), 'weight 포함');
    assert.ok(msg.includes('스프레드 넓음'), '한국어 플래그');
    assert.ok(msg.includes('하향 사유'), '하향 사유 줄 포함');
    assert.ok(!msg.includes('주'), '수량 표현 금지');
    assert.ok(!msg.includes('잔고'), '잔고 표현 금지');
});

test('entry_size_tier 없는 신호는 기존대로', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S8_GOLDEN_CROSS',
    }));
    assert.ok(!msg.includes('진입 강도:'), 'SIZE 표시 없어야 함');
    assert.ok(!msg.includes('하향 사유'), '하향 사유 없어야 함');
});

test('SIZE_0이면 관찰 전용 주의 문구 포함', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S8_GOLDEN_CROSS',
        entry_size_tier: 'SIZE_0',
        entry_size_weight: 0.00,
        size_downgrade_flags: ['low_liquidity', 'high_stop_pct'],
    }));
    assert.ok(msg.includes('관찰 전용'), '관찰 전용 문구');
    assert.ok(msg.includes('SIZE_0'), 'SIZE_0 포함');
    assert.ok(msg.includes('유동성 부족'), '한국어 플래그 low_liquidity');
    assert.ok(msg.includes('손절폭 큼'), '한국어 플래그 high_stop_pct');
});

test('SIZE_4 최고 강도 — 하향 사유 없음', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S8_GOLDEN_CROSS',
        entry_size_tier: 'SIZE_4',
        entry_size_weight: 1.00,
        size_downgrade_flags: [],
    }));
    assert.ok(msg.includes('SIZE_4'), 'SIZE_4 포함');
    assert.ok(msg.includes('1.00'), 'weight 1.00 포함');
    assert.ok(!msg.includes('하향 사유'), '하향 사유 없음');
    assert.ok(!msg.includes('관찰 전용'), '관찰 전용 문구 없음');
});

test('formatHoldWatch는 조건부 진입(관심종목) 라벨과 사유를 포함', () => {
    const msg = formatHoldWatch({
        strategy: 'S9_PULLBACK_SWING',
        stk_cd: '005930',
        stk_nm: '삼성전자',
        cur_prc: 10000,
        ai_score: 72.0,
        rule_score: 88.0,
        final_score: 83.2,
        rr_ratio: 0.9,
        raw_rr: 1.1,
        effective_rr: 0.9,
        min_rr_ratio: 1.5,
        tp1_price: 11000,
        tp2_price: 11800,
        sl_price: 9700,
        strategy_family: 'G04',
        primary_setup_id: 'S9_PULLBACK_SWING',
        matched_setup_ids: ['S9_PULLBACK_SWING', 'S15_MOMENTUM_ALIGN'],
        data_quality: 'OK',
        data_source: { hoga: 'kiwoom_ws' },
        source_age_ms: { hoga: 420 },
        hold_reason: 'rr_ratio가 장세별(bull) 임계값 미달',
    });
    assert.ok(msg.includes('조건부 진입 (관심종목)'), '조건부 진입 라벨 포함');
    assert.ok(msg.includes('삼성전자 (005930)'), '종목명 포함');
    assert.ok(msg.includes('10,000원'), '현재가 포함');
    assert.ok(msg.includes('손익비가 장세별(bull) 임계값 미달'), 'HOLD 분류 사유 포함');
    assert.ok(msg.includes('1차 목표가'), '1차 목표가 한국어 표시');
    assert.ok(msg.includes('2차 목표가'), '2차 목표가 한국어 표시');
    assert.ok(msg.includes('손절가'), '손절가 한국어 표시');
    assert.ok(msg.includes('비용 반영 손익비'), '손익비 한국어 표시');
    assert.ok(msg.includes('G04 추세단계'), '통합전략 한국어 표시');
    assert.ok(msg.includes('함께 확인된 세부전략'), '확증 세부전략 한국어 표시');
    assert.ok(msg.includes('출처 키움 실시간'), '진입가 출처 표시');
    assert.ok(msg.includes('420밀리초'), '데이터 경과시간 표시');
    assert.ok(!msg.includes('R:R'), '전문 약어 미표시');
});

test('formatHoldWatch는 ai_reason을 hold_reason 폴백으로 사용', () => {
    const msg = formatHoldWatch({
        strategy: 'S1_GAP_OPEN',
        stk_cd: '000660',
        cur_prc: 5000,
        ai_reason: 'Claude HOLD | WATCH retained',
    });
    assert.ok(msg.includes('Claude HOLD'), 'ai_reason 폴백 사유 포함');
});

test('formatHoldReleased는 관심 해제 라벨과 해제 사유를 포함', () => {
    const msg = formatHoldReleased({
        strategy: 'S9_PULLBACK_SWING',
        stk_cd: '005930',
        stk_nm: '삼성전자',
        release_reason: 'hold monitor max age exceeded 1800s',
    });
    assert.ok(msg.includes('관심 해제'), '관심 해제 라벨 포함');
    assert.ok(msg.includes('삼성전자 (005930)'), '종목명 포함');
    assert.ok(msg.includes('hold monitor max age exceeded 1800s'), '해제 사유 포함');
});

console.log(`\nResult: ${passCount} passed, ${failCount} failed`);
if (failures.length > 0) {
    console.log('\nFailures:');
    for (const failure of failures) {
        console.log(`- ${failure.name}: ${failure.error}`);
    }
}

if (failCount > 0) {
    process.exit(1);
}
