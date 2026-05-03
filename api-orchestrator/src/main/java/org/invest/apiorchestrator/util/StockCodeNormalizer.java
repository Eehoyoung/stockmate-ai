package org.invest.apiorchestrator.util;

public final class StockCodeNormalizer {

    private StockCodeNormalizer() {
    }

    public static String normalize(String stkCd) {
        if (stkCd == null) {
            return null;
        }
        String trimmed = stkCd.trim();
        int idx = trimmed.indexOf('_');
        String base = idx > 0 ? trimmed.substring(0, idx) : trimmed;
        String digits = base.replaceAll("\\D", "");
        return digits.length() >= 6 ? digits.substring(0, 6) : base;
    }
}
