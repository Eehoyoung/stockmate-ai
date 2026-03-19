package org.invest.apiorchestrator.dto.req;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
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
        @JsonProperty("trde_qty_tp") private String trdeQtyTp = "10";
        @JsonProperty("stk_cnd") private String stkCnd = "1";
        @JsonProperty("updown_incls") private String updownIncls = "0";
        @JsonProperty("crd_cnd") private String crdCnd = "0";
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
        @JsonProperty("mrkt_tp") private String mrktTp = "000";
        @JsonProperty("bf_mkrt_tp") private String bfMkrtTp = "1";
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("motn_tp") private String motnTp = "0";
        @JsonProperty("skip_stk") private String skipStk = "000000000";
        @JsonProperty("trde_qty_tp") private String trdeQtyTp = "0";
        @JsonProperty("min_trde_qty") private String minTrdeQty;
        @JsonProperty("max_trde_qty") private String maxTrdeQty;
        @JsonProperty("trde_prica_tp") private String trdePricaTp = "0";
    }

    /** ka10055 당일전일체결량 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class TodayPrevVolumeRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("tdy_pred") private String tdyPred = "1";  // 1:당일, 2:전일
    }

    /** ka10063 장중투자자별매매 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class IntradayInvestorRequest extends KiwoomApiRequest {
        @JsonProperty("mrkt_tp") private String mrktTp = "000";
        @JsonProperty("amt_qty_tp") private String amtQtyTp = "1";
        @JsonProperty("invsr") private String invsr = "6";         // 외국인
        @JsonProperty("frgn_all") private String frgnAll = "1";
        @JsonProperty("smtm_netprps_tp") private String smtmNetprpsTp = "1";
    }

    /** ka10065 장중투자자별매매상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class IntradayInvestorUpperRequest extends KiwoomApiRequest {
        @JsonProperty("trde_tp") private String trdeTp = "1";    // 1:순매수
        @JsonProperty("mrkt_tp") private String mrktTp = "000";
        @JsonProperty("orgn_tp") private String orgnTp = "9999"; // 기관계
    }

    /** ka10080 주식분봉차트 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class MinuteCandleRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("tic_scope") private String ticScope = "5";  // 5분봉
        @JsonProperty("upd_stkpc_tp") private String updStkpcTp = "1";
        @JsonProperty("base_dt") private String baseDt;
    }

    /** ka10081 주식일봉차트 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class DailyCandleRequest extends KiwoomApiRequest {
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("base_dt") private String baseDt;
        @JsonProperty("upd_stkpc_tp") private String updStkpcTp = "1";
    }

    /** ka10131 기관외국인연속매매현황 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class InstFrgnContinuousRequest extends KiwoomApiRequest {
        @JsonProperty("dt") private String dt = "3";             // 3일
        @JsonProperty("strt_dt") private String strtDt;
        @JsonProperty("end_dt") private String endDt;
        @JsonProperty("mrkt_tp") private String mrktTp = "001";
        @JsonProperty("netslmt_tp") private String netslmtTp = "2"; // 순매수
        @JsonProperty("stk_inds_tp") private String stkIndsTp = "0";
        @JsonProperty("amt_qty_tp") private String amtQtyTp = "0";
    }

    /** ka90001 테마그룹별 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ThemeGroupRequest extends KiwoomApiRequest {
        @JsonProperty("qry_tp") private String qryTp = "1";     // 테마검색
        @JsonProperty("stk_cd") private String stkCd;
        @JsonProperty("date_tp") private String dateTp = "1";   // 1일
        @JsonProperty("thema_nm") private String themaNm;
        @JsonProperty("flu_pl_amt_tp") private String fluPlAmtTp = "1"; // 상위기간수익률
    }

    /** ka90002 테마구성종목 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ThemeStockRequest extends KiwoomApiRequest {
        @JsonProperty("date_tp") private String dateTp = "1";
        @JsonProperty("thema_grp_cd") private String themaGrpCd;
    }

    /** ka90003 프로그램순매수상위50 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ProgramNetBuyRequest extends KiwoomApiRequest {
        @JsonProperty("trde_upper_tp") private String trdeUpperTp = "2"; // 순매수상위
        @JsonProperty("amt_qty_tp") private String amtQtyTp = "1";
        @JsonProperty("mrkt_tp") private String mrktTp;
    }

    /** ka90009 외국인기관매매상위 */
    @Getter @SuperBuilder @NoArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class FrgnInstUpperRequest extends KiwoomApiRequest {
        @JsonProperty("mrkt_tp") private String mrktTp = "000";
        @JsonProperty("amt_qty_tp") private String amtQtyTp = "1";
        @JsonProperty("qry_dt_tp") private String qryDtTp = "0";
        @JsonProperty("date") private String date;
    }
}
