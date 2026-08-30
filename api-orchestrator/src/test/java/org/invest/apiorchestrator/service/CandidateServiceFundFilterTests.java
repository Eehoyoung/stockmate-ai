package org.invest.apiorchestrator.service;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CandidateServiceFundFilterTests {

    @Test
    void blocksFundPrefixesAndKeepsCompanyNames() {
        assertTrue(CandidateService.isEtfOrEtn("KODEX 200"));
        assertTrue(CandidateService.isEtfOrEtn("KoAct 글로벌AI액티브"));
        assertTrue(CandidateService.isEtfOrEtn("키움 코스닥 150 TR ETN"));
        assertTrue(CandidateService.isEtfOrEtn(null));
        assertFalse(CandidateService.isEtfOrEtn("BNK금융지주"));
        assertFalse(CandidateService.isEtfOrEtn("IBK기업은행"));
        assertFalse(CandidateService.isEtfOrEtn("삼성전자"));
    }
}
