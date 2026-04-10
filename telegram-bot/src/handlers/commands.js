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
        logger.warn('Claude 사용량 조회 실패', { error: e.message });
        return { calls: 0, tokens: 0 };
    }
}

/** /status */
const status = guard(async (ctx) => {
    const h = await kiwoom.health();
    const usage = await getClaudeUsage();
    const maxCalls = Number(process.env.MAX_CLAUDE_CALLS_PER_DAY ?? 100);

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
        const strategies = ['s1','s7','s8','s9','s10','s11','s12','s13','s14','s15'];
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
        s7:  'S7_AUCTION',         s8:  'S8_GOLDEN_CROSS',
        s9:  'S9_PULLBACK_SWING',  s10: 'S10_NEW_HIGH',
        s11: 'S11_FRGN_CONT',      s12: 'S12_CLOSING',
        s13: 'S13_BOX_BREAKOUT',   s14: 'S14_OVERSOLD_BOUNCE',
        s15: 'S15_MOMENTUM_ALIGN',
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
 * /score {종목코드} — 15전략 심사 + 규칙/AI 스코어링
 * S1~S15 전략 조건을 실시간 데이터 기반으로 경량 심사 후
 * 매칭 전략별 규칙점수 + Claude AI 점수를 계산하여 결과 반환.
 *
 * 전략 미매칭 → "전략없음" 반환
 * 매칭 → 전략별 신호 카드 (formatSignal 포맷) 순서대로 전송
 */
const scoreStock = guard(async (ctx) => {
    const args  = ctx.message.text.split(' ');
    const stkCd = args[1]?.trim();
    if (!stkCd) return ctx.reply('Usage: /score 005930');
    if (!/^\d{6}$/.test(stkCd)) return ctx.reply('❌ 종목코드는 6자리 숫자입니다. 예: /score 005930');

    await ctx.reply(
        `🔍 <b>${stkCd}</b> 전략 심사 중...\nS1~S15 조건 체크 + AI 스코어링 (최대 60초 소요)`,
        { parse_mode: 'HTML' },
    );

    let d;
    try {
        d = await kiwoom.scoreStockFull(stkCd);
    } catch (e) {
        return ctx.reply(`❌ ai-engine 심사 실패: ${e.message}`);
    }

    // 데이터 수집 자체 실패 (토큰 없음 등)
    if (d.skipped && d.skipped.length === 1 && d.skipped[0].includes('데이터 수집 실패')) {
        return ctx.reply(
            `❓ <b>${stkCd}</b> – 데이터 조회 불가\n` +
            `Kiwoom 토큰 유효성 또는 ai-engine 연결을 확인하세요.\n` +
            `사유: ${d.skipped[0]}`,
            { parse_mode: 'HTML' },
        );
    }

    const messages = formatStockScore(d);

    // 메시지 배열 순서대로 전송 (전략없음은 1건)
    for (const msg of messages) {
        if (msg && msg.trim()) {
            await ctx.reply(msg, { parse_mode: 'HTML' });
        }
    }
});

/**
 * /claude {종목코드} — Claude AI 종목 종합 분석
 * ai-engine /analyze/{code} 엔드포인트 호출 → 기술적 분석 + 전략 후보 풀 정보 + Claude 의견
 */
const claudeAnalyze = guard(async (ctx) => {
    const args  = ctx.message.text.split(' ');
    const stkCd = args[1]?.trim();
    if (!stkCd) return ctx.reply('Usage: /claude 005930');
    if (!/^\d{6}$/.test(stkCd)) return ctx.reply('❌ 종목코드는 6자리 숫자입니다. 예: /claude 005930');

    await ctx.reply(`🔍 <b>${stkCd}</b> Claude 분석 중... (최대 30초 소요)`, { parse_mode: 'HTML' });

    let d;
    try {
        d = await kiwoom.analyzeStockWithClaude(stkCd);
    } catch (e) {
        return ctx.reply(`❌ ai-engine 분석 실패: ${e.message}`);
    }

    if (d.error && !d.claude_analysis) {
        return ctx.reply(`❌ 분석 오류: ${d.error}`);
    }

    const stk_nm = d.stk_nm || stkCd;
    const curPrc = Number(d.cur_prc ?? 0);
    const fluRt  = Number(d.flu_rt ?? 0);
    const fluSign = fluRt > 0 ? '+' : '';

    // 후보 풀 전략 목록
    const pools = (d.strategies_in_pool || []);
    const poolStr = pools.length > 0
        ? pools.map(s => `  • ${s}`).join('\n')
        : '  (현재 후보 풀에 없음)';

    // 기술지표 요약
    const ma5  = d.ma5  ? `${Number(d.ma5).toLocaleString()}원`  : 'N/A';
    const ma20 = d.ma20 ? `${Number(d.ma20).toLocaleString()}원` : 'N/A';
    const ma60 = d.ma60 ? `${Number(d.ma60).toLocaleString()}원` : 'N/A';
    const rsi  = d.rsi14 != null ? `${d.rsi14}` : 'N/A';
    const bbU  = d.bb_upper ? `${Number(d.bb_upper).toLocaleString()}` : 'N/A';
    const bbL  = d.bb_lower ? `${Number(d.bb_lower).toLocaleString()}` : 'N/A';

    const header =
        `🤖 <b>Claude 종목 분석 — ${stk_nm}(${stkCd})</b>\n\n` +
        `💰 현재가: <b>${curPrc.toLocaleString()}원</b>  <b>${fluSign}${fluRt}%</b>\n\n` +
        `📊 <b>전략 후보 풀</b>\n${poolStr}\n\n` +
        `📈 <b>기술지표 요약</b>\n` +
        `MA5: ${ma5} | MA20: ${ma20} | MA60: ${ma60}\n` +
        `RSI(14): ${rsi} | BB: ${bbL} ~ ${bbU}\n` +
        `──────────────────────\n`;

    const analysis = d.claude_analysis || '분석 결과 없음';

    // Telegram 메시지 4096자 제한 — 길면 분할 전송
    const full = header + analysis;
    if (full.length <= 4096) {
        await ctx.reply(full, { parse_mode: 'HTML' });
    } else {
        await ctx.reply(header, { parse_mode: 'HTML' });
        // 분석 텍스트는 HTML 태그 없이 일반 텍스트로 분할 전송
        const chunks = [];
        for (let i = 0; i < analysis.length; i += 4000) {
            chunks.push(analysis.slice(i, i + 4000));
        }
        for (const chunk of chunks) {
            await ctx.reply(chunk);
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
        `/claude {code} – Claude AI 종합 분석\n` +
        `/candidates [market] – Candidate stocks\n` +
        `/report – Today's signal summary\n\n` +
        `<b>── News & Market ──</b>\n` +
        `/news – News analysis + trading status\n` +
        `/sector – Sector analysis\n` +
        `/events – This week's economic calendar\n\n` +
        `<b>── Personal Settings ──</b>\n` +
        `/settings – My notification settings\n` +
        `/filter [s1~s15|all] – Strategy filter\n` +
        `/watchAdd {code} – Add to watchlist\n` +
        `/watchRemove {code} – Remove from watchlist\n\n` +
        `<b>── System Control ──</b>\n` +
        `/pause – Pause trading signals\n` +
        `/resume – Resume trading (CONTINUE)\n` +
        `/errors – System error status\n` +
        `/strategy {s1~s15} – Run strategy manually\n` +
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
    scoreStock, claudeAnalyze,
    isAllowed,
};
