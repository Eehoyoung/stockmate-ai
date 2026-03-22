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
    await ctx.reply('🏓 pong! StockMate AI 작동 중');
});

/** /상태 */
const status = guard(async (ctx) => {
    const h = await kiwoom.health();
    await ctx.reply(
        `🟢 <b>시스템 상태</b>\nJava API: ${h.status}\n서비스: ${h.service}`,
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

/** /시세 {종목코드} */
const quote = guard(async (ctx) => {
    const args   = ctx.message.text.split(' ');
    const stkCd  = args[1];
    if (!stkCd) return ctx.reply('사용법: /시세 005930');

    const tick = await getTickData(stkCd);
    if (!tick || Object.keys(tick).length === 0) {
        return ctx.reply(`❓ ${stkCd} 실시간 데이터 없음 (WebSocket 미구독 또는 TTL 만료)`);
    }
    await ctx.reply(
        `📈 <b>${stkCd} 실시간 시세</b>\n` +
        `현재가: <b>${tick.cur_prc ?? '-'}</b>\n` +
        `등락률: ${tick.flu_rt ?? '-'}%\n` +
        `체결강도: ${tick.cntr_str ?? '-'}\n` +
        `체결시간: ${tick.cntr_tm ?? '-'}`,
        { parse_mode: 'HTML' }
    );
});

/** /전술 {s1~s7} */
const runStrategy = guard(async (ctx) => {
    const args     = ctx.message.text.split(' ');
    const strategy = args[1];
    if (!strategy) return ctx.reply('사용법: /전술 s1');

    await ctx.reply(`⚙️ ${strategy.toUpperCase()} 수동 실행 중...`);
    const result = await kiwoom.runStrategy(strategy);
    await ctx.reply(
        `✅ <b>${result.strategy}</b> 실행 완료\n발행 신호: ${result.published}건`,
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
        return ctx.reply('✅ 필터 해제 – 모든 전략 수신');
    }

    // /filter s1 s4 → ["S1_GAP_OPEN", "S4_BIG_CANDLE"]
    const strategyMap = {
        s1: 'S1_GAP_OPEN', s2: 'S2_VI_PULLBACK', s3: 'S3_INST_FRGN',
        s4: 'S4_BIG_CANDLE', s5: 'S5_PROG_FRGN', s6: 'S6_THEME_LAGGARD', s7: 'S7_AUCTION',
    };
    const selected = args
        .map((a) => strategyMap[a.toLowerCase()])
        .filter(Boolean);

    if (selected.length === 0) {
        return ctx.reply('❌ 유효한 전략 없음. 예: /filter s1 s4');
    }

    await redis.set(filterKey, JSON.stringify(selected));
    return ctx.reply(`✅ 필터 설정: ${selected.join(', ')}`);
});

/** /매매중단 – 매매 제어를 PAUSE 로 수동 변경 */
const pauseTrading = guard(async (ctx) => {
    const result = await kiwoom.setTradingControl('PAUSE');
    await ctx.reply(`🚨 매매 중단 설정 완료\n이전 상태: ${result.prev} → <b>PAUSE</b>`, { parse_mode: 'HTML' });
});

/** /매매재개 – 매매 제어를 CONTINUE 로 수동 복귀 */
const resumeTrading = guard(async (ctx) => {
    const result = await kiwoom.setTradingControl('CONTINUE');
    await ctx.reply(`✅ 매매 재개 설정 완료\n이전 상태: ${result.prev} → <b>CONTINUE</b>`, { parse_mode: 'HTML' });
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

/** /관심등록 {종목코드} – 특정 종목 알림만 받기 */
const watchlistAdd = guard(async (ctx) => {
    const args   = ctx.message.text.split(' ');
    const stkCd  = args[1];
    if (!stkCd) return ctx.reply('사용법: /관심등록 005930');
    const redis   = getClient();
    const chatId  = String(ctx.chat.id);
    await redis.sadd(`watchlist:${chatId}`, stkCd);
    const members = await redis.smembers(`watchlist:${chatId}`);
    await ctx.reply(`⭐ 관심 종목 등록: <b>${stkCd}</b>\n현재 관심 목록: ${members.join(', ')}`, { parse_mode: 'HTML' });
});

/** /관심해제 {종목코드} – 관심 종목 제거 */
const watchlistRemove = guard(async (ctx) => {
    const args   = ctx.message.text.split(' ');
    const stkCd  = args[1];
    if (!stkCd) return ctx.reply('사용법: /관심해제 005930');
    const redis   = getClient();
    const chatId  = String(ctx.chat.id);
    await redis.srem(`watchlist:${chatId}`, stkCd);
    const members = await redis.smembers(`watchlist:${chatId}`);
    const listStr = members.length > 0 ? members.join(', ') : '없음 (모든 종목 수신)';
    await ctx.reply(`🗑 관심 종목 해제: <b>${stkCd}</b>\n현재 관심 목록: ${listStr}`, { parse_mode: 'HTML' });
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

/** /신호이력 {종목코드} */
const signalHistory = guard(async (ctx) => {
    const args  = ctx.message.text.split(' ');
    const stkCd = args[1];
    if (!stkCd) return ctx.reply('사용법: /신호이력 005930');

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
        `📖 <b>StockMate AI 명령어</b>\n\n` +
        `<b>── 조회 ──</b>\n` +
        `/신호 – 당일 신호 목록\n` +
        `/성과 – 당일 전략별 통계\n` +
        `/성과추적 – 오늘의 가상 P&L 상세\n` +
        `/전략분석 – 전략별 가상 승률/수익률\n` +
        `/신호이력 {종목코드} – 종목별 신호 이력\n` +
        `/시세 {종목코드} – 실시간 시세\n` +
        `/후보 [market] – 후보 종목\n\n` +
        `<b>── 뉴스·시장 ──</b>\n` +
        `/뉴스 – 뉴스 분석 + 매매 상태\n` +
        `/섹터 – 섹터 분석 현황\n` +
        `/이벤트 – 이번 주 경제 캘린더\n\n` +
        `<b>── 개인 설정 ──</b>\n` +
        `/설정 – 내 알림 설정 조회\n` +
        `/filter [s1~s7|all] – 전략 필터\n` +
        `/관심등록 {종목코드} – 관심 종목 추가\n` +
        `/관심해제 {종목코드} – 관심 종목 제거\n\n` +
        `<b>── 시스템 제어 ──</b>\n` +
        `/매매중단 – 매매 제어 PAUSE\n` +
        `/매매재개 – 매매 제어 CONTINUE\n` +
        `/에러 – 시스템 에러 현황\n` +
        `/전술 {s1~s7} – 전술 수동 실행\n` +
        `/토큰갱신 – 키움 토큰 갱신\n` +
        `/ws시작 / /ws종료 – WebSocket 제어\n` +
        `/상태 – 시스템 헬스체크\n` +
        `/report – 오늘 신호 요약`,
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
    isAllowed,
};
