특정 전략 파일을 점검하고 문제점을 보고합니다.

사용법:
- `/strategy-audit S8` — S8 골든크로스 전략 점검
- `/strategy-audit all` — 전체 S1–S15 점검

인자: $ARGUMENTS

다음 체크리스트로 전략 파일을 점검하세요:

## 점검 항목

### 1. Kiwoom API 응답 검증
- [ ] 모든 API 호출 후 `validate_kiwoom_response(data, api_id)` 호출 여부

### 2. Redis 후보 풀 키
- [ ] `candidates:s{N}:{market}` 형식 사용 (구형 `candidates:001` 사용 금지)
- [ ] `rdb` 파라미터로 풀 우선 읽기 → 없을 때 API 폴백 구조인지

### 3. scorer.py 연동
- [ ] `scorer.py`의 `CLAUDE_THRESHOLDS`에 해당 전략 키 존재 여부
- [ ] `score_signal()` match 블록에 케이스 존재 여부

### 4. 로깅
- [ ] `print()` 직접 사용 없는지 (logger 경유해야 함)
- [ ] ERROR/WARNING 로그에 `stk_cd` 필드 포함 여부

### 5. 비동기 패턴
- [ ] `async def` 함수 내 `await` 누락 없는지
- [ ] Redis 접근 시 `await rdb.*` 사용 여부

전략 파일 경로: `ai-engine/strategy_{N}_{name}.py`

인자가 `all`이면 S1부터 S15까지 전부 점검하고 이슈가 있는 항목만 요약 리포트로 출력하세요.
전략 번호가 지정되면 해당 파일만 상세 점검하세요.
