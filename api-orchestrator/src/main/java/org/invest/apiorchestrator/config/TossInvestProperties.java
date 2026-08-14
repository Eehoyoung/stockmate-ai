package org.invest.apiorchestrator.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 토스증권 Open API 설정.
 * docs/toss_invest_openapi_claude_required.md 기준 조회 전용(Market Data / Stock Info /
 * Market Info / Ranking / Market Indicators) 연동만 다룬다. Account/Asset/Order/
 * Conditional Order 는 이 프로젝트에서 구현하지 않는다.
 */
@Data
@Component
@ConfigurationProperties(prefix = "toss")
public class TossInvestProperties {

    /** false 이면 토스 클라이언트/스케줄러 전체가 no-op — client_id/secret 미설정 시 안전 기본값 */
    private boolean enabled = false;

    private String baseUrl = "https://openapi.tossinvest.com";
    private String clientId;
    private String clientSecret;
}
