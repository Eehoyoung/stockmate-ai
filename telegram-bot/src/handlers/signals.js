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
const { formatThreadsSignal, formatThreadsBriefing, computeThreadsRR } = require('../utils/threads_formatter');
const threads = require('../services/threads');
const { getLogger } = require('../utils/logger');

const logger = getLogger('signals');

const POLL_INTERVAL_MS = Number(process.env.POLL_INTERVAL_MS ?? 2000);
const MIN_AI_SCORE = Number(process.env.MIN_AI_SCORE ?? 62);
const HOLD_MIN_SCORE = 80;
const MAX_SIGNALS_PER_MIN = Number(process.env.MAX_SIGNALS_PER_MIN ?? 20);
const VALID_SIGNAL_STAGES = new Set(['WATCH', 'HOLD', 'ENTRY', 'CANCEL']);
const THREADS_ENABLED = process.env.THREADS_ENABLED === 'true';
const THREADS_MIN_MARKET_CAP_EOK = Number(process.env.THREADS_MIN_MARKET_CAP_EOK ?? 1000);
// 내부 엔진 min_rr 하한(1.45)에 근접하는 Threads 전용 공개 게시 차단 기준
const THREADS_MIN_RR = Number(process.env.THREADS_MIN_RR ?? 1.3);
// Threads 게시 전 관리자 미리보기용 채팅 (THREADS_ENABLED 무관하게 동작)
const THREADS_PREVIEW_CHAT_ID = process.env.TELEGRAM_THREADS_CHAT_ID || null;
const USER_SEND_DEDUP_TTL_SEC = Number(process.env.USER_SEND_DEDUP_TTL_SEC ?? 7 * 24 * 60 * 60);
const STATUS_SEND_DEDUP_TTL_SEC = Number(process.env.STATUS_SEND_DEDUP_TTL_SEC ?? 36 * 60 * 60);

let _signalCount = 0;
let _windowStart = Date.now();

/** 시가총액 1,000억 미만 소형주 필터 (Threads 전용, 억 단위 비교).
 *  시가총액 정보가 없으면 보수적으로 차단(true) — fail-safe 설계. */
function _isLowLiquidityStock(item) {
    const capEok = item.market_cap_eok != null
        ? Number(item.market_cap_eok)
        : (item.market_cap != null ? Number(item.market_cap) / 1e8 : null);
    if (capEok === null || capEok <= 0) return true;  // 시가총액 정보 없음 → 차단
    return capEok < THREADS_MIN_MARKET_CAP_EOK;
}

function _shouldPostToThreads(action, isRuleOnly) {
    if (!THREADS_ENABLED) return false;
    if (!process.env.THREADS_USER_ID || !process.env.THREADS_APP_ID) return false;
    return action === 'ENTER' || isRuleOnly;
}

function _shouldPostBriefingToThreads(type) {
    if (!THREADS_ENABLED) return false;
    if (!process.env.THREADS_USER_ID || !process.env.THREADS_APP_ID) return false;
    return type === 'STATUS_REPORT' || type === 'MIDDAY_REPORT';
}

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

function normalizeSignalStage(stage) {
    const normalized = String(stage || '').trim().toUpperCase();
    return VALID_SIGNAL_STAGES.has(normalized) ? normalized : null;
}

function getEffectiveAction(item) {
    const decision = String(item.execution_decision || '').trim().toUpperCase();
    if (decision === 'ENTER') return 'ENTER';
    if (decision === 'WATCH') return 'HOLD';
    if (decision === 'BLOCK') return 'CANCEL';
    const stage = normalizeSignalStage(item.signal_stage);
    if (stage === 'ENTRY') return 'ENTER';
    if (stage === 'WATCH' || stage === 'HOLD') return 'HOLD';
    if (stage === 'CANCEL') return 'CANCEL';
    return item.action;
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

function _stablePart(value, fallback = 'unknown') {
    const normalized = String(value ?? '').trim();
    return normalized || fallback;
}

function _stableDatePart(item) {
    const raw = item.business_date || item.trade_date || item.date || item.report_date || item.created_at || item.timestamp;
    if (raw) {
        const value = String(raw).trim();
        const dateMatch = value.match(/\d{4}-\d{2}-\d{2}/);
        if (dateMatch) return dateMatch[0];
        return value.slice(0, 10);
    }
    return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).format(new Date());
}

function _statusLogicalSlot(item) {
    return _stablePart(
        item.logical_slot || item.slot || item.slot_name || item.brief_slot || item.report_slot || item.session,
        'default'
    ).toUpperCase();
}

function _sellExitType(item) {
    return _stablePart(item.exit_type || item.recommendation_type || item.sell_type, 'UNKNOWN').toUpperCase();
}

function _fallbackSellIdentity(item) {
    return [
        item.position_id,
        item.trade_id,
        item.order_id,
        item.stk_cd,
        item.strategy,
        item.entry_price,
        item.exit_price || item.cur_prc,
        item.realized_pnl_pct,
    ].map((value) => _stablePart(value)).join(':');
}

function buildUserSendDedupKey(item) {
    if (item.type === 'SELL_SIGNAL' || item.type === 'SELL_RECOMMENDATION') {
        const eventType = _stablePart(item.event_type || item.type, item.type).toUpperCase();
        const exitType = _sellExitType(item);
        const identity = _stablePart(item.signal_id || item.signalId, _fallbackSellIdentity(item));
        return `telegram:user-send:sell:${identity}:${eventType}:${exitType}`;
    }
    if (item.type === 'STATUS_REPORT' || item.type === 'MIDDAY_REPORT') {
        return `telegram:user-send:status:${_stableDatePart(item)}:${_statusLogicalSlot(item)}`;
    }
    return null;
}

async function _claimUserSend(key, ttlSec = USER_SEND_DEDUP_TTL_SEC) {
    if (!key) return true;
    try {
        const result = await getClient().set(key, String(Date.now()), 'EX', ttlSec, 'NX');
        return result === 'OK';
    } catch (e) {
        logger.warn('user send dedup unavailable; sending without claim', { dedup_key: key, error: e.message });
        return true;
    }
}

async function _releaseUserSend(key) {
    if (!key) return;
    try {
        const client = getClient();
        if (typeof client.del === 'function') await client.del(key);
    } catch (e) {
        logger.warn('user send dedup release failed', { dedup_key: key, error: e.message });
    }
}

function getRecipientGroup(chatIds, explicitGroup) {
    if (explicitGroup) return explicitGroup;
    if (chatIds) return 'primary';
    return 'allowed';
}

function stripPersonaLines(text) {
    return String(text || '')
        .split(/\r?\n/)
        .filter((line) => {
            const normalized = line
                .replace(/<[^>]+>/g, '')
                .replace(/[^\p{L}\p{N}:：+\s]/gu, '')
                .trim()
                .toLowerCase();
            return !normalized.startsWith('페르소나:')
                && !normalized.startsWith('페르소나：')
                && !normalized.startsWith('persona:')
                && !normalized.startsWith('persona：');
        })
        .join('\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

async function _broadcast(bot, { type, text, logLabel, logMeta = {}, extraOpts = {}, chatIds = null, recipientGroup = null }) {
    const targetChatIds = chatIds || getAllowedChatIds();
    const options = { parse_mode: 'HTML', disable_web_page_preview: true, ...extraOpts };
    const displayText = stripPersonaLines(text);
    const deliveryMeta = {
        recipient_group: getRecipientGroup(chatIds, recipientGroup),
        chat_ids: targetChatIds,
    };
    let sentCount = 0;
    let failedCount = 0;

    for (const chatId of targetChatIds) {
        try {
            await bot.telegram.sendMessage(chatId, displayText, options);
            sentCount++;
        } catch (e) {
            failedCount++;
            logger.error(`${type} send failed`, { chat_id: chatId, ...deliveryMeta, ...logMeta }, e);
        }
    }
    logger.info(`${logLabel || type} sent`, {
        ...deliveryMeta,
        sent_count: sentCount,
        failed_count: failedCount,
        ...logMeta,
    });
    return { sentCount, failedCount };
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
            const dedupKey = buildUserSendDedupKey(item);
            const dedupTtlSec = (item.type === 'STATUS_REPORT' || item.type === 'MIDDAY_REPORT')
                ? STATUS_SEND_DEDUP_TTL_SEC
                : USER_SEND_DEDUP_TTL_SEC;
            const claimed = await _claimUserSend(dedupKey, dedupTtlSec);
            if (!claimed) {
                logger.info('duplicate user-facing broadcast skipped', {
                    type: item.type,
                    dedup_key: dedupKey,
                    slot: item.slot || item.slot_name || item.brief_slot || item.report_slot,
                    signal_id: item.signal_id || item.signalId,
                    exit_type: item.exit_type || item.recommendation_type || item.sell_type,
                });
                return;
            }

            const result = await _broadcast(bot, payload);
            if (dedupKey && result.sentCount === 0) {
                await _releaseUserSend(dedupKey);
            }
            // Threads 브리핑 동시 발행 (STATUS_REPORT / MIDDAY_REPORT, fire-and-forget)
            if (_shouldPostBriefingToThreads(item.type)) {
                const threadsText = formatThreadsBriefing(item);
                threads.postText(threadsText).catch((e) =>
                    logger.error('threads briefing post failed', { type: item.type }, e)
                );
            }
            // Threads 브리핑 관리자 미리보기 (THREADS_ENABLED 무관)
            if (THREADS_PREVIEW_CHAT_ID && (item.type === 'STATUS_REPORT' || item.type === 'MIDDAY_REPORT')) {
                const previewText = '[Threads 미리보기 — 브리핑]\n\n' + formatThreadsBriefing(item);
                bot.telegram.sendMessage(THREADS_PREVIEW_CHAT_ID, previewText, {
                    disable_web_page_preview: true,
                }).catch((e) => logger.error('threads briefing preview failed', { type: item.type }, e));
            }
            return;
        }
    }

    const { ai_score } = item;
    const signalStage = normalizeSignalStage(item.signal_stage);
    const action = getEffectiveAction(item);
    const isRuleOnly = item.signal_grade === 'RULE_ONLY'
        || item.validation_stage === 'RULE_ONLY'
        || item.type === 'RULE_ONLY_SIGNAL';
    if (!isRuleOnly && String(item.execution_decision || '').toUpperCase() !== 'ENTER') {
        logger.info('non-enter execution decision skipped', {
            stk_cd: item.stk_cd,
            strategy: item.strategy,
            execution_decision: item.execution_decision,
            action,
        });
        return;
    }
    if (isRuleOnly) {
        logger.info('rule-only signal suppressed from user delivery', {
            stk_cd: item.stk_cd,
            strategy: item.strategy,
        });
        return;
    }
    if (action === 'CANCEL' || signalStage === 'CANCEL') return;
    if (action === 'ENTER' && !isRuleOnly && ai_score < MIN_AI_SCORE) {
        logger.info('below score threshold', { stk_cd: item.stk_cd, strategy: item.strategy, score: ai_score });
        return;
    }
    if ((action === 'HOLD' || signalStage === 'HOLD') && ai_score < HOLD_MIN_SCORE) return;

    if (!_checkRateLimit()) {
        logger.warn('rate limit exceeded', {
            stk_cd: item.stk_cd,
            strategy: item.strategy,
            max_per_min: MAX_SIGNALS_PER_MIN,
        });
        return;
    }

    const chatIds = isRuleOnly ? getPrimaryChatIds() : getAllowedChatIds();
    if (chatIds.length === 0) {
        logger.warn(isRuleOnly ? 'TELEGRAM_PRIMARY_CHAT_ID is empty' : 'TELEGRAM_ALLOWED_CHAT_IDS is empty');
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
                action: isRuleOnly && action === 'ENTER' ? 'ENTER_RULE_ONLY' : action,
                score: ai_score,
            });
        } catch (e) {
            logger.error('signal send failed', { chat_id: chatId, stk_cd: item.stk_cd }, e);
        }
    }

    // Threads 동시 발행 (ENTER + RULE_ONLY만, fire-and-forget)
    if (_shouldPostToThreads(action, isRuleOnly)) {
        const entryPrice = Number(item.cur_prc ?? item.entry_price ?? 0);
        const tp1Price   = Number(item.claude_tp1 ?? item.tp1_price ?? 0);
        const slPrice    = Number(item.claude_sl  ?? item.sl_price  ?? 0);
        const rr = computeThreadsRR(item.stk_cd, entryPrice, tp1Price, slPrice);

        // rr === null: TP/SL 데이터 없는 신호 → 필터 적용 불가이므로 통과 허용 (의도적 설계)
        if (rr !== null && rr < THREADS_MIN_RR) {
            logger.info('threads post skipped: R:R below threshold', {
                stk_cd: item.stk_cd, strategy: item.strategy,
                rr: rr.toFixed(2), threshold: THREADS_MIN_RR,
            });
        } else if (_isLowLiquidityStock(item)) {
            logger.info('threads post skipped: low liquidity stock', {
                stk_cd: item.stk_cd, market_cap_eok: item.market_cap_eok,
            });
        } else {
            const threadsText = formatThreadsSignal(item);
            threads.postText(threadsText).catch((e) =>
                logger.error('threads post failed', {
                    stk_cd:   item.stk_cd,
                    strategy: item.strategy,
                    score:    ai_score,
                }, e)
            );
        }
    }

    // Threads 신호 관리자 미리보기 (THREADS_ENABLED 무관, ENTER + RULE_ONLY만)
    if (THREADS_PREVIEW_CHAT_ID && (action === 'ENTER' || isRuleOnly)) {
        const entryPrice = Number(item.cur_prc ?? item.entry_price ?? 0);
        const tp1Price   = Number(item.claude_tp1 ?? item.tp1_price ?? 0);
        const slPrice    = Number(item.claude_sl  ?? item.sl_price  ?? 0);
        const rr = computeThreadsRR(item.stk_cd, entryPrice, tp1Price, slPrice);

        let filterNote = '통과';
        if (rr !== null && rr < THREADS_MIN_RR) {
            filterNote = `차단 (R:R ${rr.toFixed(2)} < ${THREADS_MIN_RR})`;
        } else if (_isLowLiquidityStock(item)) {
            filterNote = `차단 (시총 ${item.market_cap_eok ?? '?'}억 < ${THREADS_MIN_MARKET_CAP_EOK}억)`;
        }

        const previewText = `[Threads 미리보기 — ${filterNote}]\n\n` + formatThreadsSignal(item);
        bot.telegram.sendMessage(THREADS_PREVIEW_CHAT_ID, previewText, {
            disable_web_page_preview: true,
        }).catch((e) => logger.error('threads preview send failed', {
            stk_cd: item.stk_cd, strategy: item.strategy,
        }, e));
    }
}

async function startPolling(bot) {
    if (THREADS_ENABLED) {
        threads.startTokenRefreshScheduler();
    }
    logger.info('ai_scored_queue polling started', {
        interval_ms:     POLL_INTERVAL_MS,
        min_score:       MIN_AI_SCORE,
        max_per_min:     MAX_SIGNALS_PER_MIN,
        threads_enabled: THREADS_ENABLED,
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

module.exports = {
    startPolling,
    startConfirmPoller,
    stripPersonaLines,
    processItem,
    buildUserSendDedupKey,
};
