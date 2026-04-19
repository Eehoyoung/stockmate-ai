'use strict';

/**
 * test-channel.js
 * 채널/그룹으로 테스트 메시지를 전송하고 결과를 출력합니다.
 *
 * 실행:
 *   node telegram-bot/test-channel.js
 */

require('dotenv').config({ path: `${__dirname}/.env` });

const { Telegraf } = require('telegraf');

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const RAW_IDS   = process.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '';

if (!BOT_TOKEN) {
    console.error('[ERROR] TELEGRAM_BOT_TOKEN 가 .env에 없습니다.');
    process.exit(1);
}

const chatIds = RAW_IDS.split(',').map(s => s.trim()).filter(Boolean);
if (chatIds.length === 0) {
    console.error('[ERROR] TELEGRAM_ALLOWED_CHAT_IDS 가 비어 있습니다.');
    process.exit(1);
}

const bot = new Telegraf(BOT_TOKEN);

const MESSAGE = `✅ <b>채널 연결 테스트</b>

봇이 이 채널에 메시지를 정상적으로 전송하고 있습니다.
매수추천 알림을 수신할 준비가 완료되었습니다.

<code>chat_id: {CHAT_ID}</code>`;

(async () => {
    console.log(`대상 chat ID: ${chatIds.join(', ')}\n`);

    for (const chatId of chatIds) {
        try {
            const text = MESSAGE.replace('{CHAT_ID}', chatId);
            const result = await bot.telegram.sendMessage(chatId, text, {
                parse_mode: 'HTML',
            });
            console.log(`[OK]  chat_id=${chatId}  message_id=${result.message_id}`);
        } catch (err) {
            console.error(`[FAIL] chat_id=${chatId}`);
            console.error(`       ${err.message}`);
            if (err.description) {
                console.error(`       Telegram: ${err.description}`);
            }
        }
    }

    process.exit(0);
})();
