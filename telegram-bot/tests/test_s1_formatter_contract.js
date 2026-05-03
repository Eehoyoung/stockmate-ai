'use strict';

const assert = require('assert');
const path = require('path');

const { formatSignal } = require(path.join(__dirname, '../src/utils/formatter'));

function makeS1(overrides = {}) {
    return {
        strategy: 'S1_GAP_OPEN',
        stk_cd: '005930',
        stk_nm: 'Samsung Electronics',
        action: 'ENTER',
        ai_score: 81.2,
        rule_score: 100,
        confidence: 'HIGH',
        cur_prc: 84300,
        tp1_price: 88000,
        display_tp2_price: 92000,
        sl_price: 82000,
        claude_tp1: 90000,
        claude_tp2: 93000,
        claude_sl: 81000,
        rr_ratio: 1.65,
        ai_reason: 'opening gap confirmed',
        ...overrides,
    };
}

function assertIncludes(message, expected) {
    assert.ok(
        message.includes(expected),
        `expected message to include ${expected}\n${message}`,
    );
}

const msg = formatSignal(makeS1());
assertIncludes(msg, 'S1_GAP_OPEN');
assertIncludes(msg, '005930');
assertIncludes(msg, 'Samsung Electronics');
assertIncludes(msg, '84,300');
assertIncludes(msg, '90,000');
assertIncludes(msg, '93,000');
assertIncludes(msg, '81,000');
assertIncludes(msg, '1.65');
assertIncludes(msg, 'opening gap confirmed');
assert.ok(!msg.includes('88,000'), 'claude_tp1 should win over rule tp1_price');
assert.ok(!msg.includes('92,000'), 'claude_tp2 should win over display_tp2_price');
assert.ok(!msg.includes('82,000'), 'claude_sl should win over rule sl_price');

const claudeOnly = formatSignal(makeS1({
    tp1_price: undefined,
    display_tp2_price: undefined,
    sl_price: undefined,
    rr_ratio: undefined,
}));
assertIncludes(claudeOnly, '90,000');
assertIncludes(claudeOnly, '93,000');
assertIncludes(claudeOnly, '81,000');

const ruleFallback = formatSignal(makeS1({
    claude_tp1: undefined,
    claude_tp2: undefined,
    claude_sl: undefined,
}));
assertIncludes(ruleFallback, '88,000');
assertIncludes(ruleFallback, '92,000');
assertIncludes(ruleFallback, '82,000');

console.log('PASS S1 formatter contract');
