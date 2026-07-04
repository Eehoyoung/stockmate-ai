package org.invest.apiorchestrator.service.strategy;

import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.invest.apiorchestrator.dto.res.KiwoomSupplementalResponses;
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
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S11FrgnContScannerTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Test
    void scansForeignContinuationWithInvestorFlowBonus() {
        KiwoomApiResponses.FrgnContNettrdUpperResponse cont = new KiwoomApiResponses.FrgnContNettrdUpperResponse();
        KiwoomApiResponses.FrgnContNettrdUpperResponse.FrgnContNettrdItem item =
                new KiwoomApiResponses.FrgnContNettrdUpperResponse.FrgnContNettrdItem();
        ReflectionTestUtils.setField(item, "stkCd", "005930");
        ReflectionTestUtils.setField(item, "stkNm", "Samsung");
        ReflectionTestUtils.setField(item, "dm1", "+10,000");
        ReflectionTestUtils.setField(item, "dm2", "+20,000");
        ReflectionTestUtils.setField(item, "dm3", "+30,000");
        ReflectionTestUtils.setField(item, "tot", "+60,000");
        ReflectionTestUtils.setField(item, "limitExhRt", "2.0");
        ReflectionTestUtils.setField(cont, "items", List.of(item));

        KiwoomSupplementalResponses.InvestorOrgTotalResponse investor =
                new KiwoomSupplementalResponses.InvestorOrgTotalResponse();
        KiwoomSupplementalResponses.InvestorOrgTotalResponse.InvestorOrgTotalItem flow =
                new KiwoomSupplementalResponses.InvestorOrgTotalResponse.InvestorOrgTotalItem();
        ReflectionTestUtils.setField(flow, "frgnrInvsr", "+50,000");
        ReflectionTestUtils.setField(flow, "orgn", "+30,000");
        ReflectionTestUtils.setField(flow, "indInvsr", "-80,000");
        ReflectionTestUtils.setField(investor, "items", List.of(flow));

        when(apiService.fetchKa10035(any())).thenReturn(cont);
        when(apiService.fetchKa10061(any())).thenReturn(investor);
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of(
                "vol_ratio", "2.0",
                "cur_prc", "10000"
        )));
        when(redisService.getAvgCntrStrength("005930", 5)).thenReturn(130.0);

        S11FrgnContScanner scanner = new S11FrgnContScanner(apiService, redisService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.market("101"));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.get(0);
        assertEquals("005930", signal.getStkCd());
        assertEquals(TradingSignal.StrategyType.S11_FRGN_CONT, signal.getStrategy());
        assertEquals(3, signal.getContinuousDays());
        assertEquals(2.0, signal.getVolRatio());
        assertEquals(130.0, signal.getCntrStrength());
        assertEquals(36.6, signal.getSignalScore());
        assertEquals("foreign_continuation_1min", signal.getEntryType());
        assertEquals(10900.0, signal.getTp1Price());
        assertEquals(11400.0, signal.getTp2Price());
        assertEquals(9500.0, signal.getSlPrice());
        assertEquals(50_000L, signal.getExtra().get("s11_foreign_amount"));
    }
}
