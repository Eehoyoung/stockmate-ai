'use strict';

const assert = require('assert');
const path = require('path');

const commandsPath = path.join(__dirname, '../src/handlers/commands.js');
const redisPath = path.join(__dirname, '../src/services/redis.js');
const kiwoomPath = path.join(__dirname, '../src/services/kiwoom.js');
const formatterPath = path.join(__dirname, '../src/utils/formatter.js');
const loggerPath = path.join(__dirname, '../src/utils/logger.js');
const confirmStorePath = path.join(__dirname, '../src/services/confirmStore.js');

function buildCommands(overrides = {}) {
    delete require.cache[commandsPath];
    delete require.cache[redisPath];
    delete require.cache[kiwoomPath];
    delete require.cache[formatterPath];
    delete require.cache[loggerPath];
    delete require.cache[confirmStorePath];

    const redisState = {
        kv: new Map(),
        sets: new Map(),
        ticks: overrides.ticks || {},
        hogas: overrides.hogas || {},
        hashes: overrides.hashes || {},
    };
    const logs = [];

    const redisClient = {
        get: async (key) => redisState.kv.get(key) ?? null,
        set: async (key, value) => { redisState.kv.set(key, value); },
        del: async (key) => { redisState.kv.delete(key); },
        sadd: async (key, value) => {
            const set = redisState.sets.get(key) || new Set();
            set.add(value);
            redisState.sets.set(key, set);
        },
        srem: async (key, value) => {
            const set = redisState.sets.get(key) || new Set();
            set.delete(value);
            redisState.sets.set(key, set);
        },
        smembers: async (key) => [...(redisState.sets.get(key) || new Set())],
        hgetall: async (key) => redisState.hashes[key] || {},
    };

    require.cache[redisPath] = {
        id: redisPath,
        filename: redisPath,
        loaded: true,
        exports: {
            getClient: () => redisClient,
            getTickData: async (stkCd) => redisState.ticks[stkCd] || {},
            getHogaData: async (stkCd) => redisState.hogas[stkCd] || {},
        },
    };

    require.cache[kiwoomPath] = {
        id: kiwoomPath,
        filename: kiwoomPath,
        loaded: true,
        exports: {
            getTodaySignals: async () => overrides.todaySignals || [],
            getTodayStats: async () => overrides.todayStats || [],
            getCandidates: async () => overrides.candidates || { candidates: [], codes: [], count: 0 },
            getCandidatePoolStatus: async () => overrides.poolStatus || null,
            getAiEngineCandidates: async () => overrides.aiPoolStatus || null,
            getSignalHistory: async () => overrides.signalHistory || [],
            health: async () => overrides.health || ({ status: 'UP', service: 'ok', business_date: '2026-04-30' }),
            getSignalPerformance: async () => overrides.performanceSignals || [],
            getPerformanceSummary: async () => overrides.performanceSummary || [],
            getStrategyAnalysis: async () => overrides.strategyAnalysis || [],
            getLiveNewsBrief: async () => overrides.liveNewsBrief || null,
            analyzeStockWithClaude: async () => overrides.claudeAnalysis || { error: 'missing mock' },
        },
    };

    require.cache[formatterPath] = {
        id: formatterPath,
        filename: formatterPath,
        loaded: true,
        exports: {
            formatDailySummary: (stats) => `daily:${stats.length}`,
            formatPerformanceSummary: (rows) => `analysis:${rows.length}`,
            formatNewsStatus: () => 'news',
            formatSectorAnalysis: () => 'sector',
            formatSignalHistory: (stkCd, rows) => `history:${stkCd}:${rows.length}`,
            formatSystemHealth: () => 'health',
            formatCalendarWeek: () => 'calendar',
            formatPerformanceDetail: () => 'track',
            formatUserSettings: (filter, watchlist) => `settings:${filter.length}:${watchlist.length}`,
            formatStockScore: () => ['score'],
        },
    };

    require.cache[loggerPath] = {
        id: loggerPath,
        filename: loggerPath,
        loaded: true,
        exports: {
            getLogger: () => ({
                info(message, meta) { logs.push({ level: 'info', message, meta }); },
                warn(message, meta) { logs.push({ level: 'warn', message, meta }); },
                error(message, meta, error) { logs.push({ level: 'error', message, meta, error }); },
            }),
        },
    };

    require.cache[confirmStorePath] = {
        id: confirmStorePath,
        filename: confirmStorePath,
        loaded: true,
        exports: {
            buildReanalysisPayload: async () => ({ ok: false }),
            getConfirmRequest: async () => null,
            listActiveConfirmRequests: async () => [],
        },
    };

    const commands = require(commandsPath);
    return { commands, redisState, logs };
}

function createCtx(text, chatId = 100) {
    const replies = [];
    return {
        chat: { id: chatId },
        message: { text },
        reply: async (message) => { replies.push(message); },
        replies,
    };
}

let passCount = 0;
let failCount = 0;

async function test(name, fn) {
    try {
        await fn();
        passCount++;
        console.log(`  OK ${name}`);
    } catch (error) {
        failCount++;
        console.log(`  FAIL ${name}`);
        console.log(`    Error: ${error.message}`);
    }
}

function assertDeliveryLog(logs, message, chatId, sentCount = 1, failedCount = 0) {
    const entry = logs.find((log) => log.level === 'info' && log.message === message);
    assert.ok(entry, `${message} log should exist`);
    assert.strictEqual(entry.meta.recipient_group, 'request_chat');
    assert.deepStrictEqual(entry.meta.chat_ids, [String(chatId)]);
    assert.strictEqual(entry.meta.sent_count, sentCount);
    assert.strictEqual(entry.meta.failed_count, failedCount);
}

(async () => {
    console.log('\ncommands.js tests');

    await test('/signals includes summary and pnl', async () => {
        const { commands } = buildCommands({
            todaySignals: [
                { stkCd: '005930', stkNm: 'Samsung Electronics', strategy: 'S1_GAP_OPEN', signalStatus: 'SENT', signalScore: 78.5, realizedPnl: 1.23 },
                { stkCd: '000660', strategy: 'S8_GOLDEN_CROSS', signalStatus: 'WIN', signalScore: 81.0 },
            ],
        });
        const ctx = createCtx('/signals');
        await commands.signals(ctx);
        assert.ok(ctx.replies[0].includes('2'));
        assert.ok(ctx.replies[0].includes('Samsung Electronics (005930)'));
        assert.ok(ctx.replies[0].includes('P&L 1.23%'));
    });

    await test('/candidates rejects unsupported market', async () => {
        const { commands } = buildCommands();
        const ctx = createCtx('/candidates nyse');
        await commands.candidates(ctx);
        assert.strictEqual(ctx.replies[0], 'Usage: /candidates [all|kospi|kosdaq|000|001|101]');
    });

    await test('/quote rejects invalid code', async () => {
        const { commands } = buildCommands();
        const ctx = createCtx('/quote 5930');
        await commands.quote(ctx);
        assert.ok(ctx.replies[0].includes('6'));
    });

    await test('/quote includes hoga balance and ratio', async () => {
        const { commands } = buildCommands({
            ticks: {
                '005930': {
                    cur_prc: 84300,
                    flu_rt: 1.25,
                    cntr_str: 138,
                    acc_trde_qty: 1234567,
                    cntr_tm: '091500',
                    bid_prc: 84200,
                    ask_prc: 84300,
                },
            },
            hogas: {
                '005930': {
                    total_buy_bid_req: 880000,
                    total_sel_bid_req: 550000,
                },
            },
        });
        const ctx = createCtx('/quote 005930');
        await commands.quote(ctx);
        assert.ok(ctx.replies[0].includes('84,200 / 84,300'));
        assert.ok(ctx.replies[0].includes('880,000 / 550,000'));
        assert.ok(ctx.replies[0].includes('1.60'));
    });

    await test('/filter removes duplicates', async () => {
        const { commands, redisState } = buildCommands();
        const ctx = createCtx('/filter s1 s1 s4');
        await commands.filter(ctx);
        const saved = JSON.parse(redisState.kv.get('user_filter:100'));
        assert.deepStrictEqual(saved, ['S1_GAP_OPEN', 'S4_BIG_CANDLE']);
    });

    await test('/watchAdd rejects invalid code', async () => {
        const { commands } = buildCommands();
        const ctx = createCtx('/watchAdd ABC');
        await commands.watchlistAdd(ctx);
        assert.ok(ctx.replies[0].includes('6'));
    });

    await test('/history rejects invalid code', async () => {
        const { commands } = buildCommands();
        const ctx = createCtx('/history 12');
        await commands.signalHistory(ctx);
        assert.ok(ctx.replies[0].includes('6'));
    });

    await test('/settings includes quick actions', async () => {
        const { commands, redisState } = buildCommands();
        redisState.kv.set('user_filter:100', JSON.stringify(['S1_GAP_OPEN']));
        redisState.sets.set('watchlist:100', new Set(['005930']));
        const ctx = createCtx('/settings');
        await commands.userSettings(ctx);
        assert.ok(ctx.replies[0].includes('Quick Actions'));
        assert.ok(ctx.replies[0].includes('/watchAdd 005930'));
    });

    await test('/news uses fixed layout when structured brief is available', async () => {
        const { commands } = buildCommands({
            liveNewsBrief: {
                slot_name: 'MIDDAY',
                used_cached_analysis: true,
                analysis: {
                    trading_control: 'CAUTIOUS',
                    market_sentiment: 'NEUTRAL',
                    midday_index_commentary: 'KOSPI is holding gains while KOSDAQ is rebounding from the morning low.',
                    midday_sectors: ['Semiconductors', 'Defense'],
                    urgent_news: ['US yields are stable overnight', 'KRW softens slightly against USD'],
                    afternoon_outlook: 'If semiconductors hold, the afternoon can grind higher.',
                    risk_factors: ['Foreign selling can return after 14:00'],
                    summary: 'Bias stays constructive, but chasing strength is still risky.',
                },
            },
        });
        const ctx = createCtx('/news');
        await commands.newsStatus(ctx);
        assert.ok(ctx.replies[0].length > 0);
        assert.ok(ctx.replies[1].includes('12:30'));
        assert.ok(ctx.replies[1].includes('현재 국장'));
        assert.ok(ctx.replies[1].includes('주요 섹터'));
        assert.ok(ctx.replies[1].includes('영향 뉴스'));
        assert.ok(ctx.replies[1].includes('한 줄 결론'));
    });

    await test('/status writes operational delivery log', async () => {
        const { commands, logs } = buildCommands();
        const ctx = createCtx('/status', 430);
        await commands.status(ctx);
        assert.ok(ctx.replies[0].length > 0);
        assertDeliveryLog(logs, 'status sent', 430);
    });

    await test('/news writes operational delivery log with chat id counts', async () => {
        const { commands, logs } = buildCommands({
            liveNewsBrief: { message: 'live-news' },
        });
        const ctx = createCtx('/news', 431);
        await commands.newsStatus(ctx);
        assert.strictEqual(ctx.replies.length, 2);
        const entries = logs.filter((log) => log.level === 'info' && log.message === 'news sent');
        assert.strictEqual(entries.length, 2);
        for (const entry of entries) {
            assert.strictEqual(entry.meta.recipient_group, 'request_chat');
            assert.deepStrictEqual(entry.meta.chat_ids, ['431']);
            assert.strictEqual(entry.meta.sent_count, 1);
            assert.strictEqual(entry.meta.failed_count, 0);
        }
    });

    await test('/report writes 20260430 operational delivery log', async () => {
        const { commands, logs } = buildCommands({
            hashes: {
                'daily_summary:20260430': {
                    total_signals: '3',
                    avg_score: '78.5',
                    by_strategy: JSON.stringify({ S1_GAP_OPEN: 2, S8_GOLDEN_CROSS: 1 }),
                },
            },
        });
        const ctx = createCtx('/report', 432);
        await commands.report(ctx);
        assert.ok(ctx.replies[0].includes('20260430'));
        assertDeliveryLog(logs, 'report sent', 432);
    });

    await test('/claude renders structured action output', async () => {
        const { commands } = buildCommands({
            claudeAnalysis: {
                stk_cd: '005930',
                stk_nm: 'Samsung Electronics',
                action: 'ENTER',
                confidence: 'HIGH',
                cur_prc: 84300,
                flu_rt: 1.25,
                cntr_str: 138.2,
                strategies_in_pool: ['S1_GAP_OPEN', 'S8_GOLDEN_CROSS'],
                daily_indicators: { ma5: 82000, ma20: 80100, ma60: 76000, rsi14: 61.2, atr_pct: 2.31 },
                minute_indicators: { tic_scope: '5', rsi14: 67.4, macd: 12.345, macd_signal: 10.222, stoch_k: 82.1, stoch_d: 76.4, atr_pct: 0.91 },
                hoga: { total_buy_bid_req: 880000, total_sel_bid_req: 550000, buy_to_sell_ratio: 1.6, best_bid: 84200, best_ask: 84300 },
                reasons: ['Minute momentum remains positive', 'Order-book stays buy-side dominant'],
                risk_factors: ['Intraday volatility can expand quickly'],
                action_guide: ['Scale in only after a pullback near 84300'],
                tp_sl: { take_profit: 87200, stop_loss: 82900 },
                summary: 'Short-term trend and order book both favor an entry.',
            },
        });
        const ctx = createCtx('/claude 005930');
        await commands.claudeAnalyze(ctx);
        assert.ok(ctx.replies[1].includes('진입 우세'));
        assert.ok(ctx.replies[1].includes('포트폴리오 연동'));
        assert.ok(ctx.replies[1].includes('TP / SL'));
        assert.ok(ctx.replies[1].includes('호가 요약'));
    });

    console.log(`\nResults: ${passCount} passed, ${failCount} failed`);
    if (failCount > 0) process.exit(1);
})();
