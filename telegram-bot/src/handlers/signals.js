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

const { popScoredQueue, getClient }                          = require('../services/redis');
const { formatSignal, formatForceClose, formatDailyReportEnhanced } = require('../utils/formatter');

const POLL_INTERVAL_MS = Number(process.env.POLL_INTERVAL_MS ?? 2000);
const MIN_AI_SCORE     = Number(process.env.MIN_AI_SCORE     ?? 65);
const HOLD_MIN_SCORE   = 80;  // HOLD 신호는 80점 이상만 알림

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
 * 관심 종목 필터 확인 (watchlist)
 * watchlist가 비어있으면 모든 종목 허용
 * @param {string} chatId
 * @param {string} stkCd
 * @returns {Promise<boolean>} true = 발송 허용
 */
async function isAllowedByWatchlist(chatId, stkCd) {
    try {
        const watchlist = await getClient().smembers(`watchlist:${chatId}`);
        if (!watchlist || watchlist.length === 0) return true; // 관심목록 없음 → 전부 허용
        return watchlist.includes(stkCd);
    } catch (e) {
        console.error('[Signal] watchlist 확인 오류:', e.message);
        return true; // 오류 시 허용
    }
}

/**
 * 단일 항목 처리 – 조건 판단 후 텔레그램 발송
 */
async function processItem(bot, item) {
    const { action, ai_score } = item;

    // PAUSE_CONFIRM_REQUEST – AI가 PAUSE를 권고했으나 사용자 컨펌 필요
    if (item.type === 'PAUSE_CONFIRM_REQUEST') {
        const chatIds = getAllowedChatIds();
        const sentimentLabel = { BULLISH: '강세 📈', BEARISH: '약세 📉', NEUTRAL: '중립 ➡️' };
        const sentiment = sentimentLabel[item.market_sentiment] || item.market_sentiment || '-';
        const riskLines = (item.risk_factors || []).map((r) => `• ${r}`).join('\n');
        const message = [
            '⚠️ <b>[매매 중단 권고]</b>',
            '',
            'AI 뉴스 분석 결과 매매 중단이 권고되었습니다.',
            `시장 심리: ${sentiment}`,
            item.summary ? `요약: ${item.summary}` : null,
            riskLines ? `리스크:\n${riskLines}` : null,
            '',
            '매매를 중단하시겠습니까?',
        ].filter((l) => l !== null).join('\n');

        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, {
                    parse_mode: 'HTML',
                    reply_markup: {
                        inline_keyboard: [[
                            { text: '✅ 확인 (중단)', callback_data: 'confirm_pause' },
                            { text: '❌ 취소',        callback_data: 'cancel_pause'  },
                        ]],
                    },
                });
            } catch (e) {
                console.error(`[Signal] PAUSE_CONFIRM_REQUEST 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        console.log('[Signal] PAUSE_CONFIRM_REQUEST 발송 완료');
        return;
    }

    // NEWS_ALERT 타입 처리 – 뉴스 기반 매매 제어 변경 알림
    if (item.type === 'NEWS_ALERT') {
        const chatIds = getAllowedChatIds();
        const message = item.message || formatNewsAlert(item);
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, {
                    parse_mode: 'HTML',
                    disable_web_page_preview: true,
                });
            } catch (e) {
                console.error(`[Signal] 뉴스 알림 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        console.log(`[Signal] NEWS_ALERT 발송 완료 control=${item.trading_control}`);
        return;
    }

    // CALENDAR_ALERT – 경제 이벤트 임박/모닝 브리핑 (Feature 2)
    if (item.type === 'CALENDAR_ALERT') {
        const chatIds = getAllowedChatIds();
        const message = item.message || `📅 [경제 캘린더] ${item.event_name || ''}`;
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, { parse_mode: 'HTML', disable_web_page_preview: true });
            } catch (e) {
                console.error(`[Signal] CALENDAR_ALERT 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        console.log(`[Signal] CALENDAR_ALERT 발송 완료 subtype=${item.subtype}`);
        return;
    }

    // SECTOR_OVERHEAT – 섹터 과열 경고 (Feature 4)
    if (item.type === 'SECTOR_OVERHEAT') {
        const chatIds = getAllowedChatIds();
        const message = item.message || `⚠️ [섹터 과열] ${item.sector || ''} ${item.count || ''}건`;
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, { parse_mode: 'HTML', disable_web_page_preview: true });
            } catch (e) {
                console.error(`[Signal] SECTOR_OVERHEAT 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        console.log(`[Signal] SECTOR_OVERHEAT 발송 완료 sector=${item.sector} count=${item.count}`);
        return;
    }

    // SYSTEM_ALERT – 시스템 경고 (Feature 5)
    if (item.type === 'SYSTEM_ALERT') {
        const chatIds = getAllowedChatIds();
        const message = item.message || `🔧 [시스템 경고]\n${(item.alerts || []).join('\n')}`;
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, { parse_mode: 'HTML', disable_web_page_preview: true });
            } catch (e) {
                console.error(`[Signal] SYSTEM_ALERT 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        console.log(`[Signal] SYSTEM_ALERT 발송 완료 alerts=${(item.alerts || []).length}건`);
        return;
    }

    // MARKET_OPEN_BRIEF – 09:01 장시작 브리핑
    if (item.type === 'MARKET_OPEN_BRIEF') {
        const chatIds = getAllowedChatIds();
        const message = item.message || '📢 장시작 브리핑';
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, { parse_mode: 'HTML', disable_web_page_preview: true });
            } catch (e) {
                console.error(`[Signal] MARKET_OPEN_BRIEF 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        console.log('[Signal] MARKET_OPEN_BRIEF 발송 완료');
        return;
    }

    // MIDDAY_REPORT – 12:30 오전 중간 보고
    if (item.type === 'MIDDAY_REPORT') {
        const chatIds = getAllowedChatIds();
        const message = item.message || '📊 오전 신호 현황';
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, message, { parse_mode: 'HTML', disable_web_page_preview: true });
            } catch (e) {
                console.error(`[Signal] MIDDAY_REPORT 발송 실패 chatId=${chatId}:`, e.message);
            }
        }
        console.log('[Signal] MIDDAY_REPORT 발송 완료');
        return;
    }

    // DAILY_REPORT 타입 – 가상 P&L 포함 향상된 포맷으로 발송
    if (item.type === 'DAILY_REPORT') {
        const chatIds = getAllowedChatIds();
        const msg = formatDailyReportEnhanced(item);
        for (const chatId of chatIds) {
            try {
                await bot.telegram.sendMessage(chatId, msg, { parse_mode: 'HTML', disable_web_page_preview: true });
            } catch (e) {
                console.error(`[Signal] 리포트 발송 실패 chatId=${chatId}:`, e.message);
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

    // 강제청산 알림
    const message = item.type === 'FORCE_CLOSE'
        ? formatForceClose(item)
        : formatSignal(item);

    for (const chatId of chatIds) {
        // 1. 전략 필터 확인
        const allowed = await isAllowedByFilter(chatId, item.strategy);
        if (!allowed) {
            console.log(`[Signal] 전략 필터로 건너뜀 chatId=${chatId} strategy=${item.strategy}`);
            continue;
        }

        // 2. 관심 종목 필터 확인 (watchlist가 있을 때 해당 종목만 발송)
        const watchAllowed = await isAllowedByWatchlist(chatId, item.stk_cd);
        if (!watchAllowed) {
            console.log(`[Signal] 관심목록 필터로 건너뜀 chatId=${chatId} stk_cd=${item.stk_cd}`);
            continue;
        }

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

/**
 * NEWS_ALERT 메시지 포맷 (Java 측에서 message 필드가 없을 경우 폴백)
 */
function formatNewsAlert(item) {
    const controlEmoji = { PAUSE: '🚨', CAUTIOUS: '⚠️', CONTINUE: '✅' };
    const controlLabel = { PAUSE: '매매 중단', CAUTIOUS: '신중 매매', CONTINUE: '정상 매매' };
    const sentimentLabel = { BULLISH: '강세 📈', BEARISH: '약세 📉', NEUTRAL: '중립 ➡️' };

    const ctrl = item.trading_control || 'CONTINUE';
    const emoji = controlEmoji[ctrl] || '📰';
    const lines = [
        `${emoji} <b>[뉴스 기반 매매 제어]</b>`,
        `상태: <b>${controlLabel[ctrl] || ctrl}</b>`,
        `시장심리: ${sentimentLabel[item.market_sentiment] || item.market_sentiment || '-'}`,
    ];
    if (item.sectors && item.sectors.length > 0) {
        lines.push(`추천섹터: ${item.sectors.join(', ')}`);
    }
    if (item.summary) {
        lines.push(`요약: ${item.summary}`);
    }
    return lines.join('\n');
}

module.exports = { startPolling };
