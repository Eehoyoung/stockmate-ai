package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.invest.apiorchestrator.util.StockCodeDeserializer;

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
            @JsonProperty("flu_rt")    private String fluRt;
            @JsonProperty("cntr_str")  private String cntrStr;
            @JsonProperty("trde_qty")  private String trdeQty;
            @JsonProperty("acc_trde_prica") private String accTrdePrica;
            @JsonProperty("acc_trde_qty") private String accTrdeQty;
            @JsonProperty("cntr_str_5min") private String cntrStr5min;
            @JsonProperty("cntr_str_20min") private String cntrStr20min;
            @JsonProperty("cntr_str_60min") private String cntrStr60min;
            @JsonProperty("stex_tp") private String stexTp;
        }
    }

    /* ───────────── 분봉차트 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class MinuteCandleResponse extends BaseResponse {
        @JsonProperty("stk_cd") @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
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
        @JsonProperty("stk_cd") @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
        @JsonProperty("stk_dt_pole_chart_qry") private List<DailyCandleItem> candles;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class DailyCandleItem {
            @JsonProperty("dt") @JsonAlias("date") private String date;
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
            @JsonProperty("stk_cd")    @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
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
            @JsonProperty("stk_cd")      @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("flu_rt")      private String fluRt;
            @JsonProperty("netprps_qty") @JsonAlias("net_buy_qty") private String netBuyQty;
            @JsonProperty("netprps_amt") @JsonAlias("net_buy_amt") private String netBuyAmt;
            @JsonProperty("acc_trde_qty") @JsonAlias("trde_qty") private String trdeQty;
            @JsonProperty("prev_netprps_amt") private String prevNetBuyAmt;
            @JsonProperty("netprps_amt_irds") private String netBuyAmtChange;
        }
    }

    /** ka10054 volatility-interruption activation history. */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ViActivationResponse extends BaseResponse {
        @JsonProperty("motn_stk") private List<ViActivationItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ViActivationItem {
            @JsonProperty("stk_cd") @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm") private String stkNm;
            @JsonProperty("acc_trde_qty") private String accumulatedVolume;
            @JsonProperty("motn_pric") private String activationPrice;
            @JsonProperty("dynm_dispty_rt") private String dynamicDeviationRate;
            @JsonProperty("trde_cntr_proc_time") private String activationTime;
            @JsonProperty("virelis_time") private String releaseTime;
            @JsonProperty("viaplc_tp") private String applicationType;
            @JsonProperty("dynm_stdpc") private String dynamicReferencePrice;
            @JsonProperty("static_stdpc") private String staticReferencePrice;
            @JsonProperty("static_dispty_rt") private String staticDeviationRate;
            @JsonProperty("open_pric_pre_flu_rt") private String openPriceChangeRate;
            @JsonProperty("vimotn_cnt") private String activationCount;
            @JsonProperty("stex_tp") private String exchangeType;
        }
    }

    /** ka10064 intraday trading chart by investor. */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class IntradayInvestorChartResponse extends BaseResponse {
        @JsonProperty("opmr_invsr_trde_chart") private List<InvestorChartItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InvestorChartItem {
            @JsonProperty("tm") private String time;
            @JsonProperty("frgnr_invsr") private String foreignInvestor;
            @JsonProperty("orgn") private String institution;
            @JsonProperty("invtrt") private String investmentTrust;
            @JsonProperty("insrnc") private String insurance;
            @JsonProperty("bank") private String bank;
            @JsonProperty("penfnd_etc") private String pensionFundEtc;
            @JsonProperty("etc_corp") private String otherCorporation;
            @JsonProperty("natn") private String nation;
        }
    }

    /* ───────────── 장중투자자별매매상위 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class IntradayInvestorUpperResponse extends BaseResponse {
        @JsonProperty("opmr_invsr_trde_upper") private List<InvestorUpperItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InvestorUpperItem {
            @JsonProperty("stk_cd")      @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("net_buy_qty") private String netBuyQty;
            @JsonProperty("net_buy_amt") private String netBuyAmt;
        }
    }

    /* ───────────── 기관외국인연속매매 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class InstFrgnContinuousResponse extends BaseResponse {
        @JsonProperty("orgn_frgnr_cont_trde_prst")
        @JsonAlias("orgn_for_cont_trde")
        private List<ContTrdeItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ContTrdeItem {
            @JsonProperty("stk_cd")       @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")       private String stkNm;
            @JsonProperty("tot_cont_netprps_dys") @JsonAlias("cont_dt_cnt") private String contDtCnt;
            @JsonProperty("tot_cont_netprps_amt") @JsonAlias("net_buy_amt") private String netBuyAmt;
            @JsonProperty("tot_cont_nettrde_qty") @JsonAlias("net_buy_qty") private String netBuyQty;
            @JsonProperty("orgn_cont_netprps_dys") private String orgnContNetBuyDays;
            @JsonProperty("orgn_cont_netprps_amt") private String orgnContNetBuyAmt;
            @JsonProperty("frgnr_cont_netprps_dys") private String foreignContNetBuyDays;
            @JsonProperty("frgnr_cont_netprps_amt") private String foreignContNetBuyAmt;
        }
    }

    /* ───────────── 프로그램순매수상위50 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ProgramNetBuyResponse extends BaseResponse {
        @JsonProperty("prm_netprps_upper_50") private List<ProgramItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ProgramItem {
            @JsonProperty("stk_cd")      @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("flu_rt")      private String fluRt;
            @JsonProperty("prm_netprps_amt") @JsonAlias("net_buy_amt") private String netBuyAmt;
            @JsonProperty("prm_netprps_qty") @JsonAlias("net_buy_qty") private String netBuyQty;
            @JsonProperty("acc_trde_qty") private String accTrdeQty;
            @JsonProperty("prm_sell_amt") private String programSellAmt;
            @JsonProperty("prm_buy_amt") private String programBuyAmt;
        }
    }

    /* ───────────── 외국인기관매매상위 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class FrgnInstUpperResponse extends BaseResponse {
        @JsonProperty("frgnr_orgn_trde_upper")
        @JsonAlias("for_inst_trde_upper")
        private List<FrgnInstItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class FrgnInstItem {
            @JsonProperty("for_netprps_stk_cd") @JsonAlias("stk_cd")
            @JsonDeserialize(using = StockCodeDeserializer.class)
            private String forNetprpsStkCd;
            @JsonProperty("for_netprps_stk_nm") @JsonAlias("stk_nm") private String forNetprpsStkNm;
            @JsonProperty("for_netprps_amt") @JsonAlias("for_buy_amt") private String forBuyAmt;
            @JsonProperty("for_netprps_qty") private String forNetprpsQty;
            @JsonProperty("orgn_netprps_stk_cd")
            @JsonDeserialize(using = StockCodeDeserializer.class)
            private String orgnNetprpsStkCd;
            @JsonProperty("orgn_netprps_stk_nm") private String orgnNetprpsStkNm;
            @JsonProperty("orgn_netprps_amt") @JsonAlias("org_buy_amt") private String orgBuyAmt;
            @JsonProperty("orgn_netprps_qty") private String orgnNetprpsQty;

            /** Compatibility view used by legacy callers that treated a row as one stock. */
            public String getStkCd() { return forNetprpsStkCd; }
            public String getStkNm() { return forNetprpsStkNm; }
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
            @JsonProperty("stk_cd")   @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
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

    /* ───────────── 예상체결등락률상위 (ka10029) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ExpCntrFluRtUpperResponse extends BaseResponse {
        @JsonProperty("exp_cntr_flu_rt_upper") private List<ExpCntrFluRtItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ExpCntrFluRtItem {
            @JsonProperty("stk_cd")       @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")       private String stkNm;
            @JsonProperty("exp_cntr_pric")private String expCntrPric;
            @JsonProperty("base_pric")    private String basePric;
            @JsonProperty("flu_rt")       private String fluRt;      // +XX.XX
            @JsonProperty("pred_pre")     private String predPre;
            @JsonProperty("exp_cntr_qty") private String expCntrQty;
            @JsonProperty("sel_req")      private String selReq;
            @JsonProperty("sel_bid")      private String selBid;
            @JsonProperty("buy_bid")      private String buyBid;
            @JsonProperty("buy_req")      private String buyReq;
        }
    }

    /* ───────────── 당일거래량상위 (ka10030) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class TdyTrdeQtyUpperResponse extends BaseResponse {
        // ka10030 은 returnCode 가 camelCase 로 오는 경우도 대응
        @JsonProperty("returnCode") private String returnCodeCamel;
        @JsonProperty("tdy_trde_qty_upper") private List<TdyTrdeQtyItem> items;

        @Override
        public boolean isSuccess() {
            if (getReturnCode() != null) return "0".equals(getReturnCode());
            return "0".equals(returnCodeCamel);
        }

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class TdyTrdeQtyItem {
            @JsonProperty("stk_cd")          @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")          private String stkNm;
            @JsonProperty("cur_prc")         private String curPrc;
            @JsonProperty("flu_rt")          private String fluRt;
            @JsonProperty("trde_qty")        private String trdeQty;
            @JsonProperty("pred_rt")         private String predRt;
            @JsonProperty("trde_tern_rt")    private String trdeTernRt;
            @JsonProperty("trde_amt")        private String trdeAmt;
            @JsonProperty("opmr_trde_qty")   private String opmrTrdeQty;
            @JsonProperty("af_mkrt_trde_qty")private String afMkrtTrdeQty;
            @JsonProperty("bf_mkrt_trde_qty")private String bfMkrtTrdeQty;
        }
    }

    /* ───────────── 거래량급증 (ka10023) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class TrdeQtySdninResponse extends BaseResponse {
        @JsonProperty("trde_qty_sdnin") private List<TrdeQtySdninItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class TrdeQtySdninItem {
            @JsonProperty("stk_cd")       @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")       private String stkNm;
            @JsonProperty("cur_prc")      private String curPrc;
            @JsonProperty("flu_rt")       private String fluRt;
            @JsonProperty("prev_trde_qty")private String prevTrdeQty;
            @JsonProperty("now_trde_qty") private String nowTrdeQty;
            @JsonProperty("sdnin_qty")    private String sdninQty;
            @JsonProperty("sdnin_rt")     private String sdninRt;   // +XX.XX
        }
    }

    /* ───────────── 가격급등락 (ka10019) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class PricJmpFluResponse extends BaseResponse {
        @JsonProperty("pric_jmpflu") private List<PricJmpFluItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class PricJmpFluItem {
            @JsonProperty("stk_cd")  @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")  private String stkNm;
            @JsonProperty("cur_prc") private String curPrc;
            @JsonProperty("flu_rt")  private String fluRt;
            @JsonProperty("base_pric")private String basePric;
            @JsonProperty("base_pre")private String basePre;
            @JsonProperty("jmp_rt")  private String jmpRt;   // +XX.XX
            @JsonProperty("trde_qty")private String trdeQty;
        }
    }

    /* ───────────── 호가잔량상위 (ka10020) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class BidReqUpperResponse extends BaseResponse {
        @JsonProperty("bid_req_upper") private List<BidReqUpperItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class BidReqUpperItem {
            @JsonProperty("stk_cd")      @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("flu_rt")      private String fluRt;
            @JsonProperty("trde_qty")    private String trdeQty;
            @JsonProperty("tot_sel_req") private String totSelReq;
            @JsonProperty("tot_buy_req") private String totBuyReq;
            @JsonProperty("netprps_req") private String netprpsReq;
            @JsonProperty("buy_rt")      private String buyRt;  // % string
        }
    }

    /* ───────────── 주식기본정보 (ka10001) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class StkBasicInfoResponse extends BaseResponse {
        @JsonProperty("stk_cd")   @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
        @JsonProperty("stk_nm")   private String stkNm;
        @JsonProperty("base_pric")private String basePric;   // 전일종가
        @JsonProperty("open_pric") private String openPric;
        @JsonProperty("high_pric") private String highPric;
        @JsonProperty("low_pric")  private String lowPric;
        @JsonProperty("exp_cntr_pric") private String expCntrPric;
        @JsonProperty("exp_cntr_qty")  private String expCntrQty;
        @JsonProperty("cur_prc")  private String curPrc;
        @JsonProperty("flu_rt")   private String fluRt;
        @JsonProperty("trde_qty") private String trdeQty;
        @JsonProperty("mac")      private String mac;         // 시가총액 (억 원)
    }

    /* ───────────── 전일대비등락률상위 (ka10027) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class FluRtUpperResponse extends BaseResponse {
        @JsonProperty("pred_pre_flu_rt_upper") private List<FluRtUpperItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class FluRtUpperItem {
            @JsonProperty("stk_cd")      @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("flu_rt")      private String fluRt;       // +XX.XX or -XX.XX
            @JsonProperty("now_trde_qty")private String nowTrdeQty;
            @JsonProperty("cntr_str")    private String cntrStr;     // 체결강도
            @JsonProperty("sel_req")     private String selReq;
            @JsonProperty("buy_req")     private String buyReq;
        }
    }

    /* ───────────── 전일거래량상위 (ka10031) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class PrevVolumeUpperResponse extends BaseResponse {
        @JsonProperty("pred_trde_qty_upper") private List<PrevVolumeUpperItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class PrevVolumeUpperItem {
            @JsonProperty("stk_cd")  @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")  private String stkNm;
            @JsonProperty("cur_prc") private String curPrc;
            @JsonProperty("trde_qty")private String trdeQty;  // 전일거래량
        }
    }

    /* ───────────── 외인연속순매매상위 (ka10035) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class FrgnContNettrdUpperResponse extends BaseResponse {
        @JsonProperty("for_cont_nettrde_upper") private List<FrgnContNettrdItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class FrgnContNettrdItem {
            @JsonProperty("stk_cd")      @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("dm1")         private String dm1;     // D-1 순매수량
            @JsonProperty("dm2")         private String dm2;     // D-2 순매수량
            @JsonProperty("dm3")         private String dm3;     // D-3 순매수량
            @JsonProperty("tot")         private String tot;     // 합계
            @JsonProperty("limit_exh_rt")private String limitExhRt;  // 한도소진율
        }
    }

    /* ───────────── 거래대금상위 (ka10032) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class TrdePricaUpperResponse extends BaseResponse {
        @JsonProperty("trde_prica_upper") private List<TrdePricaUpperItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class TrdePricaUpperItem {
            @JsonProperty("stk_cd")      @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")      private String stkNm;
            @JsonProperty("cur_prc")     private String curPrc;
            @JsonProperty("flu_rt")      private String fluRt;
            @JsonProperty("now_trde_qty")private String nowTrdeQty;
            @JsonProperty("trde_prica")  private String trdePrica;  // 거래대금(백만원)
        }
    }

    /* ───────────── 신고저가 (ka10016) ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class NtlPricResponse extends BaseResponse {
        @JsonProperty("ntl_pric") private List<NtlPricItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class NtlPricItem {
            @JsonProperty("stk_cd")              @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm")              private String stkNm;
            @JsonProperty("cur_prc")             private String curPrc;
            @JsonProperty("flu_rt")              private String fluRt;
            @JsonProperty("trde_qty")            private String trdeQty;
            @JsonProperty("pred_trde_qty_pre_rt")private String predTrdeQtyPreRt;  // 전일거래량대비율
            @JsonProperty("high_pric")           private String highPric;
            @JsonProperty("low_pric")            private String lowPric;
        }
    }

    /* ───────────── ka10087 시간외단일가 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class OvtSigPricResponse extends BaseResponse {
        /** 시간외단일가 현재가 (장전 예상가) */
        @JsonProperty("ovt_sigpric_cur_prc")      private String ovtSigpricCurPrc;
        /** 시간외단일가 등락률 (예: "+2.35", "-1.20") */
        @JsonProperty("ovt_sigpric_flu_rt")        private String ovtSigpricFluRt;
        /** 시간외단일가 누적거래량 */
        @JsonProperty("ovt_sigpric_acc_trde_qty")  private String ovtSigpricAccTrdeQty;
    }

    /* ───────────── ka10001 기본정보 ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class infoResponse extends BaseResponse {
        /** 시간외단일가 현재가 (장전 예상가) */
        @JsonProperty("ovt_sigpric_cur_prc")      private String ovtSigpricCurPrc;
        /** 시간외단일가 등락률 (예: "+2.35", "-1.20") */
        @JsonProperty("ovt_sigpric_flu_rt")        private String ovtSigpricFluRt;
        /** 시간외단일가 누적거래량 */
        @JsonProperty("ovt_sigpric_acc_trde_qty")  private String ovtSigpricAccTrdeQty;
    }
}
