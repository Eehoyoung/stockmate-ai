'use strict';

const assert = require('assert');
const { stripPersonaLines } = require('../src/handlers/signals');

function test(name, fn) {
    try {
        fn();
        console.log(`  OK ${name}`);
    } catch (err) {
        console.error(`  FAIL ${name}`);
        console.error(err);
        process.exitCode = 1;
    }
}

test('removes Korean persona line from briefing text', () => {
    const input = [
        '<b>[오전 시황 브리핑 08:00]</b>',
        '페르소나: 수석 매크로 애널리스트 + 헤드 트레이더',
        '',
        '시장 온도: <b>중립</b>',
    ].join('\n');

    const output = stripPersonaLines(input);

    assert(!output.includes('페르소나'));
    assert(output.includes('[오전 시황 브리핑 08:00]'));
    assert(output.includes('시장 온도'));
});

test('removes English persona line with icon prefix', () => {
    const input = [
        '📊 <b>[Midday Brief]</b>',
        '🧠 Persona: macro analyst + trader',
        'Main body',
    ].join('\n');

    const output = stripPersonaLines(input);

    assert(!output.toLowerCase().includes('persona'));
    assert(output.includes('Main body'));
});

if (process.exitCode) {
    process.exit(process.exitCode);
}
