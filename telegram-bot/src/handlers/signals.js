'use strict';

/**
 * handlers/signals.js
 * ai_scored_queue 를 주기적으로 폴링하여 조건에 맞는 신호를 텔레그램으로 자동 발송
 *
 * 발송 조건:
 *   - action == 'ENTER'
 *   - ai_score >= MIN_AI_SCORE (환경변수)
 * 관망(HOLD) 신호는 스코어가 높을 때만 별도 알림
 * 취소(CANCEL) 신호는 발송하지 않음
 */

const { popScoredQueue, getClient }        = require('../services/redis');
const { formatSignal, formatForceClose }   = require('../utils/formatter');

const POLL_INTERVAL_MS  = Number(process.env.POLL_INTERVAL_MS  ?? 2000);
const MIN_AI_SCORE      = Number(process.env.MIN_AI_SCORE      ?? 65);
const HOLD_MIN_SCORE    = 80;   // HOLD 신호는 80점 이상만 알림
const MAX_SIGNALS_PER_MIN = Number(process.env.MAX_SIGNALS_PER_MIN ?? 10); // 분당 최대 발송

// 분당 발송 횟수 추적
let _signalCount = 0;
let _signalWindowStart = Date.now();

function _checkRateLimit() {
    const now = Date.now();
    if (now - _signalWindowStart >= 60_000) {
        _signalCount = 0;
        _signalWindowStart = now;
    }
    if (_signalCount >= MAX_SIGNALS_PER_MIN) {
        console.warn(`[Signal] 분당 발송 한도 초과 (${_signalCount}/${MAX_SIGNALS_PER_MIN}) – 건너뜀`);
        return false;
    }
    _signalCount++;
    return true;
}

/**
 * 허용된 채팅 ID 목록 반환
 */
function getAllowedChatIds() {
    return (process.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
}

/**
 * 채팅 ID별 전략 필터 확인
 * @param {string} chatId
 * @param {string} strategy
 * @returns {Promise<boolean>} true = 발송 허용
 */
async function isAllowedByFilter(chatId, strategy) {
    try {
        const raw = await getClient().get(`user_filter:${chatId}`);
        if (!raw) return true; // 필터 없음 → 전부 허용
        const filterList = JSON.parse(raw);
        if (!filterList || filterList.length === 0) return true;
        return filterList.includes(strategy);
    } catch (e) {
        console.error('[Signal] 필터 확인 오류:', e.message);
        return true; // 오류 시 허용
    }
}

/**
 * 단일 항목 처리 – 조건 판단 후 텔레그램 발송
 */
async function processItem(bot, item) {
    const { action, ai_score } = item;

    // DAILY_REPORT 타입은 무조건 발송
    if (item.type === 'DAILY_REPORT') {
        const chatIds = getAllowedChatIds();
        const lines = [
            `📊 <b>일일 신호 리포트 (${item.date ?? ''})</b>`,
            `총 신호: ${item.total_signals ?? 0}건`,
            `평균 스코어: ${typeof item.avg_score === 'number' ? item.avg_score.toFixed(1) : '-'}점`,
        ];
        if (item.by_strategy) {
            const byStr = typeof item.by_strategy === 'object'
                ? Object.entries(item.by_strategy).map(([s, c]) => `  ${s}: ${c}건`).join('\n')
                : String(item.by_strategy);
            lines.push(`전략별:\n${byStr}`);
        }
        const msg = lines.join('\n');
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, msg, { parse_mode: 'HTML', disable_web_page_preview: true });
            } catch (e) {
                console.error(`[Signal] 리포트 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        return;
    }

    // FORCE_CLOSE 타입은 action/score 무관하게 발송
    if (item.type === 'FORCE_CLOSE') {
        const chatIds = getAllowedChatIds();
        const message = formatForceClose(item);
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, {
                    parse_mode: 'HTML',
                    disable_web_page_preview: true,
                });
            } catch (e) {
                console.error(`[Signal] 강제청산 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        return;
    }

    // CANCEL 이거나 스코어 미달 → 무시
    if (action === 'CANCEL') return;
    if (action === 'ENTER' && ai_score < MIN_AI_SCORE) {
        console.log(`[Signal] 스코어 미달 무시 [${item.stk_cd} ${item.strategy}] score=${ai_score}`);
        return;
    }
    if (action === 'HOLD' && ai_score < HOLD_MIN_SCORE) return;

    const chatIds = getAllowedChatIds();
    if (chatIds.length === 0) {
        console.warn('[Signal] TELEGRAM_ALLOWED_CHAT_IDS 미설정 – 발송 건너뜀');
        return;
    }

    const message = formatSignal(item);

    for (const chatId of chatIds) {
        // 사용자별 전략 필터 확인
        const allowed = await isAllowedByFilter(chatId, item.strategy);
        if (!allowed) {
            console.log(`[Signal] 필터로 건너뜀 chatId=${chatId} strategy=${item.strategy}`);
            continue;
        }
        // 분당 발송 한도 확인
        if (!_checkRateLimit()) continue;

        try {
            await bot.telegram.sendMessage(chatId, message, {
                parse_mode:               'HTML',
                disable_web_page_preview: true,
            });
            console.log(`[Signal] 발송 완료 → chatId=${chatId} [${item.stk_cd} ${item.strategy}] action=${action} score=${ai_score}`);
        } catch (e) {
            console.error(`[Signal] 발송 실패 chatId=${chatId}:`, e.message);
        }
    }
}

/**
 * 폴링 루프 시작
 * @param {import('telegraf').Telegraf} bot
 */
async function startPolling(bot) {
    console.log(`[Signal] ai_scored_queue 폴링 시작 (interval=${POLL_INTERVAL_MS}ms, minScore=${MIN_AI_SCORE})`);

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
            console.error('[Signal] 폴링 오류:', e.message);
        }

        // 빈 큐 연속 시 간격 점진 증가 (최대 10초)
        const nextDelay = () => {
            if (emptyCount === 0) return POLL_INTERVAL_MS;
            return Math.min(POLL_INTERVAL_MS * (1 + emptyCount * 0.1), 10_000);
        };

        setTimeout(poll, nextDelay());
    };

    setTimeout(poll, POLL_INTERVAL_MS);
}

module.exports = { startPolling };
