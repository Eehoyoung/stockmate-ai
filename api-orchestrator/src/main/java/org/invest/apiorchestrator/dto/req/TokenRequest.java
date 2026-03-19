package org.invest.apiorchestrator.dto.req;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
public class TokenRequest {

    @JsonProperty("grant_type")
    @Builder.Default
    private String grantType = "client_credentials";

    @JsonProperty("appkey")
    private String appKey;

    @JsonProperty("secretkey")
    private String secretKey;
}
