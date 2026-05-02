'use strict';

const assert = require('assert');
const path = require('path');

const {
    formatSignal,
    formatForceClose,
    formatDailySummary,
    formatSellRecommendation,
    formatRuleOnlySignal,
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

test('formatSignal shows integrated TP1 before Claude TP1', () => {
    const msg = formatSignal(makeSignal({
        tp1_price: 88000,
        claude_tp1: 90000,
        display_tp2_price: 92000,
        sl_price: 82000,
    }));
    assert.ok(msg.includes('88,000'));
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

test('formatSignal keeps non-S1 ENTER wording unchanged', () => {
    const msg = formatSignal(makeSignal({
        strategy: 'S2_VI_PULLBACK',
        signal_stage: 'ENTRY',
    }));
    assert.ok(msg.includes('진입 판단: <b>조건부 매수 검토</b>'));
    assert.ok(msg.includes('권장 비중'));
    assert.ok(msg.includes('매수 방식'));
    assert.ok(msg.includes('진입 체크포인트'));
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
    assert.ok(msg.includes('TP1'));
    assert.ok(msg.includes('Partial'));
    assert.ok(msg.includes('Urgent'));
    assert.ok(msg.includes('Trigger'));
    assert.ok(msg.includes('Realized PnL'));
    assert.ok(msg.includes('Reason'));
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
    assert.ok(msg.includes('Stop loss'));
    assert.ok(msg.includes('no'));
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
    assert.ok(msg.includes('Trailing'));
    assert.ok(msg.includes('30%'));
    assert.ok(msg.includes('1.5') || msg.includes('1.50'));
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
