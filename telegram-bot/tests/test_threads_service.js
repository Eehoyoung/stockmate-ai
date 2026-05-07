'use strict';

/**
 * test_threads_service.js — threads.js 서비스 단위 테스트
 * 실행: node telegram-bot/tests/test_threads_service.js
 *
 * 외부 의존성(axios, Redis) 전부 인라인 mock으로 대체.
 */

// ── 인라인 Mock 설정 ─────────────────────────────────────────────────────

// axios mock
const axiosMock = {
    _nextPostResponse: null,
    _postCallCount: 0,
    _getResponse: { data: { access_token: 'refreshed-token', expires_in: 5184000 } },

    post: async (url) => {
        axiosMock._postCallCount++;
        if (axiosMock._nextPostResponse) {
            const resp = axiosMock._nextPostResponse;
            axiosMock._nextPostResponse = null;
            if (resp instanceof Error) throw resp;
            return resp;
        }
        if (url.includes('threads_publish')) return { data: { id: 'post-ok' } };
        return { data: { id: 'container-ok' } };
    },

    get: async () => axiosMock._getResponse,

    reset() {
        this._nextPostResponse = null;
        this._postCallCount    = 0;
    },
};

// Redis mock
const redisMock = {
    _store: {},
    get:    async (k)    => redisMock._store[k] ?? null,
    set:    async (k, v) => { redisMock._store[k] = String(v); },
    incr:   async (k)    => { redisMock._store[k] = String((Number(redisMock._store[k] ?? 0)) + 1); return Number(redisMock._store[k]); },
    decr:   async (k)    => { redisMock._store[k] = String((Number(redisMock._store[k] ?? 0)) - 1); return Number(redisMock._store[k]); },
    expire: async ()     => 1,
    reset() { this._store = {}; },
};

// Module mock 주입
const Module  = require('module');
const origRes = Module._resolveFilename.bind(Module);
Module._resolveFilename = function (req, parent, ...rest) {
    if (req === 'axios') return '__mock_axios__';
    const resolved = origRes(req, parent, ...rest);
    return resolved;
};
require.cache['__mock_axios__'] = {
    id: '__mock_axios__', filename: '__mock_axios__', loaded: true, exports: axiosMock,
};

// threads.js 로드 전 redis mock 주입을 위해 redis 서비스 경로를 미리 패치
const path    = require('path');
const redisSvcPath = path.resolve(__dirname, '../src/services/redis.js');
require.cache[redisSvcPath] = {
    id: redisSvcPath, filename: redisSvcPath, loaded: true,
    exports: { getClient: () => redisMock },
};
const loggerSvcPath = path.resolve(__dirname, '../src/utils/logger.js');
require.cache[loggerSvcPath] = {
    id: loggerSvcPath, filename: loggerSvcPath, loaded: true,
    exports: {
        getLogger: () => ({
            info:  () => {},
            warn:  () => {},
            error: () => {},
        }),
    },
};

process.env.THREADS_USER_ID = 'test-user-123';
const threadsPath = path.resolve(__dirname, '../src/services/threads.js');
// 캐시 제거 후 신선 로드
delete require.cache[threadsPath];
const threadsService = require(threadsPath);

// ── 테스트 헬퍼 ─────────────────────────────────────────────────────────
let pass = 0, fail = 0;

async function test(name, fn) {
    try {
        await fn();
        console.log(`  PASS  ${name}`);
        pass++;
    } catch (e) {
        console.error(`  FAIL  ${name}`);
        console.error(`        ${e.message}`);
        fail++;
    } finally {
        axiosMock.reset();
        redisMock.reset();
    }
}

function assert(cond, msg) {
    if (!cond) throw new Error(msg || 'assertion failed');
}

function makeApiError(code) {
    const err = new Error(`Threads API error ${code}`);
    err.response = { data: { error: { code } } };
    return err;
}

// ── 토큰 설정 헬퍼 ──────────────────────────────────────────────────────
async function setToken(token = 'valid-token', expiryOffsetSec = 999999) {
    await redisMock.set('threads:access_token', token);
    await redisMock.set('threads:token_expiry', String(Math.floor(Date.now() / 1000) + expiryOffsetSec));
}

// ── 테스트 본문 ─────────────────────────────────────────────────────────
console.log('\n[threads_service 단위 테스트]\n');

(async () => {

    // TC1: 정상 게시 흐름 (container → publish)
    await test('TC1  정상 게시 — container + publish 순서', async () => {
        await setToken();
        let containerCalled = false, publishCalled = false;
        axiosMock.post = async (url) => {
            if (url.includes('threads_publish')) { publishCalled = true; return { data: { id: 'post-1' } }; }
            containerCalled = true; return { data: { id: 'ctn-1' } };
        };
        const postId = await threadsService.postText('테스트 게시물');
        assert(containerCalled, 'container 엔드포인트 미호출');
        assert(publishCalled,   'publish 엔드포인트 미호출');
        assert(postId === 'post-1', `예상 post id 'post-1', 실제: ${postId}`);
        axiosMock.post = axiosMock.post; // 원복은 reset()에서
    });

    // TC2: 에러 코드 190 → 토큰 갱신 후 재시도
    await test('TC2  에러 190 (토큰 만료) → 즉시 갱신 후 재시도', async () => {
        await setToken('expired-token');
        let callCount = 0;
        axiosMock.post = async (url) => {
            callCount++;
            // 첫 번째 container 호출에서 190 에러
            if (callCount === 1) throw makeApiError(190);
            if (url.includes('threads_publish')) return { data: { id: 'post-after-refresh' } };
            return { data: { id: 'ctn-after-refresh' } };
        };
        axiosMock.get = async () => ({ data: { access_token: 'new-token', expires_in: 5184000 } });

        const postId = await threadsService.postText('토큰 갱신 후 게시');
        assert(postId === 'post-after-refresh', `재시도 후 게시 실패: ${postId}`);
        // 갱신된 토큰이 Redis에 저장됐는지 확인
        const stored = await redisMock.get('threads:access_token');
        assert(stored === 'new-token', `갱신 토큰 미저장: ${stored}`);
    });

    // TC3: 에러 코드 10 (권한 없음) → 즉시 throw, 재시도 없음
    await test('TC3  에러 10 (권한 없음) → 즉시 중단', async () => {
        await setToken();
        let callCount = 0;
        axiosMock.post = async () => { callCount++; throw makeApiError(10); };
        let threw = false;
        try {
            await threadsService.postText('권한 없음 테스트');
        } catch (_) { threw = true; }
        assert(threw, '에러 10에서 throw 없음');
        assert(callCount === 1, `에러 10에서 재시도 발생 (callCount=${callCount})`);
    });

    // TC4: 일일 250건 한도 — 250회 성공, 251회 null 반환
    await test('TC4  일일 250건 한도 초과 시 null 반환', async () => {
        await setToken();
        // 카운터를 250으로 직접 설정
        const key = `threads:daily_count:${(() => {
            const d = new Date(Date.now() + 9 * 60 * 60 * 1000);
            return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`;
        })()}`;
        await redisMock.set(key, '250');

        axiosMock.post = async (url) => {
            if (url.includes('threads_publish')) return { data: { id: 'post-x' } };
            return { data: { id: 'ctn-x' } };
        };

        const result = await threadsService.postText('251번째 게시');
        assert(result === null, `한도 초과 시 null 반환 기대, 실제: ${result}`);
    });

    // TC5: 일일 카운터 첫 게시 시 TTL 설정 확인
    await test('TC5  일일 카운터 첫 게시 — TTL 설정', async () => {
        await setToken();
        let expireCalled = false;
        redisMock.expire = async () => { expireCalled = true; return 1; };
        axiosMock.post = async (url) => {
            if (url.includes('threads_publish')) return { data: { id: 'p1' } };
            return { data: { id: 'c1' } };
        };
        await threadsService.postText('카운터 첫 게시');
        assert(expireCalled, 'Redis expire 미호출 — TTL 미설정');
        redisMock.expire = async () => 1; // 원복
    });

    // TC6: THREADS_USER_ID 없으면 즉시 에러
    await test('TC6  THREADS_USER_ID 없으면 즉시 throw', async () => {
        const original = process.env.THREADS_USER_ID;
        delete process.env.THREADS_USER_ID;
        let threw = false;
        try { await threadsService.postText('유저 없음'); }
        catch (_) { threw = true; }
        assert(threw, 'USER_ID 없을 때 throw 없음');
        process.env.THREADS_USER_ID = original;
    });

    // TC7: getStoredToken — 저장된 토큰 반환
    await test('TC7  getStoredToken — Redis에서 토큰 조회', async () => {
        await redisMock.set('threads:access_token', 'my-token');
        const tok = await threadsService.getStoredToken();
        assert(tok === 'my-token', `기대 'my-token', 실제: ${tok}`);
    });

    // TC8: getDailyPostCount — 오늘 게시 수 반환
    await test('TC8  getDailyPostCount — 오늘 게시 수 조회', async () => {
        await setToken();
        axiosMock.post = async (url) => {
            if (url.includes('threads_publish')) return { data: { id: 'px' } };
            return { data: { id: 'cx' } };
        };
        await threadsService.postText('카운트 1');
        await threadsService.postText('카운트 2');
        const cnt = await threadsService.getDailyPostCount();
        assert(cnt === 2, `게시 수 기대 2, 실제: ${cnt}`);
    });

})().then(() => {
    console.log(`\n결과: ${pass}통과 / ${fail}실패\n`);
    if (fail > 0) process.exit(1);
}).catch((e) => {
    console.error('테스트 실행 오류:', e.message);
    process.exit(1);
});
