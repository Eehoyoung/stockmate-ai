package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.invest.apiorchestrator.dto.req.StrategyRequests;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class KiwoomResponseContractTests {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void serializesOfficialEtfEtnExclusionsForCandidateRankingRequests() {
        assertEquals("16", objectMapper.valueToTree(
                StrategyRequests.ExpCntrFluRtUpperRequest.builder().build())
                .get("stk_cnd").asText());
        assertEquals("20", objectMapper.valueToTree(
                StrategyRequests.TrdeQtySdninRequest.builder().build())
                .get("stk_cnd").asText());
        assertEquals("16", objectMapper.valueToTree(
                StrategyRequests.FluRtUpperRequest.builder().build())
                .get("stk_cnd").asText());
    }

    @Test
    void serializesAndDeserializesKa10054OfficialContract() throws Exception {
        var request = StrategyRequests.ViActivationRequest.builder()
                .mrktTp("001").stkCd("005930").build();
        var requestJson = objectMapper.valueToTree(request);
        assertEquals("0", requestJson.get("bf_mkrt_tp").asText());
        assertEquals("0", requestJson.get("min_trde_qty").asText());
        assertEquals("0", requestJson.get("max_trde_qty").asText());
        assertEquals("0", requestJson.get("min_trde_prica").asText());
        assertEquals("0", requestJson.get("max_trde_prica").asText());
        assertEquals("0", requestJson.get("motn_drc").asText());

        String json = """
                {"motn_stk":[{"stk_cd":"005930","stk_nm":"Samsung",
                "acc_trde_qty":"1105968","motn_pric":"67000",
                "dynm_dispty_rt":"+9.30","trde_cntr_proc_time":"172311",
                "virelis_time":"172511","viaplc_tp":"동적",
                "dynm_stdpc":"61300","static_stdpc":"0",
                "static_dispty_rt":"0.00","open_pric_pre_flu_rt":"+16.93",
                "vimotn_cnt":"23","stex_tp":"NXT"}],"return_code":0}
                """;
        var response = objectMapper.readValue(json, KiwoomApiResponses.ViActivationResponse.class);
        var item = response.getItems().getFirst();
        assertEquals("005930", item.getStkCd());
        assertEquals("67000", item.getActivationPrice());
        assertEquals("172511", item.getReleaseTime());
        assertEquals("61300", item.getDynamicReferencePrice());
        assertEquals("23", item.getActivationCount());
    }

    @Test
    void serializesAndDeserializesKa10064OfficialContract() throws Exception {
        var request = StrategyRequests.IntradayInvestorChartRequest.builder()
                .mrktTp("000")
                .stkCd("005930")
                .build();
        var requestJson = objectMapper.valueToTree(request);

        assertEquals("000", requestJson.get("mrkt_tp").asText());
        assertEquals("1", requestJson.get("amt_qty_tp").asText());
        assertEquals("0", requestJson.get("trde_tp").asText());
        assertEquals("005930", requestJson.get("stk_cd").asText());

        String json = """
                {"opmr_invsr_trde_chart":[{"tm":"095200",
                "frgnr_invsr":"-68","orgn":"-20","invtrt":"-5",
                "insrnc":"1","bank":"2","penfnd_etc":"3",
                "etc_corp":"4","natn":"5"}],"return_code":0}
                """;
        var response = objectMapper.readValue(
                json, KiwoomApiResponses.IntradayInvestorChartResponse.class);
        var item = response.getItems().getFirst();

        assertEquals("095200", item.getTime());
        assertEquals("-68", item.getForeignInvestor());
        assertEquals("-20", item.getInstitution());
        assertEquals("-5", item.getInvestmentTrust());
        assertEquals("3", item.getPensionFundEtc());
    }

    @Test
    void deserializesKa10046StrengthWindows() throws Exception {
        String json = """
                {"cntr_str_tm":[{"cntr_tm":"163713","cntr_str":"172.01",
                "cntr_str_5min":"171.50","cntr_str_20min":"168.20",
                "cntr_str_60min":"160.10","acc_trde_qty":"113636",
                "acc_trde_prica":"14449","stex_tp":"KRX"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomApiResponses.CntrStrengthTimeResponse.class);
        var item = response.getCntrStrTm().getFirst();

        assertEquals("163713", item.getCntrTm());
        assertEquals("171.50", item.getCntrStr5min());
        assertEquals("168.20", item.getCntrStr20min());
        assertEquals("160.10", item.getCntrStr60min());
        assertEquals("113636", item.getAccTrdeQty());
    }

    @Test
    void deserializesKa10063IntradayInvestorFields() throws Exception {
        String json = """
                {"opmr_invsr_trde":[{"stk_cd":"005930","stk_nm":"삼성전자",
                "acc_trde_qty":"123456","netprps_amt":"+789","netprps_qty":"+1083000",
                "prev_netprps_amt":"+700","netprps_amt_irds":"+89"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomApiResponses.IntradayInvestorResponse.class);
        var item = response.getItems().getFirst();

        assertEquals("005930", item.getStkCd());
        assertEquals("123456", item.getTrdeQty());
        assertEquals("+789", item.getNetBuyAmt());
        assertEquals("+1083000", item.getNetBuyQty());
        assertEquals("+89", item.getNetBuyAmtChange());
    }

    @Test
    void deserializesKa10131ContinuousInvestorFields() throws Exception {
        String json = """
                {"orgn_frgnr_cont_trde_prst":[{"stk_cd":"005930",
                "tot_cont_netprps_dys":"+5","tot_cont_nettrde_qty":"+174",
                "tot_cont_netprps_amt":"+48","orgn_cont_netprps_dys":"+3",
                "frgnr_cont_netprps_dys":"+2"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomApiResponses.InstFrgnContinuousResponse.class);
        var item = response.getItems().getFirst();

        assertEquals("+5", item.getContDtCnt());
        assertEquals("+174", item.getNetBuyQty());
        assertEquals("+48", item.getNetBuyAmt());
        assertEquals("+3", item.getOrgnContNetBuyDays());
        assertEquals("+2", item.getForeignContNetBuyDays());
    }

    @Test
    void deserializesKa90003ProgramRankingFields() throws Exception {
        String json = """
                {"prm_netprps_upper_50":[{"stk_cd":"005930","stk_nm":"삼성전자",
                "acc_trde_qty":"10000","prm_sell_amt":"120","prm_buy_amt":"420",
                "prm_netprps_amt":"+300"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomApiResponses.ProgramNetBuyResponse.class);
        var item = response.getItems().getFirst();

        assertEquals("005930", item.getStkCd());
        assertEquals("+300", item.getNetBuyAmt());
        assertEquals("10000", item.getAccTrdeQty());
    }

    @Test
    void deserializesKa90009SeparateForeignAndInstitutionRankings() throws Exception {
        String json = """
                {"frgnr_orgn_trde_upper":[{"for_netprps_stk_cd":"005930",
                "for_netprps_stk_nm":"삼성전자","for_netprps_amt":"+130811",
                "for_netprps_qty":"+50312","orgn_netprps_stk_cd":"000660",
                "orgn_netprps_stk_nm":"SK하이닉스","orgn_netprps_amt":"+99800",
                "orgn_netprps_qty":"+12000"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomApiResponses.FrgnInstUpperResponse.class);
        var item = response.getItems().getFirst();

        assertEquals("005930", item.getForNetprpsStkCd());
        assertEquals("000660", item.getOrgnNetprpsStkCd());
        assertEquals("+130811", item.getForBuyAmt());
        assertEquals("+99800", item.getOrgBuyAmt());
        assertEquals("005930", item.getStkCd());
    }

    @Test
    void deserializesKa90008StockProgramTrendFields() throws Exception {
        String json = """
                {"stk_tm_prm_trde_trnsn":[{"tm":"153029","cur_prc":"+245500",
                "prm_netprps_amt":"-3472","prm_netprps_amt_irds":"+771",
                "prm_netprps_qty":"-14240","prm_netprps_qty_irds":"+3142"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomSupplementalResponses.StockProgramTrendResponse.class);
        var item = response.getItems().getFirst();

        assertEquals("153029", item.getCntrTm());
        assertEquals("-3472", item.getProgramNetBuyAmt());
        assertEquals("-14240", item.getProgramNetBuyQty());
        assertEquals(item.getProgramNetBuyAmt(), item.getDfrtTrdeNetprps());
    }

    @Test
    void deserializesKa90013DailyProgramTrendFields() throws Exception {
        String json = """
                {"stk_daly_prm_trde_trnsn":[{"dt":"20241125",
                "prm_netprps_amt":"+20","prm_netprps_qty":"+50"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomSupplementalResponses.StockDailyProgramTrendResponse.class);
        var item = response.getItems().getFirst();

        assertEquals("20241125", item.getDt());
        assertEquals("+20", item.getProgramNetBuyAmt());
        assertEquals("+50", item.getProgramNetBuyQty());
    }

    @Test
    void deserializesKa10081DateFromDt() throws Exception {
        String json = """
                {"stk_cd":"005930","stk_dt_pole_chart_qry":[{"dt":"20250908",
                "cur_prc":"+70000","trde_prica":"648525"}],"return_code":0}
                """;

        var response = objectMapper.readValue(json, KiwoomApiResponses.DailyCandleResponse.class);

        assertNotNull(response.getCandles());
        assertEquals("20250908", response.getCandles().getFirst().getDate());
    }
}
