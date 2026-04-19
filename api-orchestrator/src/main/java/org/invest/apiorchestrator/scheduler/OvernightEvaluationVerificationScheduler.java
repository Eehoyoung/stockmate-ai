package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.OvernightEvaluation;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.OvernightEvaluationRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class OvernightEvaluationVerificationScheduler {

    private final OvernightEvaluationRepository overnightEvaluationRepository;
    private final RedisMarketDataService redisMarketDataService;
    private final KiwoomApiService kiwoomApiService;

    @Scheduled(cron = "0 5,20,35 9 * * MON-FRI", zone = "Asia/Seoul")
    @Transactional
    public void verifyNextDayOpen() {
        try {
            int updated = 0;
            for (OvernightEvaluation eval : overnightEvaluationRepository.findPendingVerification(OffsetDateTime.now().minusHours(8))) {
                BigDecimal nextOpen = resolveNextDayOpen(eval.getStkCd());
                if (nextOpen == null || eval.getEntryPrice() == null || eval.getEntryPrice().compareTo(BigDecimal.ZERO) <= 0) {
                    continue;
                }
                BigDecimal pnlPct = nextOpen.subtract(eval.getEntryPrice())
                        .multiply(BigDecimal.valueOf(100))
                        .divide(eval.getEntryPrice(), 4, RoundingMode.HALF_UP);
                boolean verdictCorrect = "HOLD".equalsIgnoreCase(eval.getVerdict())
                        ? pnlPct.compareTo(BigDecimal.ZERO) >= 0
                        : pnlPct.compareTo(BigDecimal.ZERO) <= 0;
                overnightEvaluationRepository.save(copyWithVerification(eval, nextOpen, pnlPct, verdictCorrect));
                updated++;
            }
            if (updated > 0) {
                log.info("[OvernightEval] verification updated: {}", updated);
            }
        } catch (Exception e) {
            log.warn("[OvernightEval] verification failed: {}", e.getMessage());
        }
    }

    private BigDecimal resolveNextDayOpen(String stkCd) {
        try {
            Map<Object, Object> expected = redisMarketDataService.getExpectedData(stkCd).orElse(null);
            if (expected != null && expected.get("exp_cntr_pric") != null) {
                BigDecimal price = dec(expected.get("exp_cntr_pric"));
                if (price != null && price.compareTo(BigDecimal.ZERO) > 0) {
                    return price;
                }
            }
            KiwoomApiResponses.StkBasicInfoResponse resp = kiwoomApiService.fetchKa10001(stkCd);
            if (resp != null && resp.isSuccess()) {
                BigDecimal openPrice = dec(resp.getOpenPric());
                if (openPrice != null && openPrice.compareTo(BigDecimal.ZERO) > 0) {
                    return openPrice;
                }
                BigDecimal curPrice = dec(resp.getCurPrc());
                if (curPrice != null && curPrice.compareTo(BigDecimal.ZERO) > 0) {
                    return curPrice;
                }
            }
        } catch (Exception e) {
            log.debug("[OvernightEval] next open resolve failed [{}]: {}", stkCd, e.getMessage());
        }
        return null;
    }

    private OvernightEvaluation copyWithVerification(OvernightEvaluation source,
                                                     BigDecimal nextOpen,
                                                     BigDecimal pnlPct,
                                                     boolean verdictCorrect) {
        return OvernightEvaluation.builder()
                .id(source.getId())
                .signalId(source.getSignalId())
                .positionId(source.getPositionId())
                .stkCd(source.getStkCd())
                .strategy(source.getStrategy())
                .javaOvernightScore(source.getJavaOvernightScore())
                .finalScore(source.getFinalScore())
                .verdict(source.getVerdict())
                .confidence(source.getConfidence())
                .reason(source.getReason())
                .pnlPct(source.getPnlPct())
                .fluRt(source.getFluRt())
                .cntrStrength(source.getCntrStrength())
                .rsi14(source.getRsi14())
                .maAlignment(source.getMaAlignment())
                .bidRatio(source.getBidRatio())
                .entryPrice(source.getEntryPrice())
                .curPrcAtEval(source.getCurPrcAtEval())
                .scoreComponents(source.getScoreComponents())
                .nextDayOpen(nextOpen)
                .nextDayPnlPct(pnlPct)
                .verdictCorrect(verdictCorrect)
                .evaluatedAt(source.getEvaluatedAt())
                .build();
    }

    private BigDecimal dec(Object raw) {
        if (raw == null) {
            return null;
        }
        try {
            return BigDecimal.valueOf(Double.parseDouble(raw.toString().replace(",", "").replace("+", "").trim()))
                    .setScale(0, RoundingMode.HALF_UP);
        } catch (Exception e) {
            return null;
        }
    }
}
