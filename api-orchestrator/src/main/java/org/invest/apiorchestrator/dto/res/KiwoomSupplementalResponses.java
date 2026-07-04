package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.invest.apiorchestrator.util.StockCodeDeserializer;

import java.util.List;

public class KiwoomSupplementalResponses {

    @Getter
    @NoArgsConstructor
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class BaseResponse {
        @JsonProperty("return_code") private String returnCode;
        @JsonProperty("return_msg") private String returnMsg;
        @JsonProperty("cont_yn") private String contYn;
        @JsonProperty("next_key") private String nextKey;

        public boolean isSuccess() {
            return "0".equals(returnCode);
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class TodayUpperExitResponse extends BaseResponse {
        @JsonProperty("tdy_upper_scesn_ori") private List<TodayUpperExitItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class TodayUpperExitItem {
            @JsonProperty("sel_scesn_tm") private String selScesnTm;
            @JsonProperty("sell_qty") private String sellQty;
            @JsonProperty("sel_upper_scesn_ori") private String selUpperScesnOri;
            @JsonProperty("buy_scesn_tm") private String buyScesnTm;
            @JsonProperty("buy_qty") private String buyQty;
            @JsonProperty("buy_upper_scesn_ori") private String buyUpperScesnOri;
            @JsonProperty("qry_dt") private String qryDt;
            @JsonProperty("qry_tm") private String qryTm;
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class InvestorOrgTotalResponse extends BaseResponse {
        @JsonProperty("stk_invsr_orgn_tot") private List<InvestorOrgTotalItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InvestorOrgTotalItem {
            @JsonProperty("ind_invsr") private String indInvsr;
            @JsonProperty("frgnr_invsr") private String frgnrInvsr;
            @JsonProperty("orgn") private String orgn;
            @JsonProperty("fnnc_invt") private String fnncInvt;
            @JsonProperty("insrnc") private String insrnc;
            @JsonProperty("invtrt") private String invtrt;
            @JsonProperty("etc_fnnc") private String etcFnnc;
            @JsonProperty("bank") private String bank;
            @JsonProperty("penfnd_etc") private String penfndEtc;
            @JsonProperty("samo_fund") private String samoFund;
            @JsonProperty("natn") private String natn;
            @JsonProperty("etc_corp") private String etcCorp;
            @JsonProperty("natfor") private String natfor;
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ProgramTrendResponse extends BaseResponse {
        @JsonProperty("prm_trde_trnsn") private List<ProgramTrendItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ProgramTrendItem {
            @JsonProperty("cntr_tm") private String cntrTm;
            @JsonProperty("dfrt_trde_sel") private String dfrtTrdeSel;
            @JsonProperty("dfrt_trde_buy") private String dfrtTrdeBuy;
            @JsonProperty("dfrt_trde_netprps") private String dfrtTrdeNetprps;
            @JsonProperty("ndiffpro_trde_sel") private String ndiffproTrdeSel;
            @JsonProperty("ndiffpro_trde_buy") private String ndiffproTrdeBuy;
            @JsonProperty("ndiffpro_trde_netprps") private String ndiffproTrdeNetprps;
            @JsonProperty("dfrt_trde_sell_qty") private String dfrtTrdeSellQty;
            @JsonProperty("dfrt_trde_buy_qty") private String dfrtTrdeBuyQty;
            @JsonProperty("dfrt_trde_netprps_qty") private String dfrtTrdeNetprpsQty;
            @JsonProperty("ndiffpro_trde_sell_qty") private String ndiffproTrdeSellQty;
            @JsonProperty("ndiffpro_trde_buy_qty") private String ndiffproTrdeBuyQty;
            @JsonProperty("ndiffpro_trde_netprps_qty") private String ndiffproTrdeNetprpsQty;
            @JsonProperty("all_sel") private String allSel;
            @JsonProperty("all_buy") private String allBuy;
            @JsonProperty("all_netprps") private String allNetprps;
            @JsonProperty("kospi200") private String kospi200;
            @JsonProperty("basis") private String basis;
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class StockProgramTrendResponse extends BaseResponse {
        @JsonProperty("stk_tm_prm_trde_trn") private List<StockProgramTrendItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class StockProgramTrendItem {
            @JsonProperty("cntr_tm") private String cntrTm;
            @JsonProperty("dfrt_trde_sel") private String dfrtTrdeSel;
            @JsonProperty("dfrt_trde_buy") private String dfrtTrdeBuy;
            @JsonProperty("dfrt_trde_netprps") private String dfrtTrdeNetprps;
            @JsonProperty("dfrt_trde_sell_qty") private String dfrtTrdeSellQty;
            @JsonProperty("dfrt_trde_buy_qty") private String dfrtTrdeBuyQty;
            @JsonProperty("dfrt_trde_netprps_qty") private String dfrtTrdeNetprpsQty;
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class StockDailyProgramTrendResponse extends BaseResponse {
        @JsonProperty("stk_daly_prm_trde_tr") private List<StockDailyProgramTrendItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class StockDailyProgramTrendItem {
            @JsonProperty("dt") private String dt;
            @JsonProperty("dfrt_trde_sel") private String dfrtTrdeSel;
            @JsonProperty("dfrt_trde_buy") private String dfrtTrdeBuy;
            @JsonProperty("dfrt_trde_netprps") private String dfrtTrdeNetprps;
            @JsonProperty("dfrt_trde_sell_qty") private String dfrtTrdeSellQty;
            @JsonProperty("dfrt_trde_buy_qty") private String dfrtTrdeBuyQty;
            @JsonProperty("dfrt_trde_netprps_qty") private String dfrtTrdeNetprpsQty;
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class SectorInvestorNetBuyResponse extends BaseResponse {
        @JsonProperty("inds_netprps") private List<SectorInvestorNetBuyItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class SectorInvestorNetBuyItem {
            @JsonProperty("inds_cd") private String indsCd;
            @JsonProperty("inds_nm") private String indsNm;
            @JsonProperty("cur_prc") private String curPrc;
            @JsonProperty("flu_rt") private String fluRt;
            @JsonProperty("orgn_netprps") private String orgnNetprps;
            @JsonProperty("for_netprps") private String forNetprps;
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class SectorCurrentPriceResponse extends BaseResponse {
        @JsonProperty("inds_cd") private String indsCd;
        @JsonProperty("inds_nm") private String indsNm;
        @JsonProperty("cur_prc") private String curPrc;
        @JsonProperty("flu_rt") private String fluRt;
        @JsonProperty("trde_qty") private String trdeQty;
        @JsonProperty("trde_prica") private String trdePrica;
        @JsonProperty("up_stk_num") private String upStkNum;
        @JsonProperty("down_stk_num") private String downStkNum;
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class SectorStocksResponse extends BaseResponse {
        @JsonProperty("inds_stkpc") private List<SectorStockItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class SectorStockItem {
            @JsonProperty("stk_cd") @JsonDeserialize(using = StockCodeDeserializer.class) private String stkCd;
            @JsonProperty("stk_nm") private String stkNm;
            @JsonProperty("cur_prc") private String curPrc;
            @JsonProperty("flu_rt") private String fluRt;
            @JsonProperty("trde_qty") private String trdeQty;
            @JsonProperty("trde_prica") private String trdePrica;
        }
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class AllSectorIndexResponse extends BaseResponse {
        @JsonProperty("all_inds_idex") private List<AllSectorIndexItem> items;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class AllSectorIndexItem {
            @JsonProperty("stk_cd") private String stkCd;
            @JsonProperty("stk_nm") private String stkNm;
            @JsonProperty("cur_prc") private String curPrc;
            @JsonProperty("flu_rt") private String fluRt;
            @JsonProperty("trde_qty") private String trdeQty;
            @JsonProperty("trde_prica") private String trdePrica;
            @JsonProperty("upl") private String upl;
            @JsonProperty("rising") private String rising;
            @JsonProperty("stdns") private String stdns;
            @JsonProperty("fall") private String fall;
            @JsonProperty("lst") private String lst;
            @JsonProperty("flo_stk_num") private String floStkNum;
        }
    }
}
