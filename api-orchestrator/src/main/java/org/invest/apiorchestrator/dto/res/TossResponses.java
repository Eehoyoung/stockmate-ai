package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 토스증권 Open API 응답 DTO 모음 (조회 전용 그룹만).
 * source of truth: docs/toss_invest_openapi_claude_required.md
 * 가격/거래량/거래대금 등 숫자 필드는 원본 문자열을 보존한다 (BigDecimal 변환은 서비스 계층에서).
 */
public class TossResponses {

    /** POST /oauth2/token — BFF 공통 envelope이 아닌 OAuth2 표준 형식 */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class OAuth2TokenResponse {
        @JsonProperty("access_token") private String accessToken;
        @JsonProperty("token_type")   private String tokenType;
        @JsonProperty("expires_in")   private Long expiresIn;
    }

    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class OAuth2ErrorResponse {
        private String error;
        @JsonProperty("error_description") private String errorDescription;
    }

    /** 공통 에러 envelope: {"error": {requestId, code, message, data}} */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ErrorResponse {
        private ErrorBody error;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class ErrorBody {
            @JsonProperty("requestId") private String requestId;
            private String code;
            private String message;
        }
    }

    /* ───────────── GET /api/v1/market-indicators/prices ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class MarketIndicatorPricesResponse {
        private List<PriceItem> result;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class PriceItem {
            private String symbol;
            private String timestamp;
            @JsonProperty("lastPrice") private String lastPrice;
        }
    }

    /* ───────────── GET /api/v1/market-indicators/{symbol}/candles ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class MarketIndicatorCandlesResponse {
        private CandleResult result;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class CandleResult {
            private List<CandleItem> candles;
            @JsonProperty("nextBefore") private String nextBefore;
        }

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class CandleItem {
            private String timestamp;
            @JsonProperty("openPrice")  private String openPrice;
            @JsonProperty("highPrice")  private String highPrice;
            @JsonProperty("lowPrice")   private String lowPrice;
            @JsonProperty("closePrice") private String closePrice;
            private String volume;
        }
    }

    /* ───────────── GET /api/v1/market-indicators/{symbol}/investor-trading ───────────── */
    @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
    public static class MarketIndicatorInvestorTradingResponse {
        private InvestorTradingResult result;

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InvestorTradingResult {
            @JsonProperty("nextUntil") private String nextUntil;
            private List<InvestorTradingRecord> records;
        }

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InvestorTradingRecord {
            private String date;
            @JsonProperty("updatedAt") private String updatedAt;
            private AmountPair individual;
            private AmountPair foreigner;
            private InstitutionAmount institution;
            @JsonProperty("otherCorporation") private AmountPair otherCorporation;
        }

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class AmountPair {
            @JsonProperty("buyAmount")  private String buyAmount;
            @JsonProperty("sellAmount") private String sellAmount;
        }

        @Getter @NoArgsConstructor @JsonIgnoreProperties(ignoreUnknown = true)
        public static class InstitutionAmount extends AmountPair {
            private Object breakdown; // 세부분류는 현재 사용하지 않음 — 원본 보존만
        }
    }
}
