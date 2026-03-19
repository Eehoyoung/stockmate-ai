package org.invest.apiorchestrator.exception;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.LocalDateTime;
import java.util.Map;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(KiwoomApiException.class)
    public ResponseEntity<Map<String, Object>> handleKiwoomApiException(KiwoomApiException e) {
        log.error("키움 API 오류: {}", e.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                .body(errorBody(e.getMessage(), "KIWOOM_API_ERROR"));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> handleIllegalArgument(IllegalArgumentException e) {
        log.warn("잘못된 요청: {}", e.getMessage());
        return ResponseEntity.badRequest()
                .body(errorBody(e.getMessage(), "BAD_REQUEST"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleGeneral(Exception e) {
        log.error("예기치 못한 오류", e);
        return ResponseEntity.internalServerError()
                .body(errorBody("서버 내부 오류가 발생했습니다.", "INTERNAL_ERROR"));
    }

    private Map<String, Object> errorBody(String message, String code) {
        return Map.of(
                "timestamp", LocalDateTime.now().toString(),
                "error_code", code,
                "message", message
        );
    }
}
