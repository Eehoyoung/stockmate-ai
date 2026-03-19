package org.invest.apiorchestrator.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class KiwoomStockItem {
    private String code;      // 종목코드
    private String name;      // 종목명
    private String marketName; // 시장명
    private String lastPrice;  // 전일종가
}
