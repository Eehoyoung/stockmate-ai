package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.invest.apiorchestrator.domain.StrategyParamHistory;
import org.invest.apiorchestrator.repository.StrategyParamHistoryRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class StrategyParamSnapshotService {

    private final StrategyParamHistoryRepository strategyParamHistoryRepository;

    @Transactional
    public int syncCurrentParams(String changedBy, String reason) {
        int inserted = 0;
        for (ParamSnapshot snapshot : currentSnapshots()) {
            Optional<StrategyParamHistory> latest = strategyParamHistoryRepository
                    .findByStrategyAndParamNameOrderByChangedAtDesc(snapshot.strategy(), snapshot.paramName())
                    .stream()
                    .findFirst();
            String prev = latest.map(StrategyParamHistory::getNewValue).orElse(null);
            if (snapshot.value().equals(prev)) {
                continue;
            }
            strategyParamHistoryRepository.save(StrategyParamHistory.builder()
                    .strategy(snapshot.strategy())
                    .paramName(snapshot.paramName())
                    .oldValue(prev)
                    .newValue(snapshot.value())
                    .changedBy(changedBy)
                    .reason(reason)
                    .build());
            inserted++;
        }
        if (inserted > 0) {
            log.info("[StrategyParam] snapshot synced: {} rows", inserted);
        }
        return inserted;
    }

    public Double getClaudeThreshold(String strategy) {
        return switch (strategy) {
            case "S1_GAP_OPEN" -> 70.0;
            case "S2_VI_PULLBACK" -> 65.0;
            case "S3_INST_FRGN" -> 60.0;
            case "S4_BIG_CANDLE" -> 75.0;
            case "S5_PROG_FRGN" -> 65.0;
            case "S6_THEME_LAGGARD" -> 60.0;
            case "S7_ICHIMOKU_BREAKOUT" -> 62.0;
            case "S8_GOLDEN_CROSS" -> 60.0;
            case "S9_PULLBACK_SWING" -> 55.0;
            case "S10_NEW_HIGH" -> 58.0;
            case "S11_FRGN_CONT" -> 58.0;
            case "S12_CLOSING" -> 60.0;
            case "S13_BOX_BREAKOUT" -> 62.0;
            case "S14_OVERSOLD_BOUNCE" -> 58.0;
            case "S15_MOMENTUM_ALIGN" -> 65.0;
            default -> 65.0;
        };
    }

    private List<ParamSnapshot> currentSnapshots() {
        Map<String, String> scheduleWindows = new LinkedHashMap<>();
        scheduleWindows.put("S1_GAP_OPEN", "08:30-09:10");
        scheduleWindows.put("S2_VI_PULLBACK", "09:00-14:50");
        scheduleWindows.put("S3_INST_FRGN", "09:30-14:30");
        scheduleWindows.put("S4_BIG_CANDLE", "09:30-14:30");
        scheduleWindows.put("S5_PROG_FRGN", "10:00-14:00");
        scheduleWindows.put("S6_THEME_LAGGARD", "09:30-13:00");
        scheduleWindows.put("S7_ICHIMOKU_BREAKOUT", "10:00-14:30");
        scheduleWindows.put("S8_GOLDEN_CROSS", "10:00-14:30");
        scheduleWindows.put("S9_PULLBACK_SWING", "09:30-13:00");
        scheduleWindows.put("S10_NEW_HIGH", "09:30-14:30");
        scheduleWindows.put("S11_FRGN_CONT", "09:30-14:30");
        scheduleWindows.put("S12_CLOSING", "14:30-15:10");
        scheduleWindows.put("S13_BOX_BREAKOUT", "09:30-14:00");
        scheduleWindows.put("S14_OVERSOLD_BOUNCE", "09:30-14:00");
        scheduleWindows.put("S15_MOMENTUM_ALIGN", "10:00-14:30");

        Map<String, Integer> candidateTtlMinutes = new LinkedHashMap<>();
        candidateTtlMinutes.put("S1_GAP_OPEN", 10);
        candidateTtlMinutes.put("S2_VI_PULLBACK", 10);
        candidateTtlMinutes.put("S3_INST_FRGN", 20);
        candidateTtlMinutes.put("S4_BIG_CANDLE", 5);
        candidateTtlMinutes.put("S5_PROG_FRGN", 20);
        candidateTtlMinutes.put("S6_THEME_LAGGARD", 20);
        candidateTtlMinutes.put("S7_ICHIMOKU_BREAKOUT", 15);
        candidateTtlMinutes.put("S8_GOLDEN_CROSS", 20);
        candidateTtlMinutes.put("S9_PULLBACK_SWING", 20);
        candidateTtlMinutes.put("S10_NEW_HIGH", 20);
        candidateTtlMinutes.put("S11_FRGN_CONT", 30);
        candidateTtlMinutes.put("S12_CLOSING", 15);
        candidateTtlMinutes.put("S13_BOX_BREAKOUT", 10);
        candidateTtlMinutes.put("S14_OVERSOLD_BOUNCE", 20);
        candidateTtlMinutes.put("S15_MOMENTUM_ALIGN", 15);

        List<ParamSnapshot> snapshots = new ArrayList<>();
        scheduleWindows.forEach((strategy, window) -> {
            boolean swing = strategy.startsWith("S7_")
                    || strategy.startsWith("S8_")
                    || strategy.startsWith("S9_")
                    || strategy.startsWith("S10_")
                    || strategy.startsWith("S11_")
                    || strategy.startsWith("S12_")
                    || strategy.startsWith("S13_")
                    || strategy.startsWith("S14_")
                    || strategy.startsWith("S15_");
            snapshots.add(new ParamSnapshot(strategy, "schedule_window", window));
            snapshots.add(new ParamSnapshot(strategy, "claude_threshold",
                    String.valueOf(getClaudeThreshold(strategy).intValue())));
            snapshots.add(new ParamSnapshot(strategy, "strategy_class", swing ? "SWING" : "DAY"));
            snapshots.add(new ParamSnapshot(strategy, "dedup_ttl_sec", swing ? "86400" : "3600"));
            snapshots.add(new ParamSnapshot(strategy, "candidate_pool_ttl_min",
                    String.valueOf(candidateTtlMinutes.getOrDefault(strategy, 20))));
        });
        return snapshots;
    }

    private record ParamSnapshot(String strategy, String paramName, String value) {
    }
}
