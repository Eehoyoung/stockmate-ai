package org.invest.apiorchestrator.util;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.invest.apiorchestrator.domain.TradingSignal;
import org.invest.apiorchestrator.dto.req.TradingSignalDto;
import org.invest.apiorchestrator.dto.res.KiwoomApiResponses;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class StockCodeNormalizerTests {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void normalizesKiwoomResponseStockCode() throws Exception {
        String json = """
                {
                  "return_code": "0",
                  "stk_cd": "039490_AL",
                  "stk_nm": "TEST"
                }
                """;

        KiwoomApiResponses.StkBasicInfoResponse response =
                objectMapper.readValue(json, KiwoomApiResponses.StkBasicInfoResponse.class);

        assertEquals("039490", response.getStkCd());
    }

    @Test
    void normalizesTradingSignalPayloadStockCode() {
        TradingSignalDto dto = TradingSignalDto.builder()
                .stkCd("039490_AL")
                .stkNm("TEST")
                .strategy(TradingSignal.StrategyType.S1_GAP_OPEN)
                .build();

        Map<String, Object> payload = dto.toQueuePayload(1L);

        assertEquals("039490", payload.get("stk_cd"));
    }
}
