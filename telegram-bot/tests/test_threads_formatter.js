'use strict';

/**
 * test_threads_formatter.js
 * 실행: node telegram-bot/tests/test_threads_formatter.js
 */

const path = require('path');
const formatterPath = path.resolve(__dirname, '../src/utils/threads_formatter');
const { formatThreadsSignal, formatThreadsBriefing, computeThreadsRR } = require(formatterPath);

let pass = 0;
let fail = 0;

function test(name, fn) {
    try {
        fn();
        console.log(`  PASS  ${name}`);
        pass++;
    } catch (e) {
        console.error(`  FAIL  ${name}`);
        console.error(`        ${e.message}`);
        fail++;
    }
}

function assert(cond, msg) {
    if (!cond) throw new Error(msg || 'assertion failed');
}

// ── 기본 픽스처 ────────────────────────────────────────────────────────────
const BASE = {
    strategy:    'S8_GOLDEN_CROSS',
    stk_nm:      '삼성전자',
    stk_cd:      '005930',
    cur_prc:     73500,
    tp1_price:   76000,
    sl_price:    71200,
    rsi:         52.3,
    vol_ratio:   1.8,
    ai_score:    81.0,
    signal_time: '2026-05-07T10:23:00+09:00',
};

console.log('\n[threads_formatter 단위 테스트]\n');

// ── TC1: 글자 수 ─────────────────────────────────────────────────────────
test('TC1  450자 이하', () => {
    const t = formatThreadsSignal(BASE);
    assert(t.length <= 450, `${t.length}자 — 450자 초과`);
});

// ── TC2: HTML 태그 없음 ──────────────────────────────────────────────────
test('TC2  HTML 태그 없음', () => {
    const t = formatThreadsSignal(BASE);
    assert(!/<[^>]+>/.test(t), 'HTML 태그 포함됨');
});

// ── TC3: 면책 문구 포함 ──────────────────────────────────────────────────
test('TC3  면책 문구 포함', () => {
    const t = formatThreadsSignal(BASE);
    assert(t.includes('투자권유가 아닙니다'), '면책 문구 없음');
    assert(t.includes('본인 책임입니다'), '책임 문구 없음');
});

// ── TC4: 해시태그 포함 ───────────────────────────────────────────────────
test('TC4  해시태그 포함', () => {
    const t = formatThreadsSignal(BASE);
    assert(t.includes('#'), '해시태그 없음');
    assert(t.includes('#국내주식'), '#국내주식 해시태그 없음');
});

// ── TC5: 금지 표현 없음 ──────────────────────────────────────────────────
test('TC5  금지 표현 없음 (매수/진입/손절/목표가/권장)', () => {
    const t = formatThreadsSignal(BASE);
    const banned = ['매수', '진입', '손절', '목표가', '권장'];
    for (const w of banned) {
        assert(!t.includes(w), `금지 표현 포함: "${w}"`);
    }
});

// ── TC6: S1 갭 오픈 전용 분기 ────────────────────────────────────────────
test('TC6  S1 갭 오픈 — 갭 비율 및 전용 헤더', () => {
    const item = { ...BASE, strategy: 'S1_GAP_OPEN', gap_pct: 2.4 };
    const t = formatThreadsSignal(item);
    assert(t.includes('[갭 오픈 패턴 감지]'), 'S1 전용 헤더 없음');
    assert(t.includes('+2.4%'), '갭 비율 없음');
    assert(!t.includes('[기술적 신호 탐지]'), 'S1에 기본 헤더 혼용');
});

// ── TC7: claude_tp1 우선 적용 ────────────────────────────────────────────
test('TC7  claude_tp1 우선 적용 (tp1_price 무시)', () => {
    const item = { ...BASE, claude_tp1: 77000, tp1_price: 76000 };
    const t = formatThreadsSignal(item);
    assert(t.includes('77,000'), 'claude_tp1(77000) 미반영');
    assert(!t.includes('76,000'), 'tp1_price(76000)가 우선됨 — claude_tp1이 덮어야 함');
});

// ── TC8: claude_sl 우선 적용 ─────────────────────────────────────────────
test('TC8  claude_sl 우선 적용 (sl_price 무시)', () => {
    const item = { ...BASE, claude_sl: 70000, sl_price: 71200 };
    const t = formatThreadsSignal(item);
    assert(t.includes('70,000'), 'claude_sl(70000) 미반영');
});

// ── TC9: 가격 없는 경우 크래시 없음 ─────────────────────────────────────
test('TC9  가격 필드 전부 없어도 크래시 없음', () => {
    const item = { strategy: 'S8_GOLDEN_CROSS', stk_cd: '005930' };
    const t = formatThreadsSignal(item);
    assert(typeof t === 'string', '문자열 반환 실패');
    assert(t.includes('투자권유가 아닙니다'), '면책 문구 없음');
});

// ── TC10: 450자 초과 입력 → 말줄임 처리 ─────────────────────────────────
test('TC10 초과 길이 item → 450자 이하 + 말줄임 처리', () => {
    const item = {
        ...BASE,
        stk_nm: '이름이매우길고아주긴종목명이라서글자수가폭발할수도있는상황테스트용더미데이터'.repeat(10),
    };
    const t = formatThreadsSignal(item);
    assert(t.length <= 450, `${t.length}자 — 450자 초과`);
    assert(t.endsWith('…'), `말줄임(…) 없음 — 실제 끝: "${t.slice(-3)}"`);
});

// ── TC11: 전략 설명 문구 포함 ────────────────────────────────────────────
test('TC11 전략 설명 문구 포함', () => {
    const t = formatThreadsSignal(BASE);
    assert(t.includes('골든크로스'), '전략 설명 없음');
});

// ── TC12: 목표·리스크 구간 라벨 확인 + 퍼센트 미노출 ─────────────────────
test('TC12 목표·리스크 구간 — 퍼센트 미노출 + 라벨 확인', () => {
    const t = formatThreadsSignal(BASE);
    assert(t.includes('목표 구간 1'), '목표 구간 1 라벨 없음');
    assert(t.includes('리스크 관리 구간'), '리스크 관리 구간 라벨 없음');
    // 퍼센트 표시 없어야 함 (자본시장법 위반 방지)
    assert(!/\(\s*[+-]\d+\.\d+%\s*\)/.test(t), '퍼센트 표시 잔존');
});

// ── TC12a: AI점수 미노출 ─────────────────────────────────────────────────
test('TC12a AI점수 미노출 — 자본시장법 §6⑥ 준수', () => {
    const item = { ...BASE, ai_score: 81.0 };
    const t = formatThreadsSignal(item);
    assert(!t.includes('AI점수'), 'AI점수 표시됨');
    assert(!t.includes('81.0'), 'AI점수 숫자 표시됨');
});

// ── formatThreadsBriefing 테스트 ─────────────────────────────────────────

const BRIEFING_ITEM = {
    type:    'STATUS_REPORT',
    message: [
        '🧠 <b>[오전 시황 브리핑 08:00]</b>',
        '페르소나: 수석 매크로 애널리스트 + 헤드 트레이더',
        '',
        '시장 온도: 강세 우위',
        '',
        '1) 전일 미 3대지수',
        '• 나스닥 사상최고치 돌파',
        '• AMD 1분기 매출 38% 급증',
        '• AI 수요로 반도체 강세 지속',
        '',
        '2) 외부 변수',
        '• 미국채 30년물 금리 5% 돌파',
        '• 원달러 환율 1,462원 급락',
        '',
        '한 줄 결론',
        '코스피가 반도체 불기둥과 함께 사상 첫 6,900선을 돌파했다.',
    ].join('\n'),
    summary: {
        queue_counts:      { telegram_queue: 5, ai_scored_queue: 3, error_queue: 2 },
        active_strategies: ['S1_GAP_OPEN', 'S8_GOLDEN_CROSS'],
        position_count:    3,
        exit_today_count:  1,
    },
};

// TC13: 450자 이하
test('TC13 브리핑 — 450자 이하', () => {
    const t = formatThreadsBriefing(BRIEFING_ITEM);
    assert(t.length <= 450, `${t.length}자 — 450자 초과`);
});

// TC14: HTML 태그 제거 확인
test('TC14 브리핑 — HTML 태그 제거', () => {
    const t = formatThreadsBriefing(BRIEFING_ITEM);
    assert(!/<[^>]+>/.test(t), 'HTML 태그 잔존');
});

// TC15: 페르소나 라인 제거 확인
test('TC15 브리핑 — 페르소나 라인 제거', () => {
    const t = formatThreadsBriefing(BRIEFING_ITEM);
    assert(!t.includes('페르소나:'), '페르소나 라인 잔존');
});

// TC16: 시스템 운영 지표 미노출 — message 내 시스템 섹션 절단
test('TC16 브리핑 — 시스템 운영 지표 미포함', () => {
    const itemWithSystem = {
        type: 'STATUS_REPORT',
        message: [
            '시장 온도: 강세 우위',
            '나스닥 사상최고치 돌파',
            '',
            'telegram_queue: 5건',
            'S1_GAP_OPEN: 활성',
            'error_queue: 2건',
            'ai_scored_queue: 3건',
        ].join('\n'),
    };
    const t = formatThreadsBriefing(itemWithSystem);
    assert(!t.includes('telegram_queue'),  'telegram_queue 노출');
    assert(!t.includes('error_queue'),     'error_queue 노출');
    assert(!t.includes('ai_scored_queue'), 'ai_scored_queue 노출');
    assert(!t.includes('S1_GAP_OPEN'),     'strategy 명칭 노출');
    assert(t.includes('시장 온도'),         '정상 내용이 제거됨');
});

// TC17: 브리핑 전용 면책 문구 포함
test('TC17 브리핑 — 면책 문구 포함', () => {
    const t = formatThreadsBriefing(BRIEFING_ITEM);
    assert(t.includes('투자권유가 아닙니다'), '면책 문구 없음');
    assert(t.includes('자동 생성 시황 분석'), '브리핑 전용 면책 문구 없음');
});

// TC18: 브리핑 해시태그 포함
test('TC18 브리핑 — 해시태그 포함', () => {
    const t = formatThreadsBriefing(BRIEFING_ITEM);
    assert(t.includes('#시황브리핑'), '#시황브리핑 없음');
    assert(t.includes('#자동기록'),   '#자동기록 없음');
});

// TC19: 긴 브리핑 → 말줄임 처리
test('TC19 브리핑 — 긴 메시지 말줄임 처리', () => {
    const longItem = {
        ...BRIEFING_ITEM,
        message: '매우긴시황내용'.repeat(100),
    };
    const t = formatThreadsBriefing(longItem);
    assert(t.length <= 450, `${t.length}자 — 450자 초과`);
    assert(
        t.includes('…') || t.split('\n\n')[0].length <= 350,
        '말줄임(…) 없이 초과됨'
    );
});

// TC20: 빈 message → 크래시 없음
test('TC20 브리핑 — 빈 message 크래시 없음', () => {
    const t = formatThreadsBriefing({ type: 'STATUS_REPORT', message: '' });
    assert(typeof t === 'string', '문자열 반환 실패');
    assert(t.includes('투자권유가 아닙니다'), '면책 문구 없음');
});

// TC21: 금지 표현 라인 필터
test('TC21 브리핑 — 금지 표현 라인 필터', () => {
    const item = {
        type: 'STATUS_REPORT',
        message: '시장 분석\n이 종목은 단기 강세 흐름입니다.\n매수를 권장합니다\n외국인 연속 순유입 지속\n목표가 상향 조정됩니다',
    };
    const t = formatThreadsBriefing(item);
    assert(!t.includes('매수를 권장'), '매수 권장 라인 미제거');
    assert(!t.includes('목표가'), '목표가 포함 라인 미제거');
    assert(t.includes('외국인 연속 순유입 지속'), '정상 라인이 제거됨');
});

// TC22: 시간대 레이블 — [개장 전]/[정오]/[마감 후]
test('TC22 시간대 레이블 — [개장 전]/[정오]/[마감 후]', () => {
    // 개장 전 (08:30 KST)
    const t1 = formatThreadsSignal({ ...BASE, signal_time: '2026-05-07T08:30:00+09:00' });
    assert(t1.includes('[개장 전]'), '[개장 전] 레이블 없음');

    // 정오 (12:00 KST)
    const t2 = formatThreadsSignal({ ...BASE, signal_time: '2026-05-07T12:00:00+09:00' });
    assert(t2.includes('[정오]'), '[정오] 레이블 없음');

    // 마감 후 (15:35 KST)
    const t3 = formatThreadsSignal({ ...BASE, signal_time: '2026-05-07T15:35:00+09:00' });
    assert(t3.includes('[마감 후]'), '[마감 후] 레이블 없음');

    // 일반 거래 시간 (10:23 KST) — BASE 기본값 → 레이블 없음
    const t4 = formatThreadsSignal(BASE);
    assert(
        !t4.includes('[개장 전]') && !t4.includes('[정오]') && !t4.includes('[마감 후]'),
        '일반 시간대에 레이블 표시됨'
    );
});

// TC23: R:R 두 단계 경고 — ⛔/⚠️ 표시
test('TC23 R:R 두 단계 경고 — ⛔/⚠️ 표시', () => {
    // BASE: entry=73500, tp1=76000, sl=71200, KOSPI → RR≈0.877 → ⛔
    const t1 = formatThreadsSignal(BASE);
    assert(t1.includes('⛔'), 'RR < 1.0인데 ⛔ 없음');

    // sl=72500 → effRisk=(1000/73500)+0.0035≈0.0171, effTarget=(2500/73500)-0.0035≈0.0305
    // RR≈1.78 → 경고 없음
    const highRR = { ...BASE, sl_price: 72500 };
    const t2 = formatThreadsSignal(highRR);
    assert(!t2.includes('⛔') && !t2.includes('⚠️'), 'RR ≥ 1.5인데 경고 있음');

    // tp1=75500, sl=72500 → effTarget=(2000/73500)-0.0035≈0.0237, effRisk=(1000/73500)+0.0035≈0.0171
    // RR≈1.39 → ⚠️
    const midRR = { ...BASE, tp1_price: 75500, sl_price: 72500 };
    const t3 = formatThreadsSignal(midRR);
    assert(t3.includes('⚠️'), 'RR 1.0-1.5인데 ⚠️ 없음');
    assert(!t3.includes('⛔'), 'RR ≥ 1.0인데 ⛔ 있음');
});

// TC23b: computeThreadsRR 계산 정확도
test('TC23b computeThreadsRR 계산 정확도 (KOSPI/KOSDAQ)', () => {
    // KOSPI: stk_cd '005930' (starts '0'), slip=0.35%
    const rrKospi = computeThreadsRR('005930', 73500, 76000, 71200);
    assert(rrKospi !== null, 'KOSPI RR null');
    // effTarget = 2500/73500 - 0.0035 ≈ 0.030514
    // effRisk   = 2300/73500 + 0.0035 ≈ 0.034793
    // RR ≈ 0.877
    assert(Math.abs(rrKospi - 0.877) < 0.01, `KOSPI RR 계산 오차: ${rrKospi}`);

    // KOSDAQ: stk_cd '263750' (starts '2'), slip=0.45%
    const rrKosdaq = computeThreadsRR('263750', 73500, 76000, 71200);
    assert(rrKosdaq !== null, 'KOSDAQ RR null');
    assert(rrKosdaq < rrKospi, 'KOSDAQ R:R이 KOSPI보다 높음 (슬리피지 차이 반영 안 됨)');

    // 유효성 검사: sl >= entry → null
    assert(computeThreadsRR('005930', 73500, 76000, 73500) === null, 'sl=entry인데 null 아님');
    assert(computeThreadsRR('005930', 0, 76000, 71200) === null, 'entry=0인데 null 아님');
});

// TC24: 브리핑 문장 경계 말줄임 처리
test('TC24 브리핑 — 문장 경계 말줄임 처리', () => {
    // 250자 문장 + 200자 나머지 → 총 451자 > bodyMax(≈356)
    // 마지막 '.'이 250번째 위치 → 40% 임계값(142) 초과 → 문장 경계 절단
    const firstPart = '가'.repeat(250) + '.';
    const rest      = '나'.repeat(200);
    const longItem  = { type: 'STATUS_REPORT', message: firstPart + rest };
    const t         = formatThreadsBriefing(longItem);
    assert(t.length <= 450, `${t.length}자 초과`);
    const textPart  = t.split('\n\n')[0];
    assert(
        textPart.endsWith('.') || textPart.endsWith('…'),
        `문장 경계 처리 없음: "${textPart.slice(-5)}"`
    );
});

// ── 결과 출력 ────────────────────────────────────────────────────────────
console.log(`\n결과: ${pass}통과 / ${fail}실패\n`);
if (fail > 0) process.exit(1);
