package org.invest.apiorchestrator.dto.res;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@NoArgsConstructor
public class TokenResponse {

    @JsonProperty("access_token")
    private String accessToken;

    @JsonProperty("token_type")
    private String tokenType;

    @JsonProperty("expires_in")
    private Long expiresIn;

    @JsonProperty("return_code")
    private String returnCode;

    @JsonProperty("return_msg")
    private String returnMsg;

    public boolean isSuccess() {
        return "0".equals(returnCode) && accessToken != null && !accessToken.isBlank();
    }
}
