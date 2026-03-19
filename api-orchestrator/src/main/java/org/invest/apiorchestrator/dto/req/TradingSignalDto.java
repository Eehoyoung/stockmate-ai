package org.invest.apiorchestrator.dto.req;

import lombok.Builder;
import lombok.Getter;
import org.invest.apiorchestrator.domain.TradingSignal;

import java.time.LocalDateTime;
import java.util.Map;

@Getter
@Builder
public class TradingSignalDto {

    private String stkCd;
    private String stkNm;
    private TradingSignal.StrategyType strategy;
    private Double signalScore;
    private Double entryPrice;
    private Double targetPct;
    private Double stopPct;
    private String entryType;
    private String marketType;

    // 전술별 부가 정보
    private Double gapPct;
    private Double cntrStrength;
    private Double bidRatio;
    private Double volRatio;
    private Double pullbackPct;
    private String themeName;
    private Double themeRank;
    private Integer volRank;
    private Boolean isNewHigh;
    private Integer continuousDays;
    private Long netBuyAmt;

    private Map<String, Object> extra;
    private LocalDateTime signalTime;

    /** TelegramQueue용 직렬화 메시지 */
    public String toTelegramMessage() {
        String emoji = switch (strategy) {
            case S1_GAP_OPEN      -> "🚀";
            case S2_VI_PULLBACK   -> "🎯";
            case S3_INST_FRGN     -> "🏦";
            case S4_BIG_CANDLE    -> "📊";
            case S5_PROG_FRGN     -> "💻";
            case S6_THEME_LAGGARD -> "🔥";
            case S7_AUCTION       -> "⚡";
        };

        StringBuilder sb = new StringBuilder();
        sb.append(String.format("%s [%s] %s %s\n", emoji, strategy.name(), stkCd,
                stkNm != null ? stkNm : ""));
        sb.append(String.format("진입: %s\n", entryType));
        sb.append(String.format("목표: +%.1f%% | 손절: %.1f%%\n", targetPct, stopPct));

        if (gapPct != null)       sb.append(String.format("갭상승: +%.2f%%\n", gapPct));
        if (cntrStrength != null) sb.append(String.format("체결강도: %.1f%%\n", cntrStrength));
        if (bidRatio != null)     sb.append(String.format("호가비율: %.2f\n", bidRatio));
        if (volRatio != null)     sb.append(String.format("거래량비율: %.1fx\n", volRatio));
        if (pullbackPct != null)  sb.append(String.format("눌림: %.2f%%\n", pullbackPct));
        if (themeName != null)    sb.append(String.format("테마: %s\n", themeName));
        if (signalScore != null)  sb.append(String.format("스코어: %.1f\n", signalScore));
        if (signalTime != null)   sb.append(String.format("시간: %s", signalTime.toLocalTime()));

        return sb.toString();
    }

    public static TradingSignalDto from(TradingSignal entity) {
        return TradingSignalDto.builder()
                .stkCd(entity.getStkCd())
                .stkNm(entity.getStkNm())
                .strategy(entity.getStrategy())
                .signalScore(entity.getSignalScore())
                .entryPrice(entity.getEntryPrice())
                .targetPct(entity.getTargetPct())
                .stopPct(entity.getStopPct())
                .entryType(entity.getEntryType())
                .marketType(entity.getMarketType())
                .gapPct(entity.getGapPct())
                .cntrStrength(entity.getCntrStrength())
                .bidRatio(entity.getBidRatio())
                .volRatio(entity.getVolRatio())
                .pullbackPct(entity.getPullbackPct())
                .themeName(entity.getThemeName())
                .signalTime(entity.getCreatedAt())
                .build();
    }
}
