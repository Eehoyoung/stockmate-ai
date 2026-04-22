'use strict';

const { getClient } = require('../services/redis');
const { markConfirmRequestSent } = require('../services/confirmStore');
const { getLogger } = require('../utils/logger');
const { normalizeForDisplay } = require('../utils/price');

const logger = getLogger('confirmGate');

const CONFIRM_POLL_INTERVAL_MS = Number(process.env.CONFIRM_POLL_INTERVAL_MS ?? 2000);

function isConfirmGateEnabled() {
    return false;
}

function resolveChatIds(allowedChatIds = []) {
    if (allowedChatIds.length > 0) return allowedChatIds;
    return String(process.env.TELEGRAM_CHAT_ID ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
}

function formatKst(dateLike) {
    if (!dateLike) return '-';
    return new Intl.DateTimeFormat('ko-KR', {
        timeZone: 'Asia/Seoul',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(new Date(dateLike));
}

async function sendConfirmRequest(bot, allowedChatIds, item) {
    const requestKey = item.confirm_request_key
        ? String(item.confirm_request_key)
        : item.id
            ? String(item.id)
            : `${item.stk_cd || 'unk'}:${item.strategy || 'unk'}`;
    const stkCd = item.stk_cd || '-';
    const stkNm = item.stk_nm || '';
    const strategy = item.strategy || '-';
    const ruleScore = typeof item.rule_score === 'number' ? item.rule_score.toFixed(1) : (item.rule_score || '-');
    const message = item.message || `[${strategy}] ${stkCd}`;

    const curPrc = normalizeForDisplay(item.cur_prc ?? item.entry_price ?? 0);
    const tp1 = item.tp1_price ? normalizeForDisplay(item.tp1_price) : null;
    const tp2 = item.tp2_price ? normalizeForDisplay(item.tp2_price) : null;
    const sl = item.sl_price ? normalizeForDisplay(item.sl_price) : null;

    const tpslLines = [];
    if (tp1 || tp2 || sl) {
        tpslLines.push('');
        tpslLines.push('규칙 기반 목표가');
        if (tp1 && curPrc > 0) {
            const pct = (((tp1 - curPrc) / curPrc) * 100).toFixed(1);
            tpslLines.push(`TP1: ${tp1.toLocaleString()}원 (+${pct}%)`);
        }
        if (tp2 && curPrc > 0) {
            const pct = (((tp2 - curPrc) / curPrc) * 100).toFixed(1);
            tpslLines.push(`TP2: ${tp2.toLocaleString()}원 (+${pct}%)`);
        }
        if (sl && curPrc > 0) {
            const pct = (((sl - curPrc) / curPrc) * 100).toFixed(1);
            tpslLines.push(`SL: ${sl.toLocaleString()}원 (${pct}%)`);
        }
        if (tp1 && sl && curPrc > 0 && sl < curPrc) {
            const rr = ((tp1 - curPrc) / (curPrc - sl)).toFixed(1);
            tpslLines.push(`R/R: 1:${rr}`);
        }
    }
    if (item.time_stop_type || item.time_stop_session) {
        const desc = [
            item.time_stop_type ? `type=${item.time_stop_type}` : null,
            item.time_stop_minutes != null ? `window=${item.time_stop_minutes}` : null,
            item.time_stop_session ? `session=${item.time_stop_session}` : null,
        ].filter(Boolean).join(', ');
        tpslLines.push(`Time stop: ${desc}`);
    }

    const text = [
        '<b>[매매 신호 컨펌 요청]</b>',
        '',
        `종목: <b>${stkNm ? `${stkNm} (${stkCd})` : stkCd}</b>`,
        `전략: ${strategy}`,
        `규칙 스코어: <b>${ruleScore}점</b>`,
        curPrc > 0 ? `진입가: ${curPrc.toLocaleString()}원` : null,
        ...tpslLines,
        '',
        `신호: ${message}`,
        item.confirm_expires_at ? `유효시간: ${formatKst(item.confirm_expires_at)} KST까지` : null,
        '',
        'Claude AI 분석을 진행하시겠습니까?',
    ].filter((line) => line !== null).join('\n');

    const chatIds = resolveChatIds(allowedChatIds);
    if (chatIds.length === 0) {
        logger.warn('컨펌 요청 발송 대상 chat id가 없습니다.');
        return;
    }

    for (const chatId of chatIds) {
        try {
            const sent = await bot.telegram.sendMessage(chatId, text, {
                parse_mode: 'HTML',
                reply_markup: {
                    inline_keyboard: [[
                        { text: '분석 진행', callback_data: `confirm_yes:${requestKey}` },
                        { text: '취소', callback_data: `confirm_no:${requestKey}` },
                    ]],
                },
            });
            await markConfirmRequestSent(requestKey, chatId, sent.message_id);
        } catch (e) {
            logger.error(`컨펌 요청 발송 실패 chatId=${chatId}: ${e.message}`);
        }
    }

    logger.info(`컨펌 요청 발송 완료 requestKey=${requestKey} [${stkCd} ${strategy}]`);
}

async function startConfirmPoller(bot, allowedChatIds) {
    if (!isConfirmGateEnabled()) {
        logger.info('ENABLE_CONFIRM_GATE 비활성화 - 컨펌 폴러 미기동');
        return;
    }

    logger.info(`human_confirm_queue 폴링 시작 (interval=${CONFIRM_POLL_INTERVAL_MS}ms)`);

    let emptyCount = 0;

    const poll = async () => {
        try {
            const redis = getClient();
            const raw = await redis.rpop('human_confirm_queue');
            if (raw) {
                emptyCount = 0;
                let item;
                try {
                    item = JSON.parse(raw);
                } catch (e) {
                    logger.error(`confirm queue JSON 파싱 실패: ${e.message}`);
                    item = null;
                }
                if (item) {
                    await sendConfirmRequest(bot, allowedChatIds, item);
                }
            } else {
                emptyCount++;
            }
        } catch (e) {
            logger.error(`컨펌 폴링 오류: ${e.message}`);
        }

        const nextDelay = emptyCount === 0
            ? CONFIRM_POLL_INTERVAL_MS
            : Math.min(CONFIRM_POLL_INTERVAL_MS * (1 + emptyCount * 0.1), 10_000);

        setTimeout(poll, nextDelay);
    };

    setTimeout(poll, CONFIRM_POLL_INTERVAL_MS);
}

module.exports = { isConfirmGateEnabled, sendConfirmRequest, startConfirmPoller };
