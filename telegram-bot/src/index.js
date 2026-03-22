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
const { startPolling }   = require('./handlers/signals');

// ── 환경변수 검증 ────────────────────────────────────────────
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
if (!BOT_TOKEN) {
    console.error('[Bot] TELEGRAM_BOT_TOKEN 환경변수 미설정 – 종료');
    process.exit(1);
}

// ── 봇 인스턴스 생성 ─────────────────────────────────────────
const bot = new Telegraf(BOT_TOKEN);

// ── 명령어 등록 ──────────────────────────────────────────────
bot.command('ping',     commands.ping);
bot.command('상태',     commands.status);
bot.command('신호',     commands.signals);
bot.command('성과',     commands.performance);
bot.command('후보',     commands.candidates);
bot.command('시세',     commands.quote);
bot.command('전술',     commands.runStrategy);
bot.command('토큰갱신',  commands.refreshToken);
bot.command('ws시작',   commands.wsStart);
bot.command('ws종료',   commands.wsStop);
bot.command('help',     commands.help);
bot.command('start',    commands.help);
bot.command('report',   commands.report);
bot.command('filter',   commands.filter);
bot.command('뉴스',     commands.newsStatus);
bot.command('섹터',     commands.sectorStatus);
bot.command('신호이력',  commands.signalHistory);
bot.command('전략분석',  commands.strategyAnalysis);
bot.command('에러',     commands.systemErrors);

// 허용되지 않은 사용자 차단
bot.use((ctx, next) => {
    if (!commands.isAllowed(ctx)) {
        console.warn(`[Bot] 미인가 접근 차단 – chatId=${ctx.chat?.id}`);
        return ctx.reply('⛔ 접근 권한 없음');
    }
    return next();
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

    // 봇 시작
    await bot.launch();
    console.log('[Bot] 봇 시작 완료');

    // ai_scored_queue 폴링 시작
    startPolling(bot);

    // 시작 메시지 발송 (선택)
    const chatIds = (process.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '')
        .split(',').map((id) => id.trim()).filter(Boolean);
    for (const chatId of chatIds) {
        try {
            await bot.telegram.sendMessage(chatId,
                '🟢 <b>StockMate AI Bot 시작</b>\n/help 로 명령어를 확인하세요.',
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
    bot.stop(signal);
    await closeRedis();
    console.log('[Bot] 종료 완료');
    process.exit(0);
}

process.once('SIGINT',  () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));

main().catch((e) => {
    console.error('[Bot] 치명적 오류:', e.message);
    process.exit(1);
});
