'use strict';

const { getActivePositions } = require('../services/positions');
const { formatActivePositionsMessage } = require('../utils/activePositionsFormatter');
const { getLogger } = require('../utils/logger');

const logger = getLogger('activePositionsScheduler');
const START_HOUR = 9;
const END_HOUR = 16;

let timer = null;

function getPrimaryChatIds() {
    return String(process.env.TELEGRAM_PRIMARY_CHAT_ID ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
}

function nextHourlySlot(now = new Date()) {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(now);
    const p = Object.fromEntries(parts.filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));

    const kstAsUtc = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute), Number(p.second), now.getMilliseconds());
    const current = new Date(kstAsUtc);
    const onExactHour = current.getUTCMinutes() === 0 && current.getUTCSeconds() === 0 && current.getUTCMilliseconds() === 0;

    let target = new Date(kstAsUtc);
    if (!onExactHour) {
        target.setUTCHours(target.getUTCHours() + 1, 0, 0, 0);
    }

    if (target.getUTCHours() < START_HOUR) {
        target.setUTCHours(START_HOUR, 0, 0, 0);
    } else if (target.getUTCHours() > END_HOUR) {
        target.setUTCDate(target.getUTCDate() + 1);
        target.setUTCHours(START_HOUR, 0, 0, 0);
    }

    const offsetMs = target.getTime() - current.getTime();
    return {
        delayMs: Math.max(0, offsetMs),
        kstSlot: target,
    };
}

async function sendActivePositionsReport(bot) {
    const chatIds = getPrimaryChatIds();
    if (chatIds.length === 0) {
        logger.warn('TELEGRAM_PRIMARY_CHAT_ID is empty; active positions report skipped');
        return;
    }

    const positions = await getActivePositions();
    const text = formatActivePositionsMessage(positions);
    let sentCount = 0;
    let failedCount = 0;

    for (const chatId of chatIds) {
        try {
            await bot.telegram.sendMessage(chatId, text, {
                parse_mode: 'HTML',
                disable_web_page_preview: true,
            });
            sentCount++;
        } catch (e) {
            failedCount++;
            logger.error('active positions report send failed', { chat_id: chatId }, e);
        }
    }

    logger.info('active positions report sent', {
        recipient_group: 'primary',
        chat_ids: chatIds,
        position_count: positions.length,
        sent_count: sentCount,
        failed_count: failedCount,
    });
}

function scheduleNext(bot) {
    const { delayMs, kstSlot } = nextHourlySlot();
    timer = setTimeout(async () => {
        try {
            await sendActivePositionsReport(bot);
        } catch (e) {
            logger.error('active positions report failed', {}, e);
        } finally {
            scheduleNext(bot);
        }
    }, delayMs);

    logger.info('active positions report scheduled', {
        delay_ms: delayMs,
        kst_slot: kstSlot.toISOString().replace('T', ' ').slice(0, 19),
    });
}

function startActivePositionsScheduler(bot) {
    if (timer) return;
    scheduleNext(bot);
}

function stopActivePositionsScheduler() {
    if (timer) {
        clearTimeout(timer);
        timer = null;
    }
}

module.exports = {
    getPrimaryChatIds,
    nextHourlySlot,
    sendActivePositionsReport,
    startActivePositionsScheduler,
    stopActivePositionsScheduler,
};
