package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.domain.PortfolioConfig;
import org.invest.apiorchestrator.domain.RiskEvent;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.CandidatePoolHistoryRepository;
import org.invest.apiorchestrator.repository.PortfolioConfigRepository;
import org.invest.apiorchestrator.repository.RiskEventRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.util.KstClock;
import org.invest.apiorchestrator.util.StockCodeNormalizer;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
public class SignalService {

    private final TradingSignalRepository signalRepository;
    private final RedisMarketDataService redisService;
    private final CandidateService candidateService;
    private final KiwoomProperties properties;
    private final ObjectMapper objectMapper;
    private final PortfolioConfigRepository portfolioConfigRepository;
    private final RiskEventRepository riskEventRepository;
    private final CandidatePoolHistoryRepository candidatePoolHistoryRepository;

    private static final Map<String, String> THEME_TO_SECTOR = Map.ofEntries(
            Map.entry("반도체", "반도체"), Map.entry("HBM", "반도체"), Map.entry("AI반도체", "반도체"),
            Map.entry("메모리", "반도체"), Map.entry("시스템반도체", "반도체"),
            Map.entry("2차전지", "2차전지"), Map.entry("배터리", "2차전지"), Map.entry("전기차", "2차전지"),
            Map.entry("양극재", "2차전지"), Map.entry("음극재", "2차전지"),
            Map.entry("바이오", "바이오"), Map.entry("제약", "바이오"), Map.entry("신약", "바이오"),
            Map.entry("의료기기", "바이오"), Map.entry("헬스케어", "바이오"),
            Map.entry("방산", "방산"), Map.entry("무기", "방산"),
            Map.entry("조선", "조선"), Map.entry("해운", "조선"),
            Map.entry("자동차", "자동차"), Map.entry("부품", "자동차"),
            Map.entry("AI", "AI"), Map.entry("인공지능", "AI"), Map.entry("로봇", "AI"),
            Map.entry("에너지", "에너지"), Map.entry("태양광", "에너지"), Map.entry("수소", "에너지")
    );

    public SignalService(TradingSignalRepository signalRepository,
                         RedisMarketDataService redisService,
                         CandidateService candidateService,
                         KiwoomProperties properties,
                         ObjectMapper objectMapper,
                         PortfolioConfigRepository portfolioConfigRepository,
                         RiskEventRepository riskEventRepository,
                         CandidatePoolHistoryRepository candidatePoolHistoryRepository) {
        this.signalRepository = signalRepository;
        this.redisService = redisService;
        this.candidateService = candidateService;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.portfolioConfigRepository = portfolioConfigRepository;
        this.riskEventRepository = riskEventRepository;
        this.candidatePoolHistoryRepository = candidatePoolHistoryRepository;
    }

    @Transactional
    public boolean processSignal(TradingSignalDto dto) {
        String stkCd = StockCodeNormalizer.normalize(dto.getStkCd());
        String strategy = dto.getStrategy().name();
        MDC.put("strategy", strategy);
        MDC.put("stk_cd", stkCd);
        try {
            if (redisService.isSignalDuplicate(stkCd, strategy)) {
                log.debug("중복 신호 무시 [{} {}]", stkCd, strategy);
                return false;
            }

            int cooldownMin = properties.getTrading().getStockCooldownMinutes();
            if (!redisService.tryAcquireStockCooldown(stkCd, cooldownMin)) {
                log.debug("종목 쿨다운 중 [{} 모든전략 {}분]", stkCd, cooldownMin);
                return false;
            }

            int maxDaily = properties.getTrading().getMaxDailySignals();
            long dailyCount = redisService.incrementDailySignalCount();
            if (dailyCount > maxDaily) {
                log.warn("[Signal] 일일 신호 상한 초과 ({}/{}), 신호 무시 [{} {}]",
                        dailyCount, maxDaily, stkCd, strategy);
                return false;
            }

            PortfolioConfig config = portfolioConfigRepository.findSingleton().orElse(null);
            if (config != null) {
                if (signalRepository.existsActivePosition(stkCd)) {
                    logRiskEvent("DUPLICATE_SIGNAL_BLOCKED", stkCd, strategy, null,
                            null, null, "이미 활성 포지션 보유 중인 종목", "신호 무시");
                    log.warn("[Signal] 이중매수 차단 [{} {}] 활성 포지션 존재", stkCd, strategy);
                    return false;
                }
                long activeCount = signalRepository.countActivePositions();
                int maxCount = config.getMaxPositionCount();
                if (activeCount >= maxCount) {
                    logRiskEvent("MAX_POSITION_EXCEEDED", stkCd, strategy, null,
                            new BigDecimal(maxCount), new BigDecimal(activeCount),
                            "최대 포지션 수 초과", "신호 무시");
                    log.warn("[Signal] 최대 포지션 수 초과 [{}/{}], 신호 무시 [{} {}]",
                            activeCount, maxCount, stkCd, strategy);
                    return false;
                }
            }

            TradingSignal signal = buildSignalEntity(dto);
            signalRepository.save(signal);

            try {
                candidatePoolHistoryRepository.markLedToSignal(
                        KstClock.today(), strategy, dto.getMarketType(), stkCd, signal.getId());
            } catch (Exception e) {
                log.debug("[Signal] pool history 갱신 실패 (무시): {}", e.getMessage());
            }

            candidateService.tagStrategy(stkCd, strategy);
            trackSectorOverheat(dto.getThemeName());

            try {
                String telegramMsg = objectMapper.writeValueAsString(dto.toQueuePayload(signal.getId()));
                redisService.pushTelegramQueue(telegramMsg);
                log.info("신호 발행 [{} {}] score={}", stkCd, strategy, dto.getSignalScore());
            } catch (Exception e) {
                log.error("텔레그램 큐 발행 실패: {}", e.getMessage());
            }

            return true;
        } finally {
            MDC.remove("strategy");
            MDC.remove("stk_cd");
        }
    }

    @Transactional
    public int processSignals(List<TradingSignalDto> signals) {
        int maxPerStrategy = properties.getTrading().getMaxSignalsPerStrategy();
        int count = 0;
        for (TradingSignalDto dto : signals.stream().limit(maxPerStrategy).toList()) {
            if (processSignal(dto)) {
                count++;
            }
        }
        return count;
    }

    @Transactional(readOnly = true)
    public List<TradingSignal> getTodaySignals() {
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);
        return signalRepository.findTodaySignals(startOfDay);
    }

    @Transactional(readOnly = true)
    public List<Object[]> getTodayStats() {
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);
        return signalRepository.getStrategyStats(startOfDay);
    }

    @Transactional(readOnly = true)
    public List<Object[]> getPerformanceStats() {
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);
        return signalRepository.getStrategyPerformanceStats(startOfDay);
    }

    @Transactional
    public int expireOldSignals() {
        LocalDateTime expireBefore = KstClock.now()
                .minusSeconds(properties.getTrading().getSignalTtlSeconds());
        return signalRepository.expireOldSignals(expireBefore);
    }

    private TradingSignal buildSignalEntity(TradingSignalDto dto) {
        BigDecimal entryPrice = toPrice(dto.getEntryPrice());
        BigDecimal tp1Price = resolveTargetPrice(dto.getTp1Price(), dto.getTargetPct(), dto::calcTarget1Price);
        BigDecimal tp2Price = resolveTargetPrice(dto.getTp2Price(), dto.resolvedTarget2Pct(), dto::calcTarget2Price);
        BigDecimal slPrice = resolveStopPrice(dto.getSlPrice(), dto.getStopPct(), dto::calcStopPrice, entryPrice);

        BigDecimal rrRatio = dto.getRrRatio() != null
                ? BigDecimal.valueOf(dto.getRrRatio()).setScale(2, RoundingMode.HALF_UP)
                : deriveRr(entryPrice, tp1Price, slPrice);

        return TradingSignal.builder()
                .stkCd(StockCodeNormalizer.normalize(dto.getStkCd()))
                .stkNm(dto.getStkNm())
                .strategy(dto.getStrategy())
                .signalScore(dto.getSignalScore())
                .entryPrice(dto.getEntryPrice())
                .targetPrice(tp1Price != null ? tp1Price.doubleValue() : null)
                .stopPrice(slPrice != null ? slPrice.doubleValue() : null)
                .tp1Price(tp1Price != null ? tp1Price.doubleValue() : null)
                .tp2Price(tp2Price != null ? tp2Price.doubleValue() : null)
                .slPrice(slPrice != null ? slPrice.doubleValue() : null)
                .targetPct(dto.getTargetPct())
                .stopPct(dto.getStopPct())
                .tpMethod(dto.getTpMethod())
                .slMethod(dto.getSlMethod())
                .rrRatio(rrRatio)
                .skipEntry(dto.getSkipEntry() != null ? dto.getSkipEntry() : false)
                .entryType(dto.getEntryType())
                .marketType(dto.getMarketType())
                .gapPct(dto.getGapPct())
                .cntrStrength(dto.getCntrStrength())
                .bidRatio(dto.getBidRatio())
                .volRatio(dto.getVolRatio())
                .pullbackPct(dto.getPullbackPct())
                .themeName(dto.getThemeName())
                .sector(resolveSector(dto.getThemeName()))
                .signalStatus(TradingSignal.SignalStatus.SENT)
                .positionStatus(entryPrice != null && entryPrice.compareTo(BigDecimal.ZERO) > 0 ? "ACTIVE" : null)
                .entryAt(entryPrice != null && entryPrice.compareTo(BigDecimal.ZERO) > 0 ? OffsetDateTime.now() : null)
                .monitorEnabled(true)
                .isOvernight(false)
                .trailingPct(dto.getTrailingPct() != null
                        ? BigDecimal.valueOf(dto.getTrailingPct()).setScale(2, RoundingMode.HALF_UP)
                        : null)
                .trailingActivation(dto.getTrailingActivation() != null
                        ? BigDecimal.valueOf(dto.getTrailingActivation()).setScale(0, RoundingMode.HALF_UP)
                        : null)
                .trailingBasis(dto.getTrailingBasis())
                .strategyVersion(dto.getStrategyVersion())
                .timeStopType(dto.getTimeStopType())
                .timeStopMinutes(dto.getTimeStopMinutes())
                .timeStopSession(dto.getTimeStopSession())
                .ruleScore(dto.getSignalScore() != null
                        ? BigDecimal.valueOf(dto.getSignalScore()).setScale(2, RoundingMode.HALF_UP)
                        : null)
                .build();
    }

    private BigDecimal resolveTargetPrice(Double directPrice, Double targetPct, TargetPriceCalculator fallback) {
        if (directPrice != null && directPrice > 0) {
            return BigDecimal.valueOf(directPrice).setScale(0, RoundingMode.HALF_UP);
        }
        if (targetPct == null) {
            return null;
        }
        double calculated = fallback.calculate();
        return calculated > 0 ? BigDecimal.valueOf(calculated).setScale(0, RoundingMode.HALF_UP) : null;
    }

    private BigDecimal resolveStopPrice(Double directPrice, Double stopPct, TargetPriceCalculator fallback, BigDecimal entryPrice) {
        if (directPrice != null && directPrice > 0) {
            return BigDecimal.valueOf(directPrice).setScale(0, RoundingMode.HALF_UP);
        }
        if (stopPct != null) {
            double calculated = fallback.calculate();
            if (calculated > 0) {
                return BigDecimal.valueOf(calculated).setScale(0, RoundingMode.HALF_UP);
            }
        }
        if (entryPrice != null && entryPrice.compareTo(BigDecimal.ZERO) > 0) {
            return entryPrice.multiply(new BigDecimal("0.97")).setScale(0, RoundingMode.HALF_UP);
        }
        return null;
    }

    private BigDecimal deriveRr(BigDecimal entryPrice, BigDecimal tp1Price, BigDecimal slPrice) {
        if (entryPrice == null || tp1Price == null || slPrice == null) {
            return null;
        }
        if (entryPrice.compareTo(BigDecimal.ZERO) <= 0 || slPrice.compareTo(entryPrice) >= 0) {
            return null;
        }
        BigDecimal reward = tp1Price.subtract(entryPrice);
        BigDecimal risk = entryPrice.subtract(slPrice);
        if (risk.compareTo(BigDecimal.ZERO) <= 0) {
            return null;
        }
        return reward.divide(risk, 2, RoundingMode.HALF_UP);
    }

    private BigDecimal toPrice(Double value) {
        if (value == null || value <= 0) {
            return null;
        }
        return BigDecimal.valueOf(value).setScale(0, RoundingMode.HALF_UP);
    }

    private void logRiskEvent(String eventType, String stkCd, String strategy,
                              Long signalId, BigDecimal threshold, BigDecimal actual,
                              String description, String actionTaken) {
        try {
            RiskEvent event = RiskEvent.builder()
                    .eventType(eventType)
                    .stkCd(stkCd)
                    .strategy(strategy)
                    .signalId(signalId)
                    .thresholdValue(threshold)
                    .actualValue(actual)
                    .description(description)
                    .actionTaken(actionTaken)
                    .build();
            riskEventRepository.save(event);
        } catch (Exception e) {
            log.warn("[RiskEvent] 저장 실패 (무시): {}", e.getMessage());
        }
    }

    private void trackSectorOverheat(String themeName) {
        if (themeName == null || themeName.isBlank()) {
            return;
        }
        String sector = resolveSector(themeName);
        if (sector == null) {
            return;
        }

        try {
            long count = redisService.incrementSectorSignalCount(sector);
            int threshold = properties.getTrading().getSectorOverheatThreshold();
            if (count >= threshold) {
                log.warn("[Signal] 섹터 과열 감지 {} {}건(임계값 {})", sector, count, threshold);
                publishSectorOverheatAlert(sector, count, threshold);
            }
        } catch (Exception e) {
            log.debug("[Signal] 섹터 추적 오류 (무시): {}", e.getMessage());
        }
    }

    private String resolveSector(String themeName) {
        if (themeName == null) {
            return null;
        }
        return THEME_TO_SECTOR.entrySet().stream()
                .filter(e -> themeName.contains(e.getKey()))
                .map(Map.Entry::getValue)
                .findFirst()
                .orElse(null);
    }

    private void publishSectorOverheatAlert(String sector, long count, int threshold) {
        try {
            String msg = objectMapper.writeValueAsString(Map.of(
                    "type", "SECTOR_OVERHEAT",
                    "sector", sector,
                    "count", count,
                    "threshold", threshold,
                    "message", String.format("⚠️ [섹터 과열] %s 섹터에 1시간 내 %d건 신호 발생 (임계값 %d)", sector, count, threshold)
            ));
            redisService.pushScoredQueue(msg);
        } catch (Exception e) {
            log.warn("[Signal] 섹터 과열 알림 발행 실패: {}", e.getMessage());
        }
    }

    @FunctionalInterface
    private interface TargetPriceCalculator {
        double calculate();
    }
}
