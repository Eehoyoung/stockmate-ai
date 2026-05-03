package org.invest.apiorchestrator.service;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OperationsHealthServiceEnvFlagTests {

    private static final String KEY = "SESSION_FLAG_TEST";

    @AfterEach
    void clearProperty() {
        System.clearProperty(KEY);
    }

    @Test
    void envFlagUsesDefaultWhenMissing() {
        assertTrue(OperationsHealthService.envFlag(KEY, true));
        assertFalse(OperationsHealthService.envFlag(KEY, false));
    }

    @Test
    void envFlagAcceptsTrueAliasesFromSystemProperty() {
        System.setProperty(KEY, "true");
        assertTrue(OperationsHealthService.envFlag(KEY, false));

        System.setProperty(KEY, "1");
        assertTrue(OperationsHealthService.envFlag(KEY, false));

        System.setProperty(KEY, "yes");
        assertTrue(OperationsHealthService.envFlag(KEY, false));
    }

    @Test
    void envFlagRejectsFalseLikeValuesFromSystemProperty() {
        System.setProperty(KEY, "false");
        assertFalse(OperationsHealthService.envFlag(KEY, true));

        System.setProperty(KEY, "0");
        assertFalse(OperationsHealthService.envFlag(KEY, true));
    }
}
