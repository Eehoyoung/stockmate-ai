'use strict';

const assert = require('assert');
const { sendMessageWithRetry } = require('../src/services/telegramSend');

async function main() {
    let calls = 0;
    const telegram = {
        sendMessage: async () => {
            calls++;
            if (calls === 1) throw { response: { error_code: 502 } };
            return { message_id: 1 };
        },
    };
    const sleeps = [];
    const result = await sendMessageWithRetry(telegram, 'chat', 'message', {}, async (ms) => sleeps.push(ms));
    assert.strictEqual(result.message_id, 1);
    assert.strictEqual(calls, 2);
    assert.strictEqual(sleeps.length, 1);

    calls = 0;
    await assert.rejects(
        sendMessageWithRetry({
            sendMessage: async () => {
                calls++;
                throw { response: { error_code: 400 } };
            },
        }, 'chat', 'message', {}, async () => {}),
    );
    assert.strictEqual(calls, 1);
    console.log('telegram retry tests passed');
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
