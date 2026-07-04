package org.invest.apiorchestrator.service.strategy;

import java.util.Collections;
import java.util.List;
import java.util.Set;

/**
 * Input envelope for a strategy scanner.
 *
 * <p>Keep this context small and immutable. Service dependencies should be
 * injected into scanner implementations, not passed through this record.
 */
public record StrategyScanContext(
        List<String> candidates,
        String market,
        Set<String> preFiltered
) {

    public static StrategyScanContext candidates(List<String> candidates) {
        return new StrategyScanContext(
                candidates == null ? Collections.emptyList() : List.copyOf(candidates),
                "",
                Collections.emptySet()
        );
    }

    public static StrategyScanContext market(String market) {
        return new StrategyScanContext(
                Collections.emptyList(),
                market == null ? "" : market,
                Collections.emptySet()
        );
    }

    public static StrategyScanContext market(String market, Set<String> preFiltered) {
        return new StrategyScanContext(
                Collections.emptyList(),
                market == null ? "" : market,
                preFiltered == null ? Collections.emptySet() : Set.copyOf(preFiltered)
        );
    }
}

