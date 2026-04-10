package org.invest.apiorchestrator.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.StockMaster;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.repository.StockMasterRepository;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * StockMasterScheduler – 매주 월요일 07:00 종목 기준정보 갱신.
 *
 * 전략 후보 풀(Redis candidates:s*:001/101) 에 등록된 종목을 대상으로
 * ka10001 (주식기본정보) 을 호출해 StockMaster 를 UPSERT 한다.
 * 키움 API 에 전종목 조회 전용 TR 이 없으므로 "트레이딩 유니버스" 기준으로 관리.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class StockMasterScheduler {

    private final KiwoomApiService kiwoomApiService;
    private final StockMasterRepository stockMasterRepository;
    private final StringRedisTemplate redis;

    private static final String[] STRATEGY_KEYS = {
            "s1","s2","s3","s4","s5","s6","s7","s8","s9","s10","s11","s12","s13","s14","s15"
    };
    private static final String[] MARKETS = {"001", "101"};

    /**
     * 매주 월요일 07:00 – 트레이딩 유니버스 종목 기준정보 갱신
     */
    @Scheduled(cron = "0 0 7 * * MON-FRI")
    @Transactional
    public void refreshStockMaster() {
        log.info("=== StockMaster 갱신 시작 (월요일 07:00) ===");
        try {
            Set<String> kospiCodes  = collectFromRedis("001");
            Set<String> kosdaqCodes = collectFromRedis("101");

            int upserted = 0;
            upserted += upsertBatch(kospiCodes, "001");
            upserted += upsertBatch(kosdaqCodes, "101");

            log.info("[StockMaster] 갱신 완료 – KOSPI {}건 KOSDAQ {}건 총 {}건 UPSERT",
                    kospiCodes.size(), kosdaqCodes.size(), upserted);
        } catch (Exception e) {
            log.error("[StockMaster] 갱신 실패: {}", e.getMessage());
        }
    }

    // ──── 내부 헬퍼 ────────────────────────────────────────────────

    /** Redis 후보 풀 키에서 종목코드 수집 */
    private Set<String> collectFromRedis(String market) {
        Set<String> codes = new HashSet<>();
        for (String s : STRATEGY_KEYS) {
            String key = "candidates:" + s + ":" + market;
            List<String> list = redis.opsForList().range(key, 0, -1);
            if (list != null) codes.addAll(list);
        }
        // 구형 키도 포함
        List<String> legacy = redis.opsForList().range("candidates:" + market, 0, -1);
        if (legacy != null) codes.addAll(legacy);
        return codes;
    }

    /** 종목코드 배치에 대해 ka10001 호출 후 UPSERT */
    private int upsertBatch(Set<String> codes, String market) {
        int count = 0;
        for (String stkCd : codes) {
            try {
                KiwoomApiResponses.StkBasicInfoResponse info = kiwoomApiService.fetchKa10001(stkCd);
                if (info == null || !info.isSuccess()) continue;

                String stkNm    = info.getStkNm() != null ? info.getStkNm() : stkCd;
                BigDecimal price = null;
                if (info.getCurPrc() != null) {
                    try {
                        price = new BigDecimal(info.getCurPrc()
                                .replace(",", "").replace("+", "").replace("-", "").trim());
                    } catch (NumberFormatException ignored) {}
                }

                StockMaster existing = stockMasterRepository.findByStkCd(stkCd).orElse(null);
                if (existing == null) {
                    stockMasterRepository.save(StockMaster.builder()
                            .stkCd(stkCd)
                            .stkNm(stkNm)
                            .market(market)
                            .isActive(true)
                            .lastPrice(price)
                            .lastPriceDate(price != null ? LocalDate.now() : null)
                            .build());
                } else {
                    // 이름·가격만 업데이트 (sector/industry 는 수동 관리)
                    stockMasterRepository.save(StockMaster.builder()
                            .stkCd(stkCd)
                            .stkNm(stkNm)
                            .market(market)
                            .sector(existing.getSector())
                            .industry(existing.getIndustry())
                            .listedAt(existing.getListedAt())
                            .parValue(existing.getParValue())
                            .listedShares(existing.getListedShares())
                            .isActive(true)
                            .lastPrice(price)
                            .lastPriceDate(price != null ? LocalDate.now() : null)
                            .build());
                }
                count++;
            } catch (Exception e) {
                log.debug("[StockMaster] {} 조회 실패 (무시): {}", stkCd, e.getMessage());
            }
        }
        return count;
    }
}
