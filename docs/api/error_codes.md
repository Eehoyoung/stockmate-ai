# 키움 API 오류 코드

## REST API 오류 코드

| 코드 | 메시지 | 대응 방법 |
|------|--------|-----------|
| `1501` | API ID가 Null이거나 값이 없습니다 | `api-id` 헤더 확인 |
| `1504` | 해당 URI에서 지원하지 않는 API ID | endpoint URL 확인 |
| `1505` | API ID가 존재하지 않습니다 | API ID 오타 확인 |
| `1511` | 필수 입력 값이 없습니다 | Request Body 필수 필드 확인 |
| `1512` | Http header 설정 오류 | 헤더 형식 확인 |
| `1513` | authorization 필드 미설정 | `authorization` 헤더 추가 |
| `1514` | authorization 형식 불일치 | `Bearer {token}` 형식 확인 |
| `1515` | Grant Type 형식 오류 | `client_credentials` 확인 |
| `1516` | Token 미정의 | 토큰 값 확인 |
| `1517` | 입력 값 형식 오류 | 파라미터 타입/형식 확인 |
| `1687` | 재귀 호출 제한 | 호출 로직 점검 |
| `1700` | 허용 요청 개수 초과 | Rate Limit → 재시도 대기 |
| `1901` | 시장 코드 없음 | `mrkt_tp` 값 확인 |
| `1902` | 종목 정보 없음 | 종목코드 확인 |
| `1999` | 예기치 못한 에러 | 로그 확인, 재시도 |
| `8001` | App Key/Secret 검증 실패 | `.env` 키 값 재확인 |
| `8005` | Token 유효하지 않음 | **토큰 재발급** (TokenService.refreshToken()) |
| `8010` | IP 불일치 | 서버 IP 고정 또는 API 설정 확인 |
| `8030` | 실전/모의 투자 구분 불일치 | URL 확인 (운영/모의 혼용 금지) |

## 공통 응답 구조

```json
{
  "return_code": 0,
  "return_msg": "정상적으로 처리되었습니다"
}
```

- `return_code == 0` → 정상
- `return_code != 0` → 오류 (위 코드 참조)

## Java 처리 패턴

```java
// KiwoomApiService 에서 401 자동 갱신
.onStatus(status -> status.value() == 401, resp -> {
    tokenService.refreshToken();  // 8005 대응
    ...
})

// 응답 코드 확인
if (!resp.isSuccess()) {
    throw new KiwoomApiException("API 오류: " + resp.getReturnMsg());
}
```

## Rate Limit 대응

- 오류코드 `1700` 수신 시 지수 백오프 재시도
- `KiwoomApiService` retry 설정: 최대 2회, 1초 간격
