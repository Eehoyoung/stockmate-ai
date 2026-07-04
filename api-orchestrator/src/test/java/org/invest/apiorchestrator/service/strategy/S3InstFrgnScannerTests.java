package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.service.KiwoomApiService;
import org.invest.apiorchestrator.service.RedisMarketDataService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S3InstFrgnScannerTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Test
    void scansOnlyContinuousInstitutionForeignBuyCandidates() {
        KiwoomApiResponses.IntradayInvestorResponse intraday = new KiwoomApiResponses.IntradayInvestorResponse();
        KiwoomApiResponses.IntradayInvestorResponse.InvestorItem included = new KiwoomApiResponses.IntradayInvestorResponse.InvestorItem();
        ReflectionTestUtils.setField(included, "stkCd", "005930");
        ReflectionTestUtils.setField(included, "stkNm", "Samsung");
        ReflectionTestUtils.setField(included, "netBuyAmt", "+2,000,000");
        KiwoomApiResponses.IntradayInvestorResponse.InvestorItem excluded = new KiwoomApiResponses.IntradayInvestorResponse.InvestorItem();
        ReflectionTestUtils.setField(excluded, "stkCd", "000660");
        ReflectionTestUtils.setField(excluded, "stkNm", "SK Hynix");
        ReflectionTestUtils.setField(excluded, "netBuyAmt", "+9,000,000");
        ReflectionTestUtils.setField(intraday, "items", List.of(included, excluded));

        KiwoomApiResponses.InstFrgnContinuousResponse continuous = new KiwoomApiResponses.InstFrgnContinuousResponse();
        KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem cont = new KiwoomApiResponses.InstFrgnContinuousResponse.ContTrdeItem();
        ReflectionTestUtils.setField(cont, "stkCd", "005930");
        ReflectionTestUtils.setField(cont, "contDtCnt", "3");
        ReflectionTestUtils.setField(continuous, "items", List.of(cont));

        when(apiService.post(
                eq("ka10063"),
                eq("/api/dostk/mrkcond"),
                any(),
                eq(KiwoomApiResponses.IntradayInvestorResponse.class)
        )).thenReturn(intraday);
        when(apiService.post(
                eq("ka10131"),
                eq("/api/dostk/frgnistt"),
                any(),
                eq(KiwoomApiResponses.InstFrgnContinuousResponse.class)
        )).thenReturn(continuous);
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of(
                "vol_ratio", "2.0",
                "cur_prc", "10000"
        )));

        S3InstFrgnScanner scanner = new S3InstFrgnScanner(apiService, redisService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.market("101"));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.get(0);
        assertEquals("005930", signal.getStkCd());
        assertEquals("Samsung", signal.getStkNm());
        assertEquals(TradingSignal.StrategyType.S3_INST_FRGN, signal.getStrategy());
        assertEquals(2_000_000L, signal.getNetBuyAmt());
        assertEquals(2.0, signal.getVolRatio());
        assertEquals(3, signal.getContinuousDays());
        assertEquals(12.0, signal.getSignalScore());
        assertEquals(10600.0, signal.getTp1Price());
        assertEquals(11000.0, signal.getTp2Price());
        assertEquals(9700.0, signal.getSlPrice());
    }
}
