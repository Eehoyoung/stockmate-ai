'use strict';

const assert = require('assert');
const path = require('path');

const signalsPath = path.resolve(__dirname, '../src/handlers/signals.js');
const redisPath = path.resolve(__dirname, '../src/services/redis.js');
const formatterPath = path.resolve(__dirname, '../src/utils/formatter.js');
const threadsFormatterPath = path.resolve(__dirname, '../src/utils/threads_formatter.js');
const threadsPath = path.resolve(__dirname, '../src/services/threads.js');
const loggerPath = path.resolve(__dirname, '../src/utils/logger.js');
const confirmGatePath = path.resolve(__dirname, '../src/handlers/confirmGate.js');

function loadSignals() {
    [
        signalsPath,
        redisPath,
        formatterPath,
        threadsFormatterPath,
        threadsPath,
        loggerPath,
        confirmGatePath,
    ].forEach((modulePath) => delete require.cache[modulePath]);

    const redisState = {
        values: new Map(),
        setCalls: [],
        delCalls: [],
    };
    const logs = [];

    const redisClient = {
        set: async (key, value, exFlag, ttlSec, nxFlag) => {
            redisState.setCalls.push({ key, value, exFlag, ttlSec, nxFlag });
            if (nxFlag === 'NX' && redisState.values.has(key)) return null;
            redisState.values.set(key, value);
            return 'OK';
        },
        del: async (key) => {
            redisState.delCalls.push(key);
            redisState.values.delete(key);
            return 1;
        },
        get: async () => null,
        smembers: async () => [],
    };

    require.cache[redisPath] = {
        id: redisPath,
        filename: redisPath,
        loaded: true,
        exports: { getClient: () => redisClient, popScoredQueue: async () => null },
    };
    require.cache[formatterPath] = {
        id: formatterPath,
        filename: formatterPath,
        loaded: true,
        exports: {
            formatSignal: () => 'signal',
            formatForceClose: () => 'force-close',
            formatDailyReportEnhanced: () => 'daily-report',
            formatSellSignal: (item) => `sell:${item.signal_id || item.stk_cd}:${item.exit_type}`,
            formatSellRecommendation: (item) => `sell-rec:${item.signal_id || item.stk_cd}:${item.recommendation_type || item.exit_type}`,
            formatNewsAlert: () => 'news',
            formatHoldWatch: (item) => `hold-watch:${item.stk_cd}:${item.hold_reason}`,
            formatHoldReleased: (item) => `hold-released:${item.stk_cd}:${item.release_reason}`,
        },
    };
    require.cache[threadsFormatterPath] = {
        id: threadsFormatterPath,
        filename: threadsFormatterPath,
        loaded: true,
        exports: {
            formatThreadsSignal: () => 'threads-signal',
            formatThreadsBriefing: () => 'threads-briefing',
            computeThreadsRR: () => 2,
        },
    };
    require.cache[threadsPath] = {
        id: threadsPath,
        filename: threadsPath,
        loaded: true,
        exports: {
            postText: async () => ({ id: 'post' }),
            startTokenRefreshScheduler: () => {},
        },
    };
    require.cache[loggerPath] = {
        id: loggerPath,
        filename: loggerPath,
        loaded: true,
        exports: {
            getLogger: () => ({
                info: (message, meta) => logs.push({ level: 'info', message, meta }),
                warn: (message, meta) => logs.push({ level: 'warn', message, meta }),
                error: (message, meta, error) => logs.push({ level: 'error', message, meta, error }),
            }),
        },
    };
    require.cache[confirmGatePath] = {
        id: confirmGatePath,
        filename: confirmGatePath,
        loaded: true,
        exports: { startConfirmPoller: () => {} },
    };

    process.env.TELEGRAM_ALLOWED_CHAT_IDS = '100,200';
    process.env.TELEGRAM_PRIMARY_CHAT_ID = '900';
    delete process.env.THREADS_ENABLED;
    delete process.env.TELEGRAM_THREADS_CHAT_ID;

    const sends = [];
    const bot = {
        telegram: {
            sendMessage: async (chatId, text, options) => {
                sends.push({ chatId: String(chatId), text, options });
                return { message_id: sends.length };
            },
        },
    };

    return { signals: require(signalsPath), redisState, logs, sends, bot };
}

async function test(name, fn) {
    try {
        await fn();
        console.log(`  OK ${name}`);
    } catch (err) {
        console.error(`  FAIL ${name}`);
        console.error(err);
        process.exitCode = 1;
    }
}

(async () => {
    await test('deduplicates duplicate SELL_SIGNAL sends by signal id, event type, and exit type', async () => {
        const { signals, redisState, sends, bot } = loadSignals();
        const item = {
            type: 'SELL_SIGNAL',
            signal_id: 'sig-123',
            event_type: 'EXIT_EXECUTED',
            exit_type: 'TP1_HIT',
            stk_cd: '005930',
            strategy: 's1',
        };

        await signals.processItem(bot, item);
        await signals.processItem(bot, { ...item, realized_pnl_pct: 3.1 });

        assert.strictEqual(sends.length, 2);
        assert.strictEqual(redisState.setCalls[0].key, 'telegram:user-send:sell:sig-123:EXIT_EXECUTED:TP1_HIT');
        assert.strictEqual(redisState.setCalls.length, 2);
    });

    await test('uses a stable fallback key when SELL_SIGNAL has no signal id', async () => {
        const { signals, sends, bot } = loadSignals();
        const item = {
            type: 'SELL_SIGNAL',
            exit_type: 'SL_HIT',
            stk_cd: '000660',
            strategy: 's2',
            entry_price: 100000,
            exit_price: 97000,
            realized_pnl_pct: -3,
        };

        const key = signals.buildUserSendDedupKey(item);
        assert(key.includes('000660'));
        assert(key.endsWith(':SELL_SIGNAL:SL_HIT'));

        await signals.processItem(bot, item);
        await signals.processItem(bot, { ...item, message: 'same logical event' });

        assert.strictEqual(sends.length, 2);
    });

    await test('deduplicates STATUS_REPORT by logical slot', async () => {
        const { signals, redisState, sends, bot } = loadSignals();
        const item = {
            type: 'STATUS_REPORT',
            business_date: '2026-05-22',
            slot: 'MORNING',
            message: 'status body v1',
        };

        await signals.processItem(bot, item);
        await signals.processItem(bot, { ...item, message: 'status body v2' });

        assert.strictEqual(sends.length, 1);
        assert.strictEqual(sends[0].chatId, '900');
        assert.strictEqual(redisState.setCalls[0].key, 'telegram:user-send:status:2026-05-22:MORNING');
    });

    await test('routes SYSTEM_ALERT only to primary chats', async () => {
        const { signals, sends, bot } = loadSignals();

        await signals.processItem(bot, {
            type: 'SYSTEM_ALERT',
            message: '[시스템 경고] test',
        });

        assert.deepStrictEqual(sends.map(({ chatId }) => chatId), ['900']);
    });

    await test('deduplicates HOLD_WATCH sends by stock+strategy identity', async () => {
        const { signals, redisState, sends, bot } = loadSignals();
        const item = {
            type: 'HOLD_WATCH',
            stk_cd: '005930',
            strategy: 's9',
            hold_reason: 'rr below threshold',
        };

        await signals.processItem(bot, item);
        await signals.processItem(bot, { ...item, hold_reason: 'rr below threshold (recheck)' });

        // HOLD_WATCH goes only to TELEGRAM_PRIMARY_CHAT_ID ('900'), not the full allowed-chat broadcast list.
        assert.strictEqual(sends.length, 1);
        assert.strictEqual(sends[0].chatId, '900');
        assert.strictEqual(redisState.setCalls[0].key, 'telegram:user-send:hold-watch:005930:s9');
        assert.strictEqual(redisState.setCalls.length, 2);
    });

    await test('HOLD_RELEASED uses its own dedup namespace distinct from HOLD_WATCH', async () => {
        const { signals, sends, bot } = loadSignals();
        const watchItem = { type: 'HOLD_WATCH', stk_cd: '000660', strategy: 's8', hold_reason: 'watching' };
        const releaseItem = { type: 'HOLD_RELEASED', stk_cd: '000660', strategy: 's8', release_reason: 'timed out' };

        await signals.processItem(bot, watchItem);
        await signals.processItem(bot, releaseItem);

        // 1 chat (primary) x 2 distinct notice types = 2 sends.
        assert.strictEqual(sends.length, 2);
    });

    if (process.exitCode) process.exit(process.exitCode);
})();
