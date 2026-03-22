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
const kiwoom             = require('./services/kiwoom');

// ── 환경변수 검증 ────────────────────────────────────────────
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
if (!BOT_TOKEN) {
    console.error('[Bot] TELEGRAM_BOT_TOKEN 환경변수 미설정 – 종료');
    process.exit(1);
}

// ── 봇 인스턴스 생성 ─────────────────────────────────────────
const bot = new Telegraf(BOT_TOKEN);

// 허용되지 않은 사용자 차단 (명령어 등록 전에 위치해야 효과 있음)
bot.use((ctx, next) => {
    if (!commands.isAllowed(ctx)) {
        console.warn(`[Bot] 미인가 접근 차단 – chatId=${ctx.chat?.id}`);
        return ctx.reply('⛔ 접근 권한 없음');
    }
    return next();
});

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
bot.command('매매중단',  commands.pauseTrading);
bot.command('매매재개',  commands.resumeTrading);
bot.command('이벤트',   commands.calendarEvents);
bot.command('성과추적',  commands.performanceDetail);
bot.command('관심등록',  commands.watchlistAdd);
bot.command('관심해제',  commands.watchlistRemove);
bot.command('설정',     commands.userSettings);

// ── 영문 명령어 별칭 (한국어 명령어가 일부 클라이언트에서 동작하지 않을 경우 대비) ──
// Telegram Bot API 명령어는 [a-z0-9_] 만 허용 – 한국어 명령이 인식 안 될 때 사용
bot.command('status',     commands.status);
bot.command('sigs',       commands.signals);
bot.command('perf',       commands.performance);
bot.command('cands',      commands.candidates);
bot.command('quote',      commands.quote);
bot.command('strategy',   commands.runStrategy);
bot.command('token',      commands.refreshToken);
bot.command('wsstart',    commands.wsStart);
bot.command('wsstop',     commands.wsStop);
bot.command('news',       commands.newsStatus);
bot.command('sector',     commands.sectorStatus);
bot.command('history',    commands.signalHistory);
bot.command('analysis',   commands.strategyAnalysis);
bot.command('errs',       commands.systemErrors);
bot.command('pause',      commands.pauseTrading);
bot.command('resume',     commands.resumeTrading);
bot.command('events',     commands.calendarEvents);
bot.command('track',      commands.performanceDetail);
bot.command('watch',      commands.watchlistAdd);
bot.command('unwatch',    commands.watchlistRemove);
bot.command('settings',   commands.userSettings);

// ── 인라인 키보드 콜백 ───────────────────────────────────────
/** 매매 중단 컨펌 – AI 권고 또는 /매매중단 수동 요청 후 사용자 확인 */
bot.action('confirm_pause', async (ctx) => {
    if (!commands.isAllowed(ctx)) {
        return ctx.answerCbQuery('⛔ 권한 없음');
    }
    try {
        const result = await kiwoom.setTradingControl('PAUSE');
        await ctx.editMessageText(
            `🚨 <b>매매 중단</b> 설정 완료\n이전 상태: ${result.prev} → <b>PAUSE</b>`,
            { parse_mode: 'HTML' }
        );
        await ctx.answerCbQuery('매매 중단 처리되었습니다.');
        console.log(`[Bot] confirm_pause – chatId=${ctx.chat?.id}`);
    } catch (e) {
        console.error('[Bot] confirm_pause 오류:', e.message);
        await ctx.answerCbQuery(`오류: ${e.message}`);
    }
});

/** 매매 중단 취소 – 현재 상태 유지 */
bot.action('cancel_pause', async (ctx) => {
    if (!commands.isAllowed(ctx)) {
        return ctx.answerCbQuery('⛔ 권한 없음');
    }
    try {
        await ctx.editMessageText('✅ 매매 중단 취소 – 기존 상태 유지', { parse_mode: 'HTML' });
        await ctx.answerCbQuery('매매 중단이 취소되었습니다.');
        console.log(`[Bot] cancel_pause – chatId=${ctx.chat?.id}`);
    } catch (e) {
        console.error('[Bot] cancel_pause 오류:', e.message);
        await ctx.answerCbQuery(`오류: ${e.message}`);
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
    try {
        bot.stop(signal);
    } catch (_) {}
    try {
        await closeRedis();
    } catch (_) {}
    console.log('[Bot] 종료 완료');
    process.exit(0);
}

process.once('SIGINT',  () => shutdown('SIGINT'));
process.once('SIGTERM', () => shutdown('SIGTERM'));

main().catch((e) => {
    console.error('[Bot] 치명적 오류:', e.message);
    process.exit(1);
});
