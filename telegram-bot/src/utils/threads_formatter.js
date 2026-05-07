'use strict';

const { normalizeForDisplay } = require('./price');

const MAX_CHARS = 450;

// ── Threads 전용 R:R 계산 (Telegram formatter.js _effectiveRR와 완전 독립) ──

const _THREADS_SLIP = { KOSPI: 0.0035, KOSDAQ: 0.0045 };

/**
 * Threads 게시용 슬리피지·수수료 반영 R:R 계산.
 * Telegram formatter.js의 _effectiveRR와 독립된 별개 구현.
 * @param {string} stkCd  종목코드 ('0'으로 시작하면 KOSPI, 그 외 KOSDAQ)
 * @param {number} entry  기준가 (현재가 또는 진입가)
 * @param {number} tp1    1차 목표가
 * @param {number} sl     리스크 관리 기준가
 * @returns {number|null} R:R 비율, 계산 불가 시 null
 */
function computeThreadsRR(stkCd, entry, tp1, sl) {
    if (!entry || !tp1 || !sl || sl >= entry) return null;
    const slip      = String(stkCd ?? '').startsWith('0') ? _THREADS_SLIP.KOSPI : _THREADS_SLIP.KOSDAQ;
    const effTarget = (tp1 - entry) / entry - slip;
    const effRisk   = (entry - sl)  / entry + slip;
    return effRisk > 0 ? effTarget / effRisk : null;
}

function _formatThreadsRR(rr) {
    if (rr === null) return null;
    const warn = rr < 1.0 ? ' ⛔' : (rr < 1.5 ? ' ⚠️' : '');
    return `R:R ${rr.toFixed(2)}${warn}`;
}

// ── 전략 설명 ─────────────────────────────────────────────────────────────

const STRATEGY_DESC_SHORT = {
    S1_GAP_OPEN:          '갭 오픈 패턴',
    S2_VI_PULLBACK:       'VI 발동 눌림목',
    S3_INST_FRGN:         '기관·외국인 거래 동향 감지',
    S4_BIG_CANDLE:        '장대양봉 거래량 급증',
    S5_PROG_FRGN:         '프로그램+외국인 동반',
    S6_THEME_LAGGARD:     '테마 후발 소외주',
    S7_ICHIMOKU_BREAKOUT: '일목균형 구름대 돌파',
    S8_GOLDEN_CROSS:      '골든크로스 (MA5×MA20)',
    S9_PULLBACK_SWING:    '5일선 눌림목',
    S10_NEW_HIGH:         '52주 신고가 돌파',
    S11_FRGN_CONT:        '외국인 3일 이상 연속 순매수',
    S12_CLOSING:          '장 마감 종가 강도',
    S13_BOX_BREAKOUT:     '박스권 상단 돌파',
    S14_OVERSOLD_BOUNCE:  'RSI 과매도 반등',
    S15_MOMENTUM_ALIGN:   '복합 모멘텀 동시 신호',
};

const HASHTAG_MAP = {
    S1_GAP_OPEN:         '#갭오픈 #국내주식 #자동기록',
    S2_VI_PULLBACK:      '#VI발동 #국내주식 #자동기록',
    S4_BIG_CANDLE:       '#장대양봉 #국내주식 #자동기록',
    S6_THEME_LAGGARD:    '#테마주 #국내주식 #자동기록',
    S8_GOLDEN_CROSS:     '#골든크로스 #국내주식 #자동기록',
    S10_NEW_HIGH:        '#신고가 #국내주식 #자동기록',
    S11_FRGN_CONT:       '#외국인매수 #국내주식 #자동기록',
    S13_BOX_BREAKOUT:    '#박스돌파 #국내주식 #자동기록',
    S14_OVERSOLD_BOUNCE: '#과매도반등 #국내주식 #자동기록',
};
const DEFAULT_HASHTAG = '#기술적분석 #국내주식 #자동기록';

const DISCLAIMER =
    '본 내용은 기술적 지표 조건 충족 사실을 자동 기록한 것입니다.' +
    ' 투자권유가 아닙니다. 투자 결정과 손익은 본인 책임입니다.';

const BRIEFING_DISCLAIMER =
    '본 내용은 AI가 공개 데이터를 기반으로 작성한 자동 생성 시황 분석입니다.' +
    ' 투자권유가 아닙니다. 투자 결정과 손익은 본인 책임입니다.';
const BRIEFING_HASHTAG = '#시황브리핑 #알고리즘트레이딩 #자동기록';

// ── 금지 표현 (자본시장법 투자권유 금지 기준) ────────────────────────────

const FORBIDDEN_WORDS = ['매수', '진입', '손절', '목표가', '권장', '추천', '비중 확대'];

// ── 시스템 운영 지표 섹션 패턴 ───────────────────────────────────────────

const SYSTEM_SECTION_PATTERNS = [
    /큐\s*상태/,
    /telegram_queue/,
    /ai_scored_queue/,
    /error_queue/,
    /vi_watch_queue/,
    /\bS\d+_[A-Z][A-Z_]+\b/,
];

// ── 헬퍼 ─────────────────────────────────────────────────────────────────

function _cap(text, max) {
    if (text.length <= max) return text;
    return text.slice(0, max - 1) + '…';
}

/** KST 기준 시간대 레이블 반환. 일반 거래 시간대는 null. */
function _timeZoneLabel(item) {
    const src     = item.signal_time ? new Date(item.signal_time) : new Date();
    const kstMs   = src.getTime() + 9 * 60 * 60 * 1000;
    const kstDate = new Date(kstMs);
    const h       = kstDate.getUTCHours();
    const m       = kstDate.getUTCMinutes();
    if (h < 9)                           return '[개장 전]';
    if (h === 12)                        return '[정오]';
    if (h > 15 || (h === 15 && m >= 30)) return '[마감 후]';
    return null;
}

function _signalTime(item) {
    const src = item.signal_time ? new Date(item.signal_time) : new Date();
    return src.toLocaleTimeString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour: '2-digit',
        minute: '2-digit',
    });
}

/** 체결강도에 강/보통/약 컨텍스트 레이블 추가 */
function _strengthLabel(strength) {
    if (strength == null) return null;
    const s = Number(strength);
    if (s >= 150) return `체결강도: ${strength} (강)`;
    if (s >= 100) return `체결강도: ${strength} (보통)`;
    return `체결강도: ${strength} (약)`;
}

/** 금지 표현이 포함된 줄 제거 (자본시장법 준수) */
function _filterForbiddenLines(text) {
    return text
        .split(/\r?\n/)
        .filter((line) => !FORBIDDEN_WORDS.some((w) => line.includes(w)))
        .join('\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

/** 시스템 운영 지표 섹션 이후 내용 잘라냄 */
function _truncateAtSystemSection(text) {
    const lines = text.split(/\r?\n/);
    const cutAt = lines.findIndex((line) => SYSTEM_SECTION_PATTERNS.some((p) => p.test(line)));
    if (cutAt === -1) return text;
    return lines.slice(0, cutAt).join('\n').trim();
}

/** 마지막 문장 경계(. ! ? 등)에서 말줄임 처리 */
function _truncateToSentence(text, max) {
    if (text.length <= max) return text;
    const cut          = text.slice(0, max);
    const lastBoundary = Math.max(
        cut.lastIndexOf('。'), cut.lastIndexOf('.'),
        cut.lastIndexOf('!'),  cut.lastIndexOf('?'),
        cut.lastIndexOf('！'), cut.lastIndexOf('？'),
    );
    if (lastBoundary > max * 0.4) return text.slice(0, lastBoundary + 1);
    return cut.slice(0, max - 1) + '…';
}

// ── HTML 파싱 / 페르소나 제거 ────────────────────────────────────────────

function _stripHtml(html) {
    return String(html || '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/p>/gi, '\n')
        .replace(/<[^>]+>/g, '')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
        .replace(/&nbsp;/g, ' ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function _stripPersonaLine(text) {
    return text
        .split(/\r?\n/)
        .filter((line) => {
            const norm = line
                .replace(/[^\p{L}\p{N}:：+\s]/gu, '')
                .trim()
                .toLowerCase();
            return !norm.startsWith('페르소나:')
                && !norm.startsWith('페르소나：')
                && !norm.startsWith('persona:')
                && !norm.startsWith('persona：');
        })
        .join('\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

// ── 공개 API ─────────────────────────────────────────────────────────────

/**
 * ENTER / RULE_ONLY_SIGNAL 전용 Threads 게시물 생성.
 * Telegram formatSignal()과 동일 item을 입력받아 법적 준수 plain text로 변환.
 *
 * 준수 사항:
 *   - AI 점수 미노출 (자본시장법 §6⑥)
 *   - TP/SL 퍼센트 표시 제거
 *   - 면책 고지를 헤더 바로 아래 배치
 *
 * @param {Object} item  ai_scored_queue 항목
 * @returns {string}     450자 이하 plain text
 */
function formatThreadsSignal(item) {
    const isS1      = item.strategy === 'S1_GAP_OPEN';
    const stratDesc = STRATEGY_DESC_SHORT[item.strategy] || item.strategy;
    const stockLabel = item.stk_nm
        ? `${item.stk_nm} (${item.stk_cd})`
        : (item.stk_cd || '-');

    const entryRaw = Number(item.cur_prc ?? item.entry_price ?? 0);
    const tp1Raw   = item.claude_tp1 ?? item.tp1_price ?? null;
    const slRaw    = item.claude_sl  ?? item.sl_price  ?? null;

    const curPrc = normalizeForDisplay(entryRaw);
    const tp1    = tp1Raw != null ? normalizeForDisplay(tp1Raw) : null;
    const sl     = slRaw  != null ? normalizeForDisplay(slRaw)  : null;

    const rsi      = item.rsi       != null ? Number(item.rsi).toFixed(1)       : null;
    const volRatio = item.vol_ratio != null ? Number(item.vol_ratio).toFixed(1) : null;
    const gapPct   = item.gap_pct   != null ? Number(item.gap_pct).toFixed(1)   : null;
    const strength = item.cntr_strength != null ? item.cntr_strength            : null;

    // 시간 및 시간대 레이블 (헤더에 임베드)
    const zoneLabel   = _timeZoneLabel(item);
    const timeStr     = _signalTime(item);
    const headerLabel = isS1 ? '[갭 오픈 패턴 감지]' : '[기술적 신호 탐지]';
    const header      = `${headerLabel} ${timeStr} KST${zoneLabel ? ' ' + zoneLabel : ''}`;

    const lines = [
        header,
        DISCLAIMER,     // 면책 고지: 헤더 바로 아래 배치 (Threads fold 이전 노출)
        `종목: ${stockLabel}`,
        isS1
            ? `패턴: 갭 상승 조건 충족${gapPct ? ` (+${gapPct}%)` : ''}`
            : `패턴: ${stratDesc} 조건 충족`,
        '',
    ];

    if (curPrc > 0) lines.push(`현재가: ${curPrc.toLocaleString()}원`);

    if (isS1) {
        if (tp1) lines.push(`상단 저항 구간: ${tp1.toLocaleString()}원`);
        if (sl)  lines.push(`하단 지지 구간: ${sl.toLocaleString()}원`);
    } else {
        if (tp1) lines.push(`목표 구간 1: ${tp1.toLocaleString()}원`);
        if (sl)  lines.push(`리스크 관리 구간: ${sl.toLocaleString()}원`);
    }

    // R:R 표시 (두 단계 경고: <1.0 ⛔, <1.5 ⚠️)
    const rrVal  = computeThreadsRR(item.stk_cd, entryRaw, Number(tp1Raw ?? 0), Number(slRaw ?? 0));
    const rrLine = _formatThreadsRR(rrVal);
    if (rrLine) lines.push(rrLine);

    // 기술 지표 (ai_score 제외 — 자본시장법 §6⑥)
    const techParts = [];
    if (isS1 && strength) techParts.push(_strengthLabel(strength));
    if (rsi)               techParts.push(`RSI: ${rsi}`);
    if (!isS1 && volRatio) techParts.push(`거래량: 전일比 ${volRatio}배`);
    if (techParts.length > 0) lines.push(techParts.join(' | '));

    lines.push('');
    lines.push(HASHTAG_MAP[item.strategy] || DEFAULT_HASHTAG);

    return _cap(lines.join('\n'), MAX_CHARS);
}

/**
 * STATUS_REPORT / MIDDAY_REPORT 브리핑 Threads 게시물 생성.
 * item.message (HTML) → 태그 제거 → 페르소나·금지 표현·시스템 운영 지표 제거 → 법적 고지 추가 → 450자 이하.
 *
 * 주의: item.summary 내 시스템 운영 지표(큐·에러·전략 상태)는 일절 사용 안 함.
 *
 * @param {Object} item  ai_scored_queue STATUS_REPORT / MIDDAY_REPORT 항목
 * @returns {string}     450자 이하 plain text
 */
function formatThreadsBriefing(item) {
    const stripped = _filterForbiddenLines(
        _truncateAtSystemSection(
            _stripPersonaLine(
                _stripHtml(String(item.message || ''))
            )
        )
    );

    const suffix  = '\n\n' + BRIEFING_DISCLAIMER + '\n\n' + BRIEFING_HASHTAG;
    const bodyMax = MAX_CHARS - suffix.length;
    const body    = _truncateToSentence(stripped, bodyMax);

    return body + suffix;
}

module.exports = { formatThreadsSignal, formatThreadsBriefing, computeThreadsRR };
