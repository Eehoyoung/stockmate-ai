'use strict';

const { normalizeForDisplay } = require('./price');

/**
 * formatter.js
 * ai_scored_queue 항목을 텔레그램 메시지로 변환
 */

const STRATEGY_EMOJI = {
    S1_GAP_OPEN:        '🚀',
    S2_VI_PULLBACK:     '🎯',
    S3_INST_FRGN:       '🏦',
    S4_BIG_CANDLE:      '📊',
    S5_PROG_FRGN:       '💻',
    S6_THEME_LAGGARD:   '🔥',
    S7_ICHIMOKU_BREAKOUT:         '☁️',
    S8_GOLDEN_CROSS:    '📈',
    S9_PULLBACK_SWING:  '🔽',
    S10_NEW_HIGH:       '🏔',
    S11_FRGN_CONT:      '🌏',
    S12_CLOSING:        '🌙',
    S13_BOX_BREAKOUT:   '📦',
    S14_OVERSOLD_BOUNCE:'🔄',
    S15_MOMENTUM_ALIGN: '🔥',
    S16_ACCUMULATION_SHADOW: '🧭',
};

const STRATEGY_DESC = {
    S1_GAP_OPEN:        '갭 상승 개장 (전일 대비 갭 3~15%)',
    S2_VI_PULLBACK:     '변동성완화장치 발동 후 눌림목 반등',
    S3_INST_FRGN:       '기관+외국인 동시 순매수',
    S4_BIG_CANDLE:      '장대양봉 + 거래량 급증',
    S5_PROG_FRGN:       '프로그램+외국인 동반 매수',
    S6_THEME_LAGGARD:   '테마주 후발 소외주 갭 상승',
    S7_ICHIMOKU_BREAKOUT:         '일목균형표 구름대 돌파 스윙',
    S8_GOLDEN_CROSS:    '5일선·20일선 골든크로스 + 거래량 확인',
    S9_PULLBACK_SWING:  '정배열 내 5일선 눌림목 반등',
    S10_NEW_HIGH:       '52주 신고가 돌파 + 거래량 급증',
    S11_FRGN_CONT:      '외국인 연속 3일 이상 순매수',
    S12_CLOSING:        '장 마감 30분 종가강도 매집',
    S13_BOX_BREAKOUT:   '박스권 상단 돌파 + 거래량 폭발',
    S14_OVERSOLD_BOUNCE:'상대강도지수 과매도 구간 반등 신호',
    S15_MOMENTUM_ALIGN: '다중 모멘텀 정렬 상승 (상대강도·이동평균·거래량)',
    S16_ACCUMULATION_SHADOW: '세력 매집 의심 박스 돌파/첫 눌림 트리거',
};

const STRATEGY_LABEL = {
    S1_GAP_OPEN: '갭 상승 개장', S2_VI_PULLBACK: '변동성완화장치 눌림목',
    S3_INST_FRGN: '기관·외국인 동반 매수', S4_BIG_CANDLE: '장대양봉',
    S5_PROG_FRGN: '프로그램·외국인 동반 매수', S6_THEME_LAGGARD: '테마 후발주',
    S7_ICHIMOKU_BREAKOUT: '일목균형표 돌파', S8_GOLDEN_CROSS: '골든크로스',
    S9_PULLBACK_SWING: '정배열 눌림목', S10_NEW_HIGH: '52주 신고가',
    S11_FRGN_CONT: '외국인 연속 매수', S12_CLOSING: '종가 강도',
    S13_BOX_BREAKOUT: '박스권 돌파', S14_OVERSOLD_BOUNCE: '과매도 반등',
    S15_MOMENTUM_ALIGN: '다중 모멘텀 정렬', S16_ACCUMULATION_SHADOW: '매집 돌파',
};

const FAMILY_LABEL = {
    G01: '세션·이벤트',
    G02: '수급추세',
    G03: '축적확인',
    G04: '추세단계',
    G05: '구조돌파',
    G06: '장중급등·테마',
    G07: '역추세반등',
};

const DAY_STRATEGIES = new Set([
    'S1_GAP_OPEN', 'S2_VI_PULLBACK', 'S4_BIG_CANDLE', 'S6_THEME_LAGGARD',
]);

function _holdingType(strategy) {
    if (strategy === 'S12_CLOSING') return '익일 보유형';
    return DAY_STRATEGIES.has(strategy) ? '당일 단기형' : '스윙형';
}

function _marketLabel(value) {
    const normalized = String(value || '').trim().toUpperCase();
    if (['001', '0', 'KOSPI'].includes(normalized)) return '코스피';
    if (['101', '10', 'KOSDAQ'].includes(normalized)) return '코스닥';
    return value ? _humanizeTerms(value) : null;
}

function _chaseRiskLabel(value) {
    const normalized = String(value || '').trim().toUpperCase();
    return { LOW: '낮음', MEDIUM: '보통', HIGH: '높음' }[normalized]
        || (value == null ? null : _humanizeTerms(value));
}

function _humanizeTerms(value) {
    return String(value ?? '')
        .replace(/effective_rr/gi, '비용 반영 손익비')
        .replace(/rr_ratio/gi, '손익비')
        .replace(/R\s*:\s*R/gi, '손익비')
        .replace(/\bRR\b/gi, '손익비')
        .replace(/\bTP1\b/gi, '1차 목표가')
        .replace(/\bTP2\b/gi, '2차 목표가')
        .replace(/\bSL\b/gi, '손절가')
        .replace(/\bsetup\b/gi, '세부전략')
        .replace(/\bminimum\b/gi, '최소 기준')
        .replace(/\s+below\s+/gi, ' 미만 ')
        .replace(/\bWATCH until\b/gi, '관찰 유지:')
        .replace(/\bWATCH\b/gi, '관찰')
        .replace(/\bkiwoom_ws\b/gi, '키움 실시간')
        .replace(/\bkiwoom_rest\b/gi, '키움 조회')
        .replace(/\btoss\b/gi, '토스 조회')
        .replace(/\bRSI\b/gi, '상대강도지수')
        .replace(/\bMA(\d+)\b/gi, '$1일선')
        .replace(/\b5D\b/gi, '최근 5일')
        .replace(/\bbull\b/gi, '상승장')
        .replace(/\bbear\b/gi, '하락장')
        .replace(/\bsideways\b/gi, '횡보장')
        .replace(/\bneutral\b/gi, '중립장')
        .replace(/([\d.]+)x\b/gi, '$1배');
}

function _dataQualityLabel(value) {
    const normalized = String(value || '').toUpperCase();
    return {
        OK: '정상',
        DEGRADED: '보조정보 부족',
        BLOCKED: '진입 차단',
    }[normalized] || '확인 필요';
}

function _enterText(value) {
    return _humanizeTerms(value)
        .replace(/\bVWAP\b/gi, '거래량가중평균가')
        .replace(/\bMACD\b/gi, '이동평균수렴확산')
        .replace(/\bADX\b/gi, '추세강도')
        .replace(/\bOBV\b/gi, '누적거래량')
        .replace(/\b[A-Za-z][A-Za-z0-9_]*\b/g, '내부 지표');
}

/**
 * HTML 특수문자 이스케이프 (Telegram HTML parse_mode 안전 출력용)
 * @param {*} str
 * @returns {string}
 */
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

const ACTION_LABEL = {
    ENTER:  '✅ 진입',
    HOLD:   '⏸️ 관망',
    CANCEL: '❌ 취소',
};

const CONFIDENCE_LABEL = {
    HIGH:   '🔴 높음',
    MEDIUM: '🟡 보통',
    LOW:    '⚪ 낮음',
};

const SIGNAL_STAGE_LABEL = {
    WATCH:  '관찰',
    HOLD:   '관망',
    ENTRY:  '조건 충족 확인',
    CANCEL: '취소',
};

function _normalizeSignalStage(stage) {
    const normalized = String(stage || '').trim().toUpperCase();
    return SIGNAL_STAGE_LABEL[normalized] ? normalized : null;
}

function _effectiveAction(item) {
    const readiness = String(item.readiness_action || '').trim().toUpperCase();
    if (readiness === 'ENTER_CANDIDATE') return 'HOLD';
    if (readiness === 'AVOID') return 'CANCEL';
    if (readiness === 'HOLD') return 'HOLD';
    if (readiness === 'ENTER') return 'ENTER';
    const decision = String(item.execution_decision || '').trim().toUpperCase();
    if (decision === 'ENTER') return 'ENTER';
    if (decision === 'WATCH') return 'HOLD';
    if (decision === 'BLOCK') return 'CANCEL';
    const stage = _normalizeSignalStage(item.signal_stage);
    if (stage === 'ENTRY') return 'ENTER';
    if (stage === 'WATCH' || stage === 'HOLD') return 'HOLD';
    if (stage === 'CANCEL') return 'CANCEL';
    return item.action;
}

function _s1EntryConditionLabel(entryType) {
    const raw = String(entryType || '').trim();
    if (!raw) return null;
    if (/market|시장가|매수|buy|entry/i.test(raw)) return '체결강도와 호가 우위 재확인';
    return raw;
}

function _s1ReasonText(reason) {
    return String(reason || '')
        .replace(/신규\s*매수/g, '신규 관찰')
        .replace(/즉시\s*매수/g, '즉시 조건 확인')
        .replace(/시장가\s*매수/g, '시장가 조건 확인')
        .replace(/추격\s*매수/g, '추격 판단')
        .replace(/매수\s*방식/g, '확인 조건')
        .replace(/권장\s*비중/g, '관찰 비중');
}

/**
 * 거래 신호 → 텔레그램 HTML 메시지
 * @param {Object} item  ai_scored_queue 항목
 * @returns {string}
 */
// 수수료+세금+슬리피지 합산 (왕복)
const SLIP_FEE = { KOSPI: 0.0035, KOSDAQ: 0.0045 };

function _slipFee(stkCd) {
    return String(stkCd ?? '').startsWith('0') ? SLIP_FEE.KOSPI : SLIP_FEE.KOSDAQ;
}

// ── 매수/매도 박스(Zone) 표시 ─────────────────────────────────────
const ZONE_STRATEGIES = new Set([
    'S8_GOLDEN_CROSS', 'S9_PULLBACK_SWING', 'S13_BOX_BREAKOUT',
    'S14_OVERSOLD_BOUNCE', 'S15_MOMENTUM_ALIGN',
]);

const STRENGTH_STARS = ['', '☆☆☆☆☆', '★☆☆☆☆', '★★☆☆☆', '★★★☆☆', '★★★★☆', '★★★★★'];

/**
 * 매수/매도 박스 블록 생성 (zone 전략에만 노출)
 * @param {Object} item  signal 객체
 * @param {number} curPrc  현재가
 * @returns {string|null}
 */
function _formatZoneBlock(item, curPrc, targetPrc) {
    if (!ZONE_STRATEGIES.has(item.strategy)) return null;

    const bz = item.buy_zone;
    const sz = item.sell_zone1;
    if (!bz || typeof bz !== 'object') return null;

    const bzLow  = Number(bz.low  || 0);
    const bzHigh = Number(bz.high || 0);
    if (!bzLow || !bzHigh) return null;

    const strength = Math.min(6, Math.max(0, Number(bz.strength || 0)));
    const stars    = STRENGTH_STARS[strength] || '☆☆☆☆☆';

    const rangePct = bzHigh > 0
        ? ((bzHigh - bzLow) / bzLow * 100).toFixed(2)
        : '-';

    const anchors  = Array.isArray(bz.anchors) ? bz.anchors.join(' · ') : '-';

    let posLabel = '';
    if (curPrc > 0 && bzLow > 0 && bzHigh > 0) {
        if (curPrc < bzLow)       posLabel = '박스 미진입';
        else if (curPrc > bzHigh) posLabel = '박스 상단 초과';
        else {
            const pct = ((curPrc - bzLow) / (bzHigh - bzLow) * 100).toFixed(0);
            posLabel  = `박스 내부 (하단 ${pct}%)`;
        }
    }

    const lines = [];
    // 현재가가 이미 매수 구간을 벗어났다면 과거 지지 구간과 그 손익비를
    // 신규 진입 가격처럼 보여주지 않는다.
    const actionableBuyZone = curPrc > 0 && curPrc >= bzLow && curPrc <= bzHigh;
    if (actionableBuyZone) {
        lines.push(
            `▼ 매수 가능 구간 [강도 ${stars}]`,
            `  ${bzLow.toLocaleString()} ━━━━━━━━━━━━ ${bzHigh.toLocaleString()} (${rangePct}%)`,
            `  근거: ${escapeHtml(_zoneAnchors(anchors))}`,
        );
        if (posLabel) lines.push(`  현재가 위치: ${posLabel}`);
    }

    if (sz && typeof sz === 'object') {
        const szLow  = Number(sz.low  || 0);
        const szHigh = Number(sz.high || 0);
        if (szLow > 0 && szHigh > 0) {
            const szRangePct = ((szHigh - szLow) / szLow * 100).toFixed(2);
            const szAnchors  = Array.isArray(sz.anchors) ? sz.anchors.join(' · ') : '-';
            if (lines.length) lines.push('');
            const isIntermediate = Number(targetPrc) > szHigh;
            lines.push(isIntermediate ? '▼ 목표가 전 중간 저항 구간' : '▼ 1차 목표 구간');
            lines.push(`  ${szLow.toLocaleString()} ━━━━━━━━━━━━ ${szHigh.toLocaleString()} (${szRangePct}%)`);
            lines.push(`  근거: ${escapeHtml(_zoneAnchors(szAnchors))}`);
            if (isIntermediate) lines.push('  참고: 1차 목표가가 아니며, 이 구간에서 매물 소화 여부 확인');
        }
    }

    const zoneRRVal = item.zone_rr != null ? Number(item.zone_rr) : null;
    const zoneOK    = zoneRRVal !== null && zoneRRVal >= 1.3 ? '✅' : '⚠️';
    const zoneRRStr = actionableBuyZone && zoneRRVal !== null
        ? `매수구간 기준 손익비: <b>${zoneRRVal.toFixed(2)}</b> ${zoneOK}` : null;
    const rrLine = [zoneRRStr].filter(Boolean).join('  |  ');
    if (rrLine) { lines.push(''); lines.push(rrLine); }

    return lines.length ? lines.join('\n') : null;
}

function _zoneAnchors(value) {
    return String(value || '-')
        .replace(/SWING_LOW/gi, '이전 저점')
        .replace(/SWING_HIGH/gi, '이전 고점')
        .replace(/BB_UPPER/gi, '볼린저 상단')
        .replace(/BB_LOWER/gi, '볼린저 하단')
        .replace(/MA(\d+)/gi, '$1일선')
        .replace(/ATR/gi, '평균 변동폭');
}

/**
 * 거래비용과 예상 체결오차를 반영한 손익비 문자열 반환
 * @returns {string|null}
 */
function _effectiveRR(stkCd, entry, tp1, sl) {
    if (!entry || !tp1 || !sl || sl >= entry) return null;
    const slip = _slipFee(stkCd);
    const effTarget = (tp1 - entry) / entry - slip;
    const effRisk   = (entry - sl)  / entry + slip;
    if (effRisk <= 0) return null;
    const rr = (effTarget / effRisk).toFixed(2);
    const warn = Number(rr) < 1.0 ? ' 주의' : '';
    return `비용 반영 손익비: <b>${rr}</b>${warn}`;
}

function _formatRegimeRR(item, rrVal) {
    const threshold = Number(item.rr_regime_threshold ?? item.market_rr_threshold);
    if (!Number.isFinite(rrVal)) return null;
    const regime = item.rr_regime ? escapeHtml(_regimeLabel(item.rr_regime)) : '';
    if (Number.isFinite(threshold) && threshold > 0) {
        const status = rrVal >= threshold ? '통과' : '주의';
        const regimeText = regime ? `${regime} ` : '';
        return `${regimeText}손익비 판정: <b>${status}</b> (${rrVal.toFixed(2)} / 기준 ${threshold.toFixed(2)})`;
    }
    const status = rrVal < 0.8 ? '주의' : '통과';
    return `현재 장세 손익비: <b>${status}</b> (${rrVal.toFixed(2)})`;
}

function _formatDataQualityLine(item) {
    const quality = item.data_quality || item.dataQuality;
    const ages = item.source_age_ms;
    const parts = [];
    if (quality) parts.push(`데이터 상태 ${_dataQualityLabel(quality)}`);
    if (ages && typeof ages === 'object' && !Array.isArray(ages)) {
        for (const [source, age] of Object.entries(ages).slice(0, 3)) {
            if (age == null) continue;
            const ms = Number(age);
            if (!Number.isFinite(ms) || ms < 0) continue;
            const sourceLabel = {
                hoga: '호가', tick: '현재가', strength: '체결강도',
                entry: '진입가', risk: '위험정보', vi: '변동성완화장치',
            }[source] || '기타 데이터';
            parts.push(`${sourceLabel} ${ms < 1000 ? `${Math.round(ms)}밀리초` : `${(ms / 1000).toFixed(1)}초`} 전`);
        }
    }
    return parts.length ? `데이터: ${parts.join(' · ')}` : null;
}

function _sourceAndAge(item, key) {
    const sources = item.data_source;
    const ages = item.source_age_ms;
    const source = sources && typeof sources === 'object' ? sources[key] : null;
    const rawAge = ages && typeof ages === 'object' ? ages[key] : null;
    const age = rawAge == null ? null : Number(rawAge);
    const details = [];
    if (source) {
        const sourceLabel = { kiwoom_ws: '키움 실시간', kiwoom_rest: '키움 조회', toss: '토스 조회' }[source] || '시장 데이터';
        details.push(`출처 ${sourceLabel}`);
    }
    if (Number.isFinite(age) && age >= 0) {
        details.push(`관측 후 ${age < 1000 ? `${Math.round(age)}밀리초` : `${(age / 1000).toFixed(1)}초`} 경과`);
    }
    return details.length ? ` · ${details.join(' · ')}` : '';
}

function _priceMethod(value) {
    return value ? ` · 산출 근거 ${_compactPriceMethod(value)}` : '';
}

function _compactPriceMethod(value) {
    if (!value) return '';
    return String(value)
        .replace(/single_tp_avg\([^)]*\)/gi, '복수 목표 평균')
        .replace(/rr_fit_[a-z0-9_]+/gi, '손익비 조정')
        .replace(/swing_resistance/gi, '스윙 저항')
        .replace(/prev_swing_high/gi, '이전 고점')
        .replace(/swing_low_D15/gi, '15일 저점')
        .replace(/bollinger_upper/gi, '볼린저 상단')
        .replace(/fib_1272(?:\([^)]*\))?/gi, '피보나치 1.272')
        .replace(/fib_1618(?:\([^)]*\))?/gi, '피보나치 1.618')
        .replace(/MA20_support/gi, '20일선 지지')
        .replace(/\(MA20_gap>6%\)/gi, ' · 20일선 괴리 6% 초과')
        .replace(/MA20/gi, '20일선')
        .replace(/ATR/gi, '평균 변동폭')
        .replace(/single_tp_primary/gi, '단일 목표 적용')
        .replace(/fib_min3pct/gi, '최소 3% 보정')
        .replace(/pct_10%_min/gi, '최소 10% 보정')
        .replace(/min_3pct/gi, '최소 3% 목표')
        .replace(/pct_([\d.]+)%?_fallback/gi, '$1% 기본 목표')
        .replace(/\(×([\d.]+)\)/g, ' ×$1')
        .split('+')
        .map((part) => part.trim())
        .map((part) => /[A-Za-z_]/.test(part) ? '전략 계산' : part)
        .filter(Boolean)
        .filter((part, index, parts) => parts.indexOf(part) === index)
        .join(' · ');
}

function _entryTypeLabel(value) {
    return {
        '당일종가_또는_익일시가': '당일 종가 또는 다음 거래일 시가',
        '시장가': '시장가',
        '지정가': '지정가',
    }[String(value || '')] || '전략 지정 방식';
}

function _strategyLabel(value) {
    return STRATEGY_LABEL[value] || '복합 전략';
}

function _sizeTierLabel(value) {
    return { SIZE_4: '매우 강함', SIZE_3: '강함', SIZE_2: '보통', SIZE_1: '낮음', SIZE_0: '관찰 전용' }[value]
        || '보통';
}

function _regimeLabel(value) {
    return { bull: '상승장', bear: '하락장', neutral: '중립장', sideways: '횡보장' }[String(value || '').toLowerCase()]
        || '현재 장세';
}

function _resolveHoldRrGate(item, reason) {
    for (const value of [item.final_rr_gate, item.rr_regime_threshold, item.market_rr_threshold]) {
        const numeric = Number(value);
        if (Number.isFinite(numeric) && numeric > 0) return numeric;
    }
    const matched = String(reason || '').match(/below\s+([\d.]+)/i);
    if (matched) return Number(matched[1]);
    const advisory = Number(item.min_rr_ratio);
    return Number.isFinite(advisory) && advisory > 0 ? advisory : null;
}

function _shortAge(value) {
    const ms = Number(value);
    if (!Number.isFinite(ms) || ms < 0) return null;
    if (ms < 1000) return '1초 미만';
    if (ms < 10000) return `${(ms / 1000).toFixed(1)}초`;
    return `${Math.round(ms / 1000)}초`;
}

function _priceWithMove(value, entry) {
    const price = normalizeForDisplay(value ?? 0);
    if (!(price > 0)) return '-';
    const base = Number(entry);
    const move = Number.isFinite(base) && base > 0 ? ` (${((price - base) / base * 100) >= 0 ? '+' : ''}${((price - base) / base * 100).toFixed(1)}%)` : '';
    return `${price.toLocaleString()}원${move}`;
}

function _formatDecisionStatus(item) {
    const hardGate = item.hard_gates_passed ?? item.hard_gate_passed;
    const portfolio = item.portfolio_arbitration_passed;
    const parts = [];
    if (hardGate != null) parts.push(`필수조건 ${hardGate ? '통과' : '미통과'}`);
    if (item.data_quality) parts.push(`데이터 상태 ${_dataQualityLabel(item.data_quality)}`);
    if (portfolio != null) parts.push(`중복·노출 검사 ${portfolio ? '통과' : '미통과'}`);
    return parts.length ? `판정 상태: ${parts.join(' · ')}` : null;
}

/**
 * ai_score + confidence 기반 포지션 크기 제안
 */
function _positionSize(aiScore, confidence) {
    const score = Number(aiScore ?? 0);
    const conf  = confidence ?? 'LOW';
    if (score >= 85 && conf === 'HIGH')   return '대';
    if (score >= 75 && conf !== 'LOW')    return '중';
    if (score >= 65)                      return '소';
    return null;
}

/**
 * 스윙 전략 공매도/신용/대차/매수유의사항 (토스) — ai-engine analyzer.py의
 * _fmt_toss_risk_line과 동일한 소스 데이터를 사용자용으로 요약한다.
 * 참고정보일 뿐 진입/청산 판단에 영향을 주지 않는다.
 * @param {object|null} tossRisk
 * @returns {string|null}
 */
function _formatTossRiskLine(tossRisk) {
    if (!tossRisk || typeof tossRisk !== 'object') return null;
    const parts = [];

    const ss = tossRisk.short_selling;
    if (ss && ss.shortSellingAmountRate != null) {
        const rate = Number(ss.shortSellingAmountRate);
        if (!Number.isNaN(rate)) parts.push(`공매도비중 ${(rate * 100).toFixed(1)}%`);
    }

    const credit = tossRisk.credit_trades;
    const balanceRate = credit?.marginLoan?.balanceRate;
    if (balanceRate != null) {
        const rate = Number(balanceRate);
        if (!Number.isNaN(rate)) parts.push(`신용융자잔고 ${(rate * 100).toFixed(2)}%`);
    }

    const lending = tossRisk.securities_lending;
    if (lending && lending.balanceQuantity) {
        parts.push(`대차잔고 ${Number(lending.balanceQuantity).toLocaleString()}주`);
    }

    const warnings = tossRisk.warnings;
    if (Array.isArray(warnings) && warnings.length) {
        const warningLabels = { OVERHEATED: '과열', INVESTMENT_WARNING: '투자 경고', INVESTMENT_RISK: '투자 위험', CAUTION: '주의' };
        const types = [...new Set(warnings.map(w => warningLabels[w?.warningType] || '기타 주의').filter(Boolean))];
        if (types.length) parts.push(`⚠️ 매수유의사항[${types.join(',')}]`);
    }

    if (!parts.length) return null;
    return `토스 리스크: ${parts.join(' | ')}`;
}

/**
 * 최근 30분 시장 전체 수급 추세 (지수 분단위 시계열, 토스) — ai-engine
 * analyzer.py의 _fmt_investor_flow_trend_line과 동일 소스. 스윙 전략에서만 채워진다.
 * @param {object|null} trend
 * @returns {string|null}
 */
function _formatInvestorFlowTrendLine(trend) {
    if (!trend || typeof trend !== 'object') return null;
    const parts = [];
    const labels = { kospi: '코스피', kosdaq: '코스닥' };
    for (const [market, label] of Object.entries(labels)) {
        const data = trend[market];
        if (!data || typeof data !== 'object') continue;
        const fDelta = data.foreigner_net_delta;
        const iDelta = data.institution_net_delta;
        if (fDelta == null && iDelta == null) continue;
        const fmt = (v) => {
            if (v == null) return '자료 없음';
            const eok = Number(v) / 1e8;
            const sign = eok >= 0 ? '+' : '';
            return `${sign}${eok.toFixed(0)}억`;
        };
        parts.push(`${label}(외인${fmt(fDelta)}/기관${fmt(iDelta)})`);
    }
    if (!parts.length) return null;
    return `시장수급추세(최근30분): ${parts.join(' | ')}`;
}

/**
 * 스윙 전략 종합 리스크·수급 블록 — 시장수급 추세와 종목 리스크를 함께 묶는다.
 * 두 필드 모두 같은 스윙 게이트를 공유하므로 데이트레이딩 전략에서는 null.
 * @param {object} item
 * @returns {string[]}
 */
function _formatSwingRiskLines(item) {
    const lines = [];
    const trendLine = _formatInvestorFlowTrendLine(item.investor_flow_trend);
    const riskLine = _formatTossRiskLine(item.toss_risk);
    if (trendLine || riskLine) {
        lines.push('📊 <b>스윙 참고 (시장수급·종목 리스크)</b>');
        if (trendLine) lines.push(trendLine);
        if (riskLine) lines.push(riskLine);
    }
    return lines;
}

function _formatWon(price) {
    const value = Number(price ?? 0);
    if (!value || value <= 0) return null;
    return `${value.toLocaleString()}원`;
}

function _formatPriceOrPct(price, pct, suffix) {
    const won = _formatWon(price);
    if (won) return `${won} ${suffix}`;
    if (pct != null) return `${pct}% 기준 ${suffix}`;
    return `- ${suffix}`;
}

function formatRuleOnlySignal(item) {
    const stockLabel = item.stk_nm
        ? item.stk_nm
        : (item.stk_cd || '-');
    const entry = item.cur_prc ?? item.entry_price;
    const target = item.tp1_price ?? item.display_tp2_price;
    const stop = item.sl_price;
    const targetPct = item.adjusted_target_pct ?? item.target_pct;
    const stopPct = item.adjusted_stop_pct ?? item.stop_pct;

    if (item.strategy === 'S1_GAP_OPEN') {
        return [
            '🚨갭상승 관찰 알림🚨',
            `종목: ${escapeHtml(stockLabel)}`,
            `관찰 기준가: ${_formatPriceOrPct(entry, null, '부근 조건 확인')}`,
            `무효화 기준: ${_formatPriceOrPct(stop, stopPct, '이탈 여부 확인')}`,
            `상단 대응 기준: ${_formatPriceOrPct(target, targetPct, '도달 여부 관찰')}`,
            '확인사항\n1. 갭 상승 이후 체결강도와 호가 유지 여부를 확인합니다.\n2. 급격한 갭 메우기나 거래량 둔화 시 관찰을 중단합니다.\n3. 최종 판단은 사용자의 계획과 리스크 기준에 따릅니다.'
        ].join('\n');
    }

    return [
        '🚨가라급등열차 점장선생🚨',
        `종목: ${escapeHtml(stockLabel)}`,
        `진입가:  ${_formatPriceOrPct(entry, null, '이하 신규매수')}`,
        `손절가:  ${_formatPriceOrPct(stop, stopPct, '손절')}`,
        `목표가 : ${_formatPriceOrPct(target, targetPct, '이상 분할 매도 대응')}`,
        '주의사항\n1. 매수는 필수가 아닙니다. \n2. 비중은 계좌의 10% 이내를 권고합니다. \n3. 투자판단은 개인에게 있습니다.'
    ].join('\n');
}

function formatSignal(item) {
    if (item.signal_grade === 'RULE_ONLY' || item.validation_stage === 'RULE_ONLY' || item.type === 'RULE_ONLY_SIGNAL') {
        return formatRuleOnlySignal(item);
    }

    const effectiveAction = _effectiveAction(item);
    const signalStage = _normalizeSignalStage(item.signal_stage);
    const isS1GapOpen = item.strategy === 'S1_GAP_OPEN';
    const emoji    = STRATEGY_EMOJI[item.strategy] ?? '📌';
    const action   = ACTION_LABEL[effectiveAction]     ?? effectiveAction;
    const conf     = CONFIDENCE_LABEL[item.confidence] ?? '⚪ 확인 필요';
    const aiScore  = (item.ai_score ?? 0).toFixed(1);
    const ruleScore= (item.rule_score ?? 0).toFixed(1);
    const stratDesc = STRATEGY_DESC[item.strategy];

    const stockLabel = item.stk_nm
        ? `${item.stk_nm} (${item.stk_cd})`
        : item.stk_cd;
    const strategyTag = effectiveAction === 'ENTER'
        ? `[${_strategyLabel(item.strategy)}${item.hold_promoted_to_enter ? ' · 관망 후 승격' : ''}]`
        : `[${item.strategy}]`;
    const lines = [
        `${emoji} <b>${strategyTag} ${stockLabel}</b>`,
    ];
    if (item.strategy_family) {
        const familyName = FAMILY_LABEL[item.strategy_family] || '복합 전략';
        const primarySetup = item.primary_setup_id || item.strategy;
        lines.push(`통합전략: <b>${escapeHtml(String(familyName))}</b>`);
        lines.push(`대표 전략: ${escapeHtml(_strategyLabel(primarySetup))} · ${_holdingType(primarySetup)}`);
        const confirmations = item.confirmed_by || item.matched_setup_ids;
        if (Array.isArray(confirmations) && confirmations.length > 1) {
            lines.push(`함께 확인된 전략: ${escapeHtml(confirmations.map(_strategyLabel).join(' · '))}`);
        }
    }
    if (stratDesc) lines.push(`<i>${stratDesc}</i>`);
    if (item.readiness_action && effectiveAction !== 'ENTER') {
        lines.push(`준비 상태: <b>${escapeHtml(_humanizeTerms(item.readiness_action))}</b>`);
        if (Array.isArray(item.readiness_reasons) && item.readiness_reasons.length) {
            lines.push(`판단 근거: ${escapeHtml(_humanizeTerms(item.readiness_reasons.slice(0, 3).join(' | ')))}`);
        }
    }

    // 진입가 표시
    const curPrc = normalizeForDisplay(item.cur_prc ?? item.entry_price ?? 0);
    const formatWon = (price) => `${Number(price).toLocaleString()}원`;
    const formatMove = (price) => {
        if (!(curPrc > 0) || !(price > 0)) return null;
        const pct = (((price - curPrc) / curPrc) * 100).toFixed(1);
        return `${pct.startsWith('-') ? '' : '+'}${pct}%`;
    };

    // ── Claude TP/SL (우선) / 규칙 기반 TP/SL (폴백) ──
    const claudeTp1 = item.claude_tp1 ? normalizeForDisplay(item.claude_tp1) : null;
    const claudeTp2 = item.claude_tp2 ? normalizeForDisplay(item.claude_tp2) : null;
    const claudeSl  = item.claude_sl  ? normalizeForDisplay(item.claude_sl)  : null;

    const tp1 = item.tp1_price ? normalizeForDisplay(item.tp1_price) : null;
    const tp2 = item.tp2_price ? normalizeForDisplay(item.tp2_price) : null;
    const displayTp2 = item.display_tp2_price ? normalizeForDisplay(item.display_tp2_price) : null;
    const sl  = item.sl_price  ? normalizeForDisplay(item.sl_price)  : null;

    const displayedTp1 = claudeTp1 || tp1;
    const displayedTp2 = claudeTp2 || displayTp2 || tp2;
    const displayedSl  = claudeSl  || sl;

    if (effectiveAction === 'ENTER') {
        lines.push('');
        lines.push(`종목: <b>${escapeHtml(stockLabel)}</b>`);
        if (isS1GapOpen) {
            lines.push(`신호 단계: <b>${SIGNAL_STAGE_LABEL[signalStage || 'WATCH']}</b>`);
            lines.push('판단: <b>갭 상승 관찰, 조건 충족 확인 필요</b>');
        } else {
            lines.push(`진입 판단: <b>진입 조건 통과</b>`);
        }
        const finalScore = item.final_score == null ? null : Number(item.final_score);
        lines.push(`점수: 규칙 ${ruleScore}점 · 인공지능 ${aiScore}점${Number.isFinite(finalScore) ? ` · 종합 ${finalScore.toFixed(1)}점` : ''}`);
        const marketLabel = _marketLabel(item.market_type || item.market);
        lines.push(`신뢰도: ${conf} · 보유 유형: ${_holdingType(item.primary_setup_id || item.strategy)}${marketLabel ? ` · 시장: ${escapeHtml(marketLabel)}` : ''}`);
        const decisionStatus = _formatDecisionStatus(item);
        if (decisionStatus) lines.push(decisionStatus);

        if (curPrc > 0) {
            lines.push(`${isS1GapOpen ? '관찰 기준가' : '진입가'}: <b>${formatWon(curPrc)}</b>${_sourceAndAge(item, 'hoga') || _sourceAndAge(item, 'entry')}`);
        }
        if (displayedTp1) {
            lines.push(`${isS1GapOpen ? '1차 상단 기준' : '1차 목표가'}: <b>${formatWon(displayedTp1)}</b>${formatMove(displayedTp1) ? ` (${formatMove(displayedTp1)})` : ''}${_priceMethod(item.tp1_method || item.tp_method)}`);
        } else {
            const targetPct = item.adjusted_target_pct ?? item.target_pct;
            if (targetPct != null) lines.push(`${isS1GapOpen ? '1차 상단 변동률' : '1차 목표 수익률'}: <b>+${targetPct}%</b>`);
        }
        if (displayedTp2) {
            lines.push(`${isS1GapOpen ? '2차 상단 기준' : '2차 목표가'}: <b>${formatWon(displayedTp2)}</b>${formatMove(displayedTp2) ? ` (${formatMove(displayedTp2)})` : ''}${_priceMethod(item.tp2_method)}`);
        }
        if (displayedSl) {
            lines.push(`${isS1GapOpen ? '무효화 기준' : '손절가'}: <b>${formatWon(displayedSl)}</b>${formatMove(displayedSl) ? ` (${formatMove(displayedSl)})` : ''}${_priceMethod(item.sl_method)}`);
        } else {
            const stopPct = item.adjusted_stop_pct ?? item.stop_pct;
            if (stopPct != null) lines.push(`${isS1GapOpen ? '무효화 변동률' : '손절 기준'}: <b>${stopPct}%</b>`);
        }

        const rawRatio = item.raw_rr == null ? null : Number(item.raw_rr);
        const effectiveValue = item.effective_rr ?? item.rr_ratio;
        const minimumValue = item.min_rr_ratio ?? item.rr_regime_threshold ?? item.market_rr_threshold;
        const effectiveRatio = effectiveValue == null ? null : Number(effectiveValue);
        const minimumRatio = minimumValue == null ? null : Number(minimumValue);
        const ratioParts = [
            Number.isFinite(rawRatio) ? `기본 손익비 ${rawRatio.toFixed(2)}` : null,
            Number.isFinite(effectiveRatio) ? `비용 반영 손익비 <b>${effectiveRatio.toFixed(2)}</b>` : null,
            Number.isFinite(minimumRatio) ? `최소 기준 ${minimumRatio.toFixed(2)}` : null,
        ].filter(Boolean);
        if (ratioParts.length) {
            lines.push(`손익 계획: ${ratioParts.join(' · ')}`);
            if (item.rr_regime_threshold != null || item.market_rr_threshold != null) {
                const regimeLine = _formatRegimeRR(item, effectiveRatio);
                if (regimeLine) lines.push(regimeLine);
            }
        } else if (item.rr_ratio != null) {
            const rrText = _formatRegimeRR(item, Number(item.rr_ratio));
            if (rrText) lines.push(rrText);
        } else if (displayedTp1 && displayedSl && curPrc > 0 && displayedSl < curPrc) {
            const effRR = _effectiveRR(item.stk_cd, curPrc, displayedTp1, displayedSl);
            if (effRR) lines.push(effRR);
        }

        const flowLine = [
            item.daily_strength_avg_5 != null ? `최근 5일 강도 ${Number(item.daily_strength_avg_5).toFixed(0)}` : null,
            item.investor_smart_money != null ? `스마트머니 ${Number(item.investor_smart_money).toLocaleString()}` : null,
            item.program_net_buy_amt != null ? `프로그램 ${Number(item.program_net_buy_amt).toLocaleString()}` : null,
        ].filter(Boolean).join(' | ');
        if (flowLine) lines.push(`수급: ${flowLine}`);
        const executionLine = [
            item.cntr_strength != null ? `체결강도 ${Number(item.cntr_strength).toFixed(0)}%` : null,
            item.bid_ratio != null ? `호가비율 ${Number(item.bid_ratio).toFixed(2)}` : null,
            (item.spread_pct ?? item.bid_ask_spread_pct) != null
                ? `매수·매도 가격차 ${Number(item.spread_pct ?? item.bid_ask_spread_pct).toFixed(2)}%` : null,
            (item.chase_risk ?? item.chase_risk_level) != null
                ? `추격 위험 ${_chaseRiskLabel(item.chase_risk ?? item.chase_risk_level)}` : null,
        ].filter(Boolean).join(' · ');
        if (executionLine) lines.push(`체결 상태: ${executionLine}`);
        if (item.volume_profile_adjusted) lines.push('매물대를 반영해 목표가와 손절가를 조정함');

        const dataQualityLine = _formatDataQualityLine(item);
        if (dataQualityLine) lines.push(dataQualityLine);

        lines.push(..._formatSwingRiskLines(item));

        const pos = _positionSize(item.ai_score, item.confidence);
        if (!isS1GapOpen && pos) lines.push(`권장 비중: <b>${pos}</b>`);

        // 진입 강도 (entry_size_tier) — 필드가 있을 때만 표시
        if (item.entry_size_tier) {
            const tierEmoji = {
                SIZE_4: '🔥', SIZE_3: '💪', SIZE_2: '📊', SIZE_1: '🔍', SIZE_0: '⛔',
            }[item.entry_size_tier] || '📊';
            const weightDisplay = item.entry_size_weight !== undefined
                ? ` (모델 상대 ${Number(item.entry_size_weight).toFixed(2)})`
                : '';
            lines.push(`${tierEmoji} 진입 강도: ${_sizeTierLabel(item.entry_size_tier)}${weightDisplay}`);

            if (item.size_downgrade_flags && item.size_downgrade_flags.length > 0) {
                const flagKorean = {
                    'spread_too_wide':         '스프레드 넓음',
                    'low_liquidity':           '유동성 부족',
                    'high_chase_risk':         '추격 리스크 높음',
                    'poor_candidate_quality':  '후보 품질 낮음',
                    'high_stop_pct':           '손절폭 큼',
                    'sector_overheated':       '섹터 과열',
                    'stale_data':              '데이터 오래됨',
                    'strategy_cap_applied':    '전략 상한 적용',
                    'execution_quality_reject':'체결 품질 불량',
                };
                const flagsKor = item.size_downgrade_flags
                    .map(f => flagKorean[f] || '기타 위험 요인')
                    .join(', ');
                lines.push(`⬇️ 하향 사유: ${flagsKor}`);
            }

            if (item.entry_size_tier === 'SIZE_0') {
                lines.push('⚠️ 진입 강도 부족 - 관찰 전용');
            }
        }

        // 매수/매도 박스 블록 (zone 전략만)
        const zoneBlock = _formatZoneBlock(item, curPrc, displayedTp1);
        if (zoneBlock) { lines.push(''); lines.push(zoneBlock); }

        if (item.entry_type) {
            const entryLabel = isS1GapOpen ? _s1EntryConditionLabel(item.entry_type) : _entryTypeLabel(item.entry_type);
            if (entryLabel) lines.push(`${isS1GapOpen ? '확인 조건' : '매수 방식'}: ${entryLabel}`);
        }
        if (item.ai_reason) {
            const reasonText = isS1GapOpen ? _s1ReasonText(item.ai_reason) : item.ai_reason;
            lines.push(`<blockquote><b>${isS1GapOpen ? '관찰 근거' : '추천 이유'}</b>\n${escapeHtml(_enterText(reasonText))}</blockquote>`);
        }

        lines.push('');
        lines.push(isS1GapOpen ? '<b>확인 체크포인트</b>' : '<b>진입 체크포인트</b>');
        lines.push(`1. 기준가: ${curPrc > 0 ? `<b>${formatWon(curPrc)}</b>` : (isS1GapOpen ? '관찰 기준가' : '매수 기준가')} 부근에서 호가와 체결 강도 유지 확인`);
        if (isS1GapOpen) {
            lines.push('2. 갭 상승 후 눌림, 거래량 둔화, 호가 약화 여부 확인');
        } else {
            lines.push(`2. 비중: ${pos ? `<b>${pos}</b> 이내` : '계획 비중 이내'}로 진입하고 손절 기준 손실폭을 먼저 확정`);
        }
        if (displayedTp2) {
            lines.push(isS1GapOpen ? '3. 상단 기준: 1차/2차 기준 도달 여부와 추세 지속성 확인' : '3. 목표 관리: 1차 목표가에서 일부 매도하고 2차 목표가까지 잔여분 추적');
        } else {
            lines.push(isS1GapOpen ? '3. 상단 기준: 목표 구간 도달 전 거래량과 체결강도 변화 점검' : '3. 목표 관리: 1차 목표가 도달 전 거래량 둔화와 호가 약화 여부 점검');
        }
        if (displayedSl) {
            lines.push(`4. 무효화 기준: <b>${formatWon(displayedSl)}</b> 이탈 시 전략 전제 훼손으로 대응`);
        } else {
            lines.push(`4. 무효화 기준: ${isS1GapOpen ? '하단 이탈 조건 충족 시' : '손절 조건 충족 시'} 전략 전제 훼손으로 대응`);
        }
        if (item.skip_entry) {
            const rrStr = item.rr_ratio != null ? ` (현재 손익비 ${Number(item.rr_ratio).toFixed(2)})` : '';
            lines.push(isS1GapOpen ? `주의: 현재 장세 손익비가 부족해 추격 판단 보류${rrStr}` : `주의: 현재 장세 손익비가 부족해 진입 보류${rrStr}`);
        }
    } else {
        if (isS1GapOpen) {
            lines.push(
                `신호 단계: <b>${SIGNAL_STAGE_LABEL[signalStage || 'WATCH']}</b>  |  신뢰도: ${conf}`,
                `AI 스코어: <b>${aiScore}</b>점  (규칙: ${ruleScore}점)`,
            );
        } else {
            lines.push(
                `${action}  |  신뢰도: ${conf}`,
                `AI 스코어: <b>${aiScore}</b>점  (규칙: ${ruleScore}점)`,
            );
        }
        if (curPrc > 0) {
            const entryLabel = isS1GapOpen ? _s1EntryConditionLabel(item.entry_type) : (item.entry_type ?? '-');
            lines.push(`${isS1GapOpen ? '관찰 기준가' : '진입가'}: <b>${curPrc.toLocaleString()}원</b>  (${entryLabel ?? '-'})`);
        }
    }

    if (effectiveAction !== 'ENTER') {
        if (tp1 || tp2 || sl) {
            lines.push('📐 <b>진입 전 가격 계획</b>');
            if (tp1 && curPrc > 0) {
                const pct = (((tp1 - curPrc) / curPrc) * 100).toFixed(1);
                lines.push(`  1차 목표가: <b>${tp1.toLocaleString()}원</b>  (+${pct}%)`);
            }
            if (tp2 && curPrc > 0) {
                const pct = (((tp2 - curPrc) / curPrc) * 100).toFixed(1);
                lines.push(`  2차 목표가: <b>${tp2.toLocaleString()}원</b>  (+${pct}%)`);
            }
            if (sl && curPrc > 0) {
                const pct = (((sl - curPrc) / curPrc) * 100).toFixed(1);
                lines.push(`  손절가: <b>${sl.toLocaleString()}원</b>  (${pct}%)`);
            }
            if (tp1 && sl && curPrc > 0 && sl < curPrc) {
                const effRR = _effectiveRR(item.stk_cd, curPrc, tp1, sl);
                if (effRR) lines.push(`  ${effRR}`);
            }
        } else {
            const targetPct = item.adjusted_target_pct ?? item.target_pct;
            const stopPct   = item.adjusted_stop_pct   ?? item.stop_pct;
            if (targetPct != null || stopPct != null) {
                lines.push(`목표: <b>+${targetPct ?? '-'}%</b>  손절: <b>${stopPct ?? '-'}%</b>`);
            }
        }
    }

    // 전술별 지표
    const indLines = [];
    if (item.gap_pct      != null) indLines.push(`갭: ${item.gap_pct}%`);
    if (effectiveAction !== 'ENTER' && item.cntr_strength != null) indLines.push(`체결강도: ${item.cntr_strength}%`);
    if (effectiveAction !== 'ENTER' && item.bid_ratio != null) indLines.push(`호가비율: ${item.bid_ratio}`);
    if (item.vol_ratio    != null) indLines.push(`거래량: ${item.vol_ratio}배`);
    if (item.pullback_pct != null) indLines.push(`눌림: ${item.pullback_pct}%`);
    if (indLines.length > 0) lines.push(indLines.join('  |  '));

    // 기술 지표 (RSI, ATR, 조건수, 보유목표일)
    const techLines = [];
    if (item.rsi      != null) techLines.push(`상대강도지수: ${Number(item.rsi).toFixed(1)}`);
    if (item.atr_pct  != null) techLines.push(`평균 변동폭: ${Number(item.atr_pct).toFixed(2)}%`);
    if (item.cond_count != null && Number(item.cond_count) > 0) techLines.push(`조건충족: ${item.cond_count}개`);
    if (item.holding_days != null) {
        const holdingDays = String(item.holding_days);
        techLines.push(`보유 목표: ${holdingDays}${/일$/.test(holdingDays) ? '' : '일'}`);
    }
    if (techLines.length > 0) lines.push(techLines.join('  |  '));

    if (item.theme_name   != null) lines.push(`테마: ${item.theme_name}`);
    if (item.net_buy_amt  != null) {
        const amt = (Number(item.net_buy_amt) / 1e8).toFixed(1);
        lines.push(`순매수: ${amt}억`);
    }

    // 포지션 크기 제안 (ENTER 신호 외)
    if (effectiveAction !== 'ENTER') {
        const pos = _positionSize(item.ai_score, item.confidence);
        if (!isS1GapOpen && pos) lines.push(`💰 권장 비중: <b>${pos}</b>`);
    }

    // AI 분석 근거
    if (item.ai_reason && effectiveAction !== 'ENTER') {
        lines.push('');
        lines.push(`<blockquote><b>관망 근거</b>\n${escapeHtml(_humanizeTerms(isS1GapOpen ? _s1ReasonText(item.ai_reason) : item.ai_reason))}</blockquote>`);
    }

    // 신호 시간
    const signalTime = item.signal_time
        ? new Date(item.signal_time).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false })
        : new Date().toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });
    lines.push(`\n🕐 ${signalTime}`);

    return lines.join('\n');
}

/**
 * 강제 청산 알림 포맷
 */
function formatForceClose(item) {
    return [
        `⚠️ <b>[강제청산] ${item.stk_cd} ${item.stk_nm ?? ''}</b>`,
        `전술: ${item.strategy}`,
        `장마감 30분 전 – 전량 시장가 청산`,
        `\n🕐 ${new Date().toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul' })}`,
    ].join('\n');
}

/**
 * 당일 성과 요약 포맷
 */
function formatDailySummary(stats) {
    if (!stats || stats.length === 0) {
        return '📊 오늘 거래 신호 없음';
    }
    const lines = ['📊 <b>당일 전략별 성과</b>', ''];
    for (const row of stats) {
        const [strategy, count, avgPnl] = row;
        const pnlStr = avgPnl != null ? `${Number(avgPnl).toFixed(2)}%` : 'N/A';
        lines.push(`${STRATEGY_EMOJI[strategy] ?? '•'} ${strategy}: ${count}건 | 평균 ${pnlStr}`);
    }
    return lines.join('\n');
}

/**
 * Feature 1 – 가상 성과 요약 포맷 (/성과추적)
 */
function formatPerformanceSummary(rows) {
    if (!rows || rows.length === 0) {
        return '📊 오늘 성과 데이터 없음';
    }
    const lines = ['📊 <b>전략별 가상 성과</b>', ''];
    for (const row of rows) {
        const [strategy, total, wins, losses, avgPnl] = row;
        const winRate = total > 0 ? ((Number(wins) / Number(total)) * 100).toFixed(0) : '-';
        const pnlStr  = avgPnl != null ? `${Number(avgPnl).toFixed(2)}%` : 'N/A';
        lines.push(`${STRATEGY_EMOJI[strategy] ?? '•'} ${strategy}: ${total}건 | 승률 ${winRate}% | 평균 ${pnlStr}`);
    }
    return lines.join('\n');
}

/**
 * Feature 3 – 뉴스 현황 포맷 (/뉴스)
 */
function formatNewsStatus({ analysis, sentiment, sectors }) {
    const sentLabel = { BULLISH: '강세 📈', BEARISH: '약세 📉', NEUTRAL: '중립 ➡️' };

    const lines = [
        `📰 <b>[뉴스 & 시장 현황]</b>`,
        `시장심리: ${sentLabel[sentiment] || sentiment || '-'}`,
    ];
    if (sectors && sectors.length > 0) {
        lines.push(`추천섹터: <b>${sectors.join(', ')}</b>`);
    }
    if (analysis && analysis.summary) {
        lines.push(`\n💬 <i>${analysis.summary}</i>`);
    }
    return lines.join('\n');
}

/**
 * Feature 3 – 섹터 분석 포맷 (/섹터)
 */
function formatSectorAnalysis({ sectors, sentiment, stats }) {
    const sentLabel = { BULLISH: '강세 📈', BEARISH: '약세 📉', NEUTRAL: '중립 ➡️' };
    const lines = [
        `🔥 <b>[섹터 분석]</b>`,
        `시장심리: ${sentLabel[sentiment] || sentiment || '-'}`,
        '',
    ];
    if (sectors && sectors.length > 0) {
        lines.push('<b>추천 섹터:</b>');
        sectors.forEach((s, i) => lines.push(`  ${i + 1}. ${s}`));
    } else {
        lines.push('추천 섹터 없음');
    }
    if (stats && stats.length > 0) {
        lines.push('');
        lines.push('<b>오늘 전략별 신호:</b>');
        for (const row of stats) {
            const [strategy, count] = row;
            lines.push(`  ${STRATEGY_EMOJI[strategy] ?? '•'} ${strategy}: ${count}건`);
        }
    }
    return lines.join('\n');
}

/**
 * Feature 3 – 종목 신호 이력 포맷 (/신호이력)
 */
function formatSignalHistory(stkCd, signals) {
    if (!signals || signals.length === 0) {
        return `📭 ${stkCd} 최근 신호 없음`;
    }
    const statusEmoji = { WIN: '✅', LOSS: '❌', SENT: '⏳', EXPIRED: '⌛', CANCELLED: '🚫', PENDING: '🕐' };
    const lines = [`📋 <b>${stkCd} 신호 이력 (최근 ${signals.length}건)</b>`, ''];
    for (const s of signals) {
        const d    = new Date(s.createdAt).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' });
        const t    = new Date(s.createdAt).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
        const pnl  = s.realizedPnl != null ? ` | P&L: ${Number(s.realizedPnl).toFixed(2)}%` : '';
        const emoji = statusEmoji[s.signalStatus] ?? '•';
        lines.push(`${emoji} ${d} ${t} [${s.strategy}] 스코어:${s.signalScore ?? '-'}${pnl}`);
    }
    return lines.join('\n');
}

/**
 * Feature 5 – 시스템 에러 현황 포맷 (/에러)
 */
function formatSystemHealth({ queueDepth, errorCount, dailySignals, tradingControl, calendarPreEvent, wsReconnect }) {
    const ctrlEmoji = { PAUSE: '🚨', CAUTIOUS: '⚠️', CONTINUE: '✅' };
    const ctrl = tradingControl || 'CONTINUE';
    const lines = [
        `🔧 <b>[시스템 상태]</b>`,
        `매매 제어: ${ctrlEmoji[ctrl] ?? '•'} ${ctrl}`,
        `이벤트 임박: ${calendarPreEvent ? '⚠️ 있음' : '없음'}`,
        `텔레그램 큐: ${queueDepth ?? 0}건`,
        `에러 큐: ${errorCount ?? 0}건`,
        `오늘 신호: ${dailySignals ?? 0}건`,
        `WS 재연결: ${wsReconnect ?? 0}회`,
    ];
    return lines.join('\n');
}

/**
 * DAILY_REPORT 확장 포맷 – 가상 P&L 포함
 */
function formatDailyReportEnhanced(item) {
    const totalSignals = Number(item.total_signals ?? 0);
    const enterCount = Number(item.enter_count ?? 0);
    const cancelCount = Number(item.cancel_count ?? 0);
    const closedCount = Number(item.closed_count ?? 0);
    const enterRate = totalSignals > 0 ? ((enterCount / totalSignals) * 100).toFixed(1) : '-';
    const lines = [
        `📊 <b>일일 종합 리포트 (${item.date ?? ''})</b>`,
        `총 신호: <b>${totalSignals}건</b>  |  평균 스코어: ${typeof item.avg_score === 'number' ? item.avg_score.toFixed(1) : '-'}점`,
        `ENTER: <b>${enterCount}건</b> (${enterRate}%)  |  CANCEL: ${cancelCount}건  |  CLOSED: ${closedCount}건`,
    ];

    // 가상 P&L (새로 추가된 필드)
    if (item.total_wins != null || item.total_losses != null) {
        const wins   = Number(item.total_wins   ?? 0);
        const losses = Number(item.total_losses ?? 0);
        const total  = wins + losses;
        const winRate = total > 0 ? ((wins / total) * 100).toFixed(0) : '-';
        const pnl    = item.avg_pnl != null ? Number(item.avg_pnl).toFixed(2) : 'N/A';
        lines.push(`가상 성과: ✅ ${wins}건 / ❌ ${losses}건  |  승률 ${winRate}%  |  평균 ${pnl}%`);
    }

    if (item.by_strategy) {
        const byStr = typeof item.by_strategy === 'object'
            ? Object.entries(item.by_strategy).map(([s, c]) => `  ${STRATEGY_EMOJI[s] ?? '•'} ${s}: ${c}건`).join('\n')
            : String(item.by_strategy);
        lines.push(`\n전략별:\n${byStr}`);
    }
    return lines.join('\n');
}

/**
 * /이벤트 – 이번 주 경제 캘린더 포맷
 */
function formatCalendarWeek(events) {
    if (!events || events.length === 0) {
        return '📅 이번 주 예정 경제 이벤트 없음';
    }
    const impactEmoji = { HIGH: '🔴', MEDIUM: '🟡', LOW: '⚪' };
    const dayNames = ['일', '월', '화', '수', '목', '금', '토'];
    const lines = ['📅 <b>[이번 주 경제 일정]</b>', ''];

    let lastDate = null;
    for (const e of events) {
        const d = new Date(e.eventDate + 'T00:00:00');
        const dateStr = `${d.getMonth() + 1}/${d.getDate()}(${dayNames[d.getDay()]})`;
        if (dateStr !== lastDate) {
            lines.push(`<b>${dateStr}</b>`);
            lastDate = dateStr;
        }
        const impact = impactEmoji[e.expectedImpact] ?? '•';
        const time   = e.eventTime ? e.eventTime.substring(0, 5) + ' ' : '';
        lines.push(`  ${impact} ${time}${e.eventName} [${e.eventType}]`);
    }
    return lines.join('\n');
}

/**
 * /성과추적 – 오늘 신호 가상 P&L 상세 포맷
 */
function formatPerformanceDetail(signals, summaryRows) {
    const lines = ['📈 <b>[오늘의 가상 성과]</b>', ''];

    // 요약 집계
    if (summaryRows && summaryRows.length > 0) {
        let totalWins = 0, totalLosses = 0, totalSent = 0, pnlSum = 0, pnlCount = 0;
        for (const row of summaryRows) {
            const [, total, wins, losses, avgPnl] = row;
            totalWins   += Number(wins   ?? 0);
            totalLosses += Number(losses ?? 0);
            totalSent   += Number(total  ?? 0);
            if (avgPnl != null) { pnlSum += Number(avgPnl); pnlCount++; }
        }
        const winRate = (totalWins + totalLosses) > 0
            ? ((totalWins / (totalWins + totalLosses)) * 100).toFixed(0) : '-';
        const avgPnl  = pnlCount > 0 ? (pnlSum / pnlCount).toFixed(2) : 'N/A';
        lines.push(`✅ WIN ${totalWins}건 / ❌ LOSS ${totalLosses}건 / ⏳ 미결 ${Math.max(0, totalSent - totalWins - totalLosses)}건`);
        lines.push(`승률: <b>${winRate}%</b>  |  평균 P&L: <b>${avgPnl}%</b>`);
        lines.push('');
    }

    // 베스트/워스트
    if (signals && signals.length > 0) {
        const closed = signals.filter(s => s.realizedPnl != null);
        if (closed.length > 0) {
            const best  = closed.reduce((a, b) => a.realizedPnl > b.realizedPnl ? a : b);
            const worst = closed.reduce((a, b) => a.realizedPnl < b.realizedPnl ? a : b);
            lines.push(`최고: ${best.stkNm ?? best.stkCd} <b>+${Number(best.realizedPnl).toFixed(2)}%</b>`);
            if (worst.stkCd !== best.stkCd) {
                lines.push(`최저: ${worst.stkNm ?? worst.stkCd} <b>${Number(worst.realizedPnl).toFixed(2)}%</b>`);
            }
        }
    }
    return lines.join('\n');
}

/**
 * /설정 – 개인 알림 설정 포맷
 */
function formatUserSettings(filter, watchlist) {
    const lines = ['⚙️ <b>[내 알림 설정]</b>', ''];
    if (filter && filter.length > 0) {
        lines.push(`전략 필터: ${filter.join(', ')}`);
    } else {
        lines.push('전략 필터: 없음 (모든 전략 수신)');
    }
    if (watchlist && watchlist.length > 0) {
        lines.push(`관심 종목: ${watchlist.join(', ')}`);
    } else {
        lines.push('관심 종목: 없음 (모든 종목 수신)');
    }
    return lines.join('\n');
}

/**
 * /score {종목코드} — S1~S16 전략 심사 결과 포맷
 *
 * @param {Object} scoreData  ai-engine /score/{stk_cd} 응답
 *   { stk_cd, stk_nm, no_match, matched_count, results, skipped, data }
 * @returns {string[]}  텔레그램 메시지 배열 (전략별 1개 + 요약 헤더 1개)
 */
function _formatClaudeFull(cf, stkLabel) {
    if (!cf || cf.error) return null;
    const actionLabels = { ENTER: '진입 우세', HOLD: '보유/관망', SELL: '매도/회피' };
    const daily   = cf.daily_indicators  || {};
    const minute  = cf.minute_indicators || {};
    const hoga    = cf.hoga || {};
    const tp      = cf.tp_sl || {};
    const pools   = Array.isArray(cf.strategies_in_pool) ? cf.strategies_in_pool : [];
    const reasons = Array.isArray(cf.reasons)      ? cf.reasons      : [];
    const risks   = Array.isArray(cf.risk_factors)  ? cf.risk_factors  : [];
    const guide   = Array.isArray(cf.action_guide)  ? cf.action_guide  : [];
    const conf    = String(cf.confidence || 'LOW').toUpperCase();

    const lines = [
        `🧠 <b>Claude 종합 분석 | ${escapeHtml(stkLabel)}</b>`,
        `판단: <b>${actionLabels[cf.action] || cf.action || '—'}</b>  |  신뢰도: <b>${conf}</b>`,
    ];

    if (pools.length > 0) {
        lines.push(`전략 후보군: ${escapeHtml(pools.join(', '))}`);
    }

    const dailyLine = [
        daily.ma5  ? `MA5 ${Number(daily.ma5).toLocaleString()}`  : null,
        daily.ma20 ? `MA20 ${Number(daily.ma20).toLocaleString()}` : null,
        daily.ma60 ? `MA60 ${Number(daily.ma60).toLocaleString()}` : null,
        daily.rsi14   != null ? `RSI ${Number(daily.rsi14).toFixed(1)}`   : null,
        daily.atr_pct != null ? `ATR ${Number(daily.atr_pct).toFixed(2)}%` : null,
    ].filter(Boolean).join(' | ');
    if (dailyLine) lines.push('', '<b>일봉 지표</b>', dailyLine);

    const minLine = [
        `${minute.tic_scope || 5}분봉`,
        minute.rsi14      != null ? `RSI ${Number(minute.rsi14).toFixed(1)}`      : null,
        minute.macd       != null ? `MACD ${Number(minute.macd).toFixed(3)}`      : null,
        minute.stoch_k    != null ? `Stoch ${Number(minute.stoch_k).toFixed(1)}/${Number(minute.stoch_d ?? 0).toFixed(1)}` : null,
        minute.atr_pct    != null ? `ATR ${Number(minute.atr_pct).toFixed(2)}%`   : null,
    ].filter(Boolean).join(' | ');
    if (minLine) lines.push('', '<b>분봉 지표</b>', minLine);

    const hogaLine = [
        hoga.total_buy_bid_req != null ? `매수잔량 ${Number(hoga.total_buy_bid_req).toLocaleString()}` : null,
        hoga.total_sel_bid_req != null ? `매도잔량 ${Number(hoga.total_sel_bid_req).toLocaleString()}` : null,
        hoga.buy_to_sell_ratio != null ? `매수/매도비 ${Number(hoga.buy_to_sell_ratio).toFixed(2)}` : null,
    ].filter(Boolean).join(' | ');
    if (hogaLine) lines.push('', '<b>호가</b>', hogaLine);

    if (reasons.length > 0) {
        lines.push('', '<b>핵심 근거</b>');
        reasons.forEach((r) => lines.push(`• ${escapeHtml(String(r))}`));
    }
    if (risks.length > 0) {
        lines.push('', '<b>리스크</b>');
        risks.forEach((r) => lines.push(`• ${escapeHtml(String(r))}`));
    }
    if (guide.length > 0) {
        lines.push('', '<b>실행 가이드</b>');
        guide.forEach((g) => lines.push(`• ${escapeHtml(String(g))}`));
    }

    const tpLine = [
        tp.take_profit != null ? `목표가 ${_formatWon(tp.take_profit)}` : null,
        tp.stop_loss   != null ? `손절가 ${_formatWon(tp.stop_loss)}`   : null,
    ].filter(Boolean).join(' | ');
    if (tpLine) lines.push('', `<b>목표가 / 손절가</b>  ${tpLine}`);

    if (cf.summary) lines.push('', `<b>한 줄 결론</b>  ${escapeHtml(cf.summary)}`);

    return lines.join('\n');
}

function formatStockScore(scoreData) {
    const { stk_cd, stk_nm, no_match, matched_count, results, skipped, data, claude_full, score_mode, used_cache, data_quality, family_matches, checked_at, generated_at } = scoreData;
    const stkLabel = stk_nm ? `${stk_nm}(${stk_cd})` : stk_cd;

    // ── 공통 헤더 (실시간 지표) ─────────────────────────────────
    const d        = data || {};
    const cf       = claude_full || {};
    const curPrc   = Number(cf.cur_prc  ?? d.cur_prc  ?? 0);
    const fluRt    = Number(cf.flu_rt   ?? d.flu_rt   ?? 0);
    const fluSign  = fluRt > 0 ? '+' : '';
    const rsi      = d.rsi14 != null ? Number(d.rsi14).toFixed(1) : 'N/A';
    const ma5      = d.ma5   ? Number(d.ma5).toLocaleString()  : 'N/A';
    const ma20     = d.ma20  ? Number(d.ma20).toLocaleString() : 'N/A';
    const ma60     = d.ma60  ? Number(d.ma60).toLocaleString() : 'N/A';
    const strength = d.avg_strength != null ? Number(d.avg_strength).toFixed(0) : 'N/A';
    const bidRatio = d.bid_ratio    != null ? Number(d.bid_ratio).toFixed(2)    : 'N/A';
    const freshness = d.freshness || {};
    const freshnessLine = Object.entries(freshness)
        .map(([key, value]) => {
            const state = String((value && value.state) || 'unknown').toUpperCase();
            const age = value && value.age_ms != null ? ` ${Math.round(Number(value.age_ms) / 1000)}s` : '';
            const source = value && value.source ? `/${value.source}` : '';
            return `${key}:${state}${age}${source}`;
        })
        .join(' | ');

    let header =
        `🔍 <b>[통합 분석] ${stkLabel}</b>\n` +
        `💰 현재가: <b>${curPrc.toLocaleString()}원</b>  <b>${fluSign}${fluRt}%</b>\n` +
        `분석 방식: <b>${score_mode === 'fast' ? '빠른 규칙 평가' : 'AI 정밀 평가'}</b>${used_cache ? ' | AI 캐시 재사용' : ''}\n` +
        `MA5: ${ma5} | MA20: ${ma20} | MA60: ${ma60}\n` +
        `RSI(14): ${rsi}  |  체결강도: ${strength}  |  호가비율: ${bidRatio}`;

    if (freshnessLine) header += `\nData: ${freshnessLine}`;
    if (data_quality?.status) header += `\n데이터 상태: <b>${escapeHtml(data_quality.status)}</b>`;
    const familyLine = Object.entries(family_matches || {}).map(([id, count]) => `${id} ${count}개`).join(' · ');
    if (familyLine) header += `\n통합전략 매칭: ${escapeHtml(familyLine)}`;
    header += `\n분석시각: ${escapeHtml(formatKstDateTime(generated_at || checked_at))}`;

    const claudeBlock = _formatClaudeFull(cf, stkLabel);

    // ── 전략없음: Claude 분석만 반환 ────────────────────────────
    if (no_match || !results || results.length === 0) {
        const skipSample = (skipped || []).slice(0, 5).join('\n  • ');
        const noMatchNote =
            `\n\n📭 <b>매칭 전략 없음</b>\n` +
            `S1~S16 세부전략 조건 미충족 — Claude 실시간 데이터 단독 분석 결과입니다.\n` +
            (skipSample ? `<i>주요 탈락 사유:\n  • ${skipSample}</i>` : '');
        const firstMsg = header + noMatchNote;
        return claudeBlock
            ? [firstMsg, claudeBlock]
            : [firstMsg];
    }

    // ── 전략 매칭: 요약 헤더 + 전략 카드 + Claude 분석 ──────────
    const summaryHeader =
        header + '\n\n' +
        `✅ <b>${matched_count}개 전략 매칭</b> — AI 점수 높은 순\n` +
        `<i>아래 전략 카드 + Claude 종합 분석 참조</i>`;

    const signalMessages = results.map((sig) => formatSignal(sig));
    return claudeBlock
        ? [summaryHeader, ...signalMessages, claudeBlock]
        : [summaryHeader, ...signalMessages];
}

/**
 * SELL_SIGNAL — 포지션 청산 알림 포맷
 * exit_type: SL_HIT / TP1_HIT / TP2_HIT / TRAILING_STOP / TREND_REVERSAL
 */
function formatSellSignal(item) {
    const EXIT_EMOJI = {
        SL_HIT:         '🔴',
        TP1_HIT:        '🟡',
        TP2_HIT:        '🟢',
        TRAILING_STOP:  '🔵',
        TREND_REVERSAL: '⚠️',
    };
    const exitType  = item.exit_type  || 'UNKNOWN';
    const emoji     = EXIT_EMOJI[exitType]  || '📤';
    const lines = _formatSellBaseLines(item, {
        title: '매도신호',
        status: '청산 실행',
        exitType,
        icon: emoji,
    });

    if (exitType === 'TRAILING_STOP' && item.peak_price) {
        const peak = normalizeForDisplay(item.peak_price);
        const tPct = Number(item.trailing_pct ?? 1.5);
        lines.push(`고점/낙폭: <b>${peak.toLocaleString()}원 / ${tPct}%</b>`);
    }

    if (exitType === 'TREND_REVERSAL') {
        const score = Number(item.reversal_score ?? 0);
        lines.push(`추세반전점수: <b>${score.toFixed(1)}/5</b>`);
        if (item.ai_reason) lines.push(`판단근거: ${escapeHtml(item.ai_reason)}`);
    }

    if (exitType === 'TIME_STOP' && item.time_stop_reason) {
        lines.push(`판단근거: ${escapeHtml(String(item.time_stop_reason))}`);
    }

    _appendSellFooter(lines, item);

    return lines.filter((l) => l !== null).join('\n');
}

/**
 * HOLD_WATCH — 조건부 진입(관심종목) 알림 포맷.
 * Claude/규칙 판단이 HOLD(WATCH)로 분류된 시점에 1회 발송.
 */
function formatHoldWatch(item) {
    const emoji = STRATEGY_EMOJI[item.strategy] ?? '📌';
    const stock = item.stk_nm
        ? `${item.stk_nm} (${item.stk_cd})`
        : item.stk_cd;
    const curPrc = normalizeForDisplay(item.cur_prc ?? item.entry_price ?? 0);
    const aiScore = item.ai_score != null ? Number(item.ai_score).toFixed(1) : null;
    const ruleScore = item.rule_score != null ? Number(item.rule_score).toFixed(1) : null;

    const familyLabel = FAMILY_LABEL[item.strategy_family] || item.strategy_family_name || '통합전략';
    const setup = item.primary_setup_id || item.strategy || '-';
    const marketLabel = _marketLabel(item.market_type || item.market);
    const lines = [
        `🔎 <b>[관심종목 · 조건 대기] ${escapeHtml(stock || '')}</b>`,
        `${escapeHtml(item.strategy_family || '-')} ${escapeHtml(familyLabel)} · <code>${escapeHtml(setup)}</code> · ${_holdingType(setup)}${marketLabel ? ` · ${escapeHtml(marketLabel)}` : ''}`,
    ];
    const confirmations = item.confirmed_by || item.matched_setup_ids;
    if (Array.isArray(confirmations) && confirmations.length > 1) {
        lines.push(`확증 세부전략: ${escapeHtml(confirmations.join(', '))}`);
    }

    const finalScore = item.final_score == null ? null : Number(item.final_score);
    const scoreLine = [
        ruleScore != null ? `규칙 ${ruleScore}` : null,
        aiScore != null ? `AI ${aiScore}` : null,
        Number.isFinite(finalScore) ? `종합 ${finalScore.toFixed(1)}` : null,
    ].filter(Boolean).join(' · ');
    if (scoreLine) lines.push(`점수: <b>${scoreLine}</b>`);
    const decisionStatus = _formatDecisionStatus(item);
    if (decisionStatus) lines.push(decisionStatus);

    const tp1 = item.claude_tp1 ?? item.tp1_price;
    const tp2 = item.claude_tp2 ?? item.display_tp2_price ?? item.tp2_price;
    const sl = item.claude_sl ?? item.sl_price;
    const reason = item.hold_reason || item.ai_reason;
    const effectiveRr = Number(item.effective_rr ?? item.rr_ratio);
    const rawRr = Number(item.raw_rr);
    const appliedGate = _resolveHoldRrGate(item, reason);
    const deficit = Number.isFinite(effectiveRr) && Number.isFinite(appliedGate) ? Math.max(0, appliedGate - effectiveRr) : null;

    lines.push('', '<b>가격 계획</b>');
    if (curPrc > 0) lines.push(`관찰가  <b>${curPrc.toLocaleString()}원</b>`);
    if (tp1) lines.push(`1차 목표  <b>${_priceWithMove(tp1, curPrc)}</b> · ${escapeHtml(_compactPriceMethod(item.tp1_method || item.tp_method))}`);
    if (tp2) lines.push(`2차 목표  <b>${_priceWithMove(tp2, curPrc)}</b> · ${escapeHtml(_compactPriceMethod(item.tp2_method))}`);
    if (sl) lines.push(`손절 기준  <b>${_priceWithMove(sl, curPrc)}</b> · ${escapeHtml(_compactPriceMethod(item.sl_method))}`);

    lines.push('', '<b>보류 판정</b>');
    if (Number.isFinite(effectiveRr)) {
        const regime = _regimeLabel(item.rr_regime || String(reason || '').match(/\((bull|bear|neutral|sideways)\)/i)?.[1]);
        lines.push(`비용 반영 손익비 <b>${effectiveRr.toFixed(2)}</b> / 적용 기준 <b>${Number.isFinite(appliedGate) ? appliedGate.toFixed(2) : '-'}</b> (${regime})`);
        if (Number.isFinite(rawRr)) lines.push(`참고: 비용 반영 전 ${rawRr.toFixed(2)}${Number.isFinite(deficit) && deficit > 0 ? ` · 기준까지 ${deficit.toFixed(2)} 부족` : ''}`);
    } else if (reason) {
        lines.push(`<blockquote>${escapeHtml(_humanizeTerms(reason))}</blockquote>`);
    }
    if (reason && Number.isFinite(effectiveRr)) {
        lines.push(`<blockquote>${escapeHtml(_humanizeTerms(reason))}</blockquote>`);
    }

    const ages = item.source_age_ms || {};
    const ageParts = [['현재가', ages.tick], ['호가', ages.hoga], ['체결강도', ages.strength]]
        .map(([label, age]) => [label, _shortAge(age)])
        .filter(([, age]) => age)
        .map(([label, age]) => `${label} ${age}`);
    if (ageParts.length) lines.push(`데이터: ${ageParts.join(' · ')}`);
    const source = item.data_source?.hoga || item.data_source?.entry;
    if (source) lines.push(`가격 출처: ${escapeHtml(String(source).toLowerCase() === 'rest' ? '조회 보완 데이터' : _humanizeTerms(source))}`);

    lines.push('', `<b>재평가 조건</b>`);
    lines.push(Number.isFinite(appliedGate)
        ? `비용 반영 손익비가 <b>${appliedGate.toFixed(2)} 이상</b>으로 개선되면 진입 여부를 다시 심사합니다.`
        : '보류 조건이 개선되면 진입 여부를 다시 심사합니다.');
    lines.push('개선되지 않거나 관찰 시간이 끝나면 관심 해제로 안내합니다.');
    _appendSellFooter(lines, item);
    return lines.join('\n');
}

/**
 * HOLD_RELEASED — 관심종목 관찰 종료(관심 해제) 알림 포맷.
 * ENTER로 승격되지 않고 hold monitor 큐에서 제거될 때 발송.
 */
function formatHoldReleased(item) {
    const emoji = STRATEGY_EMOJI[item.strategy] ?? '📌';
    const stock = item.stk_nm
        ? `${item.stk_nm} (${item.stk_cd})`
        : item.stk_cd;
    const lines = [
        `🔕 <b>[관심 해제] ${emoji} ${escapeHtml(item.strategy || '-')}</b>`,
        `종목: <b>${escapeHtml(stock || '')}</b>`,
        '조건부 진입(관심종목) 관찰을 종료합니다.',
    ];
    if (item.release_reason) {
        lines.push(`해제 사유: ${escapeHtml(String(item.release_reason))}`);
    }
    _appendSellFooter(lines, item);
    return lines.join('\n');
}

/**
 * NEWS_ALERT 메시지 포맷 (Java 측에서 message 필드가 없을 경우 폴백)
 */
function formatSellRecommendation(item) {
    const rawKind = String(
        item.recommendation_type
        || item.exit_type
        || item.sell_type
        || item.trigger_type
        || ''
    ).toUpperCase();

    const kind = rawKind.includes('TP1')
        ? 'TP1'
        : (rawKind.includes('SL')
            ? 'SL'
            : (rawKind.includes('TRAIL') ? 'TRAILING' : 'GENERAL'));

    const exitType = kind === 'TP1'
        ? 'TP1_HIT'
        : (kind === 'SL' ? 'SL_HIT' : (kind === 'TRAILING' ? 'TRAILING_STOP' : 'REVIEW'));

    const lines = _formatSellBaseLines(item, {
        title: '매도검토',
        status: item.urgent ? '즉시 검토' : '검토 필요',
        exitType,
        icon: item.urgent ? '🚨' : '📋',
    });

    if (item.trailing_pct != null || item.trailing_stop_pct != null) {
        lines.push(`트레일링: <b>${item.trailing_pct ?? item.trailing_stop_pct}%</b>`);
    }
    if (item.reason_summary) {
        lines.push(`판단근거: ${escapeHtml(item.reason_summary)}`);
    }
    if (item.ai_reason) {
        lines.push(`AI판단: ${escapeHtml(item.ai_reason)}`);
    }

    _appendSellFooter(lines, item);

    return lines.join('\n');
}

function _formatSellBaseLines(item, { title, status, exitType, icon }) {
    const stratEmoji = STRATEGY_EMOJI[item.strategy] ?? '📌';
    const label = _sellExitLabel(exitType, item.partial);
    const stock = item.stk_nm
        ? `${item.stk_cd} ${item.stk_nm}`
        : item.stk_cd;
    const entryPrc = normalizeForDisplay(item.entry_price ?? 0);
    const exitPrc = normalizeForDisplay(item.cur_prc ?? item.exit_price ?? 0);
    const triggerPrc = normalizeForDisplay(item.trigger_price ?? 0);
    const slPrc = normalizeForDisplay(item.sl_price ?? 0);

    const lines = [
        `${icon} <b>[${title}] ${stratEmoji} ${escapeHtml(item.strategy || '-')}</b>`,
        `종목: <b>${escapeHtml(stock || '')}</b>`,
        `상태: <b>${status}</b>`,
        `유형: <b>${label}</b>`,
    ];

    const pnlLabel = _formatPercent(item.realized_pnl_pct);
    if (pnlLabel) lines.push(`손익: <b>${pnlLabel}</b>`);

    lines.push('');
    if (entryPrc > 0) lines.push(`진입가: <b>${entryPrc.toLocaleString()}원</b>`);
    if (exitPrc > 0) lines.push(`청산가: <b>${exitPrc.toLocaleString()}원</b>`);
    if (triggerPrc > 0) lines.push(`기준가: <b>${triggerPrc.toLocaleString()}원</b>`);
    if (slPrc > 0 && exitType !== 'SL_HIT') lines.push(`손절기준: <b>${slPrc.toLocaleString()}원</b>`);

    const partialLabel = _partialLabel(item.partial);
    if (partialLabel) lines.push(`청산범위: <b>${partialLabel}</b>`);

    const guidance = _sellGuidance(exitType, item.partial);
    if (guidance) {
        lines.push('');
        lines.push(`메모: ${guidance}`);
    }

    return lines;
}

function _sellExitLabel(exitType, partial) {
    if (exitType === 'SL_HIT') return '손절 기준 도달';
    if (exitType === 'TP1_HIT') return _isPartialExit(partial) ? '1차 목표가 도달' : '목표가 도달';
    if (exitType === 'TP2_HIT') return '2차 목표가 도달';
    if (exitType === 'TRAILING_STOP') return '트레일링 스탑 발동';
    if (exitType === 'TREND_REVERSAL') return '추세 반전 감지';
    if (exitType === 'TIME_STOP') return '시간 기준 정리';
    if (exitType === 'REVIEW') return '포지션 점검';
    return exitType || '포지션 점검';
}

function _sellGuidance(exitType, partial) {
    if (exitType === 'TP1_HIT') {
        return _isPartialExit(partial)
            ? '1차 목표 도달. 일부 수익 실현 후 잔여 물량은 트레일링으로 관리.'
            : '목표가 도달. 포지션 청산 결과를 확인.';
    }
    if (exitType === 'TP2_HIT') return '2차 목표 도달. 잔여 포지션 청산 결과를 확인.';
    if (exitType === 'SL_HIT') return '손절 기준 도달. 추가 진입 없이 재평가.';
    if (exitType === 'TRAILING_STOP') return '이익 보호 기준 발동. 잔여 포지션 정리 여부 확인.';
    if (exitType === 'TIME_STOP') return '보유 시간 기준 도달. 자금 회전과 리스크를 우선 확인.';
    return null;
}

function _partialLabel(partial) {
    if (typeof partial === 'number') return `${partial}%`;
    if (partial === true) return '부분 청산';
    if (partial === false) return '전량/단일 목표 청산';
    if (partial == null) return null;
    return String(partial);
}

function _isPartialExit(partial) {
    if (typeof partial === 'number') return partial > 0 && partial < 100;
    if (typeof partial === 'string') {
        const normalized = partial.trim().toLowerCase();
        if (normalized === 'false' || normalized === '0' || normalized === '100%') return false;
        return normalized.length > 0;
    }
    return partial === true;
}

function _formatPercent(value) {
    if (value == null || value === '') return null;
    const num = Number(value);
    if (!Number.isFinite(num)) return null;
    const sign = num >= 0 ? '+' : '';
    return `${sign}${num.toFixed(2)}%`;
}

function _appendSellFooter(lines, item) {
    const ts = item.timestamp || item.signal_time || new Date();
    const dt = ts instanceof Date ? ts : new Date(ts);
    const displayTs = Number.isNaN(dt.getTime()) ? new Date() : dt;
    lines.push('');
    lines.push(`시간: ${displayTs.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })}`);
}

function formatNewsAlert(item) {
    const sentimentLabel = { BULLISH: '강세 📈', BEARISH: '약세 📉', NEUTRAL: '중립 ➡️' };

    const lines = [
        `📰 <b>[뉴스 브리프]</b>`,
        `시장심리: <b>${escapeHtml(sentimentLabel[item.market_sentiment] || item.market_sentiment || '-')}</b>`,
    ];
    if (item.sectors && item.sectors.length > 0) {
        lines.push(`추천섹터: <code>${escapeHtml(item.sectors.join(', '))}</code>`);
    }
    if (item.summary) {
        lines.push(`<blockquote>${escapeHtml(item.summary)}</blockquote>`);
    }
    return lines.join('\n');
}

function formatSignalEnhanced(item) {
    return formatSignal(item);
}

function formatPerformanceSummaryEnhanced(rows) {
    if (!rows || rows.length === 0) {
        return formatPerformanceSummary(rows);
    }

    const sorted = [...rows].sort((a, b) => Number(b[1] ?? 0) - Number(a[1] ?? 0));
    const totalTrades = sorted.reduce((sum, [, total]) => sum + Number(total ?? 0), 0);
    const totalWins = sorted.reduce((sum, [, , wins]) => sum + Number(wins ?? 0), 0);
    const totalLosses = sorted.reduce((sum, [, , , losses]) => sum + Number(losses ?? 0), 0);
    const overallWinRate = (totalWins + totalLosses) > 0
        ? ((totalWins / (totalWins + totalLosses)) * 100).toFixed(0)
        : '-';

    const lines = [
        '?뱤 <b>?꾨왂蹂?媛???깃낵</b>',
        `총 ${totalTrades}건 | 승 ${totalWins} / 패 ${totalLosses} | 승률 ${overallWinRate}%`,
        '',
    ];

    for (const row of sorted) {
        const [strategy, total, wins, losses, avgPnl] = row;
        const winRate = total > 0 ? ((Number(wins) / Number(total)) * 100).toFixed(0) : '-';
        const pnlStr = avgPnl != null ? `${Number(avgPnl).toFixed(2)}%` : 'N/A';
        lines.push(`${STRATEGY_EMOJI[strategy] ?? '??'} ${strategy}: ${total}건 | 승률 ${winRate}% | 평균 ${pnlStr}`);
    }
    return lines.join('\n');
}

function formatPerformanceDetailEnhanced(signals, summaryRows) {
    const base = formatPerformanceDetail(signals, summaryRows);
    if (!signals || signals.length === 0) {
        return base;
    }

    const openSignals = signals.filter((s) => s.realizedPnl == null);
    const closedSignals = signals.filter((s) => s.realizedPnl != null);
    const extra = [];

    if (openSignals.length > 0) {
        extra.push('');
        extra.push(`오픈 포지션: <b>${openSignals.length}건</b>`);
        openSignals.slice(0, 5).forEach((s, index) => {
            const stockLabel = s.stkNm ?? s.stkCd;
            extra.push(`${index + 1}. ${stockLabel} [${s.strategy}]`);
        });
        if (openSignals.length > 5) {
            extra.push(`...외 ${openSignals.length - 5}건`);
        }
    }

    if (closedSignals.length > 0) {
        const avgClosedPnl = closedSignals
            .reduce((sum, s) => sum + Number(s.realizedPnl ?? 0), 0) / closedSignals.length;
        extra.push('');
        extra.push(`청산 평균 P&L: <b>${avgClosedPnl.toFixed(2)}%</b>`);
    }

    return `${base}${extra.length > 0 ? `\n${extra.join('\n')}` : ''}`;
}

function formatUserSettingsEnhanced(filter, watchlist) {
    const base = formatUserSettings(filter, watchlist);
    const lines = [
        base,
        '',
        '명령 예시',
        '/filter all',
        '/filter s1 s4 s8',
        '/watchAdd 005930',
        '/watchRemove 005930',
    ];
    return lines.join('\n');
}

module.exports = {
    escapeHtml,
    formatSignal: formatSignalEnhanced, formatForceClose, formatDailySummary,
    formatPerformanceSummary: formatPerformanceSummaryEnhanced, formatNewsStatus, formatSectorAnalysis,
    formatSignalHistory, formatSystemHealth,
    formatDailyReportEnhanced, formatCalendarWeek, formatPerformanceDetail: formatPerformanceDetailEnhanced, formatUserSettings: formatUserSettingsEnhanced,
    formatStockScore, formatSellSignal, formatSellRecommendation, formatNewsAlert, formatRuleOnlySignal,
    formatHoldWatch, formatHoldReleased,
};
