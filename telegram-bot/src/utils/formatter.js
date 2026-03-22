'use strict';

/**
 * formatter.js
 * ai_scored_queue 항목을 텔레그램 메시지로 변환
 */

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
        const targetPrc = Math.round(curPrc * 1.08);
        const stopPrc   = Math.round(curPrc * 0.97);
        lines.push(`진입가: <b>${curPrc.toLocaleString()}원</b>`);
        lines.push(`목표가: <b>${targetPrc.toLocaleString()}원</b> (+8%)  손절가: <b>${stopPrc.toLocaleString()}원</b> (-3%)`);
        lines.push(`리스크/리워드: 1:2.7`);
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

    // AI 분석 근거
    if (item.ai_reason) {
        lines.push('');
        lines.push(`💬 <i>${item.ai_reason}</i>`);
    }

    // 신호 시간
    const signalTime = item.signal_time
        ? new Date(item.signal_time).toLocaleTimeString('ko-KR')
        : new Date().toLocaleTimeString('ko-KR');
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

/**
 * Feature 1 – 가상 성과 요약 포맷 (/성과추적)
 */
function formatPerformanceSummary(rows) {
    if (!rows || rows.length === 0) {
        return '📊 오늘 성과 데이터 없음';
    }
    const lines = ['📊 <b>전략별 가상 성과</b>', ''];
    for (const row of rows) {
        const [strategy, total, wins, losses, avgPnl] = row;
        const winRate = total > 0 ? ((Number(wins) / Number(total)) * 100).toFixed(0) : '-';
        const pnlStr  = avgPnl != null ? `${Number(avgPnl).toFixed(2)}%` : 'N/A';
        lines.push(`${STRATEGY_EMOJI[strategy] ?? '•'} ${strategy}: ${total}건 | 승률 ${winRate}% | 평균 ${pnlStr}`);
    }
    return lines.join('\n');
}

/**
 * Feature 3 – 뉴스 현황 포맷 (/뉴스)
 */
function formatNewsStatus({ analysis, control, sentiment, sectors }) {
    const ctrlEmoji = { PAUSE: '🚨', CAUTIOUS: '⚠️', CONTINUE: '✅' };
    const ctrlLabel = { PAUSE: '매매 중단', CAUTIOUS: '신중 매매', CONTINUE: '정상 매매' };
    const sentLabel = { BULLISH: '강세 📈', BEARISH: '약세 📉', NEUTRAL: '중립 ➡️' };

    const ctrl = control || 'CONTINUE';
    const lines = [
        `${ctrlEmoji[ctrl] ?? '📰'} <b>[뉴스 & 시장 현황]</b>`,
        `매매 상태: <b>${ctrlLabel[ctrl] || ctrl}</b>`,
        `시장심리: ${sentLabel[sentiment] || sentiment || '-'}`,
    ];
    if (sectors && sectors.length > 0) {
        lines.push(`추천섹터: <b>${sectors.join(', ')}</b>`);
    }
    if (analysis && analysis.summary) {
        lines.push(`\n💬 <i>${analysis.summary}</i>`);
    }
    return lines.join('\n');
}

/**
 * Feature 3 – 섹터 분석 포맷 (/섹터)
 */
function formatSectorAnalysis({ sectors, sentiment, stats }) {
    const sentLabel = { BULLISH: '강세 📈', BEARISH: '약세 📉', NEUTRAL: '중립 ➡️' };
    const lines = [
        `🔥 <b>[섹터 분석]</b>`,
        `시장심리: ${sentLabel[sentiment] || sentiment || '-'}`,
        '',
    ];
    if (sectors && sectors.length > 0) {
        lines.push('<b>추천 섹터:</b>');
        sectors.forEach((s, i) => lines.push(`  ${i + 1}. ${s}`));
    } else {
        lines.push('추천 섹터 없음');
    }
    if (stats && stats.length > 0) {
        lines.push('');
        lines.push('<b>오늘 전략별 신호:</b>');
        for (const row of stats) {
            const [strategy, count] = row;
            lines.push(`  ${STRATEGY_EMOJI[strategy] ?? '•'} ${strategy}: ${count}건`);
        }
    }
    return lines.join('\n');
}

/**
 * Feature 3 – 종목 신호 이력 포맷 (/신호이력)
 */
function formatSignalHistory(stkCd, signals) {
    if (!signals || signals.length === 0) {
        return `📭 ${stkCd} 최근 신호 없음`;
    }
    const statusEmoji = { WIN: '✅', LOSS: '❌', SENT: '⏳', EXPIRED: '⌛', CANCELLED: '🚫', PENDING: '🕐' };
    const lines = [`📋 <b>${stkCd} 신호 이력 (최근 ${signals.length}건)</b>`, ''];
    for (const s of signals) {
        const d    = new Date(s.createdAt).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' });
        const t    = new Date(s.createdAt).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
        const pnl  = s.realizedPnl != null ? ` | P&L: ${Number(s.realizedPnl).toFixed(2)}%` : '';
        const emoji = statusEmoji[s.signalStatus] ?? '•';
        lines.push(`${emoji} ${d} ${t} [${s.strategy}] 스코어:${s.signalScore ?? '-'}${pnl}`);
    }
    return lines.join('\n');
}

/**
 * Feature 5 – 시스템 에러 현황 포맷 (/에러)
 */
function formatSystemHealth({ queueDepth, errorCount, dailySignals, tradingControl, calendarPreEvent, wsReconnect }) {
    const ctrlEmoji = { PAUSE: '🚨', CAUTIOUS: '⚠️', CONTINUE: '✅' };
    const ctrl = tradingControl || 'CONTINUE';
    const lines = [
        `🔧 <b>[시스템 상태]</b>`,
        `매매 제어: ${ctrlEmoji[ctrl] ?? '•'} ${ctrl}`,
        `이벤트 임박: ${calendarPreEvent ? '⚠️ 있음' : '없음'}`,
        `텔레그램 큐: ${queueDepth ?? 0}건`,
        `에러 큐: ${errorCount ?? 0}건`,
        `오늘 신호: ${dailySignals ?? 0}건`,
        `WS 재연결: ${wsReconnect ?? 0}회`,
    ];
    return lines.join('\n');
}

/**
 * DAILY_REPORT 확장 포맷 – 가상 P&L 포함
 */
function formatDailyReportEnhanced(item) {
    const lines = [
        `📊 <b>일일 종합 리포트 (${item.date ?? ''})</b>`,
        `총 신호: <b>${item.total_signals ?? 0}건</b>  |  평균 스코어: ${typeof item.avg_score === 'number' ? item.avg_score.toFixed(1) : '-'}점`,
    ];

    // 가상 P&L (새로 추가된 필드)
    if (item.total_wins != null || item.total_losses != null) {
        const wins   = Number(item.total_wins   ?? 0);
        const losses = Number(item.total_losses ?? 0);
        const total  = wins + losses;
        const winRate = total > 0 ? ((wins / total) * 100).toFixed(0) : '-';
        const pnl    = item.avg_pnl != null ? Number(item.avg_pnl).toFixed(2) : 'N/A';
        lines.push(`가상 성과: ✅ ${wins}건 / ❌ ${losses}건  |  승률 ${winRate}%  |  평균 ${pnl}%`);
    }

    if (item.by_strategy) {
        const byStr = typeof item.by_strategy === 'object'
            ? Object.entries(item.by_strategy).map(([s, c]) => `  ${STRATEGY_EMOJI[s] ?? '•'} ${s}: ${c}건`).join('\n')
            : String(item.by_strategy);
        lines.push(`\n전략별:\n${byStr}`);
    }
    return lines.join('\n');
}

/**
 * /이벤트 – 이번 주 경제 캘린더 포맷
 */
function formatCalendarWeek(events) {
    if (!events || events.length === 0) {
        return '📅 이번 주 예정 경제 이벤트 없음';
    }
    const impactEmoji = { HIGH: '🔴', MEDIUM: '🟡', LOW: '⚪' };
    const dayNames = ['일', '월', '화', '수', '목', '금', '토'];
    const lines = ['📅 <b>[이번 주 경제 일정]</b>', ''];

    let lastDate = null;
    for (const e of events) {
        const d = new Date(e.eventDate + 'T00:00:00');
        const dateStr = `${d.getMonth() + 1}/${d.getDate()}(${dayNames[d.getDay()]})`;
        if (dateStr !== lastDate) {
            lines.push(`<b>${dateStr}</b>`);
            lastDate = dateStr;
        }
        const impact = impactEmoji[e.expectedImpact] ?? '•';
        const time   = e.eventTime ? e.eventTime.substring(0, 5) + ' ' : '';
        lines.push(`  ${impact} ${time}${e.eventName} [${e.eventType}]`);
    }
    return lines.join('\n');
}

/**
 * /성과추적 – 오늘 신호 가상 P&L 상세 포맷
 */
function formatPerformanceDetail(signals, summaryRows) {
    const lines = ['📈 <b>[오늘의 가상 성과]</b>', ''];

    // 요약 집계
    if (summaryRows && summaryRows.length > 0) {
        let totalWins = 0, totalLosses = 0, totalSent = 0, pnlSum = 0, pnlCount = 0;
        for (const row of summaryRows) {
            const [, total, wins, losses, avgPnl] = row;
            totalWins   += Number(wins   ?? 0);
            totalLosses += Number(losses ?? 0);
            totalSent   += Number(total  ?? 0);
            if (avgPnl != null) { pnlSum += Number(avgPnl); pnlCount++; }
        }
        const winRate = (totalWins + totalLosses) > 0
            ? ((totalWins / (totalWins + totalLosses)) * 100).toFixed(0) : '-';
        const avgPnl  = pnlCount > 0 ? (pnlSum / pnlCount).toFixed(2) : 'N/A';
        lines.push(`✅ WIN ${totalWins}건 / ❌ LOSS ${totalLosses}건 / ⏳ 미결 ${Math.max(0, totalSent - totalWins - totalLosses)}건`);
        lines.push(`승률: <b>${winRate}%</b>  |  평균 P&L: <b>${avgPnl}%</b>`);
        lines.push('');
    }

    // 베스트/워스트
    if (signals && signals.length > 0) {
        const closed = signals.filter(s => s.realizedPnl != null);
        if (closed.length > 0) {
            const best  = closed.reduce((a, b) => a.realizedPnl > b.realizedPnl ? a : b);
            const worst = closed.reduce((a, b) => a.realizedPnl < b.realizedPnl ? a : b);
            lines.push(`최고: ${best.stkNm ?? best.stkCd} <b>+${Number(best.realizedPnl).toFixed(2)}%</b>`);
            if (worst.stkCd !== best.stkCd) {
                lines.push(`최저: ${worst.stkNm ?? worst.stkCd} <b>${Number(worst.realizedPnl).toFixed(2)}%</b>`);
            }
        }
    }
    return lines.join('\n');
}

/**
 * /설정 – 개인 알림 설정 포맷
 */
function formatUserSettings(filter, watchlist) {
    const lines = ['⚙️ <b>[내 알림 설정]</b>', ''];
    if (filter && filter.length > 0) {
        lines.push(`전략 필터: ${filter.join(', ')}`);
    } else {
        lines.push('전략 필터: 없음 (모든 전략 수신)');
    }
    if (watchlist && watchlist.length > 0) {
        lines.push(`관심 종목: ${watchlist.join(', ')}`);
    } else {
        lines.push('관심 종목: 없음 (모든 종목 수신)');
    }
    return lines.join('\n');
}

module.exports = {
    formatSignal, formatForceClose, formatDailySummary,
    formatPerformanceSummary, formatNewsStatus, formatSectorAnalysis,
    formatSignalHistory, formatSystemHealth,
    formatDailyReportEnhanced, formatCalendarWeek, formatPerformanceDetail, formatUserSettings,
};
