package org.invest.apiorchestrator.service;

import lombok.RequiredArgsConstructor;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.service.strategy.S10NewHighEvaluator;
import org.invest.apiorchestrator.service.strategy.S12ClosingStrengthEvaluator;
import org.invest.apiorchestrator.service.strategy.S2ViPullbackEvaluator;
import org.invest.apiorchestrator.service.strategy.S4BigCandleEvaluator;
import org.invest.apiorchestrator.service.strategy.StrategyScanContext;
import org.invest.apiorchestrator.service.strategy.StrategyScannerRegistry;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.Set;

/**
 * Public strategy facade.
 *
 * <p>All new-entry scans delegate to the freshness-aware registry/evaluators.
 * The former duplicated legacy implementations read raw Redis market data when
 * a delegated evaluation returned no signal, which could turn a legitimate
 * freshness rejection into a stale entry candidate.</p>
 */
@Service
@RequiredArgsConstructor
public class StrategyService {

    private final StrategyScannerRegistry strategyScannerRegistry;
    private final S2ViPullbackEvaluator s2ViPullbackEvaluator;
    private final S4BigCandleEvaluator s4BigCandleEvaluator;
    private final S10NewHighEvaluator s10NewHighEvaluator;
    private final S12ClosingStrengthEvaluator s12ClosingStrengthEvaluator;

    public List<TradingSignalDto> scanGapOpening(List<String> candidates) {
        return scanCandidates(TradingSignal.StrategyType.S1_GAP_OPEN, candidates);
    }

    public Optional<TradingSignalDto> checkViPullback(String stkCd, double viPrice, boolean isDynamic) {
        return s2ViPullbackEvaluator.evaluate(stkCd, viPrice, isDynamic);
    }

    public List<TradingSignalDto> scanInstFrgn(String market) {
        return scanMarket(TradingSignal.StrategyType.S3_INST_FRGN, market);
    }

    public Optional<TradingSignalDto> checkBigCandle(String stkCd) {
        return s4BigCandleEvaluator.evaluate(stkCd);
    }

    public List<TradingSignalDto> scanProgramFrgn(String market) {
        return scanMarket(TradingSignal.StrategyType.S5_PROG_FRGN, market);
    }

    public List<TradingSignalDto> scanThemeLaggard() {
        return scanMarket(TradingSignal.StrategyType.S6_THEME_LAGGARD, "");
    }

    @Deprecated
    public List<TradingSignalDto> scanAuction(String market) {
        return scanAuction(market, Collections.emptySet());
    }

    @Deprecated
    public List<TradingSignalDto> scanAuction(String market, Set<String> preFiltered) {
        return strategyScannerRegistry.find(TradingSignal.StrategyType.S7_ICHIMOKU_BREAKOUT)
                .map(scanner -> scanner.scan(StrategyScanContext.market(market, preFiltered)))
                .orElseGet(Collections::emptyList);
    }

    public Optional<TradingSignalDto> checkNewHigh(String stkCd) {
        return s10NewHighEvaluator.evaluate(stkCd);
    }

    public Optional<TradingSignalDto> checkClosingStrength(String stkCd) {
        return s12ClosingStrengthEvaluator.evaluate(stkCd);
    }

    public List<TradingSignalDto> scanGoldenCross(List<String> candidates) {
        return scanCandidates(TradingSignal.StrategyType.S8_GOLDEN_CROSS, candidates);
    }

    public List<TradingSignalDto> scanPullbackSwing(List<String> candidates) {
        return scanCandidates(TradingSignal.StrategyType.S9_PULLBACK_SWING, candidates);
    }

    public List<TradingSignalDto> scanFrgnCont(String market) {
        return scanMarket(TradingSignal.StrategyType.S11_FRGN_CONT, market);
    }

    public List<TradingSignalDto> scanBoxBreakout(List<String> candidates) {
        return scanCandidates(TradingSignal.StrategyType.S13_BOX_BREAKOUT, candidates);
    }

    public List<TradingSignalDto> scanOversoldBounce(List<String> candidates) {
        return scanCandidates(TradingSignal.StrategyType.S14_OVERSOLD_BOUNCE, candidates);
    }

    public List<TradingSignalDto> scanMomentumAlign(List<String> candidates) {
        return scanCandidates(TradingSignal.StrategyType.S15_MOMENTUM_ALIGN, candidates);
    }

    public List<TradingSignalDto> scanAccumulationShadow(List<String> candidates) {
        return scanCandidates(TradingSignal.StrategyType.S16_ACCUMULATION_SHADOW, candidates);
    }

    private List<TradingSignalDto> scanCandidates(TradingSignal.StrategyType type, List<String> candidates) {
        return strategyScannerRegistry.find(type)
                .map(scanner -> scanner.scan(StrategyScanContext.candidates(candidates)))
                .orElseGet(Collections::emptyList);
    }

    private List<TradingSignalDto> scanMarket(TradingSignal.StrategyType type, String market) {
        return strategyScannerRegistry.find(type)
                .map(scanner -> scanner.scan(StrategyScanContext.market(market)))
                .orElseGet(Collections::emptyList);
    }
}
