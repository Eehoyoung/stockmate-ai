package org.invest.apiorchestrator.dto.res;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

public record CandidateSearchResponse(
        LocalDate date,
        String market,
        List<String> strategies,
        int count,
        int totalRowsScanned,
        Map<String, Object> filters,
        Map<String, Object> summary,
        List<CandidateSearchItem> candidates
) {
    public record CandidateSearchItem(
            String stkCd,
            String stkNm,
            String market,
            String sector,
            String industry,
            Long marketCap,
            BigDecimal maxPoolScore,
            int totalAppearCount,
            int strategyCount,
            OffsetDateTime firstSeen,
            OffsetDateTime lastSeen,
            boolean live,
            List<String> strategies,
            List<String> liveStrategies,
            boolean ledToSignal,
            List<Long> signalIds,
            Map<String, Object> dataQuality,
            Map<String, Object> executionValidation
    ) {
    }
}
