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
 * S4 사전 필터링 – 가격 급등 종목 (ka10019)
 * jmp_rt >= 3.0% 종목 코드 Set 반환
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PriceSurgeService {

    private final KiwoomApiService apiService;

    /**
     * 가격 급등 종목 코드 집합 반환 (jmp_rt >= 3.0%).
     * flu_tp=1 (급등), tm_tp=1, tm=30 (30분), trde_qty_tp=00010, stk_cnd=1.
     */
    public Set<String> fetchSurgeCandidates() {
        try {
            KiwoomApiResponses.PricJmpFluResponse resp =
                    apiService.fetchKa10019(
                            StrategyRequests.PricJmpFluRequest.builder()
                                    .mrktTp("000")
                                    .fluTp("1")
                                    .tmTp("1")
                                    .tm("30")
                                    .trdeQtyTp("00010")
                                    .stkCnd("1")
                                    .crdCnd("0")
                                    .pricCnd("8")
                                    .updownIncls("0")
                                    .stexTp("3")
                                    .build());

            if (resp == null || resp.getItems() == null) return Collections.emptySet();

            return resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double jmpRt = Double.parseDouble(
                                    item.getJmpRt().replace("+", "").replace(",", ""));
                            return jmpRt >= 3.0;
                        } catch (Exception e) { return false; }
                    })
                    .map(KiwoomApiResponses.PricJmpFluResponse.PricJmpFluItem::getStkCd)
                    .collect(Collectors.toSet());

        } catch (Exception e) {
            log.error("[PriceSurge] ka10019 조회 실패: {}", e.getMessage());
            return Collections.emptySet();
        }
    }
}
