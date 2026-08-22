package org.invest.apiorchestrator.repository;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.data.jpa.test.autoconfigure.DataJpaTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.jdbc.Sql;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

@DataJpaTest(properties = "spring.jpa.hibernate.ddl-auto=none")
@Sql(statements = "CREATE TABLE IF NOT EXISTS trading_signals (id BIGINT PRIMARY KEY, stk_cd VARCHAR(20), position_status VARCHAR(20))")
class TradingSignalRepositoryPositionGuardTests {

    @Autowired TradingSignalRepository repository;
    @Autowired JdbcTemplate jdbc;

    @ParameterizedTest
    @ValueSource(strings = {"ACTIVE", "PARTIAL_TP", "OVERNIGHT"})
    void everyLivePositionStateBlocksAnotherEntry(String positionStatus) {
        jdbc.update("INSERT INTO trading_signals(id, stk_cd, position_status) VALUES (?, ?, ?)",
                1, "005930", positionStatus);

        assertTrue(repository.existsActivePosition("005930"));
        assertFalse(repository.existsActivePosition("000660"));
    }
}
