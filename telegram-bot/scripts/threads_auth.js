#!/usr/bin/env node
'use strict';

/**
 * threads_auth.js — Threads 장기 토큰 초기 발급 스크립트
 *
 * 최초 1회 실행으로 OAuth 승인 → 장기 토큰(60일) 발급 → Redis 저장.
 * 이후 threads.js의 startTokenRefreshScheduler()가 자동 갱신.
 *
 * 사용법:
 *   node telegram-bot/scripts/threads_auth.js
 *   docker compose exec telegram-bot node scripts/threads_auth.js
 */

require('dotenv').config({ path: require('path').resolve(__dirname, '../../.env') });

const axios    = require('axios');
const readline = require('readline');
const Redis    = require('ioredis');

const APP_ID       = process.env.THREADS_APP_ID;
const APP_SECRET   = process.env.THREADS_APP_SECRET;
const REDIRECT_URI = process.env.THREADS_REDIRECT_URI || 'https://localhost/auth/threads';

if (!APP_ID || !APP_SECRET) {
    console.error('\n[오류] .env에 다음 항목을 설정한 후 다시 실행하세요:');
    console.error('  THREADS_APP_ID=<Meta 앱 ID>');
    console.error('  THREADS_APP_SECRET=<Meta 앱 시크릿>\n');
    process.exit(1);
}

const redis = new Redis({
    host:     process.env.REDIS_HOST     || 'localhost',
    port:     Number(process.env.REDIS_PORT || 6379),
    password: process.env.REDIS_PASSWORD || undefined,
    lazyConnect: true,
});

const rl  = readline.createInterface({ input: process.stdin, output: process.stdout });
const ask = (q) => new Promise((resolve) => rl.question(q, resolve));

async function main() {
    await redis.connect();

    console.log('\n=== Threads 토큰 초기화 ===\n');

    // ── Step 1: 인증 URL 출력 ─────────────────────────────────────────
    const authUrl =
        'https://threads.net/oauth/authorize' +
        `?client_id=${APP_ID}` +
        `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}` +
        '&scope=threads_basic,threads_content_publish' +
        '&response_type=code';

    console.log('[Step 1] 아래 URL을 브라우저에서 열어 Threads 계정으로 승인하세요:\n');
    console.log(authUrl);
    console.log('\n승인 후 리디렉션 URL의 ?code=XXXXX 부분을 복사하세요.');
    console.log('(REDIRECT_URI가 localhost인 경우 브라우저 주소창에서 code 값을 확인)\n');

    // ── Step 2: code 입력 ────────────────────────────────────────────
    const code = (await ask('[Step 2] code 값 입력: ')).trim();
    if (!code) {
        console.error('code가 비어 있습니다.');
        process.exit(1);
    }

    // ── Step 3: 단기 토큰 발급 ───────────────────────────────────────
    console.log('\n[Step 3] 단기 토큰 발급 중...');
    let shortToken, userId;
    try {
        const res = await axios.post('https://graph.threads.net/oauth/access_token', null, {
            params: {
                client_id:     APP_ID,
                client_secret: APP_SECRET,
                code,
                grant_type:    'authorization_code',
                redirect_uri:  REDIRECT_URI,
            },
            timeout: 15_000,
        });
        shortToken = res.data.access_token;
        userId     = res.data.user_id;
    } catch (e) {
        console.error('[오류] 단기 토큰 발급 실패:', e.response?.data || e.message);
        process.exit(1);
    }
    console.log(`단기 토큰 발급 완료. user_id: ${userId}`);

    // ── Step 4: 장기 토큰 교환 (60일 유효) ───────────────────────────
    console.log('[Step 4] 장기 토큰(60일) 교환 중...');
    let longToken, expiresIn;
    try {
        const res = await axios.get('https://graph.threads.net/access_token', {
            params: {
                grant_type:    'th_exchange_token',
                client_secret: APP_SECRET,
                access_token:  shortToken,
            },
            timeout: 15_000,
        });
        longToken  = res.data.access_token;
        expiresIn  = res.data.expires_in ?? 5_184_000; // 60일(초)
    } catch (e) {
        console.error('[오류] 장기 토큰 교환 실패:', e.response?.data || e.message);
        process.exit(1);
    }

    // ── Step 5: Redis 저장 ───────────────────────────────────────────
    const nowSec     = Math.floor(Date.now() / 1000);
    const expiryDate = new Date((nowSec + expiresIn) * 1000).toLocaleDateString('ko-KR');

    await redis.set('threads:access_token',    longToken);
    await redis.set('threads:token_expiry',    String(nowSec + expiresIn));
    await redis.set('threads:token_refreshed', String(nowSec));

    console.log('\n=== 완료 ===\n');
    console.log(`  토큰 만료일 : ${expiryDate}`);
    console.log(`  user_id     : ${userId}\n`);
    console.log('[필수] .env에 아래 항목을 추가하세요:');
    console.log(`  THREADS_USER_ID=${userId}`);
    console.log('  THREADS_ENABLED=true\n');
}

main()
    .catch((e) => {
        console.error('[예외]', e.message);
        process.exit(1);
    })
    .finally(() => {
        rl.close();
        redis.disconnect();
    });
