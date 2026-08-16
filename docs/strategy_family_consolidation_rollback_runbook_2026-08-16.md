# 전략군 통합 전체 롤백 런북

## 고정 복구점

- 기준 브랜치: `master`
- 기준 커밋: `5b18b10c72b08450eb0151f9ff41f2f6551e923c`
- 구현 브랜치: `codex/strategy-family-consolidation`
- 초기 상태: 기준 커밋에서 tracked worktree는 clean이었다.

## 롤백 계층

### 1. 즉시 기능 차단

`.env`에서 아래 세 값을 모두 `false`로 바꾸고 API, AI, Telegram 컨테이너를 재생성한다.

```text
ENABLE_STRATEGY_FAMILY_LINEAGE=false
ENABLE_STRATEGY_FAMILY_SHADOW_SCORING=false
ENABLE_STRATEGY_FAMILY_LIVE_ROUTING=false
```

가장 빠른 정확 복구는 배포 전 환경 사본을 되돌리는 것이다.

```powershell
Copy-Item -Force backups\strategy-family-live-canary-20260816-2340\.env.predeploy .env
docker compose up -d --force-recreate api-orchestrator ai-engine telegram-bot
```

### 2. 코드 전체 원복

작업 브랜치 밖의 사용자 변경이 없는지 먼저 `git status --short`로 확인한다. 이 작업의 각 단계는 scoped checkpoint commit으로 남긴다. 검증 후 `master`로 전환하면 기준 구현으로 돌아간다.

```powershell
git switch master
git rev-parse HEAD
```

출력 HEAD가 고정 복구점과 다르면 임의 reset하지 말고 차이를 먼저 조사한다. `git reset --hard`는 사용하지 않는다.

배포 전 이미지는 다음 immutable tag로 보존했다.

- `stockmate-ai-api-orchestrator:pre-family-20260816`
- `stockmate-ai-ai-engine:pre-family-20260816`
- `stockmate-ai-telegram-bot:pre-family-20260816`

코드 재빌드 없이 되돌릴 때는 서비스 중지 후 위 이미지를 각 `latest`로 다시 tag하고 `docker compose up -d --force-recreate`한다. DB V55는 additive이므로 그대로 두는 것이 기본 복구 방식이다.

### 3. DB 동작 롤백

V55는 additive 컬럼과 인덱스만 추가하며 기존 `strategy` 값과 제약을 변경하지 않는다. 따라서 정상 롤백은 새 기능을 끄고 컬럼을 남기는 방식이다. 이 방식은 데이터 손실이 없고 구버전 코드와 호환된다.

### 4. DB 물리 원복

컬럼까지 제거해야 하는 경우 먼저 `trading_signals`와 `flyway_schema_history`를 백업하고 유지보수 시간에 `rollback_strategy_family_v56.sql`을 먼저, `rollback_strategy_family_v55.sql`을 다음 순서로 수동 검토 후 실행한다. SQL은 알 수 없는 version 데이터가 있으면 중단한다. Flyway 이력을 임의 삭제하지 않으며 완전한 시점복구는 V55 이전 DB 백업을 사용한다.

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

장중/장마감 점검은 다음 명령을 사용한다. 종료코드 2와 `ROLLBACK_NOW`가 나오면 신규 진입을 즉시 중단하고 1단계 롤백을 실행한다.

```powershell
.\scripts\monitor_strategy_family_canary.ps1
```

## 현재 상태

- 2026-08-16 23:37 KST DB V55 적용 완료. 배포 전 DB archive는 `backups/strategy-family-live-canary-20260816-2340/postgres.dump`이며 `pg_restore --list` 판독을 통과했다.
- 같은 디렉터리에 Redis RDB, `.env.predeploy`, 이전 이미지 목록, Git HEAD를 보존했다.
- 2026-08-16 23:38 KST API, AI, Telegram live canary 재배포 완료. 세 서비스 health는 모두 healthy다.
- family lineage, 비교점수 기록, live routing이 모두 ON이다. 비교점수는 관측 필드이며 주문 자체는 shadow가 아니다.
- 배포 시각은 일요일 장외이므로 신규 주문 발생은 없었다. 첫 거래일부터 5거래일 카나리 지표를 집계한다.
- 이전 이미지 3개는 `pre-family-20260816` tag로 고정했다.
