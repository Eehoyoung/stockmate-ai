'use strict';

/**
 * services/kiwoom.js
 * Java api-orchestrator REST API 호출 래퍼
 */

const axios = require('axios');

const BASE_URL = process.env.API_BASE_URL ?? 'http://localhost:8080';

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
    const map = {
        s1: '/api/trading/strategy/s1/run',
        s2: '/api/trading/strategy/s2/run',
        s3: '/api/trading/strategy/s3/run',
        s4: '/api/trading/strategy/s4/run',
        s5: '/api/trading/strategy/s5/run',
        s6: '/api/trading/strategy/s6/run',
        s7: '/api/trading/strategy/s7/run',
    };
    const url = map[strategy.toLowerCase()];
    if (!url) throw new Error(`알 수 없는 전술: ${strategy}. 사용 가능: s1~s7`);
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

/** Feature 2 – 오늘 경제 이벤트 */
async function getCalendarToday() {
    const { data } = await api.get('/api/trading/calendar/today');
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

/** 매매 제어 수동 전환 (mode: CONTINUE | CAUTIOUS | PAUSE) */
async function setTradingControl(mode) {
    const { data } = await api.post(`/api/trading/control/${mode}`);
    return data;
}

module.exports = {
    health, getTodaySignals, getTodayStats,
    getCandidates, refreshToken, runStrategy,
    startWs, stopWs,
    getSignalPerformance, getPerformanceSummary,
    getCalendarToday, getSignalHistory, getStrategyAnalysis,
    getMonitorHealth, getCalendarWeek, setTradingControl,
};
