package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.config.KiwoomProperties;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.repository.TradingSignalRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Service
public class SignalService {

    private final TradingSignalRepository signalRepository;
    private final RedisMarketDataService redisService;
    private final KiwoomProperties properties;
    private final ObjectMapper objectMapper;

    public SignalService(TradingSignalRepository signalRepository, RedisMarketDataService redisService, KiwoomProperties properties, ObjectMapper objectMapper) {
        this.signalRepository = signalRepository;
        this.redisService = redisService;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    /**
     * 신호 저장 + Redis 중복 체크 + 텔레그램 큐 발행
     */
    @Transactional
    public boolean processSignal(TradingSignalDto dto) {
        String stkCd = dto.getStkCd();
        String strategy = dto.getStrategy().name();

        // 1. 중복 신호 체크 (Redis TTL 기반)
        if (redisService.isSignalDuplicate(stkCd, strategy)) {
            log.debug("중복 신호 무시 [{} {}]", stkCd, strategy);
            return false;
        }

        // 2. DB 저장
        TradingSignal signal = buildSignalEntity(dto);
        signalRepository.save(signal);

        // 3. 텔레그램 큐 발행
        try {
            String telegramMsg = objectMapper.writeValueAsString(Map.of(
                    "id",       signal.getId(),
                    "stk_cd",   stkCd,
                    "strategy", strategy,
                    "message",  dto.toTelegramMessage()
            ));
            redisService.pushTelegramQueue(telegramMsg);
            log.info("신호 발행 [{} {}] score={}", stkCd, strategy, dto.getSignalScore());
        } catch (Exception e) {
            log.error("텔레그램 큐 발행 실패: {}", e.getMessage());
        }

        return true;
    }

    /**
     * 복수 신호 일괄 처리 (전략 내 최대 N개 제한)
     */
    @Transactional
    public int processSignals(List<TradingSignalDto> signals) {
        int maxPerStrategy = properties.getTrading().getMaxSignalsPerStrategy();
        int count = 0;
        for (TradingSignalDto dto : signals.stream()
                .limit(maxPerStrategy).collect(Collectors.toList())) {
            if (processSignal(dto)) count++;
        }
        return count;
    }

    /**
     * 당일 신호 조회
     */
    @Transactional(readOnly = true)
    public List<TradingSignal> getTodaySignals() {
        LocalDateTime startOfDay = LocalDateTime.of(LocalDate.now(), LocalTime.MIDNIGHT);
        return signalRepository.findTodaySignals(startOfDay);
    }

    /**
     * 전략별 당일 성과 통계
     */
    @Transactional(readOnly = true)
    public List<Object[]> getTodayStats() {
        LocalDateTime startOfDay = LocalDateTime.of(LocalDate.now(), LocalTime.MIDNIGHT);
        return signalRepository.getStrategyStats(startOfDay);
    }

    /**
     * 만료된 신호 상태 업데이트 (배치)
     */
    @Transactional
    public int expireOldSignals() {
        LocalDateTime expireBefore = LocalDateTime.now()
                .minusSeconds(properties.getTrading().getSignalTtlSeconds());
        return signalRepository.expireOldSignals(expireBefore);
    }

    private TradingSignal buildSignalEntity(TradingSignalDto dto) {
        return TradingSignal.builder()
                .stkCd(dto.getStkCd())
                .stkNm(dto.getStkNm())
                .strategy(dto.getStrategy())
                .signalScore(dto.getSignalScore())
                .entryPrice(dto.getEntryPrice())
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
}
