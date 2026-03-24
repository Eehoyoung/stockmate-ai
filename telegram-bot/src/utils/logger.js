'use strict';

/**
 * telegram-bot/src/utils/logger.js
 * StockMate AI 공통 JSON 구조화 로거 – telegram-bot 모듈용.
 *
 * 출력 형식 (JSON Lines, 1줄 = 1 로그):
 *   {"ts":"2026-03-24T01:53:00.123+09:00","level":"INFO","service":"telegram-bot",
 *    "module":"signals","request_id":"...","signal_id":"...","msg":"..."}
 *
 * 사용법:
 *   const { getLogger } = require('./utils/logger');
 *   const logger = getLogger('signals');
 *   logger.info('신호 발송 완료', { signal_id: sid, stk_cd: '005930' });
 *   logger.error('발송 실패', { signal_id: sid, error_code: 'TG_SEND_FAIL' }, err);
 */

const fs   = require('fs');
const path = require('path');

const SERVICE_NAME = process.env.SERVICE_NAME || 'telegram-bot';
const LOG_LEVEL    = (process.env.LOG_LEVEL  || 'INFO').toUpperCase();
const LOG_FILE     = process.env.LOG_FILE    || path.join(__dirname, '../../logs/telegram-bot.log');

const LEVELS = { DEBUG: 0, INFO: 1, WARNING: 2, WARN: 2, ERROR: 3, CRITICAL: 4 };
const currentLevel = LEVELS[LOG_LEVEL] ?? LEVELS.INFO;

// 로그 디렉토리 생성
const logDir = path.dirname(LOG_FILE);
if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true });

const logStream = fs.createWriteStream(LOG_FILE, { flags: 'a', encoding: 'utf8' });

/**
 * KST ISO-8601 타임스탬프 반환 (ms 포함).
 * @returns {string}
 */
function nowKst() {
    return new Date().toLocaleString('sv-SE', {
        timeZone: 'Asia/Seoul',
        hour12: false,
    }).replace(' ', 'T') + '+09:00';
}

/**
 * JSON 로그 한 줄 출력.
 * @param {string} level
 * @param {string} module
 * @param {string} msg
 * @param {object} [extra={}]
 * @param {Error}  [err]
 */
function _write(level, module, msg, extra = {}, err = null) {
    if ((LEVELS[level] ?? 0) < currentLevel) return;

    const doc = {
        ts:      nowKst(),
        level,
        service: SERVICE_NAME,
        module,
        msg,
        ...extra,
    };

    if (err instanceof Error) {
        doc.exc = err.stack || err.message;
    }

    const line = JSON.stringify(doc) + '\n';
    process.stdout.write(line);
    logStream.write(line);
}

/**
 * 모듈별 logger 반환.
 * @param {string} moduleName
 * @returns {{ debug, info, warn, warning, error, critical }}
 */
function getLogger(moduleName) {
    return {
        debug:    (msg, extra, err) => _write('DEBUG',    moduleName, msg, extra, err),
        info:     (msg, extra, err) => _write('INFO',     moduleName, msg, extra, err),
        warn:     (msg, extra, err) => _write('WARNING',  moduleName, msg, extra, err),
        warning:  (msg, extra, err) => _write('WARNING',  moduleName, msg, extra, err),
        error:    (msg, extra, err) => _write('ERROR',    moduleName, msg, extra, err),
        critical: (msg, extra, err) => _write('CRITICAL', moduleName, msg, extra, err),
    };
}

module.exports = { getLogger };
