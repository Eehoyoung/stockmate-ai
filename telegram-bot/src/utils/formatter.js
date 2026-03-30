'use strict';

/**
 * formatter.js
 * ai_scored_queue 항목을 텔레그램 메시지로 변환
 */

const STRATEGY_EMOJI = {
    S1_GAP_OPEN:        '🚀',
    S2_VI_PULLBACK:     '🎯',
    S3_INST_FRGN:       '🏦',
    S4_BIG_CANDLE:      '📊',
    S5_PROG_FRGN:       '💻',
    S6_THEME_LAGGARD:   '🔥',
    S7_AUCTION:         '⚡',
    S8_GOLDEN_CROSS:    '📈',
    S9_PULLBACK_SWING:  '🔽',
    S10_NEW_HIGH:       '🏔',
    S11_FRGN_CONT:      '🌏',
    S12_CLOSING:        '🌙',
    S13_BOX_BREAKOUT:   '📦',
    S14_OVERSOLD_BOUNCE:'🔄',
    S15_MOMENTUM_ALIGN: '🔥',
};

const STRATEGY_DESC = {
    S1_GAP_OPEN:        '갭 상승 개장 (전일 대비 갭 3~15%)',
    S2_VI_PULLBACK:     'VI 발동 후 눌림목 반등',
    S3_INST_FRGN:       '기관+외국인 동시 순매수',
    S4_BIG_CANDLE:      '장대양봉 + 거래량 급증',
    S5_PROG_FRGN:       '프로그램+외국인 동반 매수',
    S6_THEME_LAGGARD:   '테마주 후발 소외주 갭 상승',
    S7_AUCTION:         '동시호가 매수세 우위 + 갭',
    S8_GOLDEN_CROSS:    'MA5×MA20 골든크로스 + 거래량 확인',
    S9_PULLBACK_SWING:  '정배열 내 5MA 눌림목 반등',
    S10_NEW_HIGH:       '52주 신고가 돌파 + 거래량 급증',
    S11_FRGN_CONT:      '외국인 연속 3일 이상 순매수',
    S12_CLOSING:        '장 마감 30분 종가강도 매집',
    S13_BOX_BREAKOUT:   '박스권 상단 돌파 + 거래량 폭발',
    S14_OVERSOLD_BOUNCE:'RSI 과매도 구간 반등 신호 (RSI < 35)',
    S15_MOMENTUM_ALIGN: '다중 모멘텀 정렬 상승 (RSI+MA+거래량)',
};

/**
 * HTML 특수문자 이스케이프 (Telegram HTML parse_mode 안전 출력용)
 * @param {*} str
 * @returns {string}
 */
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

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
// 수수료+세금+슬리피지 합산 (왕복)
const SLIP_FEE = { KOSPI: 0.0035, KOSDAQ: 0.0045 };

function _slipFee(stkCd) {
    return String(stkCd ?? '').startsWith('0') ? SLIP_FEE.KOSPI : SLIP_FEE.KOSDAQ;
}

/**
 * 슬리피지 반영 실질 R:R 문자열 반환
 * @returns {string|null}
 */
function _effectiveRR(stkCd, entry, tp1, sl) {
    if (!entry || !tp1 || !sl || sl >= entry) return null;
    const slip = _slipFee(stkCd);
    const effTarget = (tp1 - entry) / entry - slip;
    const effRisk   = (entry - sl)  / entry + slip;
    if (effRisk <= 0) return null;
    const rr = (effTarget / effRisk).toFixed(2);
    const warn = Number(rr) < 1.0 ? ' ⚠️' : '';
    return `실질R:R(슬리피지반영): <b>${rr}</b>${warn}`;
}

/**
 * ai_score + confidence 기반 포지션 크기 제안
 */
function _positionSize(aiScore, confidence) {
    const score = Number(aiScore ?? 0);
    const conf  = confidence ?? 'LOW';
    if (score >= 85 && conf === 'HIGH')   return '대 (full)';
    if (score >= 75 && conf !== 'LOW')    return '중';
    if (score >= 65)                      return '소 (half)';
    return null;
}

function formatSignal(item) {
    const emoji    = STRATEGY_EMOJI[item.strategy] ?? '📌';
    const action   = ACTION_LABEL[item.action]     ?? item.action;
    const conf     = CONFIDENCE_LABEL[item.confidence] ?? item.confidence;
    const aiScore  = (item.ai_score ?? 0).toFixed(1);
    const ruleScore= (item.rule_score ?? 0).toFixed(1);
    const stratDesc = STRATEGY_DESC[item.strategy];

    const lines = [
        `${emoji} <b>[${item.strategy}] ${item.stk_cd} ${item.stk_nm ?? ''}</b>`,
    ];
    if (stratDesc) lines.push(`<i>${stratDesc}</i>`);
    lines.push(
        `${action}  |  신뢰도: ${conf}`,
        `AI 스코어: <b>${aiScore}</b>점  (규칙: ${ruleScore}점)`,
    );

    // 진입가 표시
    const curPrc = Number(item.cur_prc ?? item.entry_price ?? 0);
    if (curPrc > 0) {
        lines.push(`진입가: <b>${curPrc.toLocaleString()}원</b>  (${item.entry_type ?? '-'})`);
    }

    // ── Claude 확정 TP/SL (human_confirmed=true 일 때 우선 표시) ──
    const claudeTp1 = item.claude_tp1 ? Number(item.claude_tp1) : null;
    const claudeTp2 = item.claude_tp2 ? Number(item.claude_tp2) : null;
    const claudeSl  = item.claude_sl  ? Number(item.claude_sl)  : null;

    if (item.human_confirmed && (claudeTp1 || claudeTp2 || claudeSl)) {
        lines.push('🤖 <b>Claude 최종 목표가</b>');
        if (claudeTp1 && curPrc > 0) {
            const pct = (((claudeTp1 - curPrc) / curPrc) * 100).toFixed(1);
            lines.push(`  TP1: <b>${claudeTp1.toLocaleString()}원</b>  (+${pct}%)`);
        }
        if (claudeTp2 && curPrc > 0) {
            const pct = (((claudeTp2 - curPrc) / curPrc) * 100).toFixed(1);
            lines.push(`  TP2: <b>${claudeTp2.toLocaleString()}원</b>  (+${pct}%)`);
        }
        if (claudeSl && curPrc > 0) {
            const pct = (((claudeSl - curPrc) / curPrc) * 100).toFixed(1);
            lines.push(`  SL:  <b>${claudeSl.toLocaleString()}원</b>  (${pct}%)`);
        }
        // R/R
        if (claudeTp1 && claudeSl && curPrc > 0 && claudeSl < curPrc) {
            const rr = ((claudeTp1 - curPrc) / (curPrc - claudeSl)).toFixed(1);
            lines.push(`  R/R: 1:${rr}`);
            const effRR = _effectiveRR(item.stk_cd, curPrc, claudeTp1, claudeSl);
            if (effRR) lines.push(`  ${effRR}`);
        }
    }

    // ── 규칙 기반 TP/SL ──
    const tp1 = item.tp1_price ? Number(item.tp1_price) : null;
    const tp2 = item.tp2_price ? Number(item.tp2_price) : null;
    const sl  = item.sl_price  ? Number(item.sl_price)  : null;

    if (!item.human_confirmed) {
        // 미확정: 규칙 기반을 주 표시
        if (tp1 || tp2 || sl) {
            lines.push('📐 <b>목표가 (규칙 기반)</b>');
            if (tp1 && curPrc > 0) {
                const pct = (((tp1 - curPrc) / curPrc) * 100).toFixed(1);
                lines.push(`  TP1: <b>${tp1.toLocaleString()}원</b>  (+${pct}%)`);
            }
            if (tp2 && curPrc > 0) {
                const pct = (((tp2 - curPrc) / curPrc) * 100).toFixed(1);
                lines.push(`  TP2: <b>${tp2.toLocaleString()}원</b>  (+${pct}%)`);
            }
            if (sl && curPrc > 0) {
                const pct = (((sl - curPrc) / curPrc) * 100).toFixed(1);
                lines.push(`  SL:  <b>${sl.toLocaleString()}원</b>  (${pct}%)`);
            }
            if (tp1 && sl && curPrc > 0 && sl < curPrc) {
                const rr = ((tp1 - curPrc) / (curPrc - sl)).toFixed(1);
                lines.push(`  R/R: 1:${rr}`);
                const effRR = _effectiveRR(item.stk_cd, curPrc, tp1, sl);
                if (effRR) lines.push(`  ${effRR}`);
            }
        } else {
            // 절대가 없으면 % 기반 폴백
            const targetPct = item.adjusted_target_pct ?? item.target_pct;
            const stopPct   = item.adjusted_stop_pct   ?? item.stop_pct;
            if (targetPct != null || stopPct != null) {
                lines.push(`목표: <b>+${targetPct ?? '-'}%</b>  손절: <b>${stopPct ?? '-'}%</b>`);
            }
        }
    } else if (tp1 || tp2 || sl) {
        // Claude 확정 후: 규칙 기반은 참고용
        const ruleParts = [];
        if (tp1) ruleParts.push(`TP1: ${tp1.toLocaleString()}원`);
        if (tp2) ruleParts.push(`TP2: ${tp2.toLocaleString()}원`);
        if (sl)  ruleParts.push(`SL: ${sl.toLocaleString()}원`);
        if (ruleParts.length > 0) {
            lines.push(`📐 규칙 기반(참고): ${ruleParts.join(' / ')}`);
        }
    }

    // 전술별 지표
    const indLines = [];
    if (item.gap_pct      != null) indLines.push(`갭: ${item.gap_pct}%`);
    if (item.cntr_strength!= null) indLines.push(`체결강도: ${item.cntr_strength}%`);
    if (item.bid_ratio    != null) indLines.push(`호가비율: ${item.bid_ratio}`);
    if (item.vol_ratio    != null) indLines.push(`거래량: ${item.vol_ratio}x`);
    if (item.pullback_pct != null) indLines.push(`눌림: ${item.pullback_pct}%`);
    if (indLines.length > 0) lines.push(indLines.join('  |  '));

    // 기술 지표 (RSI, ATR, 조건수, 보유목표일)
    const techLines = [];
    if (item.rsi      != null) techLines.push(`RSI: ${Number(item.rsi).toFixed(1)}`);
    if (item.atr_pct  != null) techLines.push(`ATR: ${Number(item.atr_pct).toFixed(2)}%`);
    if (item.cond_count != null && Number(item.cond_count) > 0) techLines.push(`조건충족: ${item.cond_count}개`);
    if (item.holding_days != null) techLines.push(`보유목표: ${item.holding_days}일`);
    if (techLines.length > 0) lines.push(techLines.join('  |  '));

    if (item.theme_name   != null) lines.push(`테마: ${item.theme_name}`);
    if (item.net_buy_amt  != null) {
        const amt = (Number(item.net_buy_amt) / 1e8).toFixed(1);
        lines.push(`순매수: ${amt}억`);
    }

    // 포지션 크기 제안 (ENTER 신호만)
    if (item.action === 'ENTER') {
        const pos = _positionSize(item.ai_score, item.confidence);
        if (pos) lines.push(`💰 권장 비중: <b>${pos}</b>`);
    }

    // AI 분석 근거
    if (item.ai_reason) {
        lines.push('');
        lines.push(`💬 <i>${escapeHtml(item.ai_reason)}</i>`);
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
    escapeHtml,
    formatSignal, formatForceClose, formatDailySummary,
    formatPerformanceSummary, formatNewsStatus, formatSectorAnalysis,
    formatSignalHistory, formatSystemHealth,
    formatDailyReportEnhanced, formatCalendarWeek, formatPerformanceDetail, formatUserSettings,
};
