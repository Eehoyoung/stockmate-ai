package org.invest.apiorchestrator.dto.req;

import lombok.Builder;
import lombok.Data;
@Data
@Builder
public class KiwoomStockRequest {
    private String mrkt_tp; // 0: 코스피, 10: 코스닥 등
}
