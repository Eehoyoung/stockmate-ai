'use strict';

const axios = require('axios');
const { Client } = require('pg');
const { getClient: getRedis, close: closeRedis } = require('./services/redis');

async function checkRedis() {
    const redis = getRedis();
    const pong = await redis.ping();
    if (pong !== 'PONG') {
        throw new Error(`redis ping unexpected response: ${pong}`);
    }
}

async function checkPostgres() {
    const client = new Client({
        host: process.env.POSTGRES_HOST ?? 'localhost',
        port: Number(process.env.POSTGRES_PORT ?? 5432),
        database: process.env.POSTGRES_DB ?? 'SMA',
        user: process.env.POSTGRES_USER ?? 'postgres',
        password: process.env.POSTGRES_PASSWORD ?? '',
    });
    await client.connect();
    try {
        await client.query('SELECT 1');
    } finally {
        await client.end();
    }
}

async function checkHttp(url) {
    const { status } = await axios.get(url, { timeout: 5000 });
    if (status < 200 || status >= 300) {
        throw new Error(`unexpected status ${status} for ${url}`);
    }
}

async function main() {
    try {
        await checkRedis();
        await checkPostgres();
        await checkHttp(`${process.env.API_ORCHESTRATOR_BASE_URL}/actuator/health`);
        await checkHttp(`${process.env.AI_ENGINE_URL}/health`);
        process.exit(0);
    } catch (err) {
        console.error(`[telegram-bot healthcheck] ${err.message}`);
        process.exit(1);
    } finally {
        try {
            await closeRedis();
        } catch (_) {
            // ignore shutdown noise during healthcheck
        }
    }
}

main();
