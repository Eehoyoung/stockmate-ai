'use strict';

/**
 * handlers/commands.js
 * 텔레그램 봇 명령어 처리
 *
 * 명령어 목록:
 * /signals – Today's signal list
 * /perf – Today's strategy stats
 * /track – Today's virtual P&L detail
 * /analysis – Strategy win rate & return
 * /history {code} – Signal history for a stock
 * /quote {code} – Realtime quote
 * /score {code} – Overnight score
 * /claude {code} – Claude AI 종합 분석
 * /candidates [market] – Candidate stocks
 * /report – Today's signal summary
 *
 * ── News & Market ──
 * /news – News analysis + trading status
 * /sector – Sector analysis
 * /events – This week's economic calendar
 *
 * ── Personal Settings ──
 * /settings – My notification settings
 * /filter [s1~s16|all] – Strategy filter
 * /watchAdd {code} – Add to watchlist
 * /watchRemove {code} – Remove from watchlist
 *
 * ── System Control ──
 * /pause – Pause trading signals
 * /resume – Resume trading (CONTINUE)
 * /errors – System error status
 * /strategy {s1~s16} – Run strategy manually
 * /token – Refresh Kiwoom token
 * /wsStart / /wsStop – WebSocket control
 * /status – System health check
 * /ping – Bot alive check
 */

const { getTickData, getHogaData, getClient } = require('../services/redis');
const {
    buildReanalysisPayload,
    getConfirmRequest,
    listActiveConfirmRequests,
} = require('../services/confirmStore');
const kiwoom          = require('../services/kiwoom');
const { getLogger }   = require('../utils/logger');

const logger = getLogger('commands');
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
    formatStockScore,
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
            logger.error('명령 처리 오류', { cmd: ctx.message?.text }, e);
            await ctx.reply(`❌ 오류: ${e.message}`);
        }
    };
}

async function sendOperationalReplies(ctx, command, replies) {
    const chatIds = [String(ctx.chat.id)];
    let sentCount = 0;
    let failedCount = 0;
    const items = Array.isArray(replies) ? replies : [replies];

    for (const item of items) {
        const text = typeof item === 'string' ? item : item.text;
        const options = typeof item === 'string' ? undefined : item.options;
        try {
            await ctx.reply(text, options);
            sentCount++;
        } catch (e) {
            failedCount++;
            logger.error(`${command} send failed`, {
                recipient_group: 'request_chat',
                chat_ids: chatIds,
                sent_count: sentCount,
                failed_count: failedCount,
            }, e);
            throw e;
        }
    }

    logger.info(`${command} sent`, {
        recipient_group: 'request_chat',
        chat_ids: chatIds,
        sent_count: sentCount,
        failed_count: failedCount,
    });
}

const STRATEGY_MAP = {
    s1:  'S1_GAP_OPEN',
    s2:  'S2_VI_PULLBACK',
    s3:  'S3_INST_FRGN',
    s4:  'S4_BIG_CANDLE',
    s5:  'S5_PROG_FRGN',
    s6:  'S6_THEME_LAGGARD',
    s7:  'S7_ICHIMOKU_BREAKOUT',
    s8:  'S8_GOLDEN_CROSS',
    s9:  'S9_PULLBACK_SWING',
    s10: 'S10_NEW_HIGH',
    s11: 'S11_FRGN_CONT',
    s12: 'S12_CLOSING',
    s13: 'S13_BOX_BREAKOUT',
    s14: 'S14_OVERSOLD_BOUNCE',
    s15: 'S15_MOMENTUM_ALIGN',
    s16: 'S16_ACCUMULATION_SHADOW',
};

const FAMILY_FILTER_MAP = {
    g01: ['S1_GAP_OPEN', 'S2_VI_PULLBACK', 'S12_CLOSING'],
    g02: ['S3_INST_FRGN', 'S5_PROG_FRGN', 'S11_FRGN_CONT'],
    g03: ['S16_ACCUMULATION_SHADOW'],
    g04: ['S8_GOLDEN_CROSS', 'S9_PULLBACK_SWING', 'S15_MOMENTUM_ALIGN'],
    g05: ['S7_ICHIMOKU_BREAKOUT', 'S10_NEW_HIGH', 'S13_BOX_BREAKOUT'],
    g06: ['S4_BIG_CANDLE', 'S6_THEME_LAGGARD'],
    g07: ['S14_OVERSOLD_BOUNCE'],
};

function expandStrategyFilterArgs(args) {
    return dedupe(args.flatMap((arg) => {
        const key = String(arg || '').toLowerCase();
        if (FAMILY_FILTER_MAP[key]) return FAMILY_FILTER_MAP[key];
        return STRATEGY_MAP[key] ? [STRATEGY_MAP[key]] : [];
    }));
}

const CANDIDATE_MARKETS = {
    '000': { code: '000', label: '전체' },
    all: { code: '000', label: '전체' },
    allmarket: { code: '000', label: '전체' },
    total: { code: '000', label: '전체' },
    '001': { code: '001', label: '코스피' },
    kospi: { code: '001', label: '코스피' },
    '101': { code: '101', label: '코스닥' },
    kosdaq: { code: '101', label: '코스닥' },
};

function parseCommandArgs(text) {
    return String(text ?? '')
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .slice(1);
}

function parseStockCodeArg(ctx, commandName) {
    const stkCd = parseCommandArgs(ctx.message?.text)[0]?.trim();
    if (!stkCd) {
        return { ok: false, message: `Usage: /${commandName} 005930` };
    }
    if (!/^\d{6}$/.test(stkCd)) {
        return { ok: false, message: `❌ 종목코드는 6자리 숫자입니다. 예: /${commandName} 005930` };
    }
    return { ok: true, stkCd };
}

function parseScoreOptions(ctx, commandName = 'score') {
    const args = parseCommandArgs(ctx.message?.text);
    const rest = args.slice(1).map((arg) => String(arg).trim().toLowerCase());
    const parsed = parseStockCodeArg(ctx, commandName);
    if (!parsed.ok) return parsed;
    const mode = rest.includes('fast') || rest.includes('rule') || rest.includes('noai') ? 'fast' : 'deep';
    const refresh = rest.includes('refresh') || rest.includes('force');
    return {
        ok: true,
        stkCd: parsed.stkCd,
        mode,
        refresh,
        enableAi: mode !== 'fast',
    };
}

function parseNewsOptions(ctx) {
    const args = parseCommandArgs(ctx.message?.text).map((arg) => String(arg).trim().toLowerCase());
    const deep = args.includes('deep') || args.includes('ai');
    return {
        refresh: args.includes('refresh') || args.includes('force'),
        deep,
        history: args.includes('history') || args.includes('replay') || args.includes('다시보기'),
    };
}

function parseCandidateMarket(rawArg) {
    const key = String(rawArg ?? '000').trim().toLowerCase();
    return CANDIDATE_MARKETS[key] || null;
}

function dedupe(items) {
    return [...new Set(items)];
}

function toFiniteNumber(value) {
    if (value == null || value === '') return null;
    const parsed = Number(String(value).replace(/,/g, ''));
    return Number.isFinite(parsed) ? parsed : null;
}

function formatWon(value, fallback = '-') {
    const numeric = toFiniteNumber(value);
    return numeric == null ? fallback : `${numeric.toLocaleString()}원`;
}

function formatSignedPercent(value, digits = 2, fallback = '-') {
    const numeric = toFiniteNumber(value);
    if (numeric == null) return fallback;
    return `${numeric > 0 ? '+' : ''}${numeric.toFixed(digits)}%`;
}

function formatFixed(value, digits = 2, fallback = '-') {
    const numeric = toFiniteNumber(value);
    return numeric == null ? fallback : numeric.toFixed(digits);
}

function normalizeList(values) {
    return Array.isArray(values)
        ? values.map((value) => String(value).trim()).filter(Boolean)
        : [];
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function buildHogaSummary(tick, hoga) {
    const bid = toFiniteNumber(hoga?.total_buy_bid_req);
    const ask = toFiniteNumber(hoga?.total_sel_bid_req);
    const bestBid = toFiniteNumber(tick?.bid_prc);
    const bestAsk = toFiniteNumber(tick?.ask_prc);
    const ratio = bid != null && ask != null && ask > 0 ? bid / ask : null;

    return {
        bestBid,
        bestAsk,
        bid,
        ask,
        ratio,
    };
}


function formatNewsBriefResponse(brief) {
    const analysis = brief?.analysis || {};
    const slotName = String(brief?.slot_name || analysis?.brief_slot || 'MORNING').toUpperCase();
    const slotLabel = {
        MORNING: '08:00 브리핑',
        MIDMORNING: '10:30 브리핑',
        MIDDAY: '12:30 브리핑',
        AFTERNOON: '14:00 브리핑',
        CLOSE: '15:40 브리핑',
    }[slotName] || '실시간 브리핑';

    const sentimentLabel = {
        BULLISH: '강세 우위',
        NEUTRAL: '중립',
        BEARISH: '약세 우위',
    }[String(analysis.market_sentiment || 'NEUTRAL').toUpperCase()] || String(analysis.market_sentiment || 'NEUTRAL');

    const sectors = normalizeList(
        ['MIDMORNING', 'MIDDAY', 'AFTERNOON'].includes(slotName)
            ? (analysis.midday_sectors || analysis.recommended_sectors)
            : slotName === 'CLOSE'
                ? (analysis.close_leaders || analysis.recommended_sectors)
                : analysis.recommended_sectors
    );
    const risks = normalizeList(analysis.risk_factors);
    const urgentNews = normalizeList(analysis.urgent_news);

    let marketLine = '';
    if (slotName === 'MORNING') {
        marketLine = String(analysis.korea_outlook || '').trim();
    } else if (['MIDMORNING', 'MIDDAY', 'AFTERNOON'].includes(slotName)) {
        marketLine = String(analysis.midday_index_commentary || analysis.midday_recap || '').trim();
    } else {
        marketLine = String(analysis.close_flow || '').trim();
    }

    const lines = [
        `📰 <b>${slotLabel}</b>`,
        `시장 톤: <b>${sentimentLabel}</b>`,
    ];

    lines.push(`AI: <b>${brief?.ai_used ? 'DEEP' : 'NO-AI/CACHE'}</b>`);

    if (marketLine) {
        lines.push('', '<b>1) 현재 국장 상황</b>', escapeHtml(marketLine));
    }

    if (sectors.length > 0) {
        lines.push('', '<b>2) 주요 섹터</b>');
        sectors.slice(0, 8).forEach((sector) => lines.push(`• ${escapeHtml(sector)}`));
    }

    const macroLines = slotName === 'MORNING'
        ? normalizeList([...(analysis.us_market_points || []), ...(analysis.us_sector_points || []), ...(analysis.macro_points || []), ...urgentNews])
        : urgentNews;
    if (macroLines.length > 0) {
        lines.push('', '<b>3) 영향 뉴스 / 외부 변수</b>');
        macroLines.slice(0, 8).forEach((item) => lines.push(`• ${escapeHtml(item)}`));
    }

    const outlook = ['MIDMORNING', 'MIDDAY', 'AFTERNOON'].includes(slotName)
        ? String(analysis.afternoon_outlook || '').trim()
        : slotName === 'CLOSE'
            ? String(analysis.tomorrow_watch || '').trim()
            : String(analysis.korea_outlook || '').trim();
    if (outlook) {
        lines.push('', `<b>4) ${slotName === 'CLOSE' ? '다음 체크포인트' : '예상 흐름'}</b>`, escapeHtml(outlook));
    }

    if (risks.length > 0) {
        lines.push('', '<b>5) 리스크</b>');
        risks.slice(0, 6).forEach((risk) => lines.push(`• ${escapeHtml(risk)}`));
    }

    if (analysis.summary) {
        lines.push('', '<b>한 줄 결론</b>', escapeHtml(String(analysis.summary).trim()));
    }

    if (brief?.used_cached_analysis) {
        lines.push('', '<i>실시간 신규 뉴스가 적어 최신 캐시를 일부 함께 사용했습니다.</i>');
    }

    return lines.join('\n');
}

/** /ping */
const ping = guard(async (ctx) => {
    await ctx.reply('🏓 pong! StockMate AI is running');
});

/**
 * Claude API 일별 사용량 조회 (Redis)
 * @returns {{ calls: number, tokens: number }}
 */
function getKstNowParts() {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(new Date());

    return Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
}

function getKstBusinessDateCompact() {
    const parts = getKstNowParts();
    return `${parts.year}${parts.month}${parts.day}`;
}

function formatKstDateTime(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) {
        return '-';
    }
    return date.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    });
}

function renderHealthSummary(health, usage) {
    const redis = health.redis || {};
    const postgres = health.postgres || {};
    const ws = health.ws || {};
    const positions = health.positions || {};
    const flags = health.flags || {};
    const schedulers = health.schedulers || {};
    const schedulerLines = [
        `news: ${schedulers.news_scheduler?.last_status ?? 'UNKNOWN'}${schedulers.news_scheduler?.last_slot ? ` (${schedulers.news_scheduler.last_slot})` : ''}`,
        `status_report: ${schedulers.status_report?.last_status ?? 'UNKNOWN'}`,
        `daily_summary: ${schedulers.daily_summary?.last_status ?? 'UNKNOWN'}`,
    ].join('\n');
    const claudeBlock = usage
        ? `\n\n?뱤 <b>Claude AI Today</b>\nCalls: <b>${usage.calls}</b> / ${usage.maxCalls}\nTokens: <b>${usage.tokens.toLocaleString()}</b>`
        : '';

    return (
        `?윟 <b>System Status</b>\n` +
        `Checked: ${formatKstDateTime(health.checked_at)} KST\n` +
        `API: ${health.status} | ${health.service}\n\n` +
        `?뱻 <b>Dependencies</b>\n` +
        `Redis: ${redis.status ?? '-'}\n` +
        `Postgres: ${postgres.status ?? '-'}\n` +
        `WS: ${ws.status ?? '-'}${ws.heartbeat_age_sec != null ? ` (${ws.heartbeat_age_sec}s ago)` : ''}\n\n` +
        `?벀 <b>Queues</b>\n` +
        `telegram_queue: ${redis.telegram_queue ?? 0}\n` +
        `ai_scored_queue: ${redis.ai_scored_queue ?? 0}\n` +
        `error_queue: ${redis.error_queue ?? 0}\n` +
        `vi_watch_queue: ${redis.vi_watch_queue ?? 0}\n\n` +
        `?뱤 <b>Positions & Flags</b>\n` +
        `Active positions: ${positions.active_count ?? 0}\n` +
        `Trading control: ${flags.trading_control ?? '-'}\n` +
        `calendar:pre_event: ${flags.calendar_pre_event ? 'true' : 'false'}\n` +
        `ws:db_writer:event_mode: ${flags.ws_db_writer_event_mode ?? '-'}\n` +
        `market_hours_bypass: ${flags.bypass_market_hours ? 'true' : 'false'}\n` +
        `strategy_session_filter: ${flags.strategy_session_filter ? 'true' : 'false'}\n` +
        `strategy_session_dry_run: ${flags.strategy_session_dry_run ? 'true' : 'false'}\n` +
        `strategy_session_fail_open: ${flags.strategy_session_fail_open ? 'true' : 'false'}\n` +
        `session_enter_guard: ${flags.session_enter_guard ? 'true' : 'false'}\n\n` +
        `?뵩 <b>Schedulers</b>\n${schedulerLines}` +
        claudeBlock
    );
}

function renderErrorSummary(health) {
    const redis = health.redis || {};
    const ws = health.ws || {};
    const flags = health.flags || {};
    const schedulers = health.schedulers || {};
    const issues = [];

    if (health.status && health.status !== 'UP') issues.push(`API health degraded: ${health.status}`);
    if (redis.status && redis.status !== 'UP') issues.push(`Redis is ${redis.status}`);
    if (health.postgres?.status && health.postgres.status !== 'UP') issues.push(`Postgres is ${health.postgres.status}`);
    if (ws.status && ws.status !== 'UP') issues.push(`WS heartbeat stale (${ws.heartbeat_age_sec ?? '-'}s)`);
    if ((redis.error_queue ?? 0) > 0) issues.push(`error_queue backlog: ${redis.error_queue}`);
    if ((redis.telegram_queue ?? 0) > 20) issues.push(`telegram_queue backlog: ${redis.telegram_queue}`);
    if ((redis.ai_scored_queue ?? 0) > 20) issues.push(`ai_scored_queue backlog: ${redis.ai_scored_queue}`);
    if (flags.calendar_pre_event) issues.push('calendar:pre_event is active');
    if ((schedulers.news_scheduler?.last_status ?? 'UNKNOWN') !== 'OK') issues.push(`news scheduler: ${schedulers.news_scheduler?.last_status ?? 'UNKNOWN'}`);
    if ((schedulers.status_report?.last_status ?? 'UNKNOWN') !== 'OK') issues.push(`status_report scheduler: ${schedulers.status_report?.last_status ?? 'UNKNOWN'}`);

    return [
        `?뵩 <b>[?쒖뒪???곹깭]</b>`,
        `Checked: ${formatKstDateTime(health.checked_at)} KST`,
        '',
        issues.length > 0 ? issues.map((issue) => `- ${issue}`).join('\n') : 'No active operational issues.',
    ].join('\n');
}

async function getClaudeUsage() {
    const redis = getClient();
    const today = getKstBusinessDateCompact();
    try {
        const callsRaw  = await redis.get(`claude:daily_calls:${today}`);
        const tokensRaw = await redis.get(`claude:daily_tokens:${today}`);
        return {
            calls:  Number(callsRaw  ?? 0),
            tokens: Number(tokensRaw ?? 0),
        };
    } catch (e) {
        logger.warn('Claude 사용량 조회 실패', { error: e.message });
        return { calls: 0, tokens: 0 };
    }
}

/** /status */
const status = guard(async (ctx) => {
    const h = await kiwoom.health();
    const usage = await getClaudeUsage();
    const maxCalls = Number(process.env.MAX_CLAUDE_CALLS_PER_DAY ?? 100);
    return sendOperationalReplies(ctx, 'status', {
        text: renderHealthSummary(h, { ...usage, maxCalls }),
        options: { parse_mode: 'HTML' },
    });

    // ws_solver.md 4.4: ws:py_heartbeat 로 Python WS 상태 진단
    const redis = getClient();
    let wsStatus = '❌ Offline (TTL expired)';
    try {
        const hb = await redis.hgetall('ws:py_heartbeat');
        if (hb && hb.updated_at) {
            const secAgo = Math.round(Date.now() / 1000 - parseFloat(hb.updated_at));
            wsStatus = `✅ Online (${secAgo}s ago)`;
        }
    } catch (_) {}

    // JAVA_WS_ENABLED=false 일 때 Java WS 는 의도적으로 비활성화됨 (Python 단독 담당)
    const javaWsEnabled = (process.env.JAVA_WS_ENABLED ?? 'false').toLowerCase() === 'true';
    let javaWsStatus = '⚪ Disabled (Python WS 단독)';
    if (javaWsEnabled) {
        try {
            const wsConn = await redis.get('ws:connected');
            javaWsStatus = wsConn === '1' ? '✅ Connected' : '❌ Disconnected';
        } catch (_) {}
    }

    // 보유 포지션 수, 큐 백로그, ws:db_writer:event_mode 조회
    let positionCount = 'N/A';
    let telegramQueueLen = 'N/A';
    let aiScoredQueueLen = 'N/A';
    let wsEventMode = 'N/A';
    try {
        positionCount = await redis.scard('open_positions') ?? 0;
    } catch (e) {
        logger.warn('/status open_positions 조회 실패', { error: e.message });
    }
    try {
        telegramQueueLen = await redis.llen('telegram_queue') ?? 0;
        aiScoredQueueLen = await redis.llen('ai_scored_queue') ?? 0;
    } catch (e) {
        logger.warn('/status 큐 백로그 조회 실패', { error: e.message });
    }
    try {
        wsEventMode = await redis.get('ws:db_writer:event_mode') ?? 'unknown';
    } catch (e) {
        logger.warn('/status ws:db_writer:event_mode 조회 실패', { error: e.message });
    }

    await ctx.reply(
        `🟢 <b>System Status</b>\n` +
        `Java API: ${h.status} | ${h.service}\n\n` +
        `📡 <b>WebSocket</b>\n` +
        `Python WS: ${wsStatus}\n` +
        `Java WS:   ${javaWsStatus}\n\n` +
        `📊 <b>Claude AI Today</b>\n` +
        `Calls: <b>${usage.calls}</b> / ${maxCalls}\n` +
        `Tokens: <b>${usage.tokens.toLocaleString()}</b>\n\n` +
        `📦 <b>큐 상태</b>\n` +
        `• 입력 큐: ${telegramQueueLen}건\n` +
        `• 출력 큐: ${aiScoredQueueLen}건\n\n` +
        `📊 <b>포지션</b>\n` +
        `• 보유: ${positionCount}종목\n` +
        `• DB이벤트모드: ${wsEventMode}`,
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
    const [result, poolStatus] = await Promise.allSettled([
        kiwoom.getCandidates(market),
        kiwoom.getCandidatePoolStatus(),
    ]);
    const data = result.status === 'fulfilled' ? result.value : { candidates: [], codes: [], count: 0 };

    const withTags = (data.candidates ?? []).slice(0, 20);
    const marketLabel = market === '001' ? '코스피' : market === '101' ? '코스닥' : '전체';

    let lines;
    if (withTags.length > 0) {
        lines = withTags.map(({ code, strategies }) => {
            const tags = strategies && strategies.length > 0
                ? ` <i>[${[...strategies].join(', ')}]</i>`
                : '';
            return `• <b>${code}</b>${tags}`;
        });
    } else {
        lines = (data.codes ?? []).slice(0, 20).map(code => `• <b>${code}</b>`);
    }

    const total = data.count ?? 0;
    const tagNote = withTags.some(c => c.strategies && c.strategies.length > 0)
        ? '\n<i>괄호 안: 오늘 해당 종목에 신호를 발생시킨 전략</i>'
        : '\n<i>아직 전략 신호 없음 (장 중 전략 실행 후 표시됩니다)</i>';

    // 전략별 풀 크기 테이블 (Java 실패 시 ai-engine fallback)
    let poolLines = '';
    let poolSource = 'orchestrator';
    let ps = poolStatus.status === 'fulfilled' ? poolStatus.value : null;
    if (!ps) {
        try {
            ps = await kiwoom.getAiEngineCandidates();
            poolSource = 'ai-engine';
        } catch (_) { ps = null; }
    }
    if (ps) {
        const strategies = ['s1','s7','s8','s9','s10','s11','s12','s13','s14','s15','s16'];
        const rows = strategies.map(s => {
            const k = market === '101' ? `${s}_101` : (market === '001' ? `${s}_001` : null);
            if (k && ps[k] != null) return `  ${s.toUpperCase()}: ${ps[k]}건`;
            // 전체 시장일 때 001+101 합산
            const k001 = `${s}_001`, k101 = `${s}_101`;
            const total = (ps[k001] ?? 0) + (ps[k101] ?? 0);
            return `  ${s.toUpperCase()}: ${total}건`;
        }).filter(Boolean);
        if (rows.length > 0) {
            const sourceTag = poolSource === 'ai-engine' ? ' <i>(ai-engine)</i>' : '';
            poolLines = `\n\n📊 <b>전략별 풀 크기</b>${sourceTag}\n` + rows.join('\n');
        }
    }

    await ctx.reply(
        `📋 <b>후보 종목 [${marketLabel}] – 총 ${total}개</b>\n\n` +
        lines.join('\n') +
        (total > 20 ? `\n… 외 ${total - 20}개` : '') +
        tagNote +
        poolLines,
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

/** /strategy {s1~s16} */
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

    // Python WS 상태 함께 확인
    const redis = getClient();
    let pyStatus = '❌ Offline';
    try {
        const hb = await redis.hgetall('ws:py_heartbeat');
        if (hb && hb.updated_at) {
            const secAgo = Math.round(Date.now() / 1000 - parseFloat(hb.updated_at));
            pyStatus = secAgo < 90 ? `✅ Online (${secAgo}s ago)` : '❌ Offline (TTL expired)';
        }
    } catch (_) {}

    await ctx.reply(
        `📡 ${result.msg}\n\n` +
        `Python WS: ${pyStatus}\n` +
        `ℹ️ Python WS는 별도 프로세스입니다.\n` +
        `오프라인이면 서버에서 <code>python main.py</code> 를 실행하세요.`,
        { parse_mode: 'HTML' }
    );
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
        s1:  'S1_GAP_OPEN',        s2:  'S2_VI_PULLBACK',
        s3:  'S3_INST_FRGN',       s4:  'S4_BIG_CANDLE',
        s5:  'S5_PROG_FRGN',       s6:  'S6_THEME_LAGGARD',
        s7:  'S7_ICHIMOKU_BREAKOUT',         s8:  'S8_GOLDEN_CROSS',
        s9:  'S9_PULLBACK_SWING',  s10: 'S10_NEW_HIGH',
        s11: 'S11_FRGN_CONT',      s12: 'S12_CLOSING',
        s13: 'S13_BOX_BREAKOUT',   s14: 'S14_OVERSOLD_BOUNCE',
        s15: 'S15_MOMENTUM_ALIGN',
        s16: 'S16_ACCUMULATION_SHADOW',
    };
    const selected = args
        .map((a) => strategyMap[a.toLowerCase()])
        .filter(Boolean);

    if (selected.length === 0) {
        return ctx.reply('❌ No valid strategy. e.g. /filter s1 s4 s8 s14');
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
    const options = parseNewsOptions(ctx);
    if (options.history) {
        const redis = getClient();
        const rawItems = await redis.lrange('news:brief:history', 0, 9);
        const items = rawItems.map((raw) => {
            try { return JSON.parse(raw); } catch (_) { return null; }
        }).filter(Boolean);
        if (!items.length) {
            try {
                const latest = await redis.get('news:analysis');
                if (latest) {
                    const analysis = JSON.parse(latest);
                    items.push({
                        business_date: getKstBusinessDateCompact(),
                        slot_name: analysis.brief_slot || 'LATEST',
                        market_sentiment: analysis.market_sentiment || 'NEUTRAL',
                        message: analysis.summary || '최근 캐시 브리핑',
                    });
                }
            } catch (_) {}
        }
        if (!items.length) return ctx.reply('📭 저장된 뉴스 브리핑이 없습니다.');
        const list = items.map((item, index) => {
            const sentiment = { BULLISH: '강세', NEUTRAL: '중립', BEARISH: '약세' }[item.market_sentiment] || item.market_sentiment;
            return `${index + 1}. <b>${escapeHtml(item.business_date)} ${escapeHtml(item.slot || item.slot_name)}</b> · ${escapeHtml(sentiment || '-')}` +
                `\n${escapeHtml(String(item.message || item.analysis?.summary || '').replace(/<[^>]+>/g, '').slice(0, 180))}`;
        });
        return sendOperationalReplies(ctx, 'news-history', {
            text: `🗂 <b>최근 뉴스 브리핑 다시보기</b>\n\n${list.join('\n\n')}\n\n웹 대시보드에서 전체 내용을 펼쳐볼 수 있습니다.`,
            options: { parse_mode: 'HTML', disable_web_page_preview: true },
        });
    }
    await sendOperationalReplies(ctx, 'news', '뉴스와 장상황을 즉시 재분석 중입니다. 잠시만 기다리세요.');

    try {
        const brief = await kiwoom.getLiveNewsBrief(null, { refresh: options.refresh, ai: options.deep });
        if (brief?.analysis || brief?.message) {
            const message = brief?.analysis ? formatNewsBriefResponse(brief) : brief.message;
            return sendOperationalReplies(ctx, 'news', {
                text: message,
                options: { parse_mode: 'HTML', disable_web_page_preview: true },
            });
        }
    } catch (e) {
        logger.warn('/news live brief failed, fallback to cached analysis', { error: e.message });
    }

    const redis = getClient();
    const sentiment = await redis.get('news:market_sentiment') || 'NEUTRAL';
    const sectorsRaw = await redis.get('news:sector_recommend');
    let sectors = [];
    try { sectors = sectorsRaw ? JSON.parse(sectorsRaw) : []; } catch (_) {}

    let analysis = null;
    try {
        const analysisRaw = await redis.get('news:analysis');
        if (analysisRaw) analysis = JSON.parse(analysisRaw);
    } catch (_) {}

    await sendOperationalReplies(ctx, 'news', {
        text: formatNewsStatus({ analysis, sentiment, sectors }),
        options: { parse_mode: 'HTML' },
    });
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
 * /score {종목코드} — 실시간 데이터 수집 → S1~S16 심사 + AI 스코어링 + Claude 종합 분석
 * 전략 매칭 시: 전략별 rule_score + AI 스코어링 카드 + Claude 종합 의견
 * 전략 미매칭 시: Claude 실시간 데이터 단독 AI 분석 반환 (후보풀 무관 동작)
 */
const scoreStock = guard(async (ctx) => {
    const parsed = parseScoreOptions(ctx, 'score');
    if (!parsed.ok) return ctx.reply(parsed.message);
    const stkCd = parsed.stkCd;
    if (!stkCd || !/^\d{6}$/.test(stkCd)) return ctx.reply('❌ 종목코드는 6자리 숫자입니다. 예: /score 005930');

    await ctx.reply(
        `🔍 <b>${stkCd}</b> 분석 중...\n실시간 데이터 수집 → S1~S16 심사 → 전략군 통합 → Claude 종합 분석 (최대 90초 소요)`,
        { parse_mode: 'HTML' },
    );

    let d;
    try {
        d = await kiwoom.scoreStockFull(stkCd, {
            enableAi: parsed.enableAi,
            refresh: parsed.refresh,
        });
    } catch (e) {
        return ctx.reply(`❌ ai-engine 심사 실패: ${e.message}`);
    }

    if (d.skipped && d.skipped.length === 1 && d.skipped[0].includes('데이터 수집 실패')) {
        return ctx.reply(
            `❓ <b>${stkCd}</b> – 데이터 조회 불가\nKiwoom 토큰 또는 ai-engine 연결을 확인하세요.\n사유: ${d.skipped[0]}`,
            { parse_mode: 'HTML' },
        );
    }

    const messages = formatStockScore(d);
    for (const msg of messages) {
        if (msg && msg.trim()) {
            if (msg.length <= 4096) {
                await ctx.reply(msg, { parse_mode: 'HTML' });
            } else {
                await ctx.reply(msg.slice(0, 4000), { parse_mode: 'HTML' });
                if (msg.slice(4000).trim()) await ctx.reply(msg.slice(4000), { parse_mode: 'HTML' });
            }
        }
    }
});

/** /claude — /score 와 동일 (이전 호환) */
const claudeAnalyze = guard(async (ctx) => {
    const parsed = parseScoreOptions(ctx, 'claude');
    if (!parsed.ok) return ctx.reply(parsed.message);
    const stkCd = parsed.stkCd;
    if (!stkCd || !/^\d{6}$/.test(stkCd)) return ctx.reply('❌ 종목코드는 6자리 숫자입니다. 예: /claude 005930');

    await ctx.reply(
        `🔍 <b>${stkCd}</b> 분석 중...\n실시간 데이터 수집 → 15전략 심사 → Claude 종합 분석 (최대 90초 소요)`,
        { parse_mode: 'HTML' },
    );

    let d;
    try {
        d = await kiwoom.scoreStockFull(stkCd, {
            enableAi: parsed.enableAi,
            refresh: parsed.refresh,
        });
    } catch (e) {
        return ctx.reply(`❌ ai-engine 분석 실패: ${e.message}`);
    }

    const messages = formatStockScore(d);
    for (const msg of messages) {
        if (msg && msg.trim()) {
            if (msg.length <= 4096) {
                await ctx.reply(msg, { parse_mode: 'HTML' });
            } else {
                await ctx.reply(msg.slice(0, 4000), { parse_mode: 'HTML' });
                if (msg.slice(4000).trim()) await ctx.reply(msg.slice(4000), { parse_mode: 'HTML' });
            }
        }
    }
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
    const healthSnapshot = await kiwoom.health();
    return ctx.reply(renderErrorSummary(healthSnapshot), { parse_mode: 'HTML' });
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

const confirmPending = guard(async (ctx) => {
    const rows = await listActiveConfirmRequests(10);
    if (!rows || rows.length === 0) {
        return ctx.reply('대기 중인 human_confirm 요청이 없습니다.');
    }

    const lines = rows.map((row, idx) => {
        const expires = new Intl.DateTimeFormat('ko-KR', {
            timeZone: 'Asia/Seoul',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
        }).format(new Date(row.expires_at));
        const stkLabel = row.stk_nm ? `${row.stk_nm}(${row.stk_cd})` : row.stk_cd;
        return `${idx + 1}. <b>${row.request_key}</b>\n${stkLabel} | ${row.strategy} | ${row.status} | 만료 ${expires}`;
    });

    await ctx.reply(
        `<b>human_confirm 보관 목록</b>\n\n${lines.join('\n\n')}\n\n/reanalyze {request_key}`,
        { parse_mode: 'HTML' },
    );
});

const reanalyzeConfirm = guard(async (ctx) => {
    const args = ctx.message.text.split(' ');
    const requestKey = args[1]?.trim();
    if (!requestKey) return ctx.reply('Usage: /reanalyze hc-...');

    const result = await buildReanalysisPayload(requestKey);
    if (!result.ok) {
        if (result.reason === 'expired') {
            return ctx.reply('해당 요청은 만료되어 재분석할 수 없습니다.');
        }
        return ctx.reply('해당 request_key를 찾지 못했습니다.');
    }

    const redis = getClient();
    await redis.lpush('confirmed_queue', JSON.stringify(result.payload));
    await ctx.reply(
        `<b>재분석 접수</b>\nrequest_key: ${requestKey}\n규칙 기반 점수와 Claude 분석을 다시 진행합니다.`,
        { parse_mode: 'HTML' },
    );
});

const HELP_MESSAGE =
    `<b>StockMate AI 사용법</b>\n` +
    `<i>현재는 자동매매/계좌 주문 연동 없이 수동 판단 보조로 동작합니다.</i>\n\n` +
    `<b>1. 종목 평가</b>\n` +
    `/score 005930 - 기본 정밀 평가(DEEP)\n` +
    `/score 005930 fast - Claude 없이 빠른 규칙 평가\n` +
    `/score 005930 deep - Claude 포함 정밀 평가\n` +
    `/score 005930 refresh - 캐시 우회 후 재평가\n` +
    `/claude 005930 - /score deep 호환 명령\n` +
    `<i>FAST 결과는 ENTER가 아니라 ENTER_CANDIDATE로 보고 직접 확인합니다.</i>\n\n` +
    `<b>2. 뉴스/시장 브리핑</b>\n` +
    `/news - 캐시/구조화 facts 기반 no-AI 브리핑\n` +
    `/news refresh - 기본 no-AI 새로고침\n` +
    `/news deep - Claude 해석 포함 브리핑\n` +
    `/news deep refresh - Claude 포함 강제 재분석\n` +
    `/sector - 섹터/테마 상태\n` +
    `/events - 이번 주 주요 일정\n\n` +
    `<b>3. 신호/성과 조회</b>\n` +
    `/signals - 오늘 신호 목록\n` +
    `/perf - 오늘 전략별 통계\n` +
    `/track - 가상 손익 상세\n` +
    `/analysis - 전략 승률/수익률 분석\n` +
    `/history 005930 - 종목별 신호 이력\n` +
    `/quote 005930 - 실시간 시세/호가\n` +
    `/candidates [all|kospi|kosdaq] - 후보군 조회\n` +
    `/report - 오늘 신호 요약\n\n` +
    `<b>4. 개인 설정</b>\n` +
    `/settings - 내 알림 설정\n` +
    `/filter [s1~s16|all] - 받을 전략 필터\n` +
    `/watchAdd 005930 - 관심 종목 추가\n` +
    `/watchRemove 005930 - 관심 종목 제거\n\n` +
    `<b>5. 운영/점검</b>\n` +
    `/status - 시스템 상태\n` +
    `/errors - 시스템 경고/오류\n` +
    `/pause - 신호 일시정지\n` +
    `/resume - 신호 재개\n` +
    `/strategy s16 - 전략 수동 실행\n` +
    `/token - 키움 토큰 재발급\n` +
    `/wsStart / /wsStop - WebSocket 제어\n` +
    `/ping - 봇 응답 확인\n\n` +
    `<b>6. 전략 코드</b>\n` +
    `s1 갭상승 | s2 VI 눌림 | s3 기관+외국인\n` +
    `s4 장대양봉 | s5 프로그램+외국인 | s6 테마 후발\n` +
    `s7 일목 돌파 | s8 골든크로스 | s9 눌림 스윙\n` +
    `s10 신고가 | s11 외국인 연속 | s12 종가베팅\n` +
    `s13 박스돌파 | s14 과매도 반등 | s15 모멘텀 정렬\n` +
    `s16 세력 매집 의심/박스 돌파`;

/** /help */
const help = guard(async (ctx) => {
    await ctx.reply(HELP_MESSAGE, { parse_mode: 'HTML' });
    return;
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
        `/claude {code} – Claude AI 종합 분석\n` +
        `/candidates [market] – Candidate stocks\n` +
        `/report – Today's signal summary\n\n` +
        `<b>── News & Market ──</b>\n` +
        `/news – News analysis + trading status\n` +
        `/sector – Sector analysis\n` +
        `/events – This week's economic calendar\n\n` +
        `<b>── Personal Settings ──</b>\n` +
        `/settings – My notification settings\n` +
        `/filter [s1~s16|all] – Strategy filter\n` +
        `/watchAdd {code} – Add to watchlist\n` +
        `/watchRemove {code} – Remove from watchlist\n\n` +
        `<b>── System Control ──</b>\n` +
        `/pause – Pause trading signals\n` +
        `/resume – Resume trading (CONTINUE)\n` +
        `/errors – System error status\n` +
        `/strategy {s1~s16} – Run strategy manually\n` +
        `/token – Refresh Kiwoom token\n` +
        `/wsStart / /wsStop – WebSocket control\n` +
        `/status – System health check\n` +
        `/ping – Bot alive check\n\n` +
        `<b>── Strategies ──</b>\n` +
        `s1: Gap open | s2: VI pullback | s3: Inst+Frgn\n` +
        `s4: Big candle | s5: Prog+Frgn | s6: Theme laggard\n` +
        `s7: Auction | s8: Golden cross | s9: Pullback swing\n` +
        `s10: 52w New High | s11: Frgn cont | s12: Closing\n` +
        `s13: Box breakout | s14: Oversold bounce | s15: Momentum align\n` +
        `s16: Accumulation shadow\n` +
        `\n💡 /score works anytime (even outside trading hours)`,
        { parse_mode: 'HTML' }
    );
});

const signalsEnhanced = guard(async (ctx) => {
    const list = await kiwoom.getTodaySignals();
    if (!list || list.length === 0) {
        return ctx.reply('📭 오늘 발행된 신호 없음');
    }

    const statusCounts = list.reduce((acc, item) => {
        const key = item.signalStatus || 'UNKNOWN';
        acc[key] = (acc[key] ?? 0) + 1;
        return acc;
    }, {});
    const statusSummary = Object.entries(statusCounts)
        .map(([status, count]) => `${status}:${count}`)
        .join(' | ');
    const lines = list.slice(0, 10).map((s, i) => {
        const stockLabel = s.stkNm ? `${s.stkNm} (${s.stkCd})` : s.stkCd;
        const pnl = s.realizedPnl != null ? ` | P&L ${Number(s.realizedPnl).toFixed(2)}%` : '';
        return `${i + 1}. <b>${stockLabel}</b> [${s.strategy}] ${s.signalStatus} | 스코어: ${s.signalScore ?? '-'}${pnl}`;
    });

    await ctx.reply(
        `📋 <b>당일 신호</b>\n` +
        `총 ${list.length}건 | ${statusSummary}\n\n` +
        `${lines.join('\n')}` +
        `${list.length > 10 ? `\n\n...외 ${list.length - 10}건` : ''}`,
        { parse_mode: 'HTML' }
    );
});

const candidatesEnhanced = guard(async (ctx) => {
    const rawArg = parseCommandArgs(ctx.message?.text)[0];
    const marketInfo = parseCandidateMarket(rawArg);
    if (!marketInfo) {
        return ctx.reply('Usage: /candidates [all|kospi|kosdaq|000|001|101]');
    }

    const market = marketInfo.code;
    const [result, poolStatus] = await Promise.allSettled([
        kiwoom.searchCandidates({ market, limit: 20, sort: 'score' }),
        kiwoom.getCandidatePoolStatus(),
    ]);
    let data = result.status === 'fulfilled'
        ? {
            count: result.value.count ?? 0,
            codes: (result.value.candidates ?? []).map(item => item.stkCd),
            candidates: (result.value.candidates ?? []).map(item => ({
                code: item.stkCd,
                strategies: item.strategies,
                live: item.live,
                dataQuality: item.dataQuality,
                executionValidation: item.executionValidation,
            })),
        }
        : null;
    if (!data) {
        try {
            data = await kiwoom.getCandidates(market);
        } catch (_) {
            data = { candidates: [], codes: [], count: 0 };
        }
    }
    const withTags = (data.candidates ?? []).slice(0, 20);

    let lines;
    if (withTags.length > 0) {
        lines = withTags.map(({ code, strategies }) => {
            const tags = strategies && strategies.length > 0
                ? ` <i>[${dedupe([...strategies]).join(', ')}]</i>`
                : '';
            return `• <b>${code}</b>${tags}`;
        });
    } else {
        lines = (data.codes ?? []).slice(0, 20).map(code => `• <b>${code}</b>`);
    }

    const total = data.count ?? 0;
    const tagNote = withTags.some(c => c.strategies && c.strategies.length > 0)
        ? '\n<i>괄호 안은 오늘 후보군에 포착된 전략입니다.</i>'
        : '\n<i>후보군은 있으나 아직 전략 태그가 붙지 않았습니다.</i>';

    let poolLines = '';
    let poolSource = 'orchestrator';
    let ps = poolStatus.status === 'fulfilled' ? poolStatus.value : null;
    if (!ps) {
        try {
            ps = await kiwoom.getAiEngineCandidates();
            poolSource = 'ai-engine';
        } catch (_) {
            ps = null;
        }
    }

    if (ps) {
        const strategies = ['s1','s7','s8','s9','s10','s11','s12','s13','s14','s15','s16'];
        const rows = strategies.map((s) => {
            const exactKey = market === '101' ? `${s}_101` : (market === '001' ? `${s}_001` : null);
            if (exactKey && ps[exactKey] != null) return `  ${s.toUpperCase()}: ${ps[exactKey]}건`;
            const totalCount = (ps[`${s}_001`] ?? 0) + (ps[`${s}_101`] ?? 0);
            return `  ${s.toUpperCase()}: ${totalCount}건`;
        });
        const sourceTag = poolSource === 'ai-engine' ? ' <i>(ai-engine)</i>' : '';
        poolLines = `\n\n📊 <b>전략별 후보 수</b>${sourceTag}\n${rows.join('\n')}`;
    }

    await ctx.reply(
        `📋 <b>후보 종목 [${marketInfo.label}]</b>\n` +
        `총 ${total}개\n\n` +
        `${lines.join('\n')}` +
        `${total > 20 ? `\n...외 ${total - 20}개` : ''}` +
        `${tagNote}${poolLines}`,
        { parse_mode: 'HTML' }
    );
});

const quoteEnhanced = guard(async (ctx) => {
    const parsed = parseStockCodeArg(ctx, 'quote');
    if (!parsed.ok) return ctx.reply(parsed.message);

    const [tick, hoga] = await Promise.all([
        getTickData(parsed.stkCd),
        getHogaData(parsed.stkCd),
    ]);
    if (!tick || Object.keys(tick).length === 0) {
        return ctx.reply(`❓ ${parsed.stkCd} – No realtime data (WebSocket not subscribed or TTL expired)`);
    }

    const fluRt = tick.flu_rt ?? '-';
    const fluSign = Number(fluRt) > 0 ? '+' : '';
    const hogaSummary = buildHogaSummary(tick, hoga);
    const spread = (tick.ask_prc && tick.bid_prc
        ? `\n호가: ${Number(tick.bid_prc).toLocaleString()} / ${Number(tick.ask_prc).toLocaleString()}`
        : '') +
        (hogaSummary.bid != null && hogaSummary.ask != null
            ? `\n잔량: ${hogaSummary.bid.toLocaleString()} / ${hogaSummary.ask.toLocaleString()}`
            : '') +
        (hogaSummary.ratio != null
            ? `\n매수/매도: ${hogaSummary.ratio.toFixed(2)}`
            : '');

    await ctx.reply(
        `📈 <b>${parsed.stkCd} 실시간 시세</b>\n` +
        `현재가: <b>${Number(tick.cur_prc ?? 0).toLocaleString()}원</b>\n` +
        `등락륜: <b>${fluSign}${fluRt}%</b>\n` +
        `체결강도: ${tick.cntr_str ?? '-'}\n` +
        `누적거래량: ${Number(tick.acc_trde_qty ?? 0).toLocaleString()}\n` +
        `체결시간: ${tick.cntr_tm ?? '-'}${spread}`,
        { parse_mode: 'HTML' }
    );
});

const reportEnhanced = guard(async (ctx) => {
    const redis = getClient();
    const health = await kiwoom.health();
    const today = (health.business_date || '').replace(/-/g, '') || getKstBusinessDateCompact();
    const data = await redis.hgetall(`daily_summary:${today}`);

    if (!data || Object.keys(data).length === 0) {
        return sendOperationalReplies(ctx, 'report', '📊 오늘 데이터 없음');
    }

    let byStrategy = '-';
    try {
        const parsed = JSON.parse(data.by_strategy ?? '{}');
        const entries = Object.entries(parsed);
        if (entries.length > 0) {
            byStrategy = entries.map(([s, c]) => `  ${s}: ${c}건`).join('\n');
        }
    } catch (_) {
        byStrategy = data.by_strategy ?? '-';
    }

    const wins = data.total_wins != null ? Number(data.total_wins) : null;
    const losses = data.total_losses != null ? Number(data.total_losses) : null;
    const totalClosed = wins != null && losses != null ? wins + losses : null;
    const winRate = totalClosed ? ((wins / totalClosed) * 100).toFixed(0) : null;

    await sendOperationalReplies(ctx, 'report', {
        text:
        `📊 <b>오늘의 신호 리포트 (${today})</b>\n\n` +
        `총 신호: <b>${data.total_signals ?? '-'}</b>\n` +
        `평균 스코어: <b>${data.avg_score ?? '-'}</b>\n` +
        `${data.avg_pnl != null ? `평균 P&L: <b>${Number(data.avg_pnl).toFixed(2)}%</b>\n` : ''}` +
        `${wins != null && losses != null ? `승/패: <b>${wins}</b> / <b>${losses}</b>${winRate ? ` | 승률 <b>${winRate}%</b>` : ''}\n` : ''}` +
        `전략별\n${byStrategy}`,
        options: { parse_mode: 'HTML' },
    });
});

const filterEnhanced = guard(async (ctx) => {
    const redis = getClient();
    const chatId = String(ctx.chat.id);
    const args = parseCommandArgs(ctx.message?.text);
    const filterKey = `user_filter:${chatId}`;

    if (args.length === 0) {
        const current = await redis.get(filterKey);
        const parsed = current ? JSON.parse(current) : null;
        if (!parsed || parsed.length === 0) {
            return ctx.reply('🔍 현재 필터 없음 (모든 전략 수신 중)');
        }
        return ctx.reply(`🔍 현재 필터: ${parsed.join(', ')}`);
    }

    if (args[0].toLowerCase() === 'all') {
        await redis.del(filterKey);
        return ctx.reply('✅ Filter cleared - receiving all strategies');
    }

    const selected = expandStrategyFilterArgs(args);

    if (selected.length === 0) {
        return ctx.reply('❌ No valid strategy. e.g. /filter g04 or /filter s1 s4');
    }

    await redis.set(filterKey, JSON.stringify(selected));
    return ctx.reply(`✅ Filter set: ${selected.join(', ')}`);
});

const watchlistAddEnhanced = guard(async (ctx) => {
    const parsed = parseStockCodeArg(ctx, 'watchAdd');
    if (!parsed.ok) return ctx.reply(parsed.message);

    const redis = getClient();
    const chatId = String(ctx.chat.id);
    await redis.sadd(`watchlist:${chatId}`, parsed.stkCd);
    const members = (await redis.smembers(`watchlist:${chatId}`)).sort();
    await ctx.reply(`⭐Added to watchlist: <b>${parsed.stkCd}</b>\nCurrent: ${members.join(', ')}`, { parse_mode: 'HTML' });
});

const watchlistRemoveEnhanced = guard(async (ctx) => {
    const parsed = parseStockCodeArg(ctx, 'watchRemove');
    if (!parsed.ok) return ctx.reply(parsed.message);

    const redis = getClient();
    const chatId = String(ctx.chat.id);
    await redis.srem(`watchlist:${chatId}`, parsed.stkCd);
    const members = (await redis.smembers(`watchlist:${chatId}`)).sort();
    const listStr = members.length > 0 ? members.join(', ') : 'None (receiving all)';
    await ctx.reply(`🗑 Removed from watchlist: <b>${parsed.stkCd}</b>\nCurrent: ${listStr}`, { parse_mode: 'HTML' });
});

const userSettingsEnhanced = guard(async (ctx) => {
    const redis = getClient();
    const chatId = String(ctx.chat.id);
    const filterRaw = await redis.get(`user_filter:${chatId}`);
    const watchRaw = (await redis.smembers(`watchlist:${chatId}`)).sort();
    let selected = [];
    try {
        selected = filterRaw ? JSON.parse(filterRaw) : [];
    } catch (_) {}

    const message = [
        formatUserSettings(selected, watchRaw),
        '',
        '<b>Quick Actions</b>',
        '/filter all',
        '/filter s1 s4 s8',
        '/watchAdd 005930',
        '/watchRemove 005930',
    ].join('\n');

    await ctx.reply(message, { parse_mode: 'HTML' });
});

const signalHistoryEnhanced = guard(async (ctx) => {
    const parsed = parseStockCodeArg(ctx, 'history');
    if (!parsed.ok) return ctx.reply(parsed.message);

    const history = await kiwoom.getSignalHistory(parsed.stkCd);
    await ctx.reply(formatSignalHistory(parsed.stkCd, history), { parse_mode: 'HTML' });
});

module.exports = {
    ping, status, signals: signalsEnhanced, performance,
    candidates: candidatesEnhanced, quote: quoteEnhanced, runStrategy,
    refreshToken, wsStart, wsStop, help,
    report: reportEnhanced, filter: filterEnhanced,
    newsStatus, sectorStatus, signalHistory: signalHistoryEnhanced, strategyAnalysis, systemErrors,
    pauseTrading, resumeTrading, calendarEvents, performanceDetail,
    watchlistAdd: watchlistAddEnhanced, watchlistRemove: watchlistRemoveEnhanced, userSettings: userSettingsEnhanced,
    scoreStock, claudeAnalyze, confirmPending, reanalyzeConfirm,
    isAllowed,
};
