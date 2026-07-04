'use strict';

const CORE_COMMANDS = [
    ['ping', 'ping'],
    ['health', 'status'],
    ['status', 'status'],
    ['signals', 'signals'],
    ['perf', 'performance'],
    ['track', 'performanceDetail'],
    ['analysis', 'strategyAnalysis'],
    ['history', 'signalHistory'],
    ['quote', 'quote'],
    ['score', 'scoreStock'],
    ['claude', 'claudeAnalyze'],
    ['candidates', 'candidates'],
    ['report', 'report'],
    ['news', 'newsStatus'],
    ['sector', 'sectorStatus'],
    ['events', 'calendarEvents'],
    ['settings', 'userSettings'],
    ['filter', 'filter'],
    ['watchAdd', 'watchlistAdd'],
    ['watchRemove', 'watchlistRemove'],
    ['pause', 'pauseTrading'],
    ['resume', 'resumeTrading'],
    ['errors', 'systemErrors'],
    ['strategy', 'runStrategy'],
    ['token', 'refreshToken'],
    ['wsStart', 'wsStart'],
    ['wsStop', 'wsStop'],
    ['help', 'help'],
    ['start', 'help'],
];

const CONFIRM_COMMANDS = [
    ['confirmPending', 'confirmPending'],
    ['reanalyze', 'reanalyzeConfirm'],
];

function registerCommandList(bot, commands, entries) {
    for (const [name, handlerName] of entries) {
        const handler = commands[handlerName];
        if (typeof handler !== 'function') {
            throw new Error(`Missing Telegram command handler: ${handlerName}`);
        }
        bot.command(name, handler);
    }
}

function registerCommands(bot, commands, options = {}) {
    registerCommandList(bot, commands, CORE_COMMANDS);
    if (options.confirmGateEnabled) {
        registerCommandList(bot, commands, CONFIRM_COMMANDS);
    }
}

module.exports = {
    CORE_COMMANDS,
    CONFIRM_COMMANDS,
    registerCommands,
};

