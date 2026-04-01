package org.invest.apiorchestrator.dto.req;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.experimental.SuperBuilder;

/**
 * 전술별 API 요청 DTO 모음
 */
public class StrategyRequests {

    /** ka10033 거래량순위요청 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class VolumeRankRequest extends KiwoomApiRequest {
        @JsonProperty("mrkt_tp") private String mrktTp;
        @Builder.Default @JsonProperty("trde_qty_tp") private String trdeQtyTp = "10";
        @Builder.Default @JsonProperty("stk_cnd") private String stkCnd = "1";
        @Builder.Default @JsonProperty("updown_incls") private String updownIncls = "0";
        @Builder.Default @JsonProperty("crd_cnd") private String crdCnd = "0";
    }

    /** ka10046 체결강도추이시간별 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class CntrStrengthTimeRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
    }

    /** ka10047 체결강도추이일별 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class CntrStrengthDailyRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
    }

    /** ka10054 변동성완화장치발동종목(REST 과거이력) */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ViActivationRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp") private String mrktTp = "000";
        @Builder.Default @JsonProperty("bf_mkrt_tp") private String bfMkrtTp = "1";
        @JsonProperty("stk_cd") private String stkCd;
        @Builder.Default @JsonProperty("motn_tp") private String motnTp = "0";
        @Builder.Default @JsonProperty("skip_stk") private String skipStk = "000000000";
        @Builder.Default @JsonProperty("trde_qty_tp") private String trdeQtyTp = "0";
        @JsonProperty("min_trde_qty") private String minTrdeQty;
        @JsonProperty("max_trde_qty") private String maxTrdeQty;
        @Builder.Default @JsonProperty("trde_prica_tp") private String trdePricaTp = "0";
    }

    /** ka10055 당일전일체결량 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class TodayPrevVolumeRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
        @Builder.Default @JsonProperty("tdy_pred") private String tdyPred = "1";  // 1:당일, 2:전일
    }

    /** ka10063 장중투자자별매매 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class IntradayInvestorRequest extends KiwoomApiRequest {
        @JsonProperty("mrkt_tp") private String mrktTp;
        @Builder.Default @JsonProperty("amt_qty_tp") private String amtQtyTp = "1";
        @Builder.Default @JsonProperty("invsr") private String invsr = "6";         // 외국인
        @Builder.Default @JsonProperty("frgn_all") private String frgnAll = "1";
        @Builder.Default @JsonProperty("smtm_netprps_tp") private String smtmNetprpsTp = "1";
        // stexTp 는 KiwoomApiRequest 부모에서 @Builder.Default "1"(KRX) 로 관리
    }

    /** ka10065 장중투자자별매매상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class IntradayInvestorUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("trde_tp") private String trdeTp = "1";    // 1:순매수
        @Builder.Default @JsonProperty("mrkt_tp") private String mrktTp = "000";
        @Builder.Default @JsonProperty("orgn_tp") private String orgnTp = "9999"; // 기관계
    }

    /** ka10080 주식분봉차트 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class MinuteCandleRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
        @Builder.Default @JsonProperty("tic_scope") private String ticScope = "5";  // 5분봉
        @Builder.Default @JsonProperty("upd_stkpc_tp") private String updStkpcTp = "1";
        @JsonProperty("base_dt") private String baseDt;
    }

    /** ka10081 주식일봉차트 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class DailyCandleRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("base_dt") private String baseDt;
        @Builder.Default @JsonProperty("upd_stkpc_tp") private String updStkpcTp = "1";
    }

    /** ka10131 기관외국인연속매매현황 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class InstFrgnContinuousRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("dt") private String dt = "3";             // 3일
        @JsonProperty("strt_dt") private String strtDt;
        @JsonProperty("end_dt") private String endDt;
        @Builder.Default @JsonProperty("mrkt_tp") private String mrktTp = "001";
        @Builder.Default @JsonProperty("netslmt_tp") private String netslmtTp = "2"; // 순매수
        @Builder.Default @JsonProperty("stk_inds_tp") private String stkIndsTp = "0";
        @Builder.Default @JsonProperty("amt_qty_tp") private String amtQtyTp = "0";
    }

    /** ka90001 테마그룹별 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ThemeGroupRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("qry_tp") private String qryTp = "1";     // 테마검색
        @JsonProperty("stk_cd") private String stkCd;
        @Builder.Default @JsonProperty("date_tp") private String dateTp = "1";   // 1일
        @JsonProperty("thema_nm") private String themaNm;
        @Builder.Default @JsonProperty("flu_pl_amt_tp") private String fluPlAmtTp = "1"; // 상위기간수익률
    }

    /** ka90002 테마구성종목 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ThemeStockRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("date_tp") private String dateTp = "1";
        @JsonProperty("thema_grp_cd") private String themaGrpCd;
    }

    /** ka90003 프로그램순매수상위50 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ProgramNetBuyRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("trde_upper_tp") private String trdeUpperTp = "2"; // 순매수상위
        @Builder.Default @JsonProperty("amt_qty_tp") private String amtQtyTp = "1";
        @JsonProperty("mrkt_tp") private String mrktTp;
    }

    /** ka90009 외국인기관매매상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class FrgnInstUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp") private String mrktTp = "000";
        @Builder.Default @JsonProperty("amt_qty_tp") private String amtQtyTp = "1";
        @Builder.Default @JsonProperty("qry_dt_tp") private String qryDtTp = "0";
        @JsonProperty("date") private String date;
    }

    /** ka10029 예상체결등락률상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ExpCntrFluRtUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")       private String mrktTp    = "000";
        @Builder.Default @JsonProperty("sort_tp")       private String sortTp    = "1";    // 1:상승률
        @Builder.Default @JsonProperty("trde_qty_cnd")  private String trdeQtyCnd = "10"; // 만주 이상
        @Builder.Default @JsonProperty("stk_cnd")       private String stkCnd    = "1";   // 관리종목 제외
        @Builder.Default @JsonProperty("crd_cnd")       private String crdCnd    = "0";   // 전체
        @Builder.Default @JsonProperty("pric_cnd")      private String pricCnd   = "8";   // 1천원 이상
        // stexTp 는 KiwoomApiRequest 부모에서 @Builder.Default "1"(KRX) 로 관리
    }

    /** ka10030 당일거래량상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class TdyTrdeQtyUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")        private String mrktTp       = "000";
        @Builder.Default @JsonProperty("sort_tp")        private String sortTp       = "1";
        @Builder.Default @JsonProperty("mang_stk_incls") private String mangStkIncls = "1"; // 관리종목 제외
        @Builder.Default @JsonProperty("crd_tp")         private String crdTp        = "0";
        @Builder.Default @JsonProperty("trde_qty_tp")    private String trdeQtyTp    = "10";
        @Builder.Default @JsonProperty("pric_tp")        private String pricTp       = "8";
        @Builder.Default @JsonProperty("trde_prica_tp")  private String trdePricaTp  = "0";
        @Builder.Default @JsonProperty("mrkt_open_tp")   private String mrktOpenTp   = "0";
    }

    /** ka10023 거래량급증 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class TrdeQtySdninRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")     private String mrktTp    = "000";
        @Builder.Default @JsonProperty("sort_tp")     private String sortTp    = "2";    // 2:급증률순
        @Builder.Default @JsonProperty("tm_tp")       private String tmTp      = "1";
        @Builder.Default @JsonProperty("trde_qty_tp") private String trdeQtyTp = "10";
        @JsonProperty("tm") private String tm;                // 분 (optional)
        @Builder.Default @JsonProperty("stk_cnd")    private String stkCnd    = "1";
        @Builder.Default @JsonProperty("pric_tp")    private String pricTp    = "8";
    }

    /** ka10019 가격급등락 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class PricJmpFluRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")      private String mrktTp      = "000";
        @Builder.Default @JsonProperty("flu_tp")       private String fluTp       = "1"; // 1:급등
        @Builder.Default @JsonProperty("tm_tp")        private String tmTp        = "1";
        @JsonProperty("tm") private String tm;
        @Builder.Default @JsonProperty("trde_qty_tp")  private String trdeQtyTp   = "00010";
        @Builder.Default @JsonProperty("stk_cnd")      private String stkCnd      = "1";
        @Builder.Default @JsonProperty("crd_cnd")      private String crdCnd      = "0";
        @Builder.Default @JsonProperty("pric_cnd")     private String pricCnd     = "8";
        @Builder.Default @JsonProperty("updown_incls") private String updownIncls = "0";
    }

    /** ka10020 호가잔량상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class BidReqUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")     private String mrktTp    = "001";
        @Builder.Default @JsonProperty("sort_tp")     private String sortTp    = "3";    // 3:매수비율순
        @Builder.Default @JsonProperty("trde_qty_tp") private String trdeQtyTp = "0000";
        @Builder.Default @JsonProperty("stk_cnd")     private String stkCnd    = "1";
        @Builder.Default @JsonProperty("crd_cnd")     private String crdCnd    = "0";
    }

    /** ka10001 주식기본정보 (전일종가 조회용) */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class StkBasicInfoRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
    }

    /** ka10027 전일대비등락률상위 – sort_tp: 1:상승률 3:하락률 5:보합 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class FluRtUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")        private String mrktTp       = "000";
        @Builder.Default @JsonProperty("sort_tp")        private String sortTp       = "1";    // 1:상승률
        @Builder.Default @JsonProperty("trde_qty_cnd")   private String trdeQtyCnd   = "0010"; // 만주 이상
        @Builder.Default @JsonProperty("stk_cnd")        private String stkCnd       = "1";    // 관리종목 제외
        @Builder.Default @JsonProperty("crd_cnd")        private String crdCnd       = "0";
        @Builder.Default @JsonProperty("updown_incls")   private String updownIncls  = "0";    // 상하한 미포함
        @Builder.Default @JsonProperty("pric_cnd")       private String pricCnd      = "8";    // 1천원 이상
        @Builder.Default @JsonProperty("trde_prica_cnd") private String trdePricaCnd = "0";
        // stexTp 는 KiwoomApiRequest 부모에서 @Builder.Default "1"(KRX) 로 관리
    }

    /** ka10031 전일거래량상위 – qry_tp: 1:전일거래량 2:전일거래대금 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class PrevVolumeUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")   private String mrktTp   = "001";
        @Builder.Default @JsonProperty("qry_tp")    private String qryTp    = "1";   // 1:전일거래량 상위
        @Builder.Default @JsonProperty("rank_strt") private String rankStrt = "0";
        @Builder.Default @JsonProperty("rank_end")  private String rankEnd  = "100";
    }

    /** ka10035 외인연속순매매상위 – trde_tp: 2:연속순매수 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class FrgnContNettrdRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")    private String mrktTp   = "000";
        @Builder.Default @JsonProperty("trde_tp")    private String trdeTp   = "2";   // 2:연속순매수
        @Builder.Default @JsonProperty("base_dt_tp") private String baseDtTp = "1";   // 1:전일기준 (strategy_11 스펙 일치)
    }

    /** ka10032 거래대금상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class TrdePricaUpperRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")        private String mrktTp       = "001";
        @Builder.Default @JsonProperty("mang_stk_incls") private String mangStkIncls = "0";    // 관리종목 미포함
    }

    /** ka10016 신고저가요청 – ntl_tp: 1:신고가 2:신저가 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class NtlPricRequest extends KiwoomApiRequest {
        @Builder.Default @JsonProperty("mrkt_tp")           private String mrktTp         = "000";
        @Builder.Default @JsonProperty("ntl_tp")            private String ntlTp          = "1";     // 1:신고가
        @Builder.Default @JsonProperty("high_low_close_tp") private String highLowCloseTp = "1";     // 1:고저기준
        @Builder.Default @JsonProperty("stk_cnd")           private String stkCnd         = "1";     // 관리종목 제외
        @Builder.Default @JsonProperty("trde_qty_tp")       private String trdeQtyTp      = "00010"; // 만주 이상
        @Builder.Default @JsonProperty("crd_cnd")           private String crdCnd         = "0";
        @Builder.Default @JsonProperty("updown_incls")      private String updownIncls    = "0";
        @Builder.Default @JsonProperty("dt")                private String dt             = "250";   // 52주
    }

    /** ka10087 시간외단일가요청 – 장전 갭다운 경보용 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class OvtSigPricRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
    }
}
