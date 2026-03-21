package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * S7 사전 필터링 – 호가잔량 매수비율 상위 종목 (ka10020)
 * buy_rt >= 200% 종목 코드 Set 반환
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BidUpperService {

    private final KiwoomApiService apiService;

    /**
     * 코스피 + 코스닥 호가 매수비율 200% 이상 종목 코드 집합.
     * sort_tp=3 (매수비율순), trde_qty_tp=0000, stk_cnd=1, crd_cnd=0.
     */
    public Set<String> fetchBidUpperCodes() {
        Set<String> result = new HashSet<>();
        for (String mrktTp : new String[]{"001", "101"}) {
            result.addAll(fetchForMarket(mrktTp));
        }
        return result;
    }

    private Set<String> fetchForMarket(String mrktTp) {
        try {
            KiwoomApiResponses.BidReqUpperResponse resp =
                    apiService.fetchKa10020(
                            StrategyRequests.BidReqUpperRequest.builder()
                                    .mrktTp(mrktTp)
                                    .sortTp("3")
                                    .trdeQtyTp("0000")
                                    .stkCnd("1")
                                    .crdCnd("0")
                                    .stexTp("1")
                                    .build());

            if (resp == null || resp.getItems() == null) return Collections.emptySet();

            return resp.getItems().stream()
                    .filter(item -> {
                        try {
                            double buyRt = Double.parseDouble(
                                    item.getBuyRt().replace("+", "").replace(",", "").replace("%", ""));
                            return buyRt >= 200.0;
                        } catch (Exception e) { return false; }
                    })
                    .map(KiwoomApiResponses.BidReqUpperResponse.BidReqUpperItem::getStkCd)
                    .collect(Collectors.toSet());

        } catch (Exception e) {
            log.error("[BidUpper] ka10020 조회 실패 [{}]: {}", mrktTp, e.getMessage());
            return Collections.emptySet();
        }
    }
}
