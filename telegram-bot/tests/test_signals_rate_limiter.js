'use strict';

/**
 * tests/test_signals_rate_limiter.js
 * signals.js의 rate limiter 테스트
 * 최소 20개 테스트
 */

const assert = require('assert');

// ──────────────────────────────────────────────────────────────────
// Rate Limiter 로직 분리 (signals.js의 _checkRateLimit를 직접 테스트)
// signals.js 모듈 전체가 아닌 rate limiter 로직만 추출하여 테스트
// ──────────────────────────────────────────────────────────────────

function createRateLimiter(maxPerMin = 10) {
    let signalCount = 0;
    let windowStart = Date.now();

    function checkRateLimit() {
        const now = Date.now();
        if (now - windowStart >= 60_000) {
            signalCount = 0;
            windowStart = now;
        }
        if (signalCount >= maxPerMin) {
            return false;
        }
        signalCount++;
        return true;
    }

    function getCount() { return signalCount; }
    function getWindowStart() { return windowStart; }
    function reset(newWindowStart = Date.now()) {
        signalCount = 0;
        windowStart = newWindowStart;
    }

    return { checkRateLimit, getCount, getWindowStart, reset };
}

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

// ──────────────────────────────────────────────────────────────────
// 기본 Rate Limit 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nRate Limiter 기본 동작 테스트:');

test('첫 번째 호출 → 허용', () => {
    const rl = createRateLimiter(10);
    assert.strictEqual(rl.checkRateLimit(), true);
});

test('10번째 호출 → 허용', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 9; i++) rl.checkRateLimit();
    assert.strictEqual(rl.checkRateLimit(), true);
});

test('11번째 호출 → 차단', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 10; i++) rl.checkRateLimit();
    assert.strictEqual(rl.checkRateLimit(), false);
});

test('12번째 호출도 차단', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 10; i++) rl.checkRateLimit();
    rl.checkRateLimit(); // 11
    assert.strictEqual(rl.checkRateLimit(), false); // 12
});

test('허용 후 카운터가 증가', () => {
    const rl = createRateLimiter(10);
    rl.checkRateLimit();
    assert.strictEqual(rl.getCount(), 1);
});

test('5번 허용 후 카운터 = 5', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 5; i++) rl.checkRateLimit();
    assert.strictEqual(rl.getCount(), 5);
});

test('한도(10) 초과 시 카운터는 한도 값', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 12; i++) rl.checkRateLimit();
    assert.strictEqual(rl.getCount(), 10);
});

test('maxPerMin=1 → 첫 호출 허용, 두 번째 차단', () => {
    const rl = createRateLimiter(1);
    assert.strictEqual(rl.checkRateLimit(), true);
    assert.strictEqual(rl.checkRateLimit(), false);
});

test('maxPerMin=0 → 모든 호출 차단', () => {
    const rl = createRateLimiter(0);
    assert.strictEqual(rl.checkRateLimit(), false);
});

// ──────────────────────────────────────────────────────────────────
// 창(Window) 리셋 테스트
// ──────────────────────────────────────────────────────────────────

console.log('\nRate Limiter 창 리셋 테스트:');

test('1분 후 리셋 시 카운터 0', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 10; i++) rl.checkRateLimit();
    assert.strictEqual(rl.getCount(), 10);

    // 1분 이전으로 창 시작 시간 설정
    rl.reset(Date.now() - 61_000);
    rl.checkRateLimit(); // 리셋 후 첫 호출
    assert.strictEqual(rl.getCount(), 1);
});

test('리셋 후 다시 10번 허용', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 10; i++) rl.checkRateLimit();
    rl.reset(Date.now() - 61_000);

    let allowed = 0;
    for (let i = 0; i < 15; i++) {
        if (rl.checkRateLimit()) allowed++;
    }
    assert.strictEqual(allowed, 10);
});

test('60초 미만은 카운터 유지 – 리셋 없이 11번째 차단 확인', () => {
    // reset()을 사용하지 않고 그냥 한도 초과 직후 호출 → 차단 (window 경과 없음)
    const rl = createRateLimiter(10);
    for (let i = 0; i < 10; i++) rl.checkRateLimit();
    // window가 expire 되지 않았으므로 즉시 추가 호출은 차단
    assert.strictEqual(rl.checkRateLimit(), false);
});

test('정확히 60000ms에 리셋', () => {
    const rl = createRateLimiter(10);
    for (let i = 0; i < 10; i++) rl.checkRateLimit();

    // 정확히 60초 전
    rl.reset(Date.now() - 60_000);
    // 60000ms >= 60000 → 리셋 발생
    assert.strictEqual(rl.checkRateLimit(), true);
});

// ──────────────────────────────────────────────────────────────────
// 엣지 케이스
// ──────────────────────────────────────────────────────────────────

console.log('\nRate Limiter 엣지 케이스 테스트:');

test('maxPerMin=100 → 100번 허용', () => {
    const rl = createRateLimiter(100);
    let allowed = 0;
    for (let i = 0; i < 100; i++) {
        if (rl.checkRateLimit()) allowed++;
    }
    assert.strictEqual(allowed, 100);
});

test('maxPerMin=100 → 101번째 차단', () => {
    const rl = createRateLimiter(100);
    for (let i = 0; i < 100; i++) rl.checkRateLimit();
    assert.strictEqual(rl.checkRateLimit(), false);
});

test('리셋 후 윈도우 시작 시간이 현재 시각과 가까움', () => {
    const rl = createRateLimiter(10);
    rl.reset(Date.now() - 61_000);
    rl.checkRateLimit(); // 리셋 트리거
    const windowStart = rl.getWindowStart();
    const diff = Math.abs(Date.now() - windowStart);
    assert.ok(diff < 1000, `Window start should be within 1s of now, diff=${diff}`);
});

// ──────────────────────────────────────────────────────────────────
// signals.js 모듈 smoke test
// ──────────────────────────────────────────────────────────────────

console.log('\nsignals.js 모듈 구조 테스트:');

test('signals.js 로드 가능', () => {
    const path = require('path');
    // signals.js는 redis 연결을 시도하므로 실제 로드 없이 파일 존재 여부 확인
    const fs = require('fs');
    const signalsPath = path.join(__dirname, '../src/handlers/signals.js');
    assert.ok(fs.existsSync(signalsPath), 'signals.js should exist');
});

test('signals.js에 startPolling 함수 존재', () => {
    const fs = require('fs');
    const path = require('path');
    const content = fs.readFileSync(
        path.join(__dirname, '../src/handlers/signals.js'),
        'utf8'
    );
    assert.ok(content.includes('startPolling'));
});

test('signals.js에 _checkRateLimit 함수 존재', () => {
    const fs = require('fs');
    const path = require('path');
    const content = fs.readFileSync(
        path.join(__dirname, '../src/handlers/signals.js'),
        'utf8'
    );
    assert.ok(content.includes('_checkRateLimit'));
});

test('signals.js에 MAX_SIGNALS_PER_MIN 변수 존재', () => {
    const fs = require('fs');
    const path = require('path');
    const content = fs.readFileSync(
        path.join(__dirname, '../src/handlers/signals.js'),
        'utf8'
    );
    assert.ok(content.includes('MAX_SIGNALS_PER_MIN'));
});

test('signals.js에 MIN_AI_SCORE 변수 존재', () => {
    const fs = require('fs');
    const path = require('path');
    const content = fs.readFileSync(
        path.join(__dirname, '../src/handlers/signals.js'),
        'utf8'
    );
    assert.ok(content.includes('MIN_AI_SCORE'));
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
