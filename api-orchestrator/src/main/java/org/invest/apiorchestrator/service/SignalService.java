package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.domain.OpenPosition;
import org.invest.apiorchestrator.domain.PortfolioConfig;
import org.invest.apiorchestrator.domain.RiskEvent;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.CandidatePoolHistoryRepository;
import org.invest.apiorchestrator.repository.OpenPositionRepository;
import org.invest.apiorchestrator.repository.PortfolioConfigRepository;
import org.invest.apiorchestrator.repository.RiskEventRepository;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.invest.apiorchestrator.util.KstClock;
import org.invest.apiorchestrator.util.StockCodeNormalizer;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
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
    private final OpenPositionRepository openPositionRepository;
    private final PortfolioConfigRepository portfolioConfigRepository;
    private final RiskEventRepository riskEventRepository;
    private final CandidatePoolHistoryRepository candidatePoolHistoryRepository;

    // 테마명 → 섹터 매핑 (정적)
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
                         OpenPositionRepository openPositionRepository,
                         PortfolioConfigRepository portfolioConfigRepository,
                         RiskEventRepository riskEventRepository,
                         CandidatePoolHistoryRepository candidatePoolHistoryRepository) {
        this.signalRepository = signalRepository;
        this.redisService = redisService;
        this.candidateService = candidateService;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.openPositionRepository = openPositionRepository;
        this.portfolioConfigRepository = portfolioConfigRepository;
        this.riskEventRepository = riskEventRepository;
        this.candidatePoolHistoryRepository = candidatePoolHistoryRepository;
    }

    /**
     * 신호 저장 + Redis 중복 체크 + 텔레그램 큐 발행
     */
    @Transactional
    public boolean processSignal(TradingSignalDto dto) {
        String stkCd = StockCodeNormalizer.normalize(dto.getStkCd());
        String strategy = dto.getStrategy().name();
        MDC.put("strategy", strategy);
        MDC.put("stk_cd", stkCd);
        try {
            // 1. 중복 신호 체크 – 전략 내 (Redis TTL 기반)
            if (redisService.isSignalDuplicate(stkCd, strategy)) {
                log.debug("중복 신호 무시 [{} {}]", stkCd, strategy);
                return false;
            }

            // 2. 종목 크로스-전략 쿨다운 (동일 종목 타 전략 N분 내 재발행 방지)
            int cooldownMin = properties.getTrading().getStockCooldownMinutes();
            if (!redisService.tryAcquireStockCooldown(stkCd, cooldownMin)) {
                log.debug("종목 쿨다운 중 [{} – 모든전략 {}분]", stkCd, cooldownMin);
                return false;
            }

            // 3. 일일 전체 신호 상한 체크
            int maxDaily = properties.getTrading().getMaxDailySignals();
            long dailyCount = redisService.incrementDailySignalCount();
            if (dailyCount > maxDaily) {
                log.warn("[Signal] 일일 신호 상한 도달 ({}/{}), 신호 무시 [{} {}]",
                        dailyCount, maxDaily, stkCd, strategy);
                return false;
            }

            // 4. PortfolioConfig 기반 포지션 한도 · 이중매수 체크
            PortfolioConfig config = portfolioConfigRepository.findSingleton().orElse(null);
            if (config != null) {
                // 4-1. 동일 종목 오버나잇 포지션 이중매수 방지 (전날 포지션이 아직 ACTIVE 상태)
                if (openPositionRepository.existsActivePosition(stkCd)) {
                    logRiskEvent("DUPLICATE_SIGNAL_BLOCKED", stkCd, strategy, null,
                            null, null, "이미 활성 포지션 보유 – 오버나잇 포지션 잔존", "신호 무시");
                    log.warn("[Signal] 이중매수 차단 [{} {}] – 활성 포지션 이미 존재", stkCd, strategy);
                    return false;
                }
                // 4-2. 최대 동시 포지션 수 초과 체크
                long activeCount = openPositionRepository.countActivePositions();
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

            // 5. DB 저장
            TradingSignal signal = buildSignalEntity(dto);
            signalRepository.save(signal);

            // 5-1. candidate_pool_history led_to_signal 갱신
            try {
                candidatePoolHistoryRepository.markLedToSignal(
                        KstClock.today(), strategy, dto.getMarketType(), stkCd, signal.getId());
            } catch (Exception e) {
                log.debug("[Signal] pool history 갱신 실패 (무시): {}", e.getMessage());
            }

            // 6. OpenPosition 생성 (진입 의도 기록 – ACTIVE 상태로 당일 추적)
            if (dto.getEntryPrice() == null || dto.getEntryPrice() <= 0) {
                log.warn("[Signal] OpenPosition 생성 건너뜀 – entryPrice 미설정 [{} {}]", stkCd, strategy);
            } else {
                try {
                    OpenPosition position = buildOpenPosition(dto, signal);
                    openPositionRepository.save(position);
                } catch (Exception e) {
                    log.error("[Signal] OpenPosition 생성 실패 [{} {}] – {}",
                            stkCd, strategy, e.getMessage(), e);
                }
            }

            // 7. 전략 태그 기록 (Redis – 후보 종목 출처 추적)
            candidateService.tagStrategy(stkCd, strategy);

            // 8. 섹터 과열 추적 + 알림
            trackSectorOverheat(dto.getThemeName());

            // 9. 텔레그램 큐 발행 – TradingSignalDto.toQueuePayload() 로 필드 계약 중앙화
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

    /**
     * 복수 신호 일괄 처리 (전략 내 최대 N개 제한)
     */
    @Transactional
    public int processSignals(List<TradingSignalDto> signals) {
        int maxPerStrategy = properties.getTrading().getMaxSignalsPerStrategy();
        int count = 0;
        for (TradingSignalDto dto : signals.stream()
                .limit(maxPerStrategy).toList()) {
            if (processSignal(dto)) count++;
        }
        return count;
    }

    /**
     * 당일 신호 조회
     */
    @Transactional(readOnly = true)
    public List<TradingSignal> getTodaySignals() {
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);
        return signalRepository.findTodaySignals(startOfDay);
    }

    /**
     * 전략별 당일 성과 통계
     */
    @Transactional(readOnly = true)
    public List<Object[]> getTodayStats() {
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);
        return signalRepository.getStrategyStats(startOfDay);
    }

    /**
     * 전략별 당일 가상 성과 통계 (WIN/LOSS/SENT 포함)
     */
    @Transactional(readOnly = true)
    public List<Object[]> getPerformanceStats() {
        LocalDateTime startOfDay = LocalDateTime.of(KstClock.today(), LocalTime.MIDNIGHT);
        return signalRepository.getStrategyPerformanceStats(startOfDay);
    }

    /**
     * 만료된 신호 상태 업데이트 (배치)
     */
    @Transactional
    public int expireOldSignals() {
        LocalDateTime expireBefore = KstClock.now()
                .minusSeconds(properties.getTrading().getSignalTtlSeconds());
        return signalRepository.expireOldSignals(expireBefore);
    }

    // ──── 내부 헬퍼 ────────────────────────────────────────────────

    private TradingSignal buildSignalEntity(TradingSignalDto dto) {
        double t1 = dto.calcTarget1Price();
        double t2 = dto.calcTarget2Price();
        double sp = dto.calcStopPrice();

        // tp1/tp2/sl: 절대가 우선, 없으면 % 기반 calc 값 fallback
        double rawTp1 = dto.getTp1Price() != null && dto.getTp1Price() > 0 ? dto.getTp1Price() : (t1 > 0 ? t1 : 0);
        double rawTp2 = dto.getTp2Price() != null && dto.getTp2Price() > 0 ? dto.getTp2Price() : (t2 > 0 ? t2 : 0);
        double rawSl  = dto.getSlPrice()  != null && dto.getSlPrice()  > 0 ? dto.getSlPrice()  : (sp > 0 ? sp : 0);

        return TradingSignal.builder()
                .stkCd(StockCodeNormalizer.normalize(dto.getStkCd()))
                .stkNm(dto.getStkNm())
                .strategy(dto.getStrategy())
                .signalScore(dto.getSignalScore())
                .entryPrice(dto.getEntryPrice())
                .targetPrice(t1 > 0 ? t1 : null)
                .stopPrice(sp > 0 ? sp : null)
                .tp1Price(rawTp1 > 0 ? rawTp1 : null)
                .tp2Price(rawTp2 > 0 ? rawTp2 : null)
                .slPrice(rawSl  > 0 ? rawSl  : null)
                .targetPct(dto.getTargetPct())
                .stopPct(dto.getStopPct())
                .entryType(dto.getEntryType())
                .marketType(dto.getMarketType())
                .gapPct(dto.getGapPct())
                .cntrStrength(dto.getCntrStrength())
                .bidRatio(dto.getBidRatio())
                .volRatio(dto.getVolRatio())
                .pullbackPct(dto.getPullbackPct())
                .themeName(dto.getThemeName())
                .signalStatus(TradingSignal.SignalStatus.SENT)
                .build();
    }

    private OpenPosition buildOpenPosition(TradingSignalDto dto, TradingSignal signal) {
        BigDecimal entryPrice = dto.getEntryPrice() != null
                ? BigDecimal.valueOf(dto.getEntryPrice()).setScale(0, java.math.RoundingMode.HALF_UP)
                : BigDecimal.ZERO;

        // slPrice: 절대가 우선, 없으면 % 기반 계산
        double slRaw = dto.getSlPrice() != null && dto.getSlPrice() > 0
                ? dto.getSlPrice()
                : dto.calcStopPrice();
        BigDecimal slPrice = slRaw > 0
                ? BigDecimal.valueOf(slRaw).setScale(0, java.math.RoundingMode.HALF_UP)
                : entryPrice.multiply(new BigDecimal("0.97")).setScale(0, java.math.RoundingMode.HALF_UP);

        double calcT1 = dto.calcTarget1Price();
        BigDecimal tp1Price = dto.getTp1Price() != null && dto.getTp1Price() > 0
                ? BigDecimal.valueOf(dto.getTp1Price()).setScale(0, java.math.RoundingMode.HALF_UP)
                : (calcT1 > 0 ? BigDecimal.valueOf(calcT1).setScale(0, java.math.RoundingMode.HALF_UP) : null);

        double calcT2 = dto.calcTarget2Price();
        BigDecimal tp2Price = dto.getTp2Price() != null && dto.getTp2Price() > 0
                ? BigDecimal.valueOf(dto.getTp2Price()).setScale(0, java.math.RoundingMode.HALF_UP)
                : (calcT2 > 0 ? BigDecimal.valueOf(calcT2).setScale(0, java.math.RoundingMode.HALF_UP) : null);

        // R:R 계산
        BigDecimal rrRatio = null;
        if (tp1Price != null && entryPrice.compareTo(BigDecimal.ZERO) > 0
                && slPrice.compareTo(entryPrice) < 0) {
            BigDecimal reward = tp1Price.subtract(entryPrice);
            BigDecimal risk   = entryPrice.subtract(slPrice);
            if (risk.compareTo(BigDecimal.ZERO) > 0) {
                rrRatio = reward.divide(risk, 2, java.math.RoundingMode.HALF_UP);
            }
        }

        return OpenPosition.builder()
                .signal(signal)
                .stkCd(StockCodeNormalizer.normalize(dto.getStkCd()))
                .stkNm(dto.getStkNm())
                .strategy(dto.getStrategy().name())
                .market(dto.getMarketType())
                .sector(resolveSector(dto.getThemeName()))
                .entryPrice(entryPrice)
                .tp1Price(tp1Price)
                .tp2Price(tp2Price)
                .slPrice(slPrice)
                .rrRatio(rrRatio)
                .ruleScore(dto.getSignalScore() != null
                        ? BigDecimal.valueOf(dto.getSignalScore()).setScale(2, java.math.RoundingMode.HALF_UP)
                        : null)
                .build();
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

    /**
     * 섹터 과열 추적 – 1시간 내 동일 섹터 N건 이상 시 SECTOR_OVERHEAT 알림 발행
     */
    private void trackSectorOverheat(String themeName) {
        if (themeName == null || themeName.isBlank()) return;
        String sector = resolveSector(themeName);
        if (sector == null) return;

        try {
            long count = redisService.incrementSectorSignalCount(sector);
            int threshold = properties.getTrading().getSectorOverheatThreshold();
            if (count >= threshold) {
                log.warn("[Signal] 섹터 과열 감지 {} {}건 (임계값={})", sector, count, threshold);
                publishSectorOverheatAlert(sector, count, threshold);
            }
        } catch (Exception e) {
            log.debug("[Signal] 섹터 추적 오류 (무시): {}", e.getMessage());
        }
    }

    private String resolveSector(String themeName) {
        if (themeName == null) return null;
        return THEME_TO_SECTOR.entrySet().stream()
                .filter(e -> themeName.contains(e.getKey()))
                .map(Map.Entry::getValue)
                .findFirst()
                .orElse(null);
    }

    private void publishSectorOverheatAlert(String sector, long count, int threshold) {
        try {
            String msg = objectMapper.writeValueAsString(Map.of(
                    "type",      "SECTOR_OVERHEAT",
                    "sector",    sector,
                    "count",     count,
                    "threshold", threshold,
                    "message",   String.format("⚠️ [섹터 과열] %s 섹터에 1시간 내 %d건 신호 발행 (임계값=%d)", sector, count, threshold)
            ));
            redisService.pushScoredQueue(msg);
        } catch (Exception e) {
            log.warn("[Signal] 섹터 과열 알림 발행 실패: {}", e.getMessage());
        }
    }
}
