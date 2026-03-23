'use strict';

/**
 * handlers/commands.js
 * 텔레그램 봇 명령어 처리
 *
 * 명령어 목록:
 *   /ping          – 봇 동작 확인
 *   /상태           – 시스템 헬스체크
 *   /신호           – 당일 신호 목록
 *   /성과           – 당일 전략별 성과
 *   /후보 [market]  – 후보 종목 조회
 *   /시세 {종목코드}  – 실시간 시세
 *   /전술 {S1~S7}   – 전술 수동 실행
 *   /토큰갱신        – 키움 토큰 수동 갱신
 *   /ws시작          – WebSocket 구독 시작
 *   /ws종료          – WebSocket 구독 종료
 *   /help           – 명령어 목록
 */

const { getTickData, getClient } = require('../services/redis');
const kiwoom          = require('../services/kiwoom');
const {
    formatDailySummary,
    formatPerformanceSummary,
    formatNewsStatus,
    formatSectorAnalysis,
    formatSignalHistory,
    formatSystemHealth,
    formatCalendarWeek,
    formatPerformanceDetail,
    formatUserSettings,
} = require('../utils/formatter');

/** 허용된 Chat ID 확인 */
function isAllowed(ctx) {
    const allowed = (process.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
    return allowed.length === 0 || allowed.includes(String(ctx.chat.id));
}

function guard(handler) {
    return async (ctx) => {
        if (!isAllowed(ctx)) {
            return ctx.reply('⛔ 권한 없음');
        }
        try {
            await handler(ctx);
        } catch (e) {
            console.error('[Command] 오류:', e.message);
            await ctx.reply(`❌ 오류: ${e.message}`);
        }
    };
}

/** /ping */
const ping = guard(async (ctx) => {
    await ctx.reply('🏓 pong! StockMate AI is running');
});

/**
 * Claude API 일별 사용량 조회 (Redis)
 * @returns {{ calls: number, tokens: number }}
 */
async function getClaudeUsage() {
    const redis = getClient();
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    try {
        const callsRaw  = await redis.get(`claude:daily_calls:${today}`);
        const tokensRaw = await redis.get(`claude:daily_tokens:${today}`);
        return {
            calls:  Number(callsRaw  ?? 0),
            tokens: Number(tokensRaw ?? 0),
        };
    } catch (e) {
        console.warn('[Commands] Claude 사용량 조회 실패:', e.message);
        return { calls: 0, tokens: 0 };
    }
}

/** /status */
const status = guard(async (ctx) => {
    const h = await kiwoom.health();
    const usage = await getClaudeUsage();
    const maxCalls = Number(process.env.MAX_CLAUDE_CALLS_PER_DAY ?? 100);

    // ws_solver.md 4.4: ws:heartbeat 로 Python WS 상태 진단
    const redis = getClient();
    let wsStatus = '❌ Offline (TTL expired)';
    try {
        const hb = await redis.hgetall('ws:heartbeat');
        if (hb && hb.updated_at) {
            const secAgo = Math.round(Date.now() / 1000 - parseFloat(hb.updated_at));
            wsStatus = `✅ Online (${secAgo}s ago)`;
        }
    } catch (_) {}

    let javaWsStatus = '❓ Unknown';
    try {
        const wsConn = await redis.get('ws:connected');
        javaWsStatus = wsConn === '1' ? '✅ Connected' : '❌ Disconnected';
    } catch (_) {}

    await ctx.reply(
        `🟢 <b>System Status</b>\n` +
        `Java API: ${h.status} | ${h.service}\n\n` +
        `📡 <b>WebSocket</b>\n` +
        `Python WS: ${wsStatus}\n` +
        `Java WS:   ${javaWsStatus}\n\n` +
        `📊 <b>Claude AI Today</b>\n` +
        `Calls: <b>${usage.calls}</b> / ${maxCalls}\n` +
        `Tokens: <b>${usage.tokens.toLocaleString()}</b>`,
        { parse_mode: 'HTML' }
    );
});

/** /신호 */
const signals = guard(async (ctx) => {
    const list = await kiwoom.getTodaySignals();
    if (!list || list.length === 0) {
        return ctx.reply('📭 오늘 발행된 신호 없음');
    }
    const lines = list.slice(0, 10).map((s, i) =>
        `${i + 1}. <b>${s.stkCd}</b> [${s.strategy}] ${s.signalStatus} | 스코어: ${s.signalScore ?? '-'}`
    );
    await ctx.reply(
        `📋 <b>당일 신호 (최근 10건)</b>\n\n${lines.join('\n')}`,
        { parse_mode: 'HTML' }
    );
});

/** /성과 */
const performance = guard(async (ctx) => {
    const stats = await kiwoom.getTodayStats();
    await ctx.reply(formatDailySummary(stats), { parse_mode: 'HTML' });
});

/** /후보 [market] */
const candidates = guard(async (ctx) => {
    const args   = ctx.message.text.split(' ');
    const market = args[1] ?? '000';
    const result = await kiwoom.getCandidates(market);
    await ctx.reply(
        `📋 <b>후보 종목 [${result.market}]</b>\n총 ${result.count}개\n${(result.codes ?? []).slice(0, 20).join(', ')}…`,
        { parse_mode: 'HTML' }
    );
});

/** /quote {종목코드} */
const quote = guard(async (ctx) => {
    const args   = ctx.message.text.split(' ');
    const stkCd  = args[1]?.trim();
    if (!stkCd) return ctx.reply('Usage: /quote 005930');
    if (!/^\d{6}$/.test(stkCd)) return ctx.reply('❌ Stock code must be 6 digits. e.g. /quote 005930');

    const tick = await getTickData(stkCd);
    if (!tick || Object.keys(tick).length === 0) {
        return ctx.reply(`❓ ${stkCd} – No realtime data (WebSocket not subscribed or TTL expired)`);
    }
    const fluRt  = tick.flu_rt ?? '-';
    const fluSign = Number(fluRt) > 0 ? '+' : '';
    await ctx.reply(
        `📈 <b>${stkCd} 실시간 시세</b>\n` +
        `현재가: <b>${Number(tick.cur_prc ?? 0).toLocaleString()}원</b>\n` +
        `등락률: <b>${fluSign}${fluRt}%</b>\n` +
        `체결강도: ${tick.cntr_str ?? '-'}\n` +
        `누적거래량: ${Number(tick.acc_trde_qty ?? 0).toLocaleString()}\n` +
        `체결시간: ${tick.cntr_tm ?? '-'}`,
        { parse_mode: 'HTML' }
    );
});

/** /strategy {s1~s7} */
const runStrategy = guard(async (ctx) => {
    const args     = ctx.message.text.split(' ');
    const strategy = args[1];
    if (!strategy) return ctx.reply('Usage: /strategy s1');

    await ctx.reply(`⚙️ Running ${strategy.toUpperCase()} manually...`);
    const result = await kiwoom.runStrategy(strategy);
    await ctx.reply(
        `✅ <b>${result.strategy}</b> complete\nPublished signals: ${result.published}`,
        { parse_mode: 'HTML' }
    );
});

/** /토큰갱신 */
const refreshToken = guard(async (ctx) => {
    const result = await kiwoom.refreshToken();
    await ctx.reply(`🔑 ${result.msg}`);
});

/** /ws시작 */
const wsStart = guard(async (ctx) => {
    const result = await kiwoom.startWs();
    await ctx.reply(`📡 ${result.msg}`);
});

/** /ws종료 */
const wsStop = guard(async (ctx) => {
    const result = await kiwoom.stopWs();
    await ctx.reply(`🔌 ${result.msg}`);
});

/** /report – 오늘 신호 요약 (daily_summary:{today}) */
const report = guard(async (ctx) => {
    const redis = getClient();
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const key   = `daily_summary:${today}`;
    const data  = await redis.hgetall(key);

    if (!data || Object.keys(data).length === 0) {
        return ctx.reply('📊 오늘 데이터 없음');
    }

    let byStrategy = '';
    try {
        const parsed = JSON.parse(data.by_strategy ?? '{}');
        byStrategy = Object.entries(parsed)
            .map(([s, c]) => `  ${s}: ${c}건`)
            .join('\n');
    } catch (_) {
        byStrategy = data.by_strategy ?? '-';
    }

    await ctx.reply(
        `📊 <b>오늘의 신호 리포트 (${today})</b>\n\n` +
        `총 신호: <b>${data.total_signals ?? '-'}건</b>\n` +
        `평균 스코어: <b>${data.avg_score ?? '-'}점</b>\n` +
        `전략별:\n${byStrategy}`,
        { parse_mode: 'HTML' }
    );
});

/** /filter – 전략 수신 필터 설정 */
const filter = guard(async (ctx) => {
    const redis  = getClient();
    const chatId = String(ctx.chat.id);
    const args   = ctx.message.text.split(' ').slice(1);
    const filterKey = `user_filter:${chatId}`;

    if (args.length === 0) {
        // 현재 필터 조회
        const current = await redis.get(filterKey);
        const parsed  = current ? JSON.parse(current) : null;
        if (!parsed || parsed.length === 0) {
            return ctx.reply('🔍 현재 필터 없음 (모든 전략 수신 중)');
        }
        return ctx.reply(`🔍 현재 필터: ${parsed.join(', ')}`);
    }

    if (args[0].toLowerCase() === 'all') {
        await redis.del(filterKey);
        return ctx.reply('✅ Filter cleared – receiving all strategies');
    }

    // /filter s1 s4 → ["S1_GAP_OPEN", "S4_BIG_CANDLE"]
    const strategyMap = {
        s1: 'S1_GAP_OPEN', s2: 'S2_VI_PULLBACK', s3: 'S3_INST_FRGN',
        s4: 'S4_BIG_CANDLE', s5: 'S5_PROG_FRGN', s6: 'S6_THEME_LAGGARD', s7: 'S7_AUCTION',
        s10: 'S10_NEW_HIGH', s12: 'S12_CLOSING',
    };
    const selected = args
        .map((a) => strategyMap[a.toLowerCase()])
        .filter(Boolean);

    if (selected.length === 0) {
        return ctx.reply('❌ No valid strategy. e.g. /filter s1 s4');
    }

    await redis.set(filterKey, JSON.stringify(selected));
    return ctx.reply(`✅ Filter set: ${selected.join(', ')}`);
});

/** /pause – 매매 제어 PAUSE 전 사용자 컨펌 요청 */
const pauseTrading = guard(async (ctx) => {
    await ctx.reply(
        '⚠️ <b>[Pause Trading – Confirm]</b>\n\nAll signal publishing will be suspended.',
        {
            parse_mode: 'HTML',
            reply_markup: {
                inline_keyboard: [[
                    { text: '✅ Confirm (Pause)', callback_data: 'confirm_pause' },
                    { text: '❌ Cancel',           callback_data: 'cancel_pause'  },
                ]],
            },
        }
    );
});

/** /resume – 매매 제어를 CONTINUE 로 수동 복귀 */
const resumeTrading = guard(async (ctx) => {
    const result = await kiwoom.setTradingControl('CONTINUE');
    await ctx.reply(`✅ Trading resumed\nPrev: ${result.prev} → <b>CONTINUE</b>`, { parse_mode: 'HTML' });
});

/** /이벤트 – 이번 주 경제 캘린더 */
const calendarEvents = guard(async (ctx) => {
    const events = await kiwoom.getCalendarWeek();
    await ctx.reply(formatCalendarWeek(events), { parse_mode: 'HTML' });
});

/** /성과추적 – 오늘의 가상 P&L 상세 */
const performanceDetail = guard(async (ctx) => {
    const [signals, summaryRows] = await Promise.all([
        kiwoom.getSignalPerformance(),
        kiwoom.getPerformanceSummary(),
    ]);
    await ctx.reply(formatPerformanceDetail(signals, summaryRows), { parse_mode: 'HTML' });
});

/** /watchAdd {종목코드} – 특정 종목 알림만 받기 */
const watchlistAdd = guard(async (ctx) => {
    const args   = ctx.message.text.split(' ');
    const stkCd  = args[1];
    if (!stkCd) return ctx.reply('Usage: /watchAdd 005930');
    const redis   = getClient();
    const chatId  = String(ctx.chat.id);
    await redis.sadd(`watchlist:${chatId}`, stkCd);
    const members = await redis.smembers(`watchlist:${chatId}`);
    await ctx.reply(`⭐ Added to watchlist: <b>${stkCd}</b>\nCurrent: ${members.join(', ')}`, { parse_mode: 'HTML' });
});

/** /watchRemove {종목코드} – 관심 종목 제거 */
const watchlistRemove = guard(async (ctx) => {
    const args   = ctx.message.text.split(' ');
    const stkCd  = args[1];
    if (!stkCd) return ctx.reply('Usage: /watchRemove 005930');
    const redis   = getClient();
    const chatId  = String(ctx.chat.id);
    await redis.srem(`watchlist:${chatId}`, stkCd);
    const members = await redis.smembers(`watchlist:${chatId}`);
    const listStr = members.length > 0 ? members.join(', ') : 'None (receiving all)';
    await ctx.reply(`🗑 Removed from watchlist: <b>${stkCd}</b>\nCurrent: ${listStr}`, { parse_mode: 'HTML' });
});

/** /설정 – 개인 알림 설정 조회 */
const userSettings = guard(async (ctx) => {
    const redis  = getClient();
    const chatId = String(ctx.chat.id);
    const filterRaw   = await redis.get(`user_filter:${chatId}`);
    const watchRaw    = await redis.smembers(`watchlist:${chatId}`);
    let filter = [];
    try { filter = filterRaw ? JSON.parse(filterRaw) : []; } catch (_) {}
    await ctx.reply(formatUserSettings(filter, watchRaw), { parse_mode: 'HTML' });
});

/** /뉴스 – 최근 뉴스 + 분석 결과 */
const newsStatus = guard(async (ctx) => {
    const redis   = getClient();
    const control   = await redis.get('news:trading_control') || 'CONTINUE';
    const sentiment = await redis.get('news:market_sentiment') || 'NEUTRAL';
    const sectorsRaw = await redis.get('news:sector_recommend');
    let sectors = [];
    try { sectors = sectorsRaw ? JSON.parse(sectorsRaw) : []; } catch (_) {}

    let analysis = null;
    try {
        const analysisRaw = await redis.get('news:analysis');
        if (analysisRaw) analysis = JSON.parse(analysisRaw);
    } catch (_) {}

    await ctx.reply(formatNewsStatus({ analysis, control, sentiment, sectors }), { parse_mode: 'HTML' });
});

/** /섹터 – 섹터 분석 현황 */
const sectorStatus = guard(async (ctx) => {
    const redis     = getClient();
    const sentiment = await redis.get('news:market_sentiment') || 'NEUTRAL';
    const sectorsRaw = await redis.get('news:sector_recommend');
    let sectors = [];
    try { sectors = sectorsRaw ? JSON.parse(sectorsRaw) : []; } catch (_) {}

    let stats = [];
    try { stats = await kiwoom.getTodayStats(); } catch (_) {}

    await ctx.reply(formatSectorAnalysis({ sectors, sentiment, stats }), { parse_mode: 'HTML' });
});

/**
 * /점수 {종목코드} – 개인 보유/관심 종목 오버나잇 가능성 점수 조회
 * 전략 신호 없이 실시간 시세(등락률·체결강도·호가비율)만으로 점수 계산
 */
const scoreStock = guard(async (ctx) => {
    const args  = ctx.message.text.split(' ');
    const stkCd = args[1]?.trim();
    if (!stkCd) return ctx.reply('Usage: /score 005930');
    if (!/^\d{6}$/.test(stkCd)) return ctx.reply('❌ Stock code must be 6 digits. e.g. /score 005930');

    await ctx.reply(`🔍 Calculating score for ${stkCd}...`);

    const d = await kiwoom.scoreStock(stkCd);

    if (!d.data_available) {
        return ctx.reply(
            `❓ <b>${stkCd}</b> – Data unavailable\n` +
            `No response from Kiwoom REST API or WebSocket.\n` +
            `Check token validity or retry later.`,
            { parse_mode: 'HTML' }
        );
    }

    const score      = Number(d.score ?? 0);
    const threshold  = Number(d.overnight_threshold ?? 65);
    const fluRt      = Number(d.flu_rt ?? 0);
    const fluSign    = fluRt > 0 ? '+' : '';
    const bidRatio   = Number(d.bid_ratio ?? 0);
    const strength   = Number(d.cntr_strength ?? 0);
    const curPrc     = Number(d.cur_prc ?? 0);
    const dataSource = d.data_source ?? 'NONE';
    const stkNm      = d.stk_nm ? `${d.stk_nm} ` : '';

    // 점수 등급 및 이모지
    let grade, gradeEmoji;
    if (score >= 80)      { grade = 'A';  gradeEmoji = '🟢'; }
    else if (score >= 65) { grade = 'B+'; gradeEmoji = '🟡'; }
    else if (score >= 50) { grade = 'B';  gradeEmoji = '🟠'; }
    else                  { grade = 'C';  gradeEmoji = '🔴'; }

    const aboveThreshold = score >= threshold;
    const thresholdLine  = aboveThreshold
        ? `✅ 오버나잇 기준(<b>${threshold}점</b>) 초과 – Claude 평가 대상`
        : `❌ 오버나잇 기준(<b>${threshold}점</b>) 미달 – 강제청산 대상`;

    // 세부 점수 바 시각화 (10단계)
    const bar = (v, max) => {
        const filled = Math.max(0, Math.round((v / max) * 10));
        return '█'.repeat(filled) + '░'.repeat(10 - filled);
    };

    const mom  = Number(d.score_momentum  ?? 0);
    const pres = Number(d.score_pressure  ?? 0);
    const str  = Number(d.score_strength  ?? 0);

    // REST fallback 시 호가·체결강도 데이터 없음 안내
    const dataNote = dataSource === 'REST'
        ? `\n⚠️ <i>WS not subscribed – score based on price change only (no hoga/strength)\nRun /wsStart then retry for full accuracy</i>`
        : '';

    const hogaLine     = dataSource === 'WS'
        ? `Bid ratio (buy/sell): <b>${bidRatio}</b>\n`
        : `Bid ratio: <i>N/A (WS not subscribed)</i>\n`;
    const strengthLine = dataSource === 'WS'
        ? `Exec strength: <b>${strength}</b>\n`
        : `Exec strength: <i>N/A (WS not subscribed)</i>\n`;

    await ctx.reply(
        `${gradeEmoji} <b>${stkNm}(${stkCd}) Score Analysis</b>\n\n` +
        `📊 Total Score: <b>${score}pt</b> (Grade ${grade})\n` +
        `${thresholdLine}\n\n` +
        `<b>── Live Data ──</b>\n` +
        `Price: <b>${curPrc.toLocaleString()}₩</b>\n` +
        `Change: <b>${fluSign}${fluRt}%</b>\n` +
        strengthLine +
        hogaLine +
        `\n<b>── Score Breakdown ──</b>\n` +
        `Momentum  : ${bar(Math.max(0, mom), 25)} ${mom > 0 ? '+' : ''}${mom}pt\n` +
        `Buy press. : ${bar(pres, 20)} +${pres}pt\n` +
        `Strength   : ${bar(str, 10)} +${str}pt\n` +
        `Base       : +25pt\n` +
        dataNote + `\n\n` +
        `💡 <i>65+: Claude overnight eval | 50-65: Caution | <50: Close recommended</i>`,
        { parse_mode: 'HTML' }
    );
});

/** /history {종목코드} */
const signalHistory = guard(async (ctx) => {
    const args  = ctx.message.text.split(' ');
    const stkCd = args[1];
    if (!stkCd) return ctx.reply('Usage: /history 005930');

    const history = await kiwoom.getSignalHistory(stkCd);
    await ctx.reply(formatSignalHistory(stkCd, history), { parse_mode: 'HTML' });
});

/** /전략분석 – 전략별 성과 상세 */
const strategyAnalysis = guard(async (ctx) => {
    const rows = await kiwoom.getStrategyAnalysis();
    await ctx.reply(formatPerformanceSummary(rows), { parse_mode: 'HTML' });
});

/** /에러 – 시스템 에러 현황 */
const systemErrors = guard(async (ctx) => {
    const health = await kiwoom.getMonitorHealth();
    await ctx.reply(
        formatSystemHealth({
            queueDepth:       health.telegram_queue,
            errorCount:       health.error_queue,
            dailySignals:     health.daily_signals,
            tradingControl:   health.trading_control,
            calendarPreEvent: health.calendar_pre_event,
            wsReconnect:      health.ws_reconnect_today,
        }),
        { parse_mode: 'HTML' }
    );
});

/** /help */
const help = guard(async (ctx) => {
    await ctx.reply(
        `📖 <b>StockMate AI Commands</b>\n\n` +
        `<b>── Query ──</b>\n` +
        `/signals – Today's signal list\n` +
        `/perf – Today's strategy stats\n` +
        `/track – Today's virtual P&L detail\n` +
        `/analysis – Strategy win rate & return\n` +
        `/history {code} – Signal history for a stock\n` +
        `/quote {code} – Realtime quote\n` +
        `/score {code} – Overnight score\n` +
        `/candidates [market] – Candidate stocks\n` +
        `/report – Today's signal summary\n\n` +
        `<b>── News & Market ──</b>\n` +
        `/news – News analysis + trading status\n` +
        `/sector – Sector analysis\n` +
        `/events – This week's economic calendar\n\n` +
        `<b>── Personal Settings ──</b>\n` +
        `/settings – My notification settings\n` +
        `/filter [s1~s7|all] – Strategy filter\n` +
        `/watchAdd {code} – Add to watchlist\n` +
        `/watchRemove {code} – Remove from watchlist\n\n` +
        `<b>── System Control ──</b>\n` +
        `/pause – Pause trading signals\n` +
        `/resume – Resume trading (CONTINUE)\n` +
        `/errors – System error status\n` +
        `/strategy {s1~s7|s10|s12} – Run strategy manually\n` +
        `/token – Refresh Kiwoom token\n` +
        `/wsStart / /wsStop – WebSocket control\n` +
        `/status – System health check\n` +
        `/ping – Bot alive check\n\n` +
        `<b>── Strategies ──</b>\n` +
        `s1: Gap open | s2: VI pullback | s3: Inst+Frgn\n` +
        `s4: Big candle | s5: Prog+Frgn | s6: Theme laggard\n` +
        `s7: Auction | s10: 52w New High | s12: Closing strength\n` +
        `\n💡 /score works anytime (even outside trading hours)`,
        { parse_mode: 'HTML' }
    );
});

module.exports = {
    ping, status, signals, performance,
    candidates, quote, runStrategy,
    refreshToken, wsStart, wsStop, help,
    report, filter,
    newsStatus, sectorStatus, signalHistory, strategyAnalysis, systemErrors,
    pauseTrading, resumeTrading, calendarEvents, performanceDetail,
    watchlistAdd, watchlistRemove, userSettings,
    scoreStock,
    isAllowed,
};
