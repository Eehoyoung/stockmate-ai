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
        /**
         * false 로 설정 시 Java WS 클라이언트 비활성화.
         * Python websocket-listener 와 동일 토큰으로 동시 연결하면
         * Kiwoom 이 선행 연결을 강제 종료하므로, 두 서비스 중 하나만 true 로 설정할 것.
         */
        private boolean enabled = true;
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
        /** 일일 전체 신호 상한 (Feature 4) */
        private int maxDailySignals = 30;
        /** 동일 섹터 1시간 내 과열 임계값 (Feature 4) */
        private int sectorOverheatThreshold = 3;
        /** 종목 크로스-전략 쿨다운 분 (Feature 4) */
        private int stockCooldownMinutes = 30;
    }
}
