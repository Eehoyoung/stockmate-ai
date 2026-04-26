'use strict';

const { popScoredQueue, getClient } = require('../services/redis');
const {
    formatSignal,
    formatForceClose,
    formatDailyReportEnhanced,
    formatSellSignal,
    formatSellRecommendation,
    formatNewsAlert,
} = require('../utils/formatter');
const { getLogger } = require('../utils/logger');

const logger = getLogger('signals');

const POLL_INTERVAL_MS = Number(process.env.POLL_INTERVAL_MS ?? 2000);
const MIN_AI_SCORE = Number(process.env.MIN_AI_SCORE ?? 65);
const HOLD_MIN_SCORE = 80;
const MAX_SIGNALS_PER_MIN = Number(process.env.MAX_SIGNALS_PER_MIN ?? 20);

let _signalCount = 0;
let _windowStart = Date.now();

function _checkRateLimit() {
    const now = Date.now();
    if (now - _windowStart >= 60_000) {
        _signalCount = 0;
        _windowStart = now;
    }
    if (_signalCount >= MAX_SIGNALS_PER_MIN) return false;
    _signalCount++;
    return true;
}

function getAllowedChatIds() {
    return (process.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
}

function getPrimaryChatIds() {
    return String(process.env.TELEGRAM_PRIMARY_CHAT_ID ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
}

async function isAllowedByFilter(chatId, strategy) {
    try {
        const raw = await getClient().get(`user_filter:${chatId}`);
        if (!raw) return true;
        const filterList = JSON.parse(raw);
        if (!filterList || filterList.length === 0) return true;
        return filterList.includes(strategy);
    } catch (e) {
        logger.error('filter check failed', {}, e);
        return true;
    }
}

async function isAllowedByWatchlist(chatId, stkCd) {
    try {
        const watchlist = await getClient().smembers(`watchlist:${chatId}`);
        if (!watchlist || watchlist.length === 0) return true;
        return watchlist.includes(stkCd);
    } catch (e) {
        logger.error('watchlist check failed', {}, e);
        return true;
    }
}

async function _broadcast(bot, { type, text, logLabel, logMeta = {}, extraOpts = {}, chatIds = null }) {
    const targetChatIds = chatIds || getAllowedChatIds();
    const options = { parse_mode: 'HTML', disable_web_page_preview: true, ...extraOpts };
    for (const chatId of targetChatIds) {
        try {
            await bot.telegram.sendMessage(chatId, text, options);
        } catch (e) {
            logger.error(`${type} send failed`, { chat_id: chatId, ...logMeta }, e);
        }
    }
    logger.info(`${logLabel || type} sent`, logMeta);
}

function _statusReportPayload(item) {
    const msg = String(item.message || '');
    return {
        type: 'STATUS_REPORT',
        chatIds: getPrimaryChatIds(),
        text: msg || '전략 상태 브리핑',
    };
}

const BROADCAST_HANDLERS = {
    PAUSE_CONFIRM_REQUEST: (item) => {
        const sentimentLabel = { BULLISH: '강세', BEARISH: '약세', NEUTRAL: '중립' };
        const sentiment = sentimentLabel[item.market_sentiment] || item.market_sentiment || '-';
        const riskLines = (item.risk_factors || []).map((r) => `- ${r}`).join('\n');
        const text = [
            '⛔ <b>[매매 중단 권고]</b>',
            '',
            'AI 분석 결과 매매 중단이 권고되었습니다.',
            `시장 분위기: ${sentiment}`,
            item.summary ? `요약: ${item.summary}` : null,
            riskLines ? `리스크\n${riskLines}` : null,
            '',
            '매매를 중단하시겠습니까?',
        ].filter((line) => line !== null).join('\n');
        return {
            type: 'PAUSE_CONFIRM_REQUEST',
            logLabel: 'PAUSE_CONFIRM_REQUEST',
            text,
            extraOpts: {
                disable_web_page_preview: false,
                reply_markup: {
                    inline_keyboard: [[
                        { text: '확인 (중단)', callback_data: 'confirm_pause' },
                        { text: '취소', callback_data: 'cancel_pause' },
                    ]],
                },
            },
        };
    },

    NEWS_ALERT: () => null,

    SCHEDULED_NEWS_BRIEF: (item) => ({
        type: 'SCHEDULED_NEWS_BRIEF',
        text: item.message || formatNewsAlert(item),
        logMeta: { slot: item.slot },
    }),

    CALENDAR_ALERT: () => null,

    SECTOR_OVERHEAT: (item) => ({
        type: 'SECTOR_OVERHEAT',
        text: item.message || `[섹터 과열] ${item.sector || ''} ${item.count || ''}건`,
        logMeta: { sector: item.sector, count: item.count },
    }),

    SYSTEM_ALERT: (item) => ({
        type: 'SYSTEM_ALERT',
        text: item.message || `[시스템 경고]\n${(item.alerts || []).join('\n')}`,
        logMeta: { alerts: (item.alerts || []).length },
    }),

    PRE_MARKET_BRIEF: () => null,
    MARKET_OPEN_BRIEF: () => null,

    STATUS_REPORT: (item) => _statusReportPayload(item),
    MIDDAY_REPORT: (item) => {
        const msg = String(item.message || '');
        if (!msg.includes('전략 상태 브리핑')) {
            return null;
        }
        return _statusReportPayload(item);
    },

    SELL_SIGNAL: (item) => ({
        type: 'SELL_SIGNAL',
        text: formatSellSignal(item),
        logMeta: {
            stk_cd: item.stk_cd,
            strategy: item.strategy,
            exit_type: item.exit_type,
            pnl: item.realized_pnl_pct,
        },
    }),

    SELL_RECOMMENDATION: (item) => ({
        type: 'SELL_RECOMMENDATION',
        text: formatSellRecommendation(item),
        logMeta: {
            stk_cd: item.stk_cd,
            strategy: item.strategy,
            recommendation_type: item.recommendation_type || item.exit_type || item.sell_type,
            partial: item.partial,
            urgent: item.urgent,
            pnl: item.realized_pnl_pct,
        },
    }),

    OVERNIGHT_HOLD: (item) => ({
        type: 'OVERNIGHT_HOLD',
        text: item.message || `[오버나이트 확인] [${item.strategy}] ${item.stk_cd}`,
        logMeta: { stk_cd: item.stk_cd, strategy: item.strategy, score: item.overnight_final },
    }),

    DAILY_REPORT: (item) => ({
        type: 'DAILY_REPORT',
        chatIds: getPrimaryChatIds(),
        text: formatDailyReportEnhanced(item),
    }),
};

async function processItem(bot, item) {
    const handler = BROADCAST_HANDLERS[item.type];
    if (handler) {
        const payload = handler(item);
        if (payload) {
            await _broadcast(bot, payload);
            return;
        }
    }

    const { action, ai_score } = item;
    const isRuleOnly = item.signal_grade === 'RULE_ONLY'
        || item.validation_stage === 'RULE_ONLY'
        || item.type === 'RULE_ONLY_SIGNAL';
    if (action === 'CANCEL') return;
    if (action === 'ENTER' && !isRuleOnly && ai_score < MIN_AI_SCORE) {
        logger.info('below score threshold', { stk_cd: item.stk_cd, strategy: item.strategy, score: ai_score });
        return;
    }
    if (action === 'HOLD' && ai_score < HOLD_MIN_SCORE) return;

    if (!_checkRateLimit()) {
        logger.warn('rate limit exceeded', {
            stk_cd: item.stk_cd,
            strategy: item.strategy,
            max_per_min: MAX_SIGNALS_PER_MIN,
        });
        return;
    }

    const chatIds = getAllowedChatIds();
    if (chatIds.length === 0) {
        logger.warn('TELEGRAM_ALLOWED_CHAT_IDS is empty');
        return;
    }

    const message = item.type === 'FORCE_CLOSE'
        ? formatForceClose(item)
        : formatSignal(item);

    for (const chatId of chatIds) {
        const allowed = await isAllowedByFilter(chatId, item.strategy);
        if (!allowed) {
            logger.info('filtered by strategy', { chat_id: chatId, strategy: item.strategy });
            continue;
        }
        const watchAllowed = await isAllowedByWatchlist(chatId, item.stk_cd);
        if (!watchAllowed) {
            logger.info('filtered by watchlist', { chat_id: chatId, stk_cd: item.stk_cd });
            continue;
        }
        try {
            await bot.telegram.sendMessage(chatId, message, {
                parse_mode: 'HTML',
                disable_web_page_preview: true,
            });
            logger.info('signal sent', {
                chat_id: chatId,
                stk_cd: item.stk_cd,
                strategy: item.strategy,
                action,
                score: ai_score,
            });
        } catch (e) {
            logger.error('signal send failed', { chat_id: chatId, stk_cd: item.stk_cd }, e);
        }
    }
}

async function startPolling(bot) {
    logger.info('ai_scored_queue polling started', {
        interval_ms: POLL_INTERVAL_MS,
        min_score: MIN_AI_SCORE,
        max_per_min: MAX_SIGNALS_PER_MIN,
    });

    let emptyCount = 0;

    const poll = async () => {
        try {
            const item = await popScoredQueue();
            if (item) {
                emptyCount = 0;
                await processItem(bot, item);
            } else {
                emptyCount++;
            }
        } catch (e) {
            logger.error('polling error', {}, e);
        }

        const nextDelay = emptyCount === 0
            ? POLL_INTERVAL_MS
            : Math.min(POLL_INTERVAL_MS * (1 + emptyCount * 0.1), 10_000);

        setTimeout(poll, nextDelay);
    };

    setTimeout(poll, POLL_INTERVAL_MS);
}

const { startConfirmPoller } = require('./confirmGate');

module.exports = { startPolling, startConfirmPoller };
