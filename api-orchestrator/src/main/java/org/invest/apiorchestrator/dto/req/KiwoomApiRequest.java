package org.invest.apiorchestrator.dto.req;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.experimental.SuperBuilder;

@Getter
@SuperBuilder
@NoArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public abstract class KiwoomApiRequest {

    @JsonProperty("stex_tp")
    protected String stexTp = "1";  // 기본: KRX

    @JsonProperty("cont_yn")
    protected String contYn;

    @JsonProperty("next_key")
    protected String nextKey;
}
