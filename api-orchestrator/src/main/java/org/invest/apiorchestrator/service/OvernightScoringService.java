package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * 오버나잇 보유 가능성 규칙 기반 사전 스코어링.
 * scorer.py 의 rule_score() 와 동일한 철학 – 규칙으로 먼저 필터링하여
 * Claude API 호출 비용을 줄인다.
 *
 * 점수 구성:
 *   전략 적합도 (5~35점) + 등락률 (-15~20점) + 미실현 손익 (-25~25점)
 *   + 호가비율 (0~15점) + 체결강도 (0~10점)  ⟹ 합계 0~100
 *
 * OVERNIGHT_EVAL_THRESHOLD(65) 이상이면 Claude 최종 판단 큐로 전달.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OvernightScoringService {

    private final RedisMarketDataService redisService;
    private final KiwoomApiService kiwoomApiService;

    /** Claude 평가 큐로 올릴 최소 점수 */
    public static final double OVERNIGHT_EVAL_THRESHOLD = 65.0;

    /**
     * 오버나잇 보유 규칙 점수 계산 (0~100).
     *
     * @param signal 평가 대상 TradingSignal
     * @return 0.0 ~ 100.0 점수
     */
    public double calcOvernightScore(TradingSignal signal) {
        double score = 0.0;
        String stkCd = signal.getStkCd();

        // 1. 전략별 오버나잇 적합도
        score += strategyBonus(signal.getStrategy());

        // 2. 실시간 틱 데이터 (flu_rt, cur_prc)
        double fluRt  = 0.0;
        double curPrc = 0.0;
        Optional<Map<Object, Object>> tickOpt = redisService.getTickData(stkCd);
        if (tickOpt.isPresent()) {
            Map<Object, Object> tick = tickOpt.get();
            fluRt  = safeDouble(tick.get("flu_rt"));
            curPrc = safeDouble(tick.get("cur_prc"));
            score += fluRtBonus(fluRt);
        }

        // 3. 미실현 손익 (진입가 대비 현재가)
        if (signal.getEntryPrice() != null && signal.getEntryPrice() > 0 && curPrc > 0) {
            double pnlPct = (curPrc - signal.getEntryPrice()) / signal.getEntryPrice() * 100.0;
            score += pnlBonus(pnlPct);
        }

        // 4. 호가 매수 우위
        Optional<Map<Object, Object>> hogaOpt = redisService.getHogaData(stkCd);
        if (hogaOpt.isPresent()) {
            Map<Object, Object> hoga = hogaOpt.get();
            double bid = safeDouble(hoga.get("total_buy_bid_req"));
            double ask = safeDouble(hoga.get("total_sel_bid_req"));
            if (ask > 0) {
                score += bidRatioBonus(bid / ask);
            }
        }

        // 5. 체결강도
        double strength = redisService.getAvgCntrStrength(stkCd, 5);
        score += strengthBonus(strength);

        double result = Math.round(Math.max(0.0, Math.min(100.0, score)) * 10) / 10.0;
        log.debug("[OvernightScore] {} {} fluRt={} score={}", stkCd, signal.getStrategy(), fluRt, result);
        return result;
    }

    /**
     * 전략·진입가 없이 종목코드만으로 점수 계산 (개인 종목 수동 조회용).
     *
     * 데이터 우선순위:
     *   1차) WebSocket Redis 실시간 데이터 (tick/hoga/strength 모두 활용)
     *   2차) Kiwoom REST API ka10001 fallback (WebSocket 미구독 시 – flu_rt/cur_prc만 활용)
     *
     * @return Map with keys: score, stk_nm, flu_rt, cur_prc, bid_ratio, cntr_strength,
     *                        score_momentum, score_pressure, score_strength,
     *                        data_available, data_source ("WS" | "REST" | "NONE")
     */
    public Map<String, Object> calcManualScore(String stkCd) {
        double momentum = 0, pressure = 0, strengthScore = 0;
        double fluRt = 0, curPrc = 0, bidRatio = 0, strength = 100.0;
        String stkNm = "";
        String dataSource = "NONE";

        // ── 1차: WebSocket Redis 데이터 ──────────────────────────────
        Optional<Map<Object, Object>> tickOpt = redisService.getTickData(stkCd);
        if (tickOpt.isPresent()) {
            dataSource = "WS";
            Map<Object, Object> tick = tickOpt.get();
            fluRt  = safeDouble(tick.get("flu_rt"));
            curPrc = safeDouble(tick.get("cur_prc"));
            momentum = momentumScore(fluRt);

            Optional<Map<Object, Object>> hogaOpt = redisService.getHogaData(stkCd);
            if (hogaOpt.isPresent()) {
                Map<Object, Object> hoga = hogaOpt.get();
                double bid = safeDouble(hoga.get("total_buy_bid_req"));
                double ask = safeDouble(hoga.get("total_sel_bid_req"));
                if (ask > 0) {
                    bidRatio = bid / ask;
                    pressure = bidRatioBonus(bidRatio);
                }
            }

            strength = redisService.getAvgCntrStrength(stkCd, 5);
            strengthScore = strengthBonus(strength);

        } else {
            // ── 2차: Kiwoom REST API fallback ────────────────────────
            try {
                KiwoomApiResponses.StkBasicInfoResponse basic = kiwoomApiService.fetchKa10001(stkCd);
                if (basic != null) {
                    fluRt  = safeDouble(basic.getFluRt());
                    curPrc = Math.abs(safeDouble(basic.getCurPrc()));  // 키움: 하락 종목은 cur_prc에 '-' 부호 포함 → 절댓값으로 실제 가격 추출
                    stkNm  = basic.getStkNm() != null ? basic.getStkNm() : "";
                    momentum = momentumScore(fluRt);
                    dataSource = "REST";
                    log.info("[ManualScore] REST fallback 성공 [{}] fluRt={} curPrc={}", stkCd, fluRt, curPrc);
                }
            } catch (Exception e) {
                log.warn("[ManualScore] REST fallback 실패 [{}]: {}", stkCd, e.getMessage());
            }
        }

        boolean dataAvailable = !"NONE".equals(dataSource);

        // 기본 베이스 25점 + 각 구성 요소
        double total = Math.round(Math.max(0.0, Math.min(100.0, 25 + momentum + pressure + strengthScore)) * 10) / 10.0;

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("stk_cd",              stkCd);
        result.put("stk_nm",              stkNm);
        result.put("score",               total);
        result.put("overnight_threshold", OVERNIGHT_EVAL_THRESHOLD);
        result.put("cur_prc",             (long) curPrc);
        result.put("flu_rt",              fluRt);
        result.put("bid_ratio",           Math.round(bidRatio * 100.0) / 100.0);
        result.put("cntr_strength",       Math.round(strength * 10.0) / 10.0);
        result.put("score_momentum",      momentum);
        result.put("score_pressure",      pressure);
        result.put("score_strength",      strengthScore);
        result.put("data_available",      dataAvailable);
        result.put("data_source",         dataSource);
        return result;
    }

    /** 등락률 기반 모멘텀 점수 (수동 조회용, 최대 25점) */
    private double momentumScore(double fluRt) {
        if (fluRt >= 2.0 && fluRt <= 8.0) return 25;   // 이상적 상승
        if (fluRt >= 0.0 && fluRt < 2.0)  return 15;   // 소폭 상승
        if (fluRt >= -2.0)                 return 5;    // 보합/소폭 하락
        if (fluRt < -5.0)                  return -20;  // 급락
        return -10;                                       // 하락
    }

    // ──── 점수 계산 헬퍼 ──────────────────────────────────────────

    private double strategyBonus(TradingSignal.StrategyType strategy) {
        return switch (strategy) {
            // 기관·외인 수급 기반: 수급이 살아있으면 익일도 지속되는 경향
            case S3_INST_FRGN, S5_PROG_FRGN -> 35;
            // 종가강도·외국인연속: 다음날 갭상승 기대
            case S12_CLOSING, S11_FRGN_CONT -> 30;
            // 신고가·박스돌파 모멘텀: 돌파 후 추세 지속
            case S10_NEW_HIGH, S13_BOX_BREAKOUT -> 30;
            // 스윙 전략: 다음날도 보유 적합
            case S7_ICHIMOKU_BREAKOUT, S8_GOLDEN_CROSS, S9_PULLBACK_SWING -> 25;
            // 다중지표 동조: 추세 지속 가능성 높음
            case S15_MOMENTUM_ALIGN -> 25;
            // 과매도 반등: 추세 불확실 – 중립
            case S14_OVERSOLD_BOUNCE -> 15;
            // 장대양봉·테마후발: 중립 – 상황에 따라 다름
            case S4_BIG_CANDLE, S6_THEME_LAGGARD -> 15;
            // 갭오픈·VI눌림·레거시 동시호가(S7_AUCTION): 오버나잇 부적합
            case S1_GAP_OPEN, S2_VI_PULLBACK, S7_AUCTION -> 5;
        };
    }

    /** 등락률 기반 가감점 */
    private double fluRtBonus(double fluRt) {
        if (fluRt >= 1.0 && fluRt <= 6.0) return 20;   // 적정 상승 – 최적
        if (fluRt >= 0.0)                  return 10;   // 보합권
        if (fluRt >= -2.0)                 return 0;    // 소폭 하락 – 중립
        return -15;                                       // 낙폭 과대 – 페널티
    }

    /** 미실현 손익 기반 가감점 */
    private double pnlBonus(double pnlPct) {
        if (pnlPct < -2.0)  return -25;  // 손절 구간 → 청산 권고
        if (pnlPct < 0.0)   return   5;  // 소폭 마이너스 – 관망 가능
        if (pnlPct < 1.0)   return  15;  // 소폭 플러스
        if (pnlPct < 4.0)   return  25;  // 건강한 수익 구간 – 홀딩 최적
        if (pnlPct < 7.0)   return  10;  // 목표가 근접 – 부분 익절 고려
        return -10;                        // 목표 초과 → 익절 권고
    }

    /** 호가비율 기반 가감점 */
    private double bidRatioBonus(double bidRatio) {
        if (bidRatio > 1.5) return 15;
        if (bidRatio > 1.2) return 10;
        return 0;
    }

    /** 체결강도 기반 가감점 */
    private double strengthBonus(double strength) {
        if (strength >= 120) return 10;
        if (strength >= 100) return  5;
        return 0;
    }

    private double safeDouble(Object v) {
        if (v == null) return 0.0;
        try {
            return Double.parseDouble(v.toString().replace(",", "").replace("+", ""));
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }
}
