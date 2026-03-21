package org.invest.apiorchestrator.config;

import lombok.Data;
import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "kiwoom")
public class KiwoomProperties {

    /** 실전/모의 환경 구분: real | mock */
    private String mode = "mock";

    private Api api = new Api();
    private Websocket websocket = new Websocket();
    private Trading trading = new Trading();

    @Getter
    @Setter
    public static class Api {
        private String baseUrl;
        private String wsUrl;
        private String appKey;
        private String appSecret;
        private int tokenTtlMinutes = 1420;
    }

    @Getter
    @Setter
    public static class Websocket {
        private long reconnectDelayMs = 3000;
        private int maxReconnectAttempts = 10;
        private int pingIntervalSeconds = 30;
    }

    @Getter
    @Setter
    public static class Trading {
        private String marketOpen = "09:00";
        private String marketClose = "15:30";
        private String preMarketStart = "07:30";
        private double commonStopLossPct = -2.0;
        private double commonTargetPct = 3.5;
        private int maxSignalsPerStrategy = 5;
        private long signalTtlSeconds = 3600;
    }
}
