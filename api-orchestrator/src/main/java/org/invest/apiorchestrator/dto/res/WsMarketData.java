package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * WebSocket 실시간 시세 데이터 DTO 모음
 */
public class WsMarketData {

    /** 0B 주식체결 */
    @Getter @Setter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class StockTick {
        @JsonProperty("stk_cd")        private String stkCd;
        @JsonProperty("cntr_tm")       private String cntrTm;
        @JsonProperty("cur_prc")       private String curPrc;
        @JsonProperty("pred_pre")      private String predPre;
        @JsonProperty("flu_rt")        private String fluRt;
        @JsonProperty("cntr_qty")      private String cntrQty;
        @JsonProperty("acc_trde_qty")  private String accTrdeQty;
        @JsonProperty("acc_trde_prica")private String accTrdePrica;
        @JsonProperty("cntr_str")      private String cntrStr;       // 체결강도

        public double getCurPrcDouble()    { return parseDouble(curPrc); }
        public double getFluRtDouble()     { return parseDouble(fluRt); }
        public long   getAccTrdeQtyLong()  { return parseLong(accTrdeQty); }
        public double getCntrStrDouble()   { return parseDouble(cntrStr); }
        private double parseDouble(String v) { try { return v == null ? 0 : Double.parseDouble(v.replace(",","").replace("+","")); } catch (Exception e) { return 0; } }
        private long   parseLong(String v)   { try { return v == null ? 0 : Long.parseLong(v.replace(",","").replace("+","")); }   catch (Exception e) { return 0; } }
    }

    /** 0D 주식호가잔량 */
    @Getter @Setter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class StockHoga {
        @JsonProperty("stk_cd")             private String stkCd;
        @JsonProperty("bid_req_base_tm")    private String bidReqBaseTm;
        // 매수 호가 1~5
        @JsonProperty("sel_bid_pric_1")     private String selBidPric1;
        @JsonProperty("sel_bid_pric_2")     private String selBidPric2;
        @JsonProperty("sel_bid_pric_3")     private String selBidPric3;
        @JsonProperty("sel_bid_pric_4")     private String selBidPric4;
        @JsonProperty("sel_bid_pric_5")     private String selBidPric5;
        @JsonProperty("sel_bid_req_1")      private String selBidReq1;
        @JsonProperty("sel_bid_req_2")      private String selBidReq2;
        @JsonProperty("sel_bid_req_3")      private String selBidReq3;
        @JsonProperty("sel_bid_req_4")      private String selBidReq4;
        @JsonProperty("sel_bid_req_5")      private String selBidReq5;
        // 매도 호가 1~5
        @JsonProperty("buy_bid_pric_1")     private String buyBidPric1;
        @JsonProperty("buy_bid_pric_2")     private String buyBidPric2;
        @JsonProperty("buy_bid_pric_3")     private String buyBidPric3;
        @JsonProperty("buy_bid_pric_4")     private String buyBidPric4;
        @JsonProperty("buy_bid_pric_5")     private String buyBidPric5;
        @JsonProperty("buy_bid_req_1")      private String buyBidReq1;
        @JsonProperty("buy_bid_req_2")      private String buyBidReq2;
        @JsonProperty("buy_bid_req_3")      private String buyBidReq3;
        @JsonProperty("buy_bid_req_4")      private String buyBidReq4;
        @JsonProperty("buy_bid_req_5")      private String buyBidReq5;
        // 잔량 합계
        @JsonProperty("total_sel_bid_req")  private String totalSelBidReq;  // 매도 총잔량
        @JsonProperty("total_buy_bid_req")  private String totalBuyBidReq;  // 매수 총잔량

        public double getBidRatio() {
            double bid = parseLong(totalBuyBidReq);
            double ask = parseLong(totalSelBidReq);
            return ask > 0 ? bid / ask : 0;
        }
        private long parseLong(String v) {
            try { return v == null ? 0 : Long.parseLong(v.replace(",","").replace("+","")); }
            catch (Exception e) { return 0; }
        }
    }

    /** 0H 주식예상체결 */
    @Getter @Setter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ExpectedExecution {
        @JsonProperty("stk_cd")           private String stkCd;
        @JsonProperty("exp_cntr_pric")    private String expCntrPric;     // 예상체결가
        @JsonProperty("exp_pred_pre")     private String expPredPre;      // 예상전일대비
        @JsonProperty("exp_flu_rt")       private String expFluRt;        // 예상등락율
        @JsonProperty("exp_cntr_qty")     private String expCntrQty;      // 예상체결수량
        @JsonProperty("pred_pre_pric")    private String predPrePric;     // 전일종가
        @JsonProperty("exp_cntr_tm")      private String expCntrTm;       // 예상체결시간

        public double getExpCntrPricDouble() { return parseDouble(expCntrPric); }
        public double getPredPrePricDouble() { return parseDouble(predPrePric); }
        public double getExpFluRtDouble()    { return parseDouble(expFluRt); }

        public double calcGapPct() {
            double prev = getPredPrePricDouble();
            double exp  = getExpCntrPricDouble();
            return prev > 0 ? (exp - prev) / prev * 100 : 0;
        }
        private double parseDouble(String v) {
            try { return v == null ? 0 : Double.parseDouble(v.replace(",","").replace("+","")); }
            catch (Exception e) { return 0; }
        }
    }

    /** 1h VI발동/해제 */
    @Getter @Setter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ViActivation {
        @JsonProperty("stk_cd")        private String stkCd;
        @JsonProperty("stk_nm")        private String stkNm;
        @JsonProperty("vi_type")       private String viType;    // 1:정적, 2:동적, 3:동적+정적
        @JsonProperty("vi_stat")       private String viStat;    // 1:발동, 2:해제
        @JsonProperty("vi_pric")       private String viPric;
        @JsonProperty("ref_pric")      private String refPric;
        @JsonProperty("acc_trde_qty")  private String accTrdeQty;
        @JsonProperty("vi_upper")      private String viUpper;
        @JsonProperty("vi_lower")      private String viLower;
        @JsonProperty("mrkt_cls")      private String mrktCls;   // 시장구분

        public boolean isActivation() { return "1".equals(viStat); }
        public boolean isRelease()    { return "2".equals(viStat); }
        // 1225 필드: "정적"/"동적"/"동적+정적" 문자열로 수신됨
        public boolean isDynamic()    { return "동적".equals(viType) || "동적+정적".equals(viType); }
        public double  getViPricDouble() {
            try { return viPric == null ? 0 : Double.parseDouble(viPric.replace(",","")); }
            catch (Exception e) { return 0; }
        }
    }

    /** WebSocket 공통 메시지 래퍼 */
    @Getter @Setter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class WsMessage {
        @JsonProperty("trnm")       private String trnm;
        @JsonProperty("grp_no")     private String grpNo;
        @JsonProperty("return_code")private String returnCode;
        @JsonProperty("return_msg") private String returnMsg;
        @JsonProperty("data")       private Object data;

        public boolean isSuccess() { return "0".equals(returnCode); }
    }
}
