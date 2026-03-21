package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor
public class TokenResponse {

    @JsonProperty("token")
    private String accessToken;

    @JsonProperty("token_type")
    private String tokenType;

    @JsonProperty("expires_dt")
    private String expiresDt;

    @JsonProperty("return_code")
    private Integer returnCode;

    @JsonProperty("return_msg")
    private String returnMsg;

    public boolean isSuccess() {
        return Integer.valueOf(0).equals(returnCode) && accessToken != null && !accessToken.isBlank();
    }
}
