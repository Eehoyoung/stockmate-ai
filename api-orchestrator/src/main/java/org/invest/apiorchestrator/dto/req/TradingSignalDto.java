package org.invest.apiorchestrator.dto.req;

import lombok.Builder;
import lombok.Getter;
import org.invest.apiorchestrator.domain.TradingSignal;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
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
    private Double target2Pct;   // 2차 목표 비율 (없으면 targetPct * 1.5 로 자동 계산)
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
    private Double bodyRatio;      // S4 장대양봉 몸통 비율

    private Map<String, Object> extra;
    private LocalDateTime signalTime;

    // ── 파생 계산값 ──────────────────────────────────────────────

    /** 2차 목표 비율 – 명시 설정이 없으면 1차의 1.5배 */
    public double resolvedTarget2Pct() {
        if (target2Pct != null) return target2Pct;
        if (targetPct  != null) return Math.round(targetPct * 1.5 * 10.0) / 10.0;
        return 0.0;
    }

    /** 진입가 기준 목표가 1 계산. entryPrice 없으면 0. */
    public double calcTarget1Price() {
        if (entryPrice == null || entryPrice <= 0 || targetPct == null) return 0;
        return Math.round(entryPrice * (1 + targetPct / 100));
    }

    /** 진입가 기준 목표가 2 계산. entryPrice 없으면 0. */
    public double calcTarget2Price() {
        if (entryPrice == null || entryPrice <= 0) return 0;
        double t2 = resolvedTarget2Pct();
        return Math.round(entryPrice * (1 + t2 / 100));
    }

    /** 진입가 기준 손절가 계산. entryPrice 없으면 0. */
    public double calcStopPrice() {
        if (entryPrice == null || entryPrice <= 0 || stopPct == null) return 0;
        return Math.round(entryPrice * (1 + stopPct / 100));
    }

    /**
     * ai-engine scorer.py 가 기대하는 snake_case 필드 계약을 단일 위치에서 관리.
     * SignalService 가 이 Map을 직렬화하여 telegram_queue 에 LPUSH 한다.
     */
    public Map<String, Object> toQueuePayload(Long signalId) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id",              signalId);
        m.put("stk_cd",          stkCd);
        m.put("stk_nm",          stkNm);
        m.put("strategy",        strategy != null ? strategy.name() : null);
        m.put("entry_type",      entryType);
        m.put("target_pct",      targetPct);
        m.put("target2_pct",     resolvedTarget2Pct());
        m.put("stop_pct",        stopPct);
        m.put("signal_score",    signalScore);
        m.put("gap_pct",         gapPct);
        m.put("cntr_strength",   cntrStrength);
        m.put("bid_ratio",       bidRatio);
        m.put("vol_ratio",       volRatio);
        m.put("pullback_pct",    pullbackPct);
        m.put("theme_name",      themeName);
        m.put("net_buy_amt",     netBuyAmt);
        m.put("continuous_days", continuousDays);
        m.put("is_new_high",     isNewHigh);
        m.put("vol_rank",        volRank);
        m.put("market_type",     marketType);
        m.put("body_ratio",      bodyRatio);
        m.put("signal_time",     signalTime != null ? signalTime.toString() : java.time.LocalDateTime.now().toString());
        m.put("cur_prc",         entryPrice);  // 진입가 = 현재가 (신호 발생 시점)
        m.put("message",         toTelegramMessage());
        return m;
    }

    /** TelegramQueue용 직렬화 메시지 (실제 가격 포함) */
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
        sb.append("🚨 매수 추천 알림\n\n");
        sb.append(String.format("📌 전략명: %s [%s]\n", emoji, strategy.name()));
        sb.append(String.format("📈 종목: %s%s\n", stkCd, stkNm != null ? " " + stkNm : ""));

        // 진입가
        if (entryPrice != null && entryPrice > 0) {
            sb.append(String.format("💰 진입가: %,.0f원", entryPrice));
        } else {
            sb.append("💰 진입가: 미확인");
        }
        if (entryType != null) sb.append(String.format("  (%s)", entryType));
        sb.append("\n");

        // 1차 목표가
        double t1 = calcTarget1Price();
        if (t1 > 0 && targetPct != null) {
            sb.append(String.format("🎯 1차 목표가: %,.0f원  (+%.1f%%)\n", t1, targetPct));
        } else if (targetPct != null) {
            sb.append(String.format("🎯 1차 목표가: +%.1f%%\n", targetPct));
        }

        // 2차 목표가
        double t2pct = resolvedTarget2Pct();
        double t2 = calcTarget2Price();
        if (t2 > 0) {
            sb.append(String.format("🎯 2차 목표가: %,.0f원  (+%.1f%%)\n", t2, t2pct));
        } else {
            sb.append(String.format("🎯 2차 목표가: +%.1f%%\n", t2pct));
        }

        // 손절가
        double sp = calcStopPrice();
        if (sp > 0 && stopPct != null) {
            sb.append(String.format("🛑 손절가: %,.0f원  (%.1f%%)\n", sp, stopPct));
        } else if (stopPct != null) {
            sb.append(String.format("🛑 손절가: %.1f%%\n", stopPct));
        }

        // 사유
        sb.append("📊 사유:");
        if (gapPct != null)       sb.append(String.format(" 갭+%.2f%%", gapPct));
        if (cntrStrength != null) sb.append(String.format(" 체결강도%.0f%%", cntrStrength));
        if (bidRatio != null)     sb.append(String.format(" 호가비%.2fx", bidRatio));
        if (volRatio != null)     sb.append(String.format(" 거래량%.1fx", volRatio));
        if (pullbackPct != null)  sb.append(String.format(" 눌림%.2f%%", pullbackPct));
        if (themeName != null)    sb.append(String.format(" 테마:%s", themeName));
        if (netBuyAmt != null)    sb.append(String.format(" 순매수%,d만원", netBuyAmt / 10000));
        sb.append("\n");

        if (signalScore != null)  sb.append(String.format("⭐ 스코어: %.1f\n", signalScore));
        if (signalTime != null)   sb.append(String.format("🕐 시간: %s", signalTime.toLocalTime()));

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
