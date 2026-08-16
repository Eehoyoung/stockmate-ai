package org.invest.apiorchestrator.domain;

import org.junit.jupiter.api.Test;

import java.util.EnumSet;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class StrategyFamilyCatalogTests {

    @Test
    void mapsEveryLegacySetupExactlyOnce() {
        assertEquals(16, TradingSignal.StrategyType.values().length);
        assertEquals(
                EnumSet.allOf(TradingSignal.StrategyType.class),
                StrategyFamilyCatalog.allSetups());
        for (TradingSignal.StrategyType setup : TradingSignal.StrategyType.values()) {
            assertNotNull(StrategyFamilyCatalog.familyFor(setup));
        }
    }

    @Test
    void approvedMembershipIsStable() {
        Map<TradingSignal.StrategyType, String> expected = Map.ofEntries(
                Map.entry(TradingSignal.StrategyType.S1_GAP_OPEN, "G01"),
                Map.entry(TradingSignal.StrategyType.S2_VI_PULLBACK, "G01"),
                Map.entry(TradingSignal.StrategyType.S12_CLOSING, "G01"),
                Map.entry(TradingSignal.StrategyType.S3_INST_FRGN, "G02"),
                Map.entry(TradingSignal.StrategyType.S5_PROG_FRGN, "G02"),
                Map.entry(TradingSignal.StrategyType.S11_FRGN_CONT, "G02"),
                Map.entry(TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW, "G03"),
                Map.entry(TradingSignal.StrategyType.S8_GOLDEN_CROSS, "G04"),
                Map.entry(TradingSignal.StrategyType.S9_PULLBACK_SWING, "G04"),
                Map.entry(TradingSignal.StrategyType.S15_MOMENTUM_ALIGN, "G04"),
                Map.entry(TradingSignal.StrategyType.S7_ICHIMOKU_BREAKOUT, "G05"),
                Map.entry(TradingSignal.StrategyType.S10_NEW_HIGH, "G05"),
                Map.entry(TradingSignal.StrategyType.S13_BOX_BREAKOUT, "G05"),
                Map.entry(TradingSignal.StrategyType.S4_BIG_CANDLE, "G06"),
                Map.entry(TradingSignal.StrategyType.S6_THEME_LAGGARD, "G06"),
                Map.entry(TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE, "G07"));

        expected.forEach((setup, family) ->
                assertEquals(family, StrategyFamilyCatalog.familyFor(setup).id()));
    }

    @Test
    void nullSetupFailsClosed() {
        assertThrows(IllegalArgumentException.class,
                () -> StrategyFamilyCatalog.familyFor(null));
    }

    @Test
    void redisSetupKeysAreOrderedAndIncludeS16() {
        Map<String, TradingSignal.StrategyType> keys = StrategyFamilyCatalog.setupKeys();

        assertEquals(16, keys.size());
        assertEquals("s1", keys.keySet().iterator().next());
        assertEquals(TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW, keys.get("s16"));
    }

    @Test
    void killSwitchDefaultsOffWhenEnvironmentIsAbsentOrFalse() {
        String configured = System.getenv("ENABLE_STRATEGY_FAMILY_LINEAGE");
        if (configured == null || configured.equalsIgnoreCase("false")) {
            assertFalse(StrategyFamilyCatalog.lineageEnabled());
        }
    }

    @Test
    void liveRoutingKillSwitchCanBeEnabledForVerifiedRuntime() {
        String key = "ENABLE_STRATEGY_FAMILY_LIVE_ROUTING";
        String previous = System.getProperty(key);
        try {
            System.setProperty(key, "true");
            assertTrue(StrategyFamilyCatalog.liveRoutingEnabled());
            System.setProperty(key, "false");
            assertFalse(StrategyFamilyCatalog.liveRoutingEnabled());
        } finally {
            if (previous == null) System.clearProperty(key);
            else System.setProperty(key, previous);
        }
    }
}
