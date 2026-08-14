package org.invest.apiorchestrator.exception;

public class TossApiException extends RuntimeException {
    public TossApiException(String message) {
        super(message);
    }
    public TossApiException(String message, Throwable cause) {
        super(message, cause);
    }
}
