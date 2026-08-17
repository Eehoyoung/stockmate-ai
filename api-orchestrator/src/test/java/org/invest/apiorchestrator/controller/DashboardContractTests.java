package org.invest.apiorchestrator.controller;

import org.junit.jupiter.api.Test;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DashboardContractTests {

    @Test
    void dashboardEntryPointRedirectsToStaticArtifact() {
        assertTrue(new DashboardController().dashboard().equals("redirect:/dashboard/index.html"));
    }

    @Test
    void dashboardUsesFamilyFirstKoreanTradingContract() throws Exception {
        try (InputStream stream = getClass().getResourceAsStream("/static/dashboard/index.html")) {
            assertTrue(stream != null, "dashboard resource must exist");
            String html = new String(stream.readAllBytes(), StandardCharsets.UTF_8);

            for (int family = 1; family <= 7; family++) {
                assertTrue(html.contains(String.format("G%02d", family)));
            }
            assertTrue(html.contains("통합 전략군 G01—G07"));
            assertTrue(html.contains("1차 목표가"));
            assertTrue(html.contains("2차 목표가"));
            assertTrue(html.contains("손절가"));
            assertTrue(html.contains("손익비"));
            assertTrue(html.contains("/signals/performance/summary/family"));
            assertFalse(html.contains("TP1</th>"));
            assertFalse(html.contains("SL</th>"));
        }
    }
}
