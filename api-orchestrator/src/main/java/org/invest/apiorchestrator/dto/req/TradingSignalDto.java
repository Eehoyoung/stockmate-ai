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
    private Double volSurgeRt;     // S10: 거래량 급증률 % (scorer.py vol_surge_rt 필드용)
    private Double rsi;            // S8/S9/S13/S14/S15: RSI 현재값
    private Double atrPct;         // S14/S15: ATR % (변동성 측정)
    private Integer condCount;     // S14/S15: 선택 조건 충족 개수
    private String holdingDays;    // S8/S9/S13/S14/S15: 예상 보유기간

    // ── 전략별 기술적 분석 기반 TP/SL 절대가 (Phase 1 규칙 기반) ──
    private Double tp1Price;     // 1차 목표가 (기술적 저항 또는 %기반)
    private Double tp2Price;     // 2차 목표가
    private Double slPrice;      // 손절가 (기술적 지지 또는 %기반)

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
        m.put("vol_surge_rt",    volSurgeRt);
        m.put("pullback_pct",    pullbackPct);
        m.put("theme_name",      themeName);
        m.put("net_buy_amt",     netBuyAmt);
        m.put("continuous_days", continuousDays);
        m.put("is_new_high",     isNewHigh);
        m.put("vol_rank",        volRank);
        m.put("market_type",     marketType);
        m.put("body_ratio",      bodyRatio);
        m.put("rsi",             rsi);
        m.put("atr_pct",         atrPct);
        m.put("cond_count",      condCount);
        m.put("holding_days",    holdingDays);
        m.put("tp1_price",       tp1Price);
        m.put("tp2_price",       tp2Price);
        m.put("sl_price",        slPrice);
        m.put("signal_time",     signalTime != null ? signalTime.toString() : LocalDateTime.now().toString());
        m.put("cur_prc",         entryPrice);  // 진입가 = 현재가 (신호 발생 시점)
        m.put("message",         toTelegramMessage());
        return m;
    }

    /** TelegramQueue용 직렬화 메시지 (실제 가격 포함) */
    public String toTelegramMessage() {
        String emoji = switch (strategy) {
            case S1_GAP_OPEN         -> "🚀";
            case S2_VI_PULLBACK      -> "🎯";
            case S3_INST_FRGN        -> "🏦";
            case S4_BIG_CANDLE       -> "📊";
            case S5_PROG_FRGN        -> "💻";
            case S6_THEME_LAGGARD    -> "🔥";
            case S7_AUCTION          -> "⚡";
            case S8_GOLDEN_CROSS     -> "📈";
            case S9_PULLBACK_SWING   -> "🔽";
            case S10_NEW_HIGH        -> "🏔";
            case S11_FRGN_CONT       -> "🌏";
            case S12_CLOSING         -> "🌙";
            case S13_BOX_BREAKOUT    -> "📦";
            case S14_OVERSOLD_BOUNCE -> "🔄";
            case S15_MOMENTUM_ALIGN  -> "⚡";
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

        // TP/SL – 기술적 절대가 우선, 없으면 % 기반 계산
        double t1  = tp1Price != null && tp1Price > 0 ? tp1Price : calcTarget1Price();
        double t2  = tp2Price != null && tp2Price > 0 ? tp2Price : calcTarget2Price();
        double sl  = slPrice  != null && slPrice  > 0 ? slPrice  : calcStopPrice();
        double ep  = entryPrice != null && entryPrice > 0 ? entryPrice : 0;

        sb.append("📐 목표가 (규칙 기반)\n");
        if (t1 > 0) {
            String t1PctStr = ep > 0 ? String.format(" (+%.1f%%)", (t1 - ep) / ep * 100) : "";
            sb.append(String.format("  TP1: %,.0f원%s\n", t1, t1PctStr));
        }
        if (t2 > 0) {
            String t2PctStr = ep > 0 ? String.format(" (+%.1f%%)", (t2 - ep) / ep * 100) : "";
            sb.append(String.format("  TP2: %,.0f원%s\n", t2, t2PctStr));
        }
        if (sl > 0) {
            String slPctStr = ep > 0 ? String.format(" (%.1f%%)", (sl - ep) / ep * 100) : "";
            sb.append(String.format("  SL:  %,.0f원%s\n", sl, slPctStr));
        }
        // R/R 비율
        if (ep > 0 && t1 > 0 && sl > 0 && sl < ep) {
            double reward = t1 - ep;
            double risk   = ep - sl;
            if (risk > 0) sb.append(String.format("  R/R: 1:%.1f\n", reward / risk));
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
        if (rsi != null)          sb.append(String.format(" RSI%.1f", rsi));
        if (atrPct != null)       sb.append(String.format(" ATR%.2f%%", atrPct));
        if (condCount != null)    sb.append(String.format(" 지표%d개", condCount));
        if (holdingDays != null)  sb.append(String.format(" [%s]", holdingDays));
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
