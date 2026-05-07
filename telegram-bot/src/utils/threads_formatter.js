'use strict';

const { normalizeForDisplay } = require('./price');

const MAX_CHARS = 450;

const STRATEGY_DESC_SHORT = {
    S1_GAP_OPEN:          '갭 오픈 패턴',
    S2_VI_PULLBACK:       'VI 발동 눌림목',
    S3_INST_FRGN:         '기관+외국인 동반 매수',
    S4_BIG_CANDLE:        '장대양봉 거래량 급증',
    S5_PROG_FRGN:         '프로그램+외국인 동반',
    S6_THEME_LAGGARD:     '테마 후발 소외주',
    S7_ICHIMOKU_BREAKOUT: '일목균형 구름대 돌파',
    S8_GOLDEN_CROSS:      '골든크로스 (MA5×MA20)',
    S9_PULLBACK_SWING:    '5MA 눌림목 반등',
    S10_NEW_HIGH:         '52주 신고가 돌파',
    S11_FRGN_CONT:        '외국인 연속 순매수',
    S12_CLOSING:          '장 마감 종가 강도',
    S13_BOX_BREAKOUT:     '박스권 상단 돌파',
    S14_OVERSOLD_BOUNCE:  'RSI 과매도 반등',
    S15_MOMENTUM_ALIGN:   '다중 모멘텀 정렬',
};

const HASHTAG_MAP = {
    S1_GAP_OPEN:      '#갭오픈 #국내주식 #자동기록',
    S2_VI_PULLBACK:   '#VI발동 #국내주식 #자동기록',
    S4_BIG_CANDLE:    '#장대양봉 #국내주식 #자동기록',
    S6_THEME_LAGGARD: '#테마주 #국내주식 #자동기록',
    S8_GOLDEN_CROSS:  '#골든크로스 #국내주식 #자동기록',
    S10_NEW_HIGH:     '#신고가 #국내주식 #자동기록',
};
const DEFAULT_HASHTAG = '#기술적분석 #국내주식 #자동기록';

const DISCLAIMER =
    '본 내용은 기술적 지표 조건 충족 사실을 자동 기록한 것입니다.' +
    ' 투자권유가 아닙니다. 투자 결정과 손익은 본인 책임입니다.';

const BRIEFING_DISCLAIMER =
    '본 내용은 AI가 공개 데이터를 기반으로 작성한 자동 생성 시황 분석입니다.' +
    ' 투자권유가 아닙니다. 투자 결정과 손익은 본인 책임입니다.';
const BRIEFING_HASHTAG = '#시황브리핑 #알고리즘트레이딩 #자동기록';

function _pct(price, base) {
    if (!price || !base || base <= 0) return '';
    const p = (((price - base) / base) * 100).toFixed(1);
    return `(${p.startsWith('-') ? '' : '+'}${p}%)`;
}

function _cap(text, max) {
    if (text.length <= max) return text;
    return text.slice(0, max - 1) + '…';
}

function _signalTime(item) {
    const src = item.signal_time ? new Date(item.signal_time) : new Date();
    return src.toLocaleTimeString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour: '2-digit',
        minute: '2-digit',
    });
}

/**
 * ENTER / RULE_ONLY_SIGNAL 전용 Threads 게시물 생성.
 * Telegram formatSignal()과 동일 item을 입력받아 법적 준수 plain text로 변환.
 *
 * @param {Object} item  ai_scored_queue 항목
 * @returns {string}     450자 이하 plain text
 */
function formatThreadsSignal(item) {
    const isS1 = item.strategy === 'S1_GAP_OPEN';
    const stratDesc = STRATEGY_DESC_SHORT[item.strategy] || item.strategy;
    const stockLabel = item.stk_nm
        ? `${item.stk_nm} (${item.stk_cd})`
        : (item.stk_cd || '-');

    const curPrc = normalizeForDisplay(item.cur_prc ?? item.entry_price ?? 0);

    // Claude TP/SL 우선, 없으면 규칙 기반 폴백
    const tp1 = item.claude_tp1
        ? normalizeForDisplay(item.claude_tp1)
        : (item.tp1_price ? normalizeForDisplay(item.tp1_price) : null);
    const sl = item.claude_sl
        ? normalizeForDisplay(item.claude_sl)
        : (item.sl_price ? normalizeForDisplay(item.sl_price) : null);

    const rsi       = item.rsi       != null ? Number(item.rsi).toFixed(1)       : null;
    const volRatio  = item.vol_ratio != null ? Number(item.vol_ratio).toFixed(1) : null;
    const aiScore   = item.ai_score  != null ? Number(item.ai_score).toFixed(1)  : null;
    const gapPct    = item.gap_pct   != null ? Number(item.gap_pct).toFixed(1)   : null;
    const strength  = item.cntr_strength != null ? item.cntr_strength            : null;

    const header = isS1 ? '[갭 오픈 패턴 감지] 자동 발행' : '[기술적 신호 탐지] 자동 발행';

    const lines = [
        header,
        `종목: ${stockLabel}`,
        isS1
            ? `패턴: 갭 상승 조건 충족${gapPct ? ` (+${gapPct}%)` : ''}`
            : `패턴: ${stratDesc} 조건 충족`,
        `시간: ${_signalTime(item)} KST`,
        '',
    ];

    if (curPrc > 0) lines.push(`현재가: ${curPrc.toLocaleString()}원`);

    if (isS1) {
        if (tp1) lines.push(`상단 저항 구간: ${tp1.toLocaleString()}원`);
        if (sl)  lines.push(`하단 지지 구간: ${sl.toLocaleString()}원`);
    } else {
        if (tp1) lines.push(`1차 저항 구간: ${tp1.toLocaleString()}원 ${_pct(tp1, curPrc)}`.trimEnd());
        if (sl)  lines.push(`하단 지지 구간: ${sl.toLocaleString()}원 ${_pct(sl, curPrc)}`.trimEnd());
    }

    const techParts = [];
    if (isS1 && strength) techParts.push(`체결강도: ${strength}`);
    if (rsi)              techParts.push(`RSI: ${rsi}`);
    if (!isS1 && volRatio) techParts.push(`거래량: 전일比 ${volRatio}배`);
    if (aiScore)          techParts.push(`AI점수: ${aiScore}점`);
    if (techParts.length > 0) lines.push(techParts.join(' | '));

    lines.push('');
    lines.push(DISCLAIMER);
    lines.push('');
    lines.push(HASHTAG_MAP[item.strategy] || DEFAULT_HASHTAG);

    return _cap(lines.join('\n'), MAX_CHARS);
}

// ── HTML 파싱 / 페르소나 제거 헬퍼 (브리핑 전용) ─────────────────────────

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

/**
 * STATUS_REPORT / MIDDAY_REPORT 브리핑 Threads 게시물 생성.
 * item.message (HTML) → 태그 제거 → 페르소나 라인 제거 → 법적 고지 추가 → 450자 이하.
 *
 * 주의: item.summary 내 시스템 운영 지표(큐 깊이·에러 큐·전략 상태 등)는 일절 사용 안 함.
 *
 * @param {Object} item  ai_scored_queue STATUS_REPORT / MIDDAY_REPORT 항목
 * @returns {string}     450자 이하 plain text
 */
function formatThreadsBriefing(item) {
    const stripped = _stripPersonaLine(_stripHtml(String(item.message || '')));

    const suffix  = '\n\n' + BRIEFING_DISCLAIMER + '\n\n' + BRIEFING_HASHTAG;
    const bodyMax = MAX_CHARS - suffix.length;
    const body    = stripped.length > bodyMax
        ? stripped.slice(0, bodyMax - 1) + '…'
        : stripped;

    return body + suffix;
}

module.exports = { formatThreadsSignal, formatThreadsBriefing };
