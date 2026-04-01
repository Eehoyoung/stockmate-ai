package org.invest.apiorchestrator.dto.req;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.experimental.SuperBuilder;

@Getter
@SuperBuilder
@NoArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public abstract class KiwoomApiRequest {

    /** @Builder.Default: @SuperBuilder 빌더 경로에서도 필드 초기값("1")이 적용됨 */
    @Builder.Default
    @JsonProperty("stex_tp")
    protected String stexTp = "1";  // 기본: KRX

    @JsonProperty("cont_yn")
    protected String contYn;

    @JsonProperty("next_key")
    protected String nextKey;
}
