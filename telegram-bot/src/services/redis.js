'use strict';

/**
 * services/redis.js
 * ioredis 클라이언트 싱글턴 + ai_scored_queue 폴링
 */

const Redis        = require('ioredis');
const { getLogger } = require('../utils/logger');

const logger = getLogger('redis');

let client = null;

/**
 * Redis 클라이언트 반환 (싱글턴)
 */
function getClient() {
    if (client) return client;

    client = new Redis({
        host:             process.env.REDIS_HOST     ?? 'localhost',
        port:             Number(process.env.REDIS_PORT ?? 6379),
        password:         process.env.REDIS_PASSWORD ?? undefined,
        lazyConnect:      false,
        retryStrategy:    (times) => Math.min(times * 500, 5000),
        enableReadyCheck: true,
    });

    client.on('connect',      ()  => logger.info('[Redis] 연결 성공'));
    client.on('error',        (e) => logger.error('[Redis] 오류', { err: e.message }));
    client.on('reconnecting', ()  => logger.warn('[Redis] 재연결 중...'));

    return client;
}

/**
 * ai_scored_queue 에서 항목 꺼내기 (RPOP)
 * @returns {Promise<Object|null>}
 */
async function popScoredQueue() {
    const raw = await getClient().rpop('ai_scored_queue');
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch (e) {
        logger.error('[Redis] JSON 파싱 실패', { err: e.message, raw: raw.slice(0, 80) });
        return null;
    }
}

/**
 * Redis 에서 특정 종목 실시간 시세 조회
 * (봇 명령어 /시세 에서 사용)
 */
async function getTickData(stkCd) {
    return getClient().hgetall(`ws:tick:${stkCd}`);
}

/**
 * Redis에서 특정 종목 실시간 호가 조회
 */
async function getHogaData(stkCd) {
    return getClient().hgetall(`ws:hoga:${stkCd}`);
}

/**
 * 당일 신호 통계 조회용 – Java API 를 통해 가져오므로 여기선 미사용
 * 직접 Redis 조회가 필요할 경우 확장
 */
async function close() {
    if (client) {
        await client.quit();
        client = null;
    }
}

module.exports = { getClient, popScoredQueue, getTickData, getHogaData, close };
