'use strict';

/**
 * telegram-bot/src/index.js
 * ──────────────────────────────────────────────────────────
 * StockMate AI – Telegram Bot (Node.js + Telegraf)
 *
 * 역할
 *   1. ai_scored_queue 를 폴링하여 거래 신호를 텔레그램으로 자동 발송
 *   2. 봇 명령어로 시스템 상태 조회 및 수동 제어
 *
 * 실행
 *   npm start
 *   npm run dev   (nodemon)
 */

require('dotenv').config();

const { Telegraf }       = require('telegraf');
const { close: closeRedis } = require('./services/redis');
const commands           = require('./handlers/commands');
const { startPolling, startConfirmPoller } = require('./handlers/signals');
const kiwoom             = require('./services/kiwoom');

// ── 환경변수 검증 ────────────────────────────────────────────
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
if (!BOT_TOKEN) {
    console.error('[Bot] TELEGRAM_BOT_TOKEN 환경변수 미설정 – 종료');
    process.exit(1);
}

// ── 봇 인스턴스 생성 ─────────────────────────────────────────
const bot = new Telegraf(BOT_TOKEN);

// 허용되지 않은 사용자 차단
bot.use((ctx, next) => {
    if (!commands.isAllowed(ctx)) {
        const chatId = ctx.chat?.id;
        console.warn(`[Bot] 미인가 접근 차단 – chatId=${chatId}`);
        return ctx.reply(
            `⛔ Access denied\n\n` +
            `접근 권한이 없습니다.\n` +
            `관리자에게 아래 Chat ID를 전달하세요:\n\n` +
            `🆔 <code>${chatId}</code>`,
            { parse_mode: 'HTML' }
        );
    }
    return next();
});

// ── 명령어 등록 (영문 전용) ────────────────────────────────────
bot.command('ping',         commands.ping);

// 조회
bot.command('status',       commands.status);
bot.command('signals',      commands.signals);
bot.command('perf',         commands.performance);
bot.command('track',        commands.performanceDetail);
bot.command('analysis',     commands.strategyAnalysis);
bot.command('history',      commands.signalHistory);
bot.command('quote',        commands.quote);
bot.command('score',        commands.scoreStock);
bot.command('candidates',   commands.candidates);
bot.command('report',       commands.report);

// 뉴스·시장
bot.command('news',         commands.newsStatus);
bot.command('sector',       commands.sectorStatus);
bot.command('events',       commands.calendarEvents);

// 개인 설정
bot.command('settings',     commands.userSettings);
bot.command('filter',       commands.filter);
bot.command('watchAdd',     commands.watchlistAdd);
bot.command('watchRemove',  commands.watchlistRemove);

// 시스템 제어
bot.command('pause',        commands.pauseTrading);
bot.command('resume',       commands.resumeTrading);
bot.command('errors',       commands.systemErrors);
bot.command('strategy',     commands.runStrategy);
bot.command('token',        commands.refreshToken);
bot.command('wsStart',      commands.wsStart);
bot.command('wsStop',       commands.wsStop);

// 도움말
bot.command('help',         commands.help);
bot.command('start',        commands.help);

// ── 인라인 키보드 콜백 ───────────────────────────────────────
/** 매매 중단 컨펌 – AI 권고 또는 /pause 수동 요청 후 사용자 확인 */
bot.action('confirm_pause', async (ctx) => {
    if (!commands.isAllowed(ctx)) {
        return ctx.answerCbQuery('⛔ Access denied');
    }
    try {
        const result = await kiwoom.setTradingControl('PAUSE');
        await ctx.editMessageText(
            `🚨 <b>Trading Paused</b>\nPrev: ${result.prev} → <b>PAUSE</b>`,
            { parse_mode: 'HTML' }
        );
        await ctx.answerCbQuery('Trading has been paused.');
        console.log(`[Bot] confirm_pause – chatId=${ctx.chat?.id}`);
    } catch (e) {
        console.error('[Bot] confirm_pause 오류:', e.message);
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

/** 매매 중단 취소 – 현재 상태 유지 */
bot.action('cancel_pause', async (ctx) => {
    if (!commands.isAllowed(ctx)) {
        return ctx.answerCbQuery('⛔ Access denied');
    }
    try {
        await ctx.editMessageText('✅ Pause cancelled – status unchanged', { parse_mode: 'HTML' });
        await ctx.answerCbQuery('Pause cancelled.');
        console.log(`[Bot] cancel_pause – chatId=${ctx.chat?.id}`);
    } catch (e) {
        console.error('[Bot] cancel_pause 오류:', e.message);
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

// ── Human Confirm Gate 콜백 ───────────────────────────────────
const { getClient: getRedis } = require('./services/redis');

/** 신호 컨펌 – confirmed_queue 에 등록 후 Claude 분석 진행 */
bot.action(/^confirm_yes:(.+)$/, async (ctx) => {
    if (!commands.isAllowed(ctx)) {
        return ctx.answerCbQuery('⛔ Access denied');
    }
    const sigId = ctx.match[1];
    try {
        const redis      = getRedis();
        const pendingRaw = await redis.get(`confirm_pending:${sigId}`);
        if (!pendingRaw) {
            await ctx.editMessageText('⏰ 컨펌 시간 초과 – 신호가 만료되었습니다.', { parse_mode: 'HTML' });
            await ctx.answerCbQuery('신호가 만료되었습니다.');
            return;
        }
        // confirmed_queue 에 LPUSH (confirm_worker 가 RPOP)
        await redis.lpush('confirmed_queue', pendingRaw);
        await redis.del(`confirm_pending:${sigId}`);
        await ctx.editMessageText(
            `✅ <b>분석 진행</b>\n신호 ID: ${sigId}\nClaude AI 분석이 시작되었습니다.`,
            { parse_mode: 'HTML' }
        );
        await ctx.answerCbQuery('Claude 분석을 시작합니다.');
        console.log(`[Bot] confirm_yes – sigId=${sigId} chatId=${ctx.chat?.id}`);
    } catch (e) {
        console.error('[Bot] confirm_yes 오류:', e.message);
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

/** 신호 취소 – confirm_pending 삭제 후 무시 */
bot.action(/^confirm_no:(.+)$/, async (ctx) => {
    if (!commands.isAllowed(ctx)) {
        return ctx.answerCbQuery('⛔ Access denied');
    }
    const sigId = ctx.match[1];
    try {
        const redis = getRedis();
        await redis.del(`confirm_pending:${sigId}`);
        await ctx.editMessageText(
            `❌ <b>신호 취소</b>\n신호 ID: ${sigId}\nClaude 분석 없이 취소되었습니다.`,
            { parse_mode: 'HTML' }
        );
        await ctx.answerCbQuery('신호를 취소했습니다.');
        console.log(`[Bot] confirm_no – sigId=${sigId} chatId=${ctx.chat?.id}`);
    } catch (e) {
        console.error('[Bot] confirm_no 오류:', e.message);
        await ctx.answerCbQuery(`Error: ${e.message}`);
    }
});

// ── 오류 핸들러 ──────────────────────────────────────────────
bot.catch((err, ctx) => {
    console.error(`[Bot] 처리되지 않은 오류 (update_type=${ctx.updateType}):`, err.message);
});

// ── 시작 ─────────────────────────────────────────────────────
async function main() {
    console.log('='.repeat(50));
    console.log('  StockMate AI – Telegram Bot 시작');
    console.log('='.repeat(50));

    await bot.launch();
    console.log('[Bot] 봇 시작 완료');

    startPolling(bot);

    const chatIds = (process.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '')
        .split(',').map((id) => id.trim()).filter(Boolean);
    startConfirmPoller(bot, chatIds);

    for (const chatId of chatIds) {
        try {
            await bot.telegram.sendMessage(chatId,
                '🟢 <b>StockMate AI Bot started</b>\nType /help for commands.',
                { parse_mode: 'HTML' }
            );
        } catch (e) {
            console.warn('[Bot] 시작 메시지 발송 실패:', e.message);
        }
    }
}

// ── 종료 처리 ────────────────────────────────────────────────
async function shutdown(signal) {
    console.log(`\n[Bot] 종료 시그널 수신 (${signal})`);
    try { bot.stop(signal); } catch (_) {}
    try { await closeRedis(); } catch (_) {}
    console.log('[Bot] 종료 완료');
    process.exit(0);
}

process.once('SIGINT',  () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));

main().catch((e) => {
    console.error('[Bot] 치명적 오류:', e.message);
    process.exit(1);
});
