# 전략군 통합 전체 롤백 런북

## 고정 복구점

- 기준 브랜치: `master`
- 기준 커밋: `5b18b10c72b08450eb0151f9ff41f2f6551e923c`
- 구현 브랜치: `codex/strategy-family-consolidation`
- 초기 상태: 기준 커밋에서 tracked worktree는 clean이었다.

## 롤백 계층

### 1. 즉시 기능 차단

`ENABLE_STRATEGY_FAMILY_LINEAGE=false`로 두면 신규 family 계보 발행은 비활성이다. 기본값도 false다. 이후 도입되는 family 주문 라우팅은 별도 kill switch가 기본 false인 상태에서만 추가한다.

### 2. 코드 전체 원복

작업 브랜치 밖의 사용자 변경이 없는지 먼저 `git status --short`로 확인한다. 이 작업의 각 단계는 scoped checkpoint commit으로 남긴다. 검증 후 `master`로 전환하면 기준 구현으로 돌아간다.

```powershell
git switch master
git rev-parse HEAD
```

출력 HEAD가 고정 복구점과 다르면 임의 reset하지 말고 차이를 먼저 조사한다. `git reset --hard`는 사용하지 않는다.

### 3. DB 동작 롤백

V55는 additive 컬럼과 인덱스만 추가하며 기존 `strategy` 값과 제약을 변경하지 않는다. 따라서 정상 롤백은 새 기능을 끄고 컬럼을 남기는 방식이다. 이 방식은 데이터 손실이 없고 구버전 코드와 호환된다.

### 4. DB 물리 원복

컬럼까지 제거해야 하는 경우 먼저 `trading_signals`와 `flyway_schema_history`를 백업하고, 유지보수 시간에 [rollback_strategy_family_v55.sql](../scripts/rollback_strategy_family_v55.sql)을 수동 검토 후 실행한다. 이 SQL은 다른 policy version 데이터가 있으면 중단한다. Flyway 이력을 임의 삭제하지 않으며 완전한 시점복구는 V55 이전 DB 백업을 사용한다.

## 단계별 체크포인트 규칙

각 WP 커밋은 다음을 포함한다.

- 변경 파일만 명시적 stage
- 실행한 테스트와 결과
- 새 환경변수와 기본값
- DB migration 적용 여부
- 되돌릴 feature flag
- 이전 checkpoint hash

## 즉시 롤백 조건

- 중복 포지션 1건
- setup 계보 누락 1건
- stale 필수 데이터 ENTER 1건
- hard gate 또는 RR 우회 1건
- family와 setup exit 정책 오적용 1건
- 주문 ACK/체결 매핑 누락률 0.5% 초과
- AI JSON 실패율 1% 초과

## 현재 상태

- DB migration 미적용
- 컨테이너 재배포 없음
- 외부 주문·메시지 없음
- 신규 family 계보 기본 OFF
