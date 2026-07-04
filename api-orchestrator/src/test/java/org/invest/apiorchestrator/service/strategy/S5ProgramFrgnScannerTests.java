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
class S5ProgramFrgnScannerTests {

    @Mock
    KiwoomApiService apiService;

    @Mock
    RedisMarketDataService redisService;

    @Test
    void scansOnlyProgramNetBuyStocksAlsoInForeignInstitutionUpperList() {
        KiwoomApiResponses.ProgramNetBuyResponse program = new KiwoomApiResponses.ProgramNetBuyResponse();
        KiwoomApiResponses.ProgramNetBuyResponse.ProgramItem included = new KiwoomApiResponses.ProgramNetBuyResponse.ProgramItem();
        ReflectionTestUtils.setField(included, "stkCd", "005930");
        ReflectionTestUtils.setField(included, "stkNm", "Samsung");
        ReflectionTestUtils.setField(included, "netBuyAmt", "+3,500,000");
        KiwoomApiResponses.ProgramNetBuyResponse.ProgramItem excluded = new KiwoomApiResponses.ProgramNetBuyResponse.ProgramItem();
        ReflectionTestUtils.setField(excluded, "stkCd", "000660");
        ReflectionTestUtils.setField(excluded, "stkNm", "SK Hynix");
        ReflectionTestUtils.setField(excluded, "netBuyAmt", "+9,000,000");
        ReflectionTestUtils.setField(program, "items", List.of(included, excluded));

        KiwoomApiResponses.FrgnInstUpperResponse frgn = new KiwoomApiResponses.FrgnInstUpperResponse();
        KiwoomApiResponses.FrgnInstUpperResponse.FrgnInstItem frgnItem = new KiwoomApiResponses.FrgnInstUpperResponse.FrgnInstItem();
        ReflectionTestUtils.setField(frgnItem, "stkCd", "005930");
        ReflectionTestUtils.setField(frgn, "items", List.of(frgnItem));

        when(apiService.post(
                eq("ka90003"),
                eq("/api/dostk/stkinfo"),
                any(),
                eq(KiwoomApiResponses.ProgramNetBuyResponse.class)
        )).thenReturn(program);
        when(apiService.post(
                eq("ka90009"),
                eq("/api/dostk/rkinfo"),
                any(),
                eq(KiwoomApiResponses.FrgnInstUpperResponse.class)
        )).thenReturn(frgn);
        when(redisService.getTickData("005930")).thenReturn(Optional.of(Map.of("cur_prc", "10000")));

        S5ProgramFrgnScanner scanner = new S5ProgramFrgnScanner(apiService, redisService);
        List<TradingSignalDto> results = scanner.scan(StrategyScanContext.market("101"));

        assertEquals(1, results.size());
        TradingSignalDto signal = results.get(0);
        assertEquals("005930", signal.getStkCd());
        assertEquals("Samsung", signal.getStkNm());
        assertEquals(TradingSignal.StrategyType.S5_PROG_FRGN, signal.getStrategy());
        assertEquals(3_500_000L, signal.getNetBuyAmt());
        assertEquals(3.5, signal.getSignalScore());
        assertEquals("program_frgn_1min", signal.getEntryType());
        assertEquals(10600.0, signal.getTp1Price());
        assertEquals(10900.0, signal.getTp2Price());
        assertEquals(9700.0, signal.getSlPrice());
    }
}
