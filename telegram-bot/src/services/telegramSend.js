'use strict';

const MAX_ATTEMPTS = Number(process.env.TELEGRAM_SEND_MAX_ATTEMPTS ?? 3);
const BASE_DELAY_MS = Number(process.env.TELEGRAM_SEND_RETRY_BASE_MS ?? 500);

function retryableStatus(error) {
    return Number(error?.response?.error_code ?? error?.response?.status ?? error?.code ?? 0);
}

async function sendMessageWithRetry(telegram, chatId, text, options, sleep = (ms) => new Promise((r) => setTimeout(r, ms))) {
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        try {
            return await telegram.sendMessage(chatId, text, options);
        } catch (error) {
            const status = retryableStatus(error);
            if ((status !== 429 && status < 500) || attempt === MAX_ATTEMPTS) throw error;
            const retryAfterMs = Number(error?.response?.parameters?.retry_after ?? 0) * 1000;
            const jitterMs = Math.floor(Math.random() * 100);
            await sleep(Math.max(retryAfterMs, BASE_DELAY_MS * (2 ** (attempt - 1))) + jitterMs);
        }
    }
}

module.exports = { sendMessageWithRetry, retryableStatus };
