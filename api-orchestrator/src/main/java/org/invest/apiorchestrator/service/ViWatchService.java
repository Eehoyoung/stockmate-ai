package org.invest.apiorchestrator.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.ViEvent;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.WsMarketData;
import org.invest.apiorchestrator.repository.ViEventRepository;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class ViWatchService {

    private final RedisMarketDataService redisService;
    private final StrategyService strategyService;
    private final SignalService signalService;
    private final ViEventRepository viEventRepository;
    private final ObjectMapper objectMapper;

    /**
     * VI 감시 큐에서 아이템을 꺼내 눌림목 체크
     * 스케줄러에서 5초마다 호출
     */
    @Async("wsExecutor")
    public void processViWatchQueue() {
        int processed = 0;
        while (processed < 20) { // 한 번에 최대 20건
            Optional<String> itemOpt = redisService.pollViWatchQueue();
            if (itemOpt.isEmpty()) break;

            try {
                Map<String, Object> item = objectMapper.readValue(
                        itemOpt.get(), new TypeReference<>() {});

                String stkCd    = (String) item.get("stk_cd");
                double viPrice  = ((Number) item.get("vi_price")).doubleValue();
                long watchUntil = ((Number) item.get("watch_until")).longValue();
                boolean isDynamic = Boolean.TRUE.equals(item.get("is_dynamic"));

                // 감시 시간 초과 → 무시
                if (System.currentTimeMillis() > watchUntil) {
                    log.debug("VI 감시 시간 초과 [{}]", stkCd);
                    processed++;
                    continue;
                }

                Optional<TradingSignalDto> sigOpt =
                        strategyService.checkViPullback(stkCd, viPrice, isDynamic);

                if (sigOpt.isPresent()) {
                    boolean sent = signalService.processSignal(sigOpt.get());
                    if (sent) {
                        log.info("[S2] VI 눌림목 신호 발행 [{}] vi={} pullback={}%",
                                stkCd, viPrice, sigOpt.get().getPullbackPct());
                    }
                } else {
                    // 아직 조건 미충족 → 큐에 다시 넣기 (감시 시간 내에만)
                    redisService.pushViWatchBack(itemOpt.get());
                }
            } catch (Exception e) {
                log.warn("VI 감시 처리 오류: {}", e.getMessage());
            }
            processed++;
        }
    }

    /**
     * WebSocket에서 VI 이벤트 수신 시 호출
     */
    public void handleViEvent(WsMarketData.ViActivation vi) {
        try {
            // Redis에 VI 상태 저장
            redisService.saveViEvent(vi);

            // DB 저장
            ViEvent event = ViEvent.builder()
                    .stkCd(vi.getStkCd())
                    .stkNm(vi.getStkNm())
                    .viType(vi.getViType())
                    .viStatus(vi.getViStat())
                    .viPrice(vi.getViPricDouble())
                    .accVolume(parseLong(vi.getAccTrdeQty()))
                    .marketType(vi.getMrktCls())
                    .build();
            viEventRepository.save(event);

            log.info("VI {} [{}] type={} price={}",
                    vi.isActivation() ? "발동" : "해제",
                    vi.getStkCd(), vi.getViType(), vi.getViPricDouble());

        } catch (Exception e) {
            log.error("VI 이벤트 처리 오류: {}", e.getMessage());
        }
    }

    private long parseLong(String v) {
        try { return v == null ? 0 : Long.parseLong(v.replace(",", "")); }
        catch (Exception e) { return 0; }
    }
}
