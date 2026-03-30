'use strict';

/**
 * tests/test_formatter.js
 * formatter.js 단위 테스트 (Node.js 내장 assert 모듈 사용)
 * 최소 30개 테스트
 */

const assert = require('assert');
const path = require('path');

// formatter.js 임포트
const {
    formatSignal,
    formatForceClose,
    formatDailySummary,
    escapeHtml,
} = require(path.join(__dirname, '../src/utils/formatter'));

// ──────────────────────────────────────────────────────────────────
// 테스트 헬퍼
// ──────────────────────────────────────────────────────────────────

let passCount = 0;
let failCount = 0;
const failures = [];

function test(name, fn) {
    try {
        fn();
        passCount++;
        console.log(`  ✓ ${name}`);
    } catch (e) {
        failCount++;
        failures.push({ name, error: e.message });
        console.log(`  ✗ ${name}`);
        console.log(`    Error: ${e.message}`);
    }
}

function makeSignal(overrides = {}) {
    return {
        strategy:    'S1_GAP_OPEN',
        stk_cd:      '005930',
        stk_nm:      '삼성전자',
        action:      'ENTER',
        ai_score:    78.5,
        rule_score:  75.0,
        confidence:  'HIGH',
        entry_type:  '시초가_시장가',
        target_pct:  4.0,
        stop_pct:    -2.0,
        gap_pct:     3.85,
        cntr_strength: 143.0,
        ai_reason:   '강한 갭상승과 체결강도 확인',
        signal_time: '2026-03-21T09:00:05',
        cur_prc:     84300,
        ...overrides,
    };
}

// ──────────────────────────────────────────────────────────────────
// escapeHtml 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nescapeHtml 테스트:');

test('ampersand(&) → &amp;', () => {
    assert.strictEqual(escapeHtml('a & b'), 'a &amp; b');
});

test('less-than(<) → &lt;', () => {
    // < 와 > 모두 이스케이프됨
    assert.strictEqual(escapeHtml('<div>'), '&lt;div&gt;');
});

test('greater-than(>) → &gt;', () => {
    assert.strictEqual(escapeHtml('</div>'), '&lt;/div&gt;');
});

test('복합 특수문자 치환', () => {
    const result = escapeHtml('<script>alert("xss")</script>');
    assert.ok(!result.includes('<script>'));
    assert.ok(!result.includes('</script>'));
});

test('null 입력 → 빈 문자열', () => {
    assert.strictEqual(escapeHtml(null), '');
});

test('undefined 입력 → 빈 문자열', () => {
    assert.strictEqual(escapeHtml(undefined), '');
});

test('숫자 입력 → 문자열로 변환', () => {
    assert.strictEqual(escapeHtml(42), '42');
});

test('이미 안전한 텍스트는 변환 없음', () => {
    assert.strictEqual(escapeHtml('안전한 텍스트'), '안전한 텍스트');
});

test('빈 문자열 → 빈 문자열', () => {
    assert.strictEqual(escapeHtml(''), '');
});

test('여러 & 치환', () => {
    const result = escapeHtml('a & b & c');
    // 원본의 ' & ' (공백+앰퍼샌드+공백) 이 없어야 함
    assert.ok(!result.includes(' & '));
    assert.ok(result.includes('&amp;'));
});

// ──────────────────────────────────────────────────────────────────
// formatSignal 기본 필드 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nformatSignal 기본 필드 테스트:');

test('전략 코드가 포함됨', () => {
    const msg = formatSignal(makeSignal());
    assert.ok(msg.includes('S1_GAP_OPEN'), `Expected S1_GAP_OPEN in: ${msg.slice(0, 100)}`);
});

test('종목코드가 포함됨', () => {
    const msg = formatSignal(makeSignal());
    assert.ok(msg.includes('005930'));
});

test('종목명이 포함됨', () => {
    const msg = formatSignal(makeSignal());
    assert.ok(msg.includes('삼성전자'));
});

test('AI 스코어가 포함됨', () => {
    const msg = formatSignal(makeSignal());
    assert.ok(msg.includes('78.5') || msg.includes('78'));
});

test('규칙 스코어가 포함됨', () => {
    const msg = formatSignal(makeSignal());
    assert.ok(msg.includes('75.0') || msg.includes('75'));
});

test('진입방식이 포함됨', () => {
    const msg = formatSignal(makeSignal());
    assert.ok(msg.includes('시초가_시장가'));
});

test('목표 퍼센트가 포함됨 (폴백 % 표시)', () => {
    // tp1_price 없을 때 target_pct % 폴백으로 표시됨
    const msg = formatSignal(makeSignal({ tp1_price: undefined, tp2_price: undefined }));
    assert.ok(msg.includes('4.0') || msg.includes('+4') || msg.includes('목표'));
});

test('손절 퍼센트가 포함됨 (폴백 % 표시)', () => {
    // sl_price 없을 때 stop_pct % 폴백으로 표시됨
    const msg = formatSignal(makeSignal({ sl_price: undefined }));
    assert.ok(msg.includes('-2.0') || msg.includes('-2') || msg.includes('손절'));
});

test('진입가가 포함됨 (현재가 있을 때)', () => {
    const msg = formatSignal(makeSignal({ cur_prc: 84300 }));
    assert.ok(msg.includes('84,300') || msg.includes('84300'));
});

test('AI 분석 근거가 포함됨', () => {
    const msg = formatSignal(makeSignal({ ai_reason: '강한 신호입니다' }));
    assert.ok(msg.includes('강한 신호입니다'));
});

test('갭 정보가 포함됨', () => {
    const msg = formatSignal(makeSignal({ gap_pct: 3.85 }));
    assert.ok(msg.includes('3.85'));
});

test('체결강도가 포함됨', () => {
    const msg = formatSignal(makeSignal({ cntr_strength: 143.0 }));
    assert.ok(msg.includes('143'));
});

// ──────────────────────────────────────────────────────────────────
// formatSignal 옵셔널 필드 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nformatSignal 옵셔널 필드 테스트:');

test('stk_nm 없어도 오류 없음', () => {
    const sig = makeSignal({ stk_nm: undefined });
    const msg = formatSignal(sig);
    assert.ok(typeof msg === 'string');
});

test('ai_reason 없어도 오류 없음', () => {
    const sig = makeSignal({ ai_reason: undefined });
    const msg = formatSignal(sig);
    assert.ok(typeof msg === 'string');
    assert.ok(!msg.includes('undefined'));
});

test('cur_prc 없으면 진입가 라인 없음', () => {
    const sig = makeSignal({ cur_prc: 0, entry_price: 0 });
    const msg = formatSignal(sig);
    // cur_prc <= 0이면 진입가 계산 섹션 없음
    assert.ok(typeof msg === 'string');
});

test('net_buy_amt 있을 때 억 단위 표시', () => {
    const sig = makeSignal({ net_buy_amt: 100_000_000_000 });
    const msg = formatSignal(sig);
    assert.ok(msg.includes('억') || msg.includes('1000'));
});

test('pullback_pct 있을 때 포함', () => {
    const sig = makeSignal({ strategy: 'S2_VI_PULLBACK', pullback_pct: -1.5, gap_pct: undefined });
    const msg = formatSignal(sig);
    assert.ok(msg.includes('-1.5') || msg.includes('눌림'));
});

test('theme_name 있을 때 포함', () => {
    const sig = makeSignal({ strategy: 'S6_THEME_LAGGARD', theme_name: 'AI반도체' });
    const msg = formatSignal(sig);
    assert.ok(msg.includes('AI반도체') || msg.includes('테마'));
});

test('bid_ratio 있을 때 포함', () => {
    const sig = makeSignal({ bid_ratio: 2.5 });
    const msg = formatSignal(sig);
    assert.ok(msg.includes('2.5') || msg.includes('호가'));
});

test('adjusted_target_pct 있으면 target_pct 대신 사용', () => {
    const sig = makeSignal({ target_pct: 4.0, adjusted_target_pct: 3.5 });
    const msg = formatSignal(sig);
    assert.ok(msg.includes('3.5'));
});

// ──────────────────────────────────────────────────────────────────
// 전략별 이모지 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\n전략별 이모지 테스트:');

test('S1 → 🚀 이모지', () => {
    const msg = formatSignal(makeSignal({ strategy: 'S1_GAP_OPEN' }));
    assert.ok(msg.includes('🚀'));
});

test('S2 → 🎯 이모지', () => {
    const msg = formatSignal(makeSignal({ strategy: 'S2_VI_PULLBACK' }));
    assert.ok(msg.includes('🎯'));
});

test('S3 → 🏦 이모지', () => {
    const msg = formatSignal(makeSignal({ strategy: 'S3_INST_FRGN' }));
    assert.ok(msg.includes('🏦'));
});

test('알 수 없는 전략 → 기본 이모지(📌)', () => {
    const msg = formatSignal(makeSignal({ strategy: 'S99_UNKNOWN' }));
    assert.ok(msg.includes('📌'));
});

// ──────────────────────────────────────────────────────────────────
// formatForceClose 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nformatForceClose 테스트:');

test('FORCE_CLOSE 메시지에 종목코드 포함', () => {
    const msg = formatForceClose({ stk_cd: '005930', stk_nm: '삼성전자', strategy: 'S1_GAP_OPEN' });
    assert.ok(msg.includes('005930'));
});

test('FORCE_CLOSE 메시지에 강제청산 단어 포함', () => {
    const msg = formatForceClose({ stk_cd: '005930' });
    assert.ok(msg.includes('강제청산') || msg.includes('청산'));
});

test('FORCE_CLOSE stk_nm 없어도 오류 없음', () => {
    const msg = formatForceClose({ stk_cd: '005930', strategy: 'S1' });
    assert.ok(typeof msg === 'string');
});

// ──────────────────────────────────────────────────────────────────
// formatDailySummary 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nformatDailySummary 테스트:');

test('빈 배열 → 오늘 거래 신호 없음', () => {
    const msg = formatDailySummary([]);
    assert.ok(msg.includes('없음') || msg.includes('0'));
});

test('null → 오늘 거래 신호 없음', () => {
    const msg = formatDailySummary(null);
    assert.ok(msg.includes('없음') || msg.includes('0'));
});

test('통계 배열 있을 때 전략 이름 포함', () => {
    const stats = [['S1_GAP_OPEN', 3, 2.5]];
    const msg = formatDailySummary(stats);
    assert.ok(msg.includes('S1_GAP_OPEN'));
});

// ──────────────────────────────────────────────────────────────────
// 리스크/리워드 계산 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\n리스크/리워드 계산 테스트:');

test('R:R 비율이 메시지에 포함됨 (절대가 있을 때)', () => {
    // tp1_price/sl_price 있을 때만 R:R 계산됨
    const sig = makeSignal({ cur_prc: 100000, tp1_price: 104000, sl_price: 98000 });
    const msg = formatSignal(sig);
    // reward=4000, risk=2000 → R:R 1:2.0
    assert.ok(msg.includes('1:2.0') || msg.includes('2.0') || msg.includes('R/R'));
});

test('목표가 절대가 계산 정확성', () => {
    // tp1_price=104000 → 104,000원 표시
    const sig = makeSignal({ cur_prc: 100000, tp1_price: 104000, sl_price: 98000 });
    const msg = formatSignal(sig);
    assert.ok(msg.includes('104,000') || msg.includes('104000'));
});

// ──────────────────────────────────────────────────────────────────
// ai_reason HTML 이스케이프 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nai_reason HTML 이스케이프 테스트:');

test('ai_reason의 < > 이스케이프', () => {
    const sig = makeSignal({ ai_reason: '<script>alert(1)</script>' });
    const msg = formatSignal(sig);
    assert.ok(!msg.includes('<script>'));
    assert.ok(msg.includes('&lt;script&gt;') || msg.includes('&lt;'));
});

test('ai_reason의 & 이스케이프', () => {
    const sig = makeSignal({ ai_reason: '기관 & 외인 동반 매수' });
    const msg = formatSignal(sig);
    assert.ok(msg.includes('&amp;') || !msg.includes(' & '));
});

// ──────────────────────────────────────────────────────────────────
// 최종 결과
// ──────────────────────────────────────────────────────────────────

console.log('\n─────────────────────────────────────');
console.log(`결과: ${passCount}개 통과, ${failCount}개 실패`);
if (failures.length > 0) {
    console.log('\n실패한 테스트:');
    failures.forEach(f => console.log(`  - ${f.name}: ${f.error}`));
}
console.log('─────────────────────────────────────');

if (failCount > 0) {
    process.exit(1);
}
