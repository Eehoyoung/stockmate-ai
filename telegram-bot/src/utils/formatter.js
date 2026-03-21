'use strict';

/**
 * formatter.js
 * ai_scored_queue 항목을 텔레그램 메시지로 변환
 */

/**
 * Telegram HTML 모드에서 문제가 되는 특수문자를 이스케이프
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

const STRATEGY_EMOJI = {
    S1_GAP_OPEN:       '🚀',
    S2_VI_PULLBACK:    '🎯',
    S3_INST_FRGN:      '🏦',
    S4_BIG_CANDLE:     '📊',
    S5_PROG_FRGN:      '💻',
    S6_THEME_LAGGARD:  '🔥',
    S7_AUCTION:        '⚡',
};

const ACTION_LABEL = {
    ENTER:  '✅ 진입',
    HOLD:   '⏸️ 관망',
    CANCEL: '❌ 취소',
};

const CONFIDENCE_LABEL = {
    HIGH:   '🔴 높음',
    MEDIUM: '🟡 보통',
    LOW:    '⚪ 낮음',
};

/**
 * 거래 신호 → 텔레그램 HTML 메시지
 * @param {Object} item  ai_scored_queue 항목
 * @returns {string}
 */
function formatSignal(item) {
    const emoji    = STRATEGY_EMOJI[item.strategy] ?? '📌';
    const action   = ACTION_LABEL[item.action]     ?? item.action;
    const conf     = CONFIDENCE_LABEL[item.confidence] ?? item.confidence;
    const aiScore  = (item.ai_score ?? 0).toFixed(1);
    const ruleScore= (item.rule_score ?? 0).toFixed(1);

    const lines = [
        `${emoji} <b>[${item.strategy}] ${item.stk_cd} ${item.stk_nm ?? ''}</b>`,
        `${action}  |  신뢰도: ${conf}`,
        `AI 스코어: <b>${aiScore}</b>점  (규칙: ${ruleScore}점)`,
        `진입방식: ${item.entry_type ?? '-'}`,
    ];

    const targetPct = item.adjusted_target_pct ?? item.target_pct;
    const stopPct   = item.adjusted_stop_pct   ?? item.stop_pct;
    if (targetPct != null || stopPct != null) {
        lines.push(`목표: <b>+${targetPct ?? '-'}%</b>  손절: <b>${stopPct ?? '-'}%</b>`);
    }

    // 진입가 / 목표가 / 손절가 / 리스크리워드
    const curPrc = Number(item.cur_prc ?? item.entry_price ?? 0);
    if (curPrc > 0) {
        const tgtPct = Number(targetPct ?? item.target_pct ?? 8);
        const stpPct = Number(stopPct  ?? item.stop_pct   ?? -3);
        const targetPrc = Math.round(curPrc * (1 + tgtPct / 100));
        const stopPrc   = Math.round(curPrc * (1 + stpPct / 100));
        const rr = stpPct !== 0 ? (tgtPct / Math.abs(stpPct)).toFixed(1) : '-';
        lines.push(`진입가: <b>${curPrc.toLocaleString()}원</b>`);
        lines.push(`목표가: <b>${targetPrc.toLocaleString()}원</b> (+${tgtPct}%)  손절가: <b>${stopPrc.toLocaleString()}원</b> (${stpPct}%)`);
        lines.push(`리스크/리워드: 1:${rr}`);
    }

    // 전술별 지표
    if (item.gap_pct      != null) lines.push(`갭/상승: ${item.gap_pct}%`);
    if (item.cntr_strength!= null) lines.push(`체결강도: ${item.cntr_strength}%`);
    if (item.bid_ratio    != null) lines.push(`호가비율(매수/매도): ${item.bid_ratio}`);
    if (item.vol_ratio    != null) lines.push(`거래량비율: ${item.vol_ratio}x`);
    if (item.pullback_pct != null) lines.push(`눌림: ${item.pullback_pct}%`);
    if (item.theme_name   != null) lines.push(`테마: ${item.theme_name}`);
    if (item.net_buy_amt  != null) {
        const amt = (Number(item.net_buy_amt) / 1e8).toFixed(1);
        lines.push(`순매수: ${amt}억`);
    }

    // AI 분석 근거 (HTML 이스케이프 처리)
    if (item.ai_reason) {
        lines.push('');
        lines.push(`💬 <i>${escapeHtml(item.ai_reason)}</i>`);
    }

    // 신호 시간
    let signalTime;
    try {
        signalTime = item.signal_time
            ? new Date(item.signal_time).toLocaleTimeString('ko-KR')
            : new Date().toLocaleTimeString('ko-KR');
    } catch (_) {
        signalTime = new Date().toLocaleTimeString('ko-KR');
    }
    lines.push(`\n🕐 ${signalTime}`);

    return lines.join('\n');
}

/**
 * 강제 청산 알림 포맷
 */
function formatForceClose(item) {
    return [
        `⚠️ <b>[강제청산] ${item.stk_cd} ${item.stk_nm ?? ''}</b>`,
        `전술: ${item.strategy}`,
        `장마감 30분 전 – 전량 시장가 청산`,
        `\n🕐 ${new Date().toLocaleTimeString('ko-KR')}`,
    ].join('\n');
}

/**
 * 당일 성과 요약 포맷
 */
function formatDailySummary(stats) {
    if (!stats || stats.length === 0) {
        return '📊 오늘 거래 신호 없음';
    }
    const lines = ['📊 <b>당일 전략별 성과</b>', ''];
    for (const row of stats) {
        const [strategy, count, avgPnl] = row;
        const pnlStr = avgPnl != null ? `${Number(avgPnl).toFixed(2)}%` : 'N/A';
        lines.push(`${STRATEGY_EMOJI[strategy] ?? '•'} ${strategy}: ${count}건 | 평균 ${pnlStr}`);
    }
    return lines.join('\n');
}

module.exports = { formatSignal, formatForceClose, formatDailySummary, escapeHtml };
