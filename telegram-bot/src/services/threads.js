'use strict';

const axios  = require('axios');
const { getClient } = require('./redis');
const { getLogger } = require('../utils/logger');

const logger = getLogger('threads');

const BASE_URL = 'https://graph.threads.net/v1.0';

const TOKEN_KEY   = 'threads:access_token';
const EXPIRY_KEY  = 'threads:token_expiry';
const REFRESH_KEY = 'threads:token_refreshed';

const REFRESH_BEFORE_SEC = 10 * 24 * 60 * 60; // 만료 10일 전 갱신
const TOKEN_TTL_SEC      = 60 * 24 * 60 * 60; // 기본 60일
const DAILY_POST_LIMIT   = 250;               // Threads API 일일 게시 한도

// ── 에러 코드 분류 ────────────────────────────────────────────────────────
// https://developers.facebook.com/docs/graph-api/guides/error-handling
const THREADS_ERROR = {
    TOKEN_EXPIRED:    190,  // 토큰 만료/무효 → 즉시 갱신 후 재시도
    RATE_LIMIT:        32,  // 앱 레이트 리밋 초과 → 대기 후 재시도
    APP_RATE_LIMIT:    36,  // 앱 요청 한도 초과 → 대기 후 재시도
    PERMISSION:        10,  // 권한 없음 → 재시도 불가
};
const RATE_LIMIT_BACKOFF_MS = 60_000; // 레이트 리밋 대기 60초

function _extractErrorCode(e) {
    // axios 응답 에러: e.response.data.error.code
    const code = e?.response?.data?.error?.code ?? e?.response?.data?.code;
    return typeof code === 'number' ? code : null;
}

function _isRateLimit(code) {
    return code === THREADS_ERROR.RATE_LIMIT || code === THREADS_ERROR.APP_RATE_LIMIT;
}

// ── 일일 게시 카운터 (Redis, KST 기준 자정 만료) ─────────────────────────

function _dailyCountKey() {
    const d = new Date(Date.now() + 9 * 60 * 60 * 1000); // UTC→KST
    const yyyy = d.getUTCFullYear();
    const mm   = String(d.getUTCMonth() + 1).padStart(2, '0');
    const dd   = String(d.getUTCDate()).padStart(2, '0');
    return `threads:daily_count:${yyyy}-${mm}-${dd}`;
}

/** KST 자정까지 남은 초 계산 */
function _secondsUntilKstMidnight() {
    const nowUtcMs    = Date.now();
    const kstMs       = nowUtcMs + 9 * 60 * 60 * 1000;
    const kstDate     = new Date(kstMs);
    const kstMidnight = new Date(
        Date.UTC(kstDate.getUTCFullYear(), kstDate.getUTCMonth(), kstDate.getUTCDate() + 1)
    ).getTime() - 9 * 60 * 60 * 1000; // KST 자정 → UTC ms
    return Math.max(60, Math.ceil((kstMidnight - nowUtcMs) / 1000));
}

/**
 * 일일 한도 확인 후 카운터 증가.
 * @returns {Promise<boolean>} true = 게시 가능, false = 한도 초과
 */
async function _checkAndIncrDailyCount() {
    const redis = getClient();
    const key   = _dailyCountKey();
    const count = await redis.incr(key);
    if (count === 1) {
        // 첫 게시 시 KST 자정까지 TTL 설정
        await redis.expire(key, _secondsUntilKstMidnight());
    }
    if (count > DAILY_POST_LIMIT) {
        // 초과분 되돌림 (카운터 오염 방지)
        await redis.decr(key);
        return false;
    }
    return true;
}

async function getDailyPostCount() {
    const count = await getClient().get(_dailyCountKey());
    return Number(count ?? 0);
}

// ── 토큰 관리 ────────────────────────────────────────────────────────────

async function getStoredToken() {
    return getClient().get(TOKEN_KEY);
}

async function _shouldRefresh() {
    const expiry = await getClient().get(EXPIRY_KEY);
    if (!expiry) return true;
    const nowSec = Math.floor(Date.now() / 1000);
    return (Number(expiry) - nowSec) < REFRESH_BEFORE_SEC;
}

async function refreshToken() {
    const token = await getStoredToken();
    if (!token) throw new Error('threads:access_token not set in Redis — run scripts/threads_auth.js first');

    const res = await axios.get('https://graph.threads.net/refresh_access_token', {
        params: { grant_type: 'th_refresh_token', access_token: token },
        timeout: 10_000,
    });

    const newToken  = res.data.access_token;
    const expiresIn = res.data.expires_in ?? TOKEN_TTL_SEC;
    const nowSec    = Math.floor(Date.now() / 1000);
    const redis     = getClient();

    await redis.set(TOKEN_KEY,   newToken);
    await redis.set(EXPIRY_KEY,  String(nowSec + expiresIn));
    await redis.set(REFRESH_KEY, String(nowSec));

    logger.info('threads token refreshed', { expires_in_days: Math.floor(expiresIn / 86400) });
    return newToken;
}

async function _getToken() {
    if (await _shouldRefresh()) {
        try { return await refreshToken(); }
        catch (e) { logger.error('token refresh failed, falling back to stored token', {}, e); }
    }
    const token = await getStoredToken();
    if (!token) throw new Error('Threads access token not configured — run scripts/threads_auth.js');
    return token;
}

// ── 2단계 게시 ───────────────────────────────────────────────────────────

async function _createContainer(text, token, userId) {
    const res = await axios.post(
        `${BASE_URL}/${userId}/threads`,
        null,
        {
            params: { media_type: 'TEXT', text, access_token: token },
            timeout: 15_000,
        }
    );
    const id = res.data?.id;
    if (!id) throw new Error(`container id missing: ${JSON.stringify(res.data)}`);
    return id;
}

async function _publishContainer(containerId, token, userId) {
    const res = await axios.post(
        `${BASE_URL}/${userId}/threads_publish`,
        null,
        {
            params: { creation_id: containerId, access_token: token },
            timeout: 15_000,
        }
    );
    const id = res.data?.id;
    if (!id) throw new Error(`publish id missing: ${JSON.stringify(res.data)}`);
    return id;
}

/**
 * 텍스트 포스트 발행 — 에러 코드별 분기 처리 포함
 *
 * 에러 코드 처리:
 *   190 (토큰 만료)  → 즉시 토큰 갱신 후 1회 재시도
 *   32/36 (레이트 리밋) → 60초 대기 후 재시도
 *   10 (권한 없음)   → 즉시 중단 (재시도 없음)
 *
 * 일일 한도:
 *   Redis 카운터(KST 기준)로 250건 초과 시 스킵
 *
 * @param {string} text      게시할 plain text (450자 이내 권장)
 * @param {number} [retries] 최대 재시도 횟수 (기본 3)
 * @returns {Promise<string>} 게시된 threads post id
 */
async function postText(text, retries = 3) {
    const userId = process.env.THREADS_USER_ID;
    if (!userId) throw new Error('THREADS_USER_ID not set in environment');

    // ── 일일 한도 확인 ──────────────────────────────────────────────
    const allowed = await _checkAndIncrDailyCount();
    if (!allowed) {
        logger.warn('threads daily post limit reached', {
            limit: DAILY_POST_LIMIT,
            key:   _dailyCountKey(),
        });
        return null;
    }

    let lastErr;
    let tokenRefreshed  = false;
    let rateLimitRetried = false;

    for (let attempt = 1; attempt <= retries; attempt++) {
        try {
            const token       = await _getToken();
            const containerId = await _createContainer(text, token, userId);

            // Meta 권장: 컨테이너 생성 후 500ms 대기
            await new Promise((r) => setTimeout(r, 500));

            const postId = await _publishContainer(containerId, token, userId);
            logger.info('threads post published', {
                post_id: postId,
                chars:   text.length,
                attempt,
            });
            return postId;

        } catch (e) {
            lastErr = e;
            const code = _extractErrorCode(e);

            // ── 에러 코드별 분기 ──────────────────────────────────
            if (code === THREADS_ERROR.PERMISSION) {
                // 권한 없음: 재시도해도 의미 없음
                logger.error('threads permission denied (code 10) — check app permissions', { code }, e);
                throw e;
            }

            if (code === THREADS_ERROR.TOKEN_EXPIRED && !tokenRefreshed) {
                // 토큰 만료: 즉시 갱신 후 1회 재시도
                logger.warn('threads token expired (code 190), refreshing token');
                try {
                    await refreshToken();
                    tokenRefreshed = true;
                    continue; // 갱신 후 루프 재진입 (attempt 유지)
                } catch (refreshErr) {
                    logger.error('token refresh failed after 190 error', {}, refreshErr);
                    throw refreshErr;
                }
            }

            if (_isRateLimit(code)) {
                if (rateLimitRetried) {
                    // 레이트 리밋 재시도는 1회로 제한 — 반복 대기 방지
                    logger.error(`threads rate limited (code ${code}) after 1 retry — aborting`, { attempt }, e);
                    throw e;
                }
                logger.warn(`threads rate limited (code ${code}), waiting ${RATE_LIMIT_BACKOFF_MS}ms`, { attempt });
                rateLimitRetried = true;
                await new Promise((r) => setTimeout(r, RATE_LIMIT_BACKOFF_MS));
                continue;
            }

            // 그 외 일반 오류: 지수 백오프 재시도
            if (attempt < retries) {
                const delayMs = 1000 * Math.pow(2, attempt - 1); // 1s, 2s, 4s
                logger.warn(`threads attempt ${attempt}/${retries} failed (code ${code ?? 'unknown'}), retry in ${delayMs}ms`, {
                    error: e.message,
                });
                await new Promise((r) => setTimeout(r, delayMs));
            }
        }
    }

    logger.error('threads post failed after all retries', { retries }, lastErr);
    throw lastErr;
}

// ── 토큰 갱신 스케줄러 ───────────────────────────────────────────────────

/**
 * 6시간 주기로 토큰 만료 여부를 점검하고 필요 시 갱신.
 * startPolling() 호출 시 THREADS_ENABLED=true 일 때만 등록.
 */
function startTokenRefreshScheduler() {
    const CHECK_MS = 6 * 60 * 60 * 1000;
    setInterval(async () => {
        try {
            if (await _shouldRefresh()) {
                logger.info('threads token nearing expiry, refreshing');
                await refreshToken();
            }
        } catch (e) {
            logger.error('scheduled threads token refresh failed', {}, e);
        }
    }, CHECK_MS);
    logger.info('threads token refresh scheduler started', { check_interval_h: 6 });
}

module.exports = {
    postText,
    refreshToken,
    getStoredToken,
    getDailyPostCount,
    startTokenRefreshScheduler,
};
