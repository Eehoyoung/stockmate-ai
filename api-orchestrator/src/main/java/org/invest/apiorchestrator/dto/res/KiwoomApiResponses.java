package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 키움 REST API 공통 응답 + 전술별 응답 DTO 모음
 */
public class KiwoomApiResponses {

    /** 공통 응답 래퍼 */
    @Getter
    @NoArgsConstructor
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class BaseResponse {
        @JsonProperty("return_code") private String returnCode;
        @JsonProperty("return_msg")  private String returnMsg;
        @JsonProperty("cont_yn")     private String contYn;
        @JsonProperty("next_key")    private String nextKey;

        public boolean isSuccess() { return "0".equals(returnCode); }
        public boolean hasMore()   { return "Y".equals(contYn); }
    }

    /* ───────────── 체결강도 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class CntrStrengthTimeResponse extends BaseResponse {
        @JsonProperty("cntr_str_tm") private List<CntrStrengthItem> cntrStrTm;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class CntrStrengthItem {
            @JsonProperty("cntr_tm")   private String cntrTm;
            @JsonProperty("cur_prc")   private String curPrc;
            @JsonProperty("pred_pre")  private String predPre;
            @JsonProperty("cntr_str")  private String cntrStr;
            @JsonProperty("trde_qty")  private String trdeQty;
        }
    }

    /* ───────────── 분봉차트 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class MinuteCandleResponse extends BaseResponse {
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("stk_min_pole_chart_qry") private List<CandleItem> candles;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class CandleItem {
            @JsonProperty("cntr_tm")   private String cntrTm;
            @JsonProperty("cur_prc")   private String curPrc;
            @JsonProperty("open_pric") private String openPric;
            @JsonProperty("high_pric") private String highPric;
            @JsonProperty("low_pric")  private String lowPric;
            @JsonProperty("pred_pre")  private String predPre;
            @JsonProperty("trde_qty")  private String trdeQty;
            @JsonProperty("trde_prica")private String trdePrica;
        }
    }

    /* ───────────── 일봉차트 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class DailyCandleResponse extends BaseResponse {
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("stk_dt_pole_chart_qry") private List<DailyCandleItem> candles;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class DailyCandleItem {
            @JsonProperty("date")      private String date;
            @JsonProperty("cur_prc")   private String curPrc;
            @JsonProperty("open_pric") private String openPric;
            @JsonProperty("high_pric") private String highPric;
            @JsonProperty("low_pric")  private String lowPric;
            @JsonProperty("trde_qty")  private String trdeQty;
            @JsonProperty("trde_prica")private String trdePrica;
        }
    }

    /* ───────────── 거래량순위 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class VolumeRankResponse extends BaseResponse {
        @JsonProperty("trde_qty_upper") private List<VolumeRankItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class VolumeRankItem {
            @JsonProperty("rank")      private String rank;
            @JsonProperty("stk_cd")    private String stkCd;
            @JsonProperty("stk_nm")    private String stkNm;
            @JsonProperty("cur_prc")   private String curPrc;
            @JsonProperty("flu_rt")    private String fluRt;
            @JsonProperty("trde_qty")  private String trdeQty;
            @JsonProperty("trde_prica")private String trdePrica;
            @JsonProperty("cntr_str")  private String cntrStr;
        }
    }

    /* ───────────── 장중투자자별매매 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class IntradayInvestorResponse extends BaseResponse {
        @JsonProperty("opmr_invsr_trde") private List<InvestorItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InvestorItem {
            @JsonProperty("stk_cd")      private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("flu_rt")      private String fluRt;
            @JsonProperty("net_buy_qty") private String netBuyQty;
            @JsonProperty("net_buy_amt") private String netBuyAmt;
            @JsonProperty("trde_qty")    private String trdeQty;
        }
    }

    /* ───────────── 장중투자자별매매상위 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class IntradayInvestorUpperResponse extends BaseResponse {
        @JsonProperty("opmr_invsr_trde_upper") private List<InvestorUpperItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InvestorUpperItem {
            @JsonProperty("stk_cd")      private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("net_buy_qty") private String netBuyQty;
            @JsonProperty("net_buy_amt") private String netBuyAmt;
        }
    }

    /* ───────────── 기관외국인연속매매 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class InstFrgnContinuousResponse extends BaseResponse {
        @JsonProperty("orgn_for_cont_trde") private List<ContTrdeItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ContTrdeItem {
            @JsonProperty("stk_cd")       private String stkCd;
            @JsonProperty("stk_nm")       private String stkNm;
            @JsonProperty("cont_dt_cnt")  private String contDtCnt;
            @JsonProperty("net_buy_amt")  private String netBuyAmt;
            @JsonProperty("net_buy_qty")  private String netBuyQty;
        }
    }

    /* ───────────── 프로그램순매수상위50 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ProgramNetBuyResponse extends BaseResponse {
        @JsonProperty("prm_netprps_upper_50") private List<ProgramItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ProgramItem {
            @JsonProperty("stk_cd")      private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("flu_rt")      private String fluRt;
            @JsonProperty("net_buy_amt") private String netBuyAmt;
            @JsonProperty("net_buy_qty") private String netBuyQty;
        }
    }

    /* ───────────── 외국인기관매매상위 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class FrgnInstUpperResponse extends BaseResponse {
        @JsonProperty("for_inst_trde_upper") private List<FrgnInstItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class FrgnInstItem {
            @JsonProperty("stk_cd")      private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("for_buy_amt") private String forBuyAmt;
            @JsonProperty("org_buy_amt") private String orgBuyAmt;
            @JsonProperty("cur_prc")     private String curPrc;
        }
    }

    /* ───────────── 테마그룹별 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ThemeGroupResponse extends BaseResponse {
        @JsonProperty("thme_grp") private List<ThemeGroupItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ThemeGroupItem {
            @JsonProperty("thema_grp_cd") private String themaGrpCd;
            @JsonProperty("thema_nm")     private String themaNm;
            @JsonProperty("flu_rt")       private String fluRt;
            @JsonProperty("dt_prft_rt")   private String dtPrftRt;
            @JsonProperty("stk_cnt")      private String stkCnt;
        }
    }

    /* ───────────── 테마구성종목 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ThemeStockResponse extends BaseResponse {
        @JsonProperty("thme_comp_stk") private List<ThemeStockItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ThemeStockItem {
            @JsonProperty("stk_cd")   private String stkCd;
            @JsonProperty("stk_nm")   private String stkNm;
            @JsonProperty("cur_prc")  private String curPrc;
            @JsonProperty("flu_rt")   private String fluRt;
            @JsonProperty("trde_qty") private String trdeQty;
        }
    }

    /* ───────────── 당일전일체결량 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class TodayPrevVolumeResponse extends BaseResponse {
        @JsonProperty("tdy_pred_cntr_qty") private List<VolItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class VolItem {
            @JsonProperty("cntr_tm")  private String cntrTm;
            @JsonProperty("cntr_pric")private String cntrPric;
            @JsonProperty("cntr_qty") private String cntrQty;
        }
    }
}
