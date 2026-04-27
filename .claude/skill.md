# StockMate AI – Slash Command Index

커맨드 파일은 `.claude/commands/` 에 위치합니다. `/커맨드명` 으로 호출합니다.

## 커맨드 목록

| 커맨드 | 파일 | 설명 |
|--------|------|------|
| `/logs [service]` | `commands/logs.md` | Docker 서비스 로그 스트리밍. 서비스명 생략 시 전체 출력 |
| `/redis-status` | `commands/redis-status.md` | Redis 큐 깊이 + S1–S15 후보 풀 크기 조회 |
| `/trace <id>` | `commands/trace.md` | signal_id / request_id 로 전 모듈 로그 교차 추적 |
| `/new-migration <name>` | `commands/new-migration.md` | 다음 버전 Flyway SQL 파일 자동 생성 |
| `/strategy-audit <S번호\|all>` | `commands/strategy-audit.md` | 전략 파일 5개 항목 체크리스트 점검 |

## 사용 예시

```
/logs api-orchestrator
/redis-status
/trace sig-3f2a1b00-...
/new-migration add_tp_sl_columns
/strategy-audit S8
/strategy-audit all
```
