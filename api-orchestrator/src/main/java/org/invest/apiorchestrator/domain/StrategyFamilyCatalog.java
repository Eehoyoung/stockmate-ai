package org.invest.apiorchestrator.domain;

import java.util.Collections;
import java.util.EnumMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * Additive G01-G07 catalog. Legacy {@link TradingSignal.StrategyType} values
 * remain the immutable setup and persistence keys.
 */
public final class StrategyFamilyCatalog {

    public static final String POLICY_VERSION = "family_v1_2026_08_16";

    public record Family(String id, String name, String displayNameKo, int ruleThreshold) {}

    private static final Map<TradingSignal.StrategyType, Family> BY_SETUP;

    static {
        EnumMap<TradingSignal.StrategyType, Family> values =
                new EnumMap<>(TradingSignal.StrategyType.class);
        register(values, new Family("G01", "SESSION_EVENT", "세션·이벤트", 70),
                TradingSignal.StrategyType.S1_GAP_OPEN,
                TradingSignal.StrategyType.S2_VI_PULLBACK,
                TradingSignal.StrategyType.S12_CLOSING);
        register(values, new Family("G02", "FLOW_TREND", "수급추세", 70),
                TradingSignal.StrategyType.S3_INST_FRGN,
                TradingSignal.StrategyType.S5_PROG_FRGN,
                TradingSignal.StrategyType.S11_FRGN_CONT);
        register(values, new Family("G03", "ACCUMULATION_CONFIRM", "축적확인", 78),
                TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW);
        register(values, new Family("G04", "TREND_PHASE", "추세단계", 70),
                TradingSignal.StrategyType.S8_GOLDEN_CROSS,
                TradingSignal.StrategyType.S9_PULLBACK_SWING,
                TradingSignal.StrategyType.S15_MOMENTUM_ALIGN);
        register(values, new Family("G05", "STRUCTURAL_BREAKOUT", "구조돌파", 74),
                TradingSignal.StrategyType.S7_ICHIMOKU_BREAKOUT,
                TradingSignal.StrategyType.S10_NEW_HIGH,
                TradingSignal.StrategyType.S13_BOX_BREAKOUT);
        register(values, new Family("G06", "INTRADAY_THEME_MOMENTUM", "장중급등·테마", 72),
                TradingSignal.StrategyType.S4_BIG_CANDLE,
                TradingSignal.StrategyType.S6_THEME_LAGGARD);
        register(values, new Family("G07", "REVERSAL_BOUNCE", "역추세반등", 75),
                TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE);
        if (values.size() != TradingSignal.StrategyType.values().length) {
            throw new IllegalStateException("strategy family catalog is incomplete");
        }
        BY_SETUP = Collections.unmodifiableMap(values);
    }

    private StrategyFamilyCatalog() {}

    private static void register(
            Map<TradingSignal.StrategyType, Family> target,
            Family family,
            TradingSignal.StrategyType... setups) {
        for (TradingSignal.StrategyType setup : setups) {
            if (target.put(setup, family) != null) {
                throw new IllegalStateException("duplicate strategy family mapping: " + setup);
            }
        }
    }

    public static Family familyFor(TradingSignal.StrategyType setup) {
        if (setup == null || !BY_SETUP.containsKey(setup)) {
            throw new IllegalArgumentException("unknown strategy setup: " + setup);
        }
        return BY_SETUP.get(setup);
    }

    public static Set<TradingSignal.StrategyType> allSetups() {
        return Collections.unmodifiableSet(new LinkedHashSet<>(BY_SETUP.keySet()));
    }

    /** Default-off runtime kill switch used throughout the shadow migration. */
    public static boolean lineageEnabled() {
        String value = System.getenv().getOrDefault("ENABLE_STRATEGY_FAMILY_LINEAGE", "false");
        return Set.of("1", "true", "yes", "on").contains(value.trim().toLowerCase());
    }
}
