package org.invest.apiorchestrator.dto.res;

import lombok.Data;
import org.invest.apiorchestrator.dto.KiwoomStockItem;

import java.util.List;

@Data
public class KiwoomStockResponse {
    private String return_code;
    private String return_msg;
    private List<KiwoomStockItem> list;
}
