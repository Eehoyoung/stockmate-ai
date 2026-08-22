package org.invest.apiorchestrator.domain;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;

class StrategyFamilyLineageContractTests {

    @Test
    void apiSerializationPreservesSharedQueueDbTelegramLineageFixture() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JsonNode fixture = mapper.readTree(Files.readString(
                Path.of("..", "test-fixtures", "strategy_family_lineage.json")));
        TradingSignal signal = TradingSignal.builder()
                .stkCd(fixture.get("stk_cd").asText())
                .strategy(TradingSignal.StrategyType.valueOf(fixture.get("strategy").asText()))
                .strategyFamily(fixture.get("strategy_family").asText())
                .strategyFamilyName(fixture.get("strategy_family_name").asText())
                .primarySetupId(fixture.get("primary_setup_id").asText())
                .matchedSetupIds(fixture.get("matched_setup_ids").toString())
                .confirmedByFamilyIds(fixture.get("confirmed_by_family_ids").toString())
                .familyPolicyVersion(fixture.get("family_policy_version").asText())
                .setupVersion(fixture.get("setup_version").asText())
                .ruleScoreVersion(fixture.get("rule_score_version").asText())
                .promptVersion(fixture.get("prompt_version").asText())
                .dataSource(fixture.get("data_source").toString())
                .sourceTimestamp(fixture.get("source_timestamp").toString())
                .sourceAgeMs(fixture.get("source_age_ms").toString())
                .fallbackReason(fixture.get("fallback_reason").toString())
                .build();

        JsonNode api = mapper.valueToTree(signal);
        assertEquals(fixture.get("strategy_family").asText(), api.get("strategyFamily").asText());
        assertEquals(fixture.get("strategy_family_name").asText(), api.get("strategyFamilyName").asText());
        assertEquals(fixture.get("primary_setup_id").asText(), api.get("primarySetupId").asText());
        assertEquals(fixture.get("matched_setup_ids").toString(), api.get("matchedSetupIds").asText());
        assertEquals(fixture.get("confirmed_by_family_ids").toString(), api.get("confirmedByFamilyIds").asText());
        assertEquals(fixture.get("family_policy_version").asText(), api.get("familyPolicyVersion").asText());
        assertEquals(fixture.get("setup_version").asText(), api.get("setupVersion").asText());
        assertEquals(fixture.get("rule_score_version").asText(), api.get("ruleScoreVersion").asText());
        assertEquals(fixture.get("prompt_version").asText(), api.get("promptVersion").asText());
        assertEquals(fixture.get("data_source").toString(), api.get("dataSource").asText());
        assertEquals(fixture.get("source_timestamp").toString(), api.get("sourceTimestamp").asText());
        assertEquals(fixture.get("source_age_ms").toString(), api.get("sourceAgeMs").asText());
        assertEquals(fixture.get("fallback_reason").toString(), api.get("fallbackReason").asText());
    }
}
