'use strict';

require('dotenv').config();

const { Telegraf } = require('telegraf');
const { close: closeRedis, getClient: getRedis } = require('./services/redis');
const {
    approveConfirmRequest,
    close: closeConfirmStore,
    rejectConfirmRequest,
} = require('./services/confirmStore');
const { getLogger } = require('./utils/logger');

const logger = getLogger('index');

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
let commands;
let startPolling;
let startConfirmPoller;
let kiwoom;

function getAllowedChatIds() {
    const allowed = String(process.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
    if (allowed.length > 0) return allowed;
    return String(process.env.TELEGRAM_CHAT_ID ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean);
}

function validateRequiredEnv() {
    const missing = [];
    if (!BOT_TOKEN) missing.push('TELEGRAM_BOT_TOKEN');
    if (!process.env.API_ORCHESTRATOR_BASE_URL) missing.push('API_ORCHESTRATOR_BASE_URL');
    if (getAllowedChatIds().length === 0) missing.push('TELEGRAM_ALLOWED_CHAT_IDS or TELEGRAM_CHAT_ID');

    if (missing.length > 0) {
        logger.error('[Bot] required env missing', { missing });
        process.exit(1);
    }
}

validateRequiredEnv();
commands = require('./handlers/commands');
({ startPolling, startConfirmPoller } = require('./handlers/signals'));
kiwoom = require('./services/kiwoom');

const bot = new Telegraf(BOT_TOKEN);

bot.use((ctx, next) => {
    if (!commands.isAllowed(ctx)) {
        const chatId = ctx.chat?.id;
        logger.warn('[Bot] unauthorized access blocked', { chatId });
        return ctx.reply(
            `Access denied\n\n관리자에게 아래 Chat ID를 전달하세요.\n\n<code>${chatId}</code>`,
            { parse_mode: 'HTML' }
        );
    }
    return next();
});

bot.command('ping', commands.ping);
bot.command('health', commands.status);
bot.command('status', commands.status);
bot.command('signals', commands.signals);
bot.command('perf', commands.performance);
bot.command('track', commands.performanceDetail);
bot.command('analysis', commands.strategyAnalysis);
bot.command('history', commands.signalHistory);
bot.command('quote', commands.quote);
bot.command('score', commands.scoreStock);
bot.command('claude', commands.claudeAnalyze);
bot.command('candidates', commands.candidates);
bot.command('report', commands.report);
bot.command('news', commands.newsStatus);
bot.command('sector', commands.sectorStatus);
bot.command('events', commands.calendarEvents);
bot.command('settings', commands.userSettings);
bot.command('filter', commands.filter);
bot.command('watchAdd', commands.watchlistAdd);
bot.command('watchRemove', commands.watchlistRemove);
bot.command('confirmPending', commands.confirmPending);
bot.command('reanalyze', commands.reanalyzeConfirm);
bot.command('pause', commands.pauseTrading);
bot.command('resume', commands.resumeTrading);
bot.command('errors', commands.systemErrors);
bot.command('strategy', commands.runStrategy);
bot.command('token', commands.refreshToken);
bot.command('wsStart', commands.wsStart);
bot.command('wsStop', commands.wsStop);
bot.command('help', commands.help);
bot.command('start', commands.help);

bot.action('confirm_pause', async (ctx) => {
    if (!commands.isAllowed(ctx)) return ctx.answerCbQuery('Access denied');
    try {
        const result = await kiwoom.setTradingControl('PAUSE');
        await ctx.editMessageText(
            `✅ <b>Trading Paused</b>\nPrev: ${result.prev} -> <b>PAUSE</b>`,
            { parse_mode: 'HTML' }
        );
        await ctx.answerCbQuery('Trading has been paused.');
    } catch (e) {
        logger.error('[Bot] confirm_pause error', { err: e.message });
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

bot.action('cancel_pause', async (ctx) => {
    if (!commands.isAllowed(ctx)) return ctx.answerCbQuery('Access denied');
    try {
        await ctx.editMessageText('✅ Pause cancelled - status unchanged', { parse_mode: 'HTML' });
        await ctx.answerCbQuery('Pause cancelled.');
    } catch (e) {
        logger.error('[Bot] cancel_pause error', { err: e.message });
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

bot.action(/^confirm_yes:(.+)$/, async (ctx) => {
    if (!commands.isAllowed(ctx)) return ctx.answerCbQuery('Access denied');
    const requestKey = ctx.match[1];
    try {
        const approved = await approveConfirmRequest(requestKey, ctx.chat?.id, ctx.callbackQuery?.message?.message_id);
        if (!approved.ok) {
            const text = approved.reason === 'expired'
                ? '해당 컨펌 요청은 만료되었습니다.'
                : approved.reason === 'not_found'
                    ? '해당 컨펌 요청을 찾지 못했습니다.'
                    : `이미 처리된 요청입니다. (${approved.reason})`;
            await ctx.editMessageText(text, { parse_mode: 'HTML' });
            await ctx.answerCbQuery(text);
            return;
        }

        const payload = {
            ...(approved.payload || {}),
            confirm_request_key: requestKey,
            human_confirmed: true,
        };
        await getRedis().lpush('confirmed_queue', JSON.stringify(payload));
        await ctx.editMessageText(
            `<b>분석 진행</b>\nrequest_key: ${requestKey}\nClaude AI 분석을 시작했습니다.`,
            { parse_mode: 'HTML' }
        );
        await ctx.answerCbQuery('Claude 분석을 시작했습니다.');
        logger.info('[Bot] confirm_yes', { requestKey, chatId: ctx.chat?.id });
    } catch (e) {
        logger.error('[Bot] confirm_yes error', { err: e.message });
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

bot.action(/^confirm_no:(.+)$/, async (ctx) => {
    if (!commands.isAllowed(ctx)) return ctx.answerCbQuery('Access denied');
    const requestKey = ctx.match[1];
    try {
        const cancelled = await rejectConfirmRequest(requestKey, ctx.chat?.id, ctx.callbackQuery?.message?.message_id);
        await ctx.editMessageText(
            cancelled
                ? `<b>신호 취소</b>\nrequest_key: ${requestKey}\nClaude 분석 없이 취소했습니다.`
                : `이미 만료되었거나 처리된 요청입니다.\nrequest_key: ${requestKey}`,
            { parse_mode: 'HTML' }
        );
        await ctx.answerCbQuery(cancelled ? '신호를 취소했습니다.' : '이미 처리된 요청입니다.');
        logger.info('[Bot] confirm_no', { requestKey, chatId: ctx.chat?.id });
    } catch (e) {
        logger.error('[Bot] confirm_no error', { err: e.message });
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

bot.catch((err, ctx) => {
    logger.error('[Bot] unhandled error', { update_type: ctx.updateType, err: err.message });
});

async function main() {
    logger.info('[Bot] StockMate AI Telegram Bot start');
    bot.launch();
    startPolling(bot);

    const chatIds = getAllowedChatIds();
    startConfirmPoller(bot, chatIds);

}

async function shutdown(signal) {
    logger.info('[Bot] shutdown signal', { signal });
    try { bot.stop(signal); } catch (_) {}
    try { await closeRedis(); } catch (_) {}
    try { await closeConfirmStore(); } catch (_) {}
    process.exit(0);
}

process.once('SIGINT', () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));

if (require.main === module) {
    main().catch((e) => {
        logger.error('[Bot] fatal error', { err: e.message });
        process.exit(1);
    });
}

module.exports = {
    getAllowedChatIds,
    validateRequiredEnv,
    main,
};
