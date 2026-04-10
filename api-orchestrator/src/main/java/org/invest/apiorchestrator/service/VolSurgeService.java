package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * S4 사전 필터링 – 거래량 급증 종목 (ka10023)
 * sdnin_rt >= 50% 종목 코드 Set 반환
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class VolSurgeService {

    private final KiwoomApiService apiService;

    /**
     * 거래량 급증 종목 코드 집합 반환 (sdnin_rt >= 50%).
     * sort_tp=2 (급증률순), tm_tp=1, tm=5 (5분), trde_qty_tp=10, stk_cnd=1.
     */
    public Set<String> fetchSurgeCandidates() {
        try {
            KiwoomApiResponses.TrdeQtySdninResponse resp =
                    apiService.fetchKa10023(
                            StrategyRequests.TrdeQtySdninRequest.builder()
                                    .mrktTp("000")
                                    .sortTp("2")
                                    .tmTp("1")
                                    .tm("5")
                                    .trdeQtyTp("10")
                                    .stkCnd("1")
                                    .pricTp("8")
                                    .stexTp("3")
                                    .build());

            if (resp == null || resp.getItems() == null) return Collections.emptySet();

            return resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double sdninRt = Double.parseDouble(
                                    item.getSdninRt().replace("+", "").replace(",", ""));
                            return sdninRt >= 50.0;
                        } catch (Exception e) { return false; }
                    })
                    .map(KiwoomApiResponses.TrdeQtySdninResponse.TrdeQtySdninItem::getStkCd)
                    .collect(Collectors.toSet());

        } catch (Exception e) {
            log.error("[VolSurge] ka10023 조회 실패: {}", e.getMessage());
            return Collections.emptySet();
        }
    }
}
