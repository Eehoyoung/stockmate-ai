package org.invest.apiorchestrator.scheduler;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.domain.TradingSignal.SignalStatus;
import org.invest.apiorchestrator.domain.TradingSignal.StrategyType;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import org.invest.apiorchestrator.util.KstClock;
import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * OvernightRiskScheduler – 장전 갭다운 경보 (G3)
 *
 * 08:30에 전일 SENT/OVERNIGHT_HOLD 상태인 스윙 신호를 조회하여
 * 시간외단일가(ka10087) 또는 ws:expected 데이터로 장전 등락률을 확인한다.
 * 등락률 ≤ -3% 이면 OVERNIGHT_RISK_ALERT 를 telegram_queue 에 발행한다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OvernightRiskScheduler {

    private final TradingSignalRepository signalRepository;
    private final RedisMarketDataService  redisService;
    private final KiwoomApiService        kiwoomApiService;
    private final ObjectMapper            objectMapper;

    /** 갭다운 경보 임계값 (등락률 ≤ -3%) */
    private static final double GAP_DOWN_THRESHOLD = -3.0;

    /** 오버나잇 보유 대상 전략 */
    private static final Set<StrategyType> SWING_STRATEGIES = EnumSet.of(
            StrategyType.S8_GOLDEN_CROSS,
            StrategyType.S9_PULLBACK_SWING,
            StrategyType.S10_NEW_HIGH,
            StrategyType.S11_FRGN_CONT,
            StrategyType.S13_BOX_BREAKOUT,
            StrategyType.S14_OVERSOLD_BOUNCE,
            StrategyType.S15_MOMENTUM_ALIGN
    );

    @Scheduled(cron = "0 30 8 * * MON-FRI", zone = "Asia/Seoul")
    public void checkOvernightRisk() {
        log.info("=== 장전 갭다운 경보 스캔 시작 (08:30) ===");
        try {
            // 직전 2거래일 이내 SENT 또는 OVERNIGHT_HOLD 신호 조회
            LocalDateTime since = KstClock.now().minusDays(2);
            List<TradingSignal> candidates = new java.util.ArrayList<>(
                    signalRepository.findBySignalStatusAndCreatedAtAfter(SignalStatus.SENT, since));
            candidates.addAll(
                    signalRepository.findBySignalStatusAndCreatedAtAfter(SignalStatus.OVERNIGHT_HOLD, since));

            if (candidates.isEmpty()) {
                log.info("[OvernightRisk] 오버나잇 보유 신호 없음");
                return;
            }

            int alertCount = 0;

            for (TradingSignal signal : candidates) {
                if (!SWING_STRATEGIES.contains(signal.getStrategy())) continue;

                String stkCd  = signal.getStkCd();
                double fluRt  = resolvePreMarketFluRt(stkCd);

                if (fluRt <= GAP_DOWN_THRESHOLD) {
                    pushAlert(signal, fluRt);
                    alertCount++;
                }
            }
            log.info("[OvernightRisk] 스캔 완료 – 경보 {}건 발행", alertCount);

        } catch (Exception e) {
            log.error("[OvernightRisk] 스캔 오류: {}", e.getMessage());
        }
    }

    /**
     * 장전 등락률 조회 순서:
     *   1) Redis ws:expected:{stkCd} – key "12" (예상등락율)
     *   2) Kiwoom REST ka10087 – ovt_sigpric_flu_rt
     *   3) 조회 실패 시 0.0 반환 (경보 미발행)
     */
    private double resolvePreMarketFluRt(String stkCd) {
        // 1) Redis ws:expected 우선 조회
        try {
            Optional<Map<Object, Object>> expData = redisService.getExpectedData(stkCd);
            if (expData.isPresent()) {
                Object fluRtVal = expData.get().get("12"); // key 12 = 예상등락율
                if (fluRtVal != null) {
                    return parseDouble(fluRtVal.toString());
                }
            }
        } catch (Exception e) {
            log.debug("[OvernightRisk] ws:expected 조회 실패 [{}]: {}", stkCd, e.getMessage());
        }

        // 2) ka10087 시간외단일가 폴백
        try {
            KiwoomApiResponses.OvtSigPricResponse resp = kiwoomApiService.fetchKa10087(stkCd);
            if (resp != null && resp.isSuccess() && resp.getOvtSigpricFluRt() != null) {
                return parseDouble(resp.getOvtSigpricFluRt());
            }
        } catch (Exception e) {
            log.debug("[OvernightRisk] ka10087 조회 실패 [{}]: {}", stkCd, e.getMessage());
        }

        return 0.0;
    }

    private double parseDouble(String val) {
        if (val == null || val.isBlank()) return 0.0;
        try {
            return Double.parseDouble(val.replace("+", "").replace(",", "").trim());
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }

    private void pushAlert(TradingSignal signal, double fluRt) {
        try {
            String msg = objectMapper.writeValueAsString(Map.of(
                    "type",        "OVERNIGHT_RISK_ALERT",
                    "stk_cd",      signal.getStkCd(),
                    "stk_nm",      signal.getStkNm() != null ? signal.getStkNm() : "",
                    "strategy",    signal.getStrategy().name(),
                    "flu_rt",      fluRt,
                    "entry_price", signal.getEntryPrice() != null ? signal.getEntryPrice() : 0,
                    "stop_price",  signal.getStopPrice()  != null ? signal.getStopPrice()  : 0,
                    "message",     String.format(
                            "⚠️ 갭다운 경보 [%s] %s %s\n장전 예상 등락률 %.2f%% – 손절선 재확인 필요",
                            signal.getStrategy().name(),
                            signal.getStkCd(),
                            signal.getStkNm() != null ? signal.getStkNm() : "",
                            fluRt)
            ));
            redisService.pushTelegramQueue(msg);
            log.warn("[OvernightRisk] 경보 발행 [{}] fluRt={}%", signal.getStkCd(), fluRt);
        } catch (Exception e) {
            log.error("[OvernightRisk] 경보 발행 실패 [{}]: {}", signal.getStkCd(), e.getMessage());
        }
    }
}
