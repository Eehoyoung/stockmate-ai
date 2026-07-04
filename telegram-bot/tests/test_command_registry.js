'use strict';

const assert = require('assert');
const { CORE_COMMANDS, CONFIRM_COMMANDS, registerCommands } = require('../src/commands/registry');

function buildCommands() {
    const commands = {};
    for (const [, handlerName] of [...CORE_COMMANDS, ...CONFIRM_COMMANDS]) {
        commands[handlerName] = async () => {};
    }
    return commands;
}

function buildBot() {
    const registered = [];
    return {
        registered,
        command(name, handler) {
            registered.push({ name, handler });
        },
    };
}

function testRegistersCoreCommands() {
    const bot = buildBot();
    registerCommands(bot, buildCommands(), { confirmGateEnabled: false });

    assert.deepStrictEqual(bot.registered.map((item) => item.name), CORE_COMMANDS.map(([name]) => name));
}

function testRegistersConfirmCommandsWhenEnabled() {
    const bot = buildBot();
    registerCommands(bot, buildCommands(), { confirmGateEnabled: true });

    assert.deepStrictEqual(
        bot.registered.map((item) => item.name),
        [...CORE_COMMANDS, ...CONFIRM_COMMANDS].map(([name]) => name)
    );
}

function testRejectsMissingHandlers() {
    const bot = buildBot();
    const commands = buildCommands();
    delete commands.scoreStock;

    assert.throws(() => registerCommands(bot, commands), /scoreStock/);
}

testRegistersCoreCommands();
testRegistersConfirmCommandsWhenEnabled();
testRejectsMissingHandlers();
console.log('test_command_registry passed');

