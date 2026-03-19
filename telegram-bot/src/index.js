const { Telegraf } = require('telegraf');
require('dotenv').config();

const bot = new Telegraf(process.env.TELEGRAM_BOT_TOKEN);

bot.command('ping', ctx => ctx.reply('🏓 pong! StockMate AI 작동 중'));

bot.launch();
console.log('Bot started');
