package org.invest.apiorchestrator.controller;

import lombok.RequiredArgsConstructor;
import org.invest.apiorchestrator.dto.res.CandidateSearchResponse;
import org.invest.apiorchestrator.service.CandidateSearchService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping({"/api/candidates", "/api/trading/candidates"})
@RequiredArgsConstructor
public class CandidateController {

    private final CandidateSearchService candidateSearchService;

    @GetMapping("/search")
    public ResponseEntity<CandidateSearchResponse> search(
            @RequestParam(required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE)
            LocalDate date,
            @RequestParam(defaultValue = "000") String market,
            @RequestParam(required = false) String strategy,
            @RequestParam(required = false) String strategies,
            @RequestParam(required = false, name = "q") String query,
            @RequestParam(required = false) String sector,
            @RequestParam(required = false) BigDecimal minPoolScore,
            @RequestParam(required = false) Integer minAppearCount,
            @RequestParam(required = false) Integer seenWithinMin,
            @RequestParam(required = false) Boolean ledToSignal,
            @RequestParam(defaultValue = "false") boolean liveOnly,
            @RequestParam(defaultValue = "score") String sort,
            @RequestParam(defaultValue = "50") int limit
    ) {
        CandidateSearchService.SearchRequest request = new CandidateSearchService.SearchRequest(
                date,
                market,
                splitCsv(strategy, strategies),
                query,
                sector,
                minPoolScore,
                minAppearCount,
                seenWithinMin,
                ledToSignal,
                liveOnly,
                sort,
                limit
        );
        return ResponseEntity.ok(candidateSearchService.search(request));
    }

    @GetMapping("/data-quality")
    public ResponseEntity<Map<String, Object>> dataQuality(
            @RequestParam(defaultValue = "000") String market,
            @RequestParam(required = false) String strategy,
            @RequestParam(required = false) String strategies
    ) {
        return ResponseEntity.ok(candidateSearchService.buildDataQualityReport(market, splitCsv(strategy, strategies)));
    }

    private static List<String> splitCsv(String... rawValues) {
        if (rawValues == null || rawValues.length == 0) {
            return List.of();
        }
        return Arrays.stream(rawValues)
                .filter(raw -> raw != null && !raw.isBlank())
                .flatMap(raw -> Arrays.stream(raw.split(",")))
                .map(String::trim)
                .filter(value -> !value.isBlank())
                .toList();
    }
}
