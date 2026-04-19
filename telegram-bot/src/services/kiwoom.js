'use strict';

/**
 * services/kiwoom.js
 * Java api-orchestrator REST API 호출 래퍼
 */

const axios = require('axios');

const BASE_URL = process.env.API_ORCHESTRATOR_BASE_URL;

if (!BASE_URL) {
    throw new Error('API_ORCHESTRATOR_BASE_URL is required');
}

const api = axios.create({
    baseURL: BASE_URL,
    timeout: 10_000,
    headers: { 'Content-Type': 'application/json' },
});

/** 헬스체크 */
async function health() {
    const { data } = await api.get('/api/trading/health');
    return data;
}

/** 당일 신호 목록 */
async function getTodaySignals() {
    const { data } = await api.get('/api/trading/signals/today');
    return data;
}

/** 당일 통계 */
async function getTodayStats() {
    const { data } = await api.get('/api/trading/signals/stats');
    return data;
}

/** 후보 종목 목록 */
async function getCandidates(market = '000') {
    const { data } = await api.get('/api/trading/candidates', { params: { market } });
    return data;
}

/** 토큰 수동 갱신 */
async function refreshToken() {
    const { data } = await api.post('/api/trading/token/refresh');
    return data;
}

/** 전술 수동 실행 */
async function runStrategy(strategy, params = {}) {
    const s = strategy.toLowerCase();
    // s1~s15 모두 동일한 URL 패턴 사용
    const valid = ['s1','s2','s3','s4','s5','s6','s7','s8','s9','s10','s11','s12','s13','s14','s15'];
    if (!valid.includes(s)) {
        throw new Error(`알 수 없는 전술: ${strategy}. 사용 가능: s1~s15`);
    }
    const url = `/api/trading/strategy/${s}/run`;
    const { data } = await api.post(url, null, { params });
    return data;
}

/** WebSocket 구독 시작 */
async function startWs() {
    const { data } = await api.post('/api/trading/ws/start');
    return data;
}

/** WebSocket 구독 해제 */
async function stopWs() {
    const { data } = await api.post('/api/trading/ws/stop');
    return data;
}

/** Feature 1 – 성과 목록 */
async function getSignalPerformance() {
    const { data } = await api.get('/api/trading/signals/performance');
    return data;
}

/** Feature 1 – 성과 요약 */
async function getPerformanceSummary() {
    const { data } = await api.get('/api/trading/signals/performance/summary');
    return data;
}

/** Feature 3 – 종목별 신호 이력 */
async function getSignalHistory(stkCd, days = 7) {
    const { data } = await api.get(`/api/trading/signals/stock/${stkCd}`, { params: { days } });
    return data;
}

/** Feature 3 – 전략별 성과 분석 */
async function getStrategyAnalysis() {
    const { data } = await api.get('/api/trading/signals/strategy-analysis');
    return data;
}

/** Feature 5 – 시스템 모니터링 헬스 */
async function getMonitorHealth() {
    const { data } = await api.get('/api/trading/monitor/health');
    return data;
}

/** 이번 주 경제 캘린더 */
async function getCalendarWeek() {
    const { data } = await api.get('/api/trading/calendar/week');
    return data;
}

/** 종목 오버나잇 점수 조회 (개인 수동 확인용) */
async function scoreStock(stkCd) {
    const { data } = await api.get(`/api/trading/score/${stkCd}`);
    return data;
}

/** 매매 제어 수동 전환 (mode: CONTINUE | CAUTIOUS | PAUSE) */
async function setTradingControl(mode) {
    const { data } = await api.post(`/api/trading/control/${mode}`);
    return data;
}

/** 전략별 후보 풀 크기 조회 (Java orchestrator) */
async function getCandidatePoolStatus() {
    const { data } = await api.get('/api/trading/candidates/pool-status');
    return data;
}

/** ai-engine /candidates 엔드포인트 — Java down 시 fallback 또는 보조 확인 */
async function getAiEngineCandidates() {
    const AI_ENGINE_URL = process.env.AI_ENGINE_URL || 'http://ai-engine:8082';
    const axios = require('axios');
    const { data } = await axios.get(`${AI_ENGINE_URL}/candidates`, { timeout: 5000 });
    // pools 필드를 Java getCandidatePoolStatus() 형식(s1_001 등)으로 변환
    const normalized = {};
    for (const [key, count] of Object.entries(data.pools || {})) {
        // "candidates:s1:001" → "s1_001"
        const m = key.match(/^candidates:(s\d+):(\d+)$/);
        if (m) normalized[`${m[1]}_${m[2]}`] = count;
    }
    return normalized;
}

/** /claude {code} — ai-engine Claude 종목 분석 요청 */
async function analyzeStockWithClaude(stkCd) {
    const AI_ENGINE_URL = process.env.AI_ENGINE_URL || 'http://ai-engine:8082';
    const { data } = await axios.get(`${AI_ENGINE_URL}/analyze/${stkCd}`, { timeout: 40_000 });
    return data;
}

/**
 * /score {code} — ai-engine 15전략 심사 + 규칙/AI 스코어링
 * @param {string} stkCd 6자리 종목코드
 * @param {boolean} enableAi  AI 스코어링 활성화 여부 (기본 true)
 * @returns {Promise<Object>} { stk_cd, stk_nm, no_match, matched_count, results, skipped, data }
 */
async function scoreStockFull(stkCd, enableAi = true) {
    const AI_ENGINE_URL = process.env.AI_ENGINE_URL || 'http://ai-engine:8082';
    const aiParam = enableAi ? 'true' : 'false';
    const { data } = await axios.get(
        `${AI_ENGINE_URL}/score/${stkCd}?ai=${aiParam}`,
        { timeout: 60_000 },   // AI 분석 포함 최대 60초
    );
    return data;
}

/** /news 즉시 브리핑 */
async function getLiveNewsBrief(slot) {
    const AI_ENGINE_URL = process.env.AI_ENGINE_URL || 'http://ai-engine:8082';
    const params = slot ? { slot } : undefined;
    const { data } = await axios.get(
        `${AI_ENGINE_URL}/news/brief`,
        { params, timeout: 40_000 },
    );
    return data;
}

module.exports = {
    health, getTodaySignals, getTodayStats,
    getCandidates, refreshToken, runStrategy,
    startWs, stopWs,
    getSignalPerformance, getPerformanceSummary,
    getSignalHistory, getStrategyAnalysis,
    getMonitorHealth, getCalendarWeek, setTradingControl,
    scoreStock, getCandidatePoolStatus, getAiEngineCandidates,
    analyzeStockWithClaude, scoreStockFull, getLiveNewsBrief,
};
