'use strict';

const assert = require('assert');
const path = require('path');

const {
    formatActivePositionsMessage,
    formatKstYymmdd,
} = require(path.join(__dirname, '../src/utils/activePositionsFormatter'));
const {
    nextHourlySlot,
    slotKey,
} = require(path.join(__dirname, '../src/handlers/activePositionsScheduler'));

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

test('formatKstYymmdd renders buy date in yymmdd', () => {
    assert.strictEqual(formatKstYymmdd('2026-05-14T09:05:00+09:00'), '260514');
});

test('formatActivePositionsMessage includes active position fields', () => {
    const msg = formatActivePositionsMessage([
        {
            stk_cd: '005930',
            stk_nm: '삼성전자',
            entry_price: 84300,
            tp1_price: 88000,
            sl_price: 82000,
            buy_at: '2026-05-14T09:05:00+09:00',
        },
    ], new Date('2026-05-14T10:00:00+09:00'));

    assert.ok(msg.includes('[활성 종목 현황]'));
    assert.ok(msg.includes('현재 활성 포지션: <b>1</b>개'));
    assert.ok(msg.includes('삼성전자(005930)'));
    assert.ok(msg.includes('매수단가: <b>84,300원</b>'));
    assert.ok(msg.includes('1차목표가: <b>88,000원</b>'));
    assert.ok(msg.includes('손절가: <b>82,000원</b>'));
    assert.ok(msg.includes('매수일: <b>260514</b>'));
});

test('formatActivePositionsMessage escapes stock labels', () => {
    const msg = formatActivePositionsMessage([
        {
            stk_cd: '000001',
            stk_nm: '<위험&종목>',
            entry_price: 1,
            tp1_price: 2,
            sl_price: 0.5,
            buy_at: '2026-05-14T09:00:00+09:00',
        },
    ]);

    assert.ok(msg.includes('&lt;위험&amp;종목&gt;'));
    assert.ok(!msg.includes('<위험&종목>'));
});

test('formatActivePositionsMessage handles empty positions', () => {
    const msg = formatActivePositionsMessage([], new Date('2026-05-14T16:00:00+09:00'));
    assert.ok(msg.includes('현재 활성 포지션: <b>0</b>개'));
    assert.ok(msg.includes('현재 활성화된 종목이 없습니다.'));
});

test('nextHourlySlot schedules from pre-open to 09:00 KST', () => {
    const result = nextHourlySlot(new Date('2026-05-14T08:30:00+09:00'));
    assert.strictEqual(result.delayMs, 30 * 60 * 1000);
    assert.strictEqual(result.kstSlot.getUTCHours(), 9);
});

test('nextHourlySlot schedules exact in-window hour immediately', () => {
    const result = nextHourlySlot(new Date('2026-05-14T12:00:00+09:00'));
    assert.strictEqual(result.delayMs, 0);
    assert.strictEqual(result.kstSlot.getUTCHours(), 12);
});

test('nextHourlySlot skips current exact hour when requested by recursive scheduler', () => {
    const result = nextHourlySlot(new Date('2026-05-14T09:00:00+09:00'), {
        includeCurrentExact: false,
    });
    assert.strictEqual(result.delayMs, 60 * 60 * 1000);
    assert.strictEqual(result.kstSlot.getUTCHours(), 10);
});

test('slotKey is stable at hourly precision', () => {
    assert.strictEqual(slotKey(new Date(Date.UTC(2026, 4, 14, 9, 0, 0))), '2026-05-14 09');
    assert.strictEqual(slotKey(new Date(Date.UTC(2026, 4, 14, 9, 59, 59))), '2026-05-14 09');
});

test('nextHourlySlot schedules after 16:00 window to next day 09:00 KST', () => {
    const result = nextHourlySlot(new Date('2026-05-14T16:00:01+09:00'));
    assert.strictEqual(result.kstSlot.getUTCDate(), 15);
    assert.strictEqual(result.kstSlot.getUTCHours(), 9);
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
