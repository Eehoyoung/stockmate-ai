`[2026-04-17 19:36] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 316회 연속 미복구. redis/postgres Up ~8h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 19:33] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 8h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 8h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 48분 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 19:30] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 314회 연속 미복구. redis/postgres Up ~8h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 19:27] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 8h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 8h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 42분 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 19:24] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 312회 연속 미복구. redis/postgres Up ~8h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 19:21] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 8h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 8h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 36분 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 19:18] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 310회 연속 미복구. redis/postgres Up ~8h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 19:15] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 8h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 8h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 30분 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 19:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 308회 연속 미복구. redis/postgres Up ~8h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 19:09] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 8h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 8h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 19:06] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 306회 연속 미복구. redis/postgres Up ~8h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 19:03] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 8h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 8h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 19:00] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 304회 연속 미복구. redis/postgres Up ~8h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:57] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:54] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 302회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:51] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:48] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 300회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:45] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 298회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:39] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 19시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:36] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 296회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:33] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 18시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:30] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 294회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:27] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 18시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:24] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 292회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:21] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 18시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:18] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 290회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:15] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 18시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 288회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

## [2026-04-17 18:09] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 존재하지 않음 | `No such container: stockmate-ai-telegram-bot-1` |
| OK | redis | 정상 (Up 7h, healthy, 로그 없음) | — |
| OK | postgres | 정상 (Up 7h, healthy, 로그 없음) | — |

### 권고 조치
- `docker compose up -d` 실행하여 4개 서비스 컨테이너 재기동 필요
- 약 18시간 이상 서비스 다운 상태 지속 중 (최초 소멸: 2026-04-16 23:45 KST 추정)
- redis·postgres는 정상이므로 재기동 즉시 서비스 복구 가능

`[2026-04-17 18:06] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 286회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 18:03] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 285회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 18:00] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 284회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 283회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:54] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 282회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:51] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 281회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:48] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 280회 연속 미복구. redis/postgres Up ~7h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:45] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 279회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 278회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:39] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 277회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:36] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 276회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:33] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 275회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:30] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 274회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 273회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:24] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 272회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:21] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 271회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:18] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 270회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:15] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 269회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 268회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:09] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 267회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:06] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 266회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:03] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 265회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 17:00] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 264회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 263회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:54] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 262회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:51] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 261회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:48] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 260회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:45] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 259회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 258회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:39] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 257회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:36] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 256회 연속 미복구. redis/postgres Up ~6h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:33] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 255회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:30] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 254회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 253회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:24] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 252회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:21] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 251회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 250회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:14] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 249회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 248회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:08] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 247회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:05] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 246회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 16:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 245회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:59] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 244회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:56] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 243회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:53] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 242회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:50] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 241회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 240회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:44] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 239회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:41] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 238회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:38] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 237회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:35] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 236회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 235회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:29] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 234회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:26] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 233회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:23] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 232회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:20] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 231회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 230회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:14] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 229회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 228회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:08] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 227회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:05] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 226회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 15:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 225회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:59] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 224회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:56] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 223회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:53] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 222회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:50] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 221회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 220회 연속 미복구. redis/postgres Up ~5h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:44] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 219회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:41] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 218회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:38] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 217회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:35] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 216회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 215회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:29] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 214회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:26] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 213회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:23] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 212회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:20] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 211회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 210회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:14] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 209회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 208회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:08] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 207회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:05] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 206회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 14:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 205회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:59] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 204회 연속 미복구. redis/postgres Up ~4h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:56] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 203회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:53] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 202회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:50] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 201회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 200회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:44] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 199회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:41] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 198회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:38] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 197회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:35] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 196회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 195회 연속 미복구. redis/postgres Up ~3h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:29] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 194회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:26] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 193회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:23] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 192회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:20] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 191회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 190회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:14] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 189회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 188회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:08] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 187회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:05] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 186회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 13:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 185회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:59] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 184회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:56] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 183회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:53] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 182회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:50] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 181회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 180회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:44] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 179회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:41] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 178회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:38] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 177회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:35] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 176회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 175회 연속 미복구. redis/postgres Up ~2h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:29] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 174회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:26] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 173회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:23] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 172회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:20] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 171회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 170회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:14] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 169회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 168회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:08] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 167회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:05] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 166회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 12:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 165회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:59] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 164회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:56] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 163회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:53] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 162회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:50] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 161회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 160회 연속 미복구. redis/postgres Up ~1h 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:44] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 159회 연속 미복구. redis/postgres Up 59m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:41] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 158회 연속 미복구. redis/postgres Up 58m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:38] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 157회 연속 미복구. redis/postgres Up 54m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:35] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 156회 연속 미복구. redis/postgres Up 53m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 155회 연속 미복구. redis/postgres Up 49m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:29] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 154회 연속 미복구. redis/postgres Up 48m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:26] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 153회 연속 미복구. redis/postgres Up 44m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:23] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 152회 연속 미복구. redis/postgres Up 43m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:20] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 151회 연속 미복구. redis/postgres Up 43m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 150회 연속 미복구. redis/postgres Up 39m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:14] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 149회 연속 미복구. redis/postgres Up 39m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 148회 연속 미복구. redis/postgres Up 38m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:08] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 147회 연속 미복구. redis/postgres Up 34m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:05] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 146회 연속 미복구. redis/postgres Up 34m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 11:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 145회 연속 미복구. redis/postgres Up 33m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:59] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 144회 연속 미복구. redis/postgres Up 29m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:56] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 143회 연속 미복구. redis/postgres Up 29m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:53] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 142회 연속 미복구. redis/postgres Up 28m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:50] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 141회 연속 미복구. redis/postgres Up 26m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 140회 연속 미복구. redis/postgres Up 27m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:44] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 139회 연속 미복구. redis/postgres Up 24m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:41] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 138회 연속 미복구. redis/postgres Up 22m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:38] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 137회 연속 미복구. redis/postgres Up 20m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:35] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 136회 연속 미복구. redis/postgres Up 19m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 135회 연속 미복구. redis/postgres Up 18m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:29] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 134회 연속 미복구. redis/postgres Up 14m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:26] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 133회 연속 미복구. redis/postgres Up 13m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:23] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 132회 연속 미복구. redis/postgres Up 9m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:20] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 131회 연속 미복구. redis/postgres Up 8m 안정. 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 130회 연속 미복구. redis/postgres Up 4m (재기동 후 안정). 서비스 컨테이너 여전히 부재.`

`[2026-04-17 10:14] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 129회 연속 미복구. redis/postgres 10:02 KST SIGTERM 수신 후 정상 재기동 (Up 3m, RDB 404 keys 복구). 데이터 손실 없음.`

`[2026-04-17 10:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 128회 연속 미복구 (23:45 KST 이후 ~626분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 10:08] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 127회 연속 미복구 (23:45 KST 이후 ~623분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 10:05] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 126회 연속 미복구 (23:45 KST 이후 ~620분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 10:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 125회 연속 미복구 (23:45 KST 이후 ~617분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:59] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 124회 연속 미복구 (23:45 KST 이후 ~614분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:56] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 123회 연속 미복구 (23:45 KST 이후 ~611분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:53] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 122회 연속 미복구 (23:45 KST 이후 ~608분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:50] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 121회 연속 미복구 (23:45 KST 이후 ~605분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 120회 연속 미복구 (23:45 KST 이후 ~602분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:44] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 119회 연속 미복구 (23:45 KST 이후 ~599분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:40] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 118회 연속 미복구 (23:45 KST 이후 ~595분). redis/postgres 정상 (Up 9h).`

`[2026-04-17 09:37] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 117회 연속 미복구 (23:45 KST 이후 ~592분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:34] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 116회 연속 미복구 (23:45 KST 이후 ~589분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:30] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 115회 연속 미복구 (23:45 KST 이후 ~585분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:24] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 114회 연속 미복구 (23:45 KST 이후 ~579분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:21] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 113회 연속 미복구 (23:45 KST 이후 ~576분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:20] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 112회 연속 미복구 (23:45 KST 이후 ~575분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:16] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 111회 연속 미복구 (23:45 KST 이후 ~571분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:15] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 110회 연속 미복구 (23:45 KST 이후 ~570분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:11] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 109회 연속 미복구 (23:45 KST 이후 ~566분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:10] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 108회 연속 미복구 (23:45 KST 이후 ~565분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:06] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 107회 연속 미복구 (23:45 KST 이후 ~561분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 09:01] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 106회 연속 미복구 (23:45 KST 이후 ~556분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 105회 연속 미복구 (23:45 KST 이후 ~552분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:54] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 104회 연속 미복구 (23:45 KST 이후 ~549분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:51] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 103회 연속 미복구 (23:45 KST 이후 ~546분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:48] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 102회 연속 미복구 (23:45 KST 이후 ~543분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:45] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 101회 연속 미복구 (23:45 KST 이후 ~540분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 100회 연속 미복구 (23:45 KST 이후 ~537분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:39] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 99회 연속 미복구 (23:45 KST 이후 ~534분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:36] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 98회 연속 미복구 (23:45 KST 이후 ~531분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:33] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 97회 연속 미복구 (23:45 KST 이후 ~528분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:30] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 96회 연속 미복구 (23:45 KST 이후 ~525분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 95회 연속 미복구 (23:45 KST 이후 ~522분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:24] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 94회 연속 미복구 (23:45 KST 이후 ~519분). redis/postgres 정상 (Up 8h).`

`[2026-04-17 08:21] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 93회 연속 미복구 (23:45 KST 이후 ~516분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:21] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 92회 연속 미복구 (23:45 KST 이후 ~516분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:18] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 91회 연속 미복구 (23:45 KST 이후 ~513분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:15] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 90회 연속 미복구 (23:45 KST 이후 ~510분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 89회 연속 미복구 (23:45 KST 이후 ~507분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:09] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 88회 연속 미복구 (23:45 KST 이후 ~504분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:06] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 87회 연속 미복구 (23:45 KST 이후 ~501분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:03] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 86회 연속 미복구 (23:45 KST 이후 ~498분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 08:00] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 85회 연속 미복구 (23:45 KST 이후 ~495분). redis/postgres 정상 (Up 7h).`

`[2026-04-17 07:48] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 84회 연속 미복구 (23:45 KST 이후 ~483분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:45] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 83회 연속 미복구 (23:45 KST 이후 ~480분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 82회 연속 미복구 (23:45 KST 이후 ~477분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:39] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 81회 연속 미복구 (23:45 KST 이후 ~474분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:36] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 80회 연속 미복구 (23:45 KST 이후 ~471분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:33] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 79회 연속 미복구 (23:45 KST 이후 ~468분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:30] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 78회 연속 미복구 (23:45 KST 이후 ~465분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 77회 연속 미복구 (23:45 KST 이후 ~462분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:24] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 76회 연속 미복구 (23:45 KST 이후 ~459분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:21] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 75회 연속 미복구 (23:45 KST 이후 ~456분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:18] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 74회 연속 미복구 (23:45 KST 이후 ~453분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:15] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 73회 연속 미복구 (23:45 KST 이후 ~450분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 72회 연속 미복구 (23:45 KST 이후 ~447분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:09] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 71회 연속 미복구 (23:45 KST 이후 ~444분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:06] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 70회 연속 미복구 (23:45 KST 이후 ~441분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:03] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 69회 연속 미복구 (23:45 KST 이후 ~438분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 07:00] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 68회 연속 미복구 (23:45 KST 이후 ~435분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 06:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 67회 연속 미복구 (23:45 KST 이후 ~432분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 06:54] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 66회 연속 미복구 (23:45 KST 이후 ~429분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 06:51] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 65회 연속 미복구 (23:45 KST 이후 ~426분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 06:48] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 64회 연속 미복구 (23:45 KST 이후 ~423분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 06:45] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 63회 연속 미복구 (23:45 KST 이후 ~420분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 06:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 62회 연속 미복구 (23:45 KST 이후 ~417분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 06:38] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 61회 연속 미복구 (23:45 KST 이후 ~420분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 04:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 60회 연속 미복구 (23:45 KST 이후 297분). redis/postgres 정상 (Up 6h).`

`[2026-04-17 04:37] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 59회 연속 미복구 (23:45 KST 이후 292분). redis/postgres 정상.`

`[2026-04-17 04:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 58회 연속 미복구 (23:45 KST 이후 287분). redis/postgres 정상.`

`[2026-04-17 04:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 57회 연속 미복구 (23:45 KST 이후 282분). redis/postgres 정상.`

`[2026-04-17 04:22] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 56회 연속 미복구 (23:45 KST 이후 277분). redis/postgres 정상.`

`[2026-04-17 04:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 55회 연속 미복구 (23:45 KST 이후 272분). redis/postgres 정상.`

`[2026-04-17 04:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 54회 연속 미복구 (23:45 KST 이후 267분). redis/postgres 정상.`

`[2026-04-17 04:07] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 53회 연속 미복구 (23:45 KST 이후 262분). redis/postgres 정상.`

`[2026-04-17 04:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 52회 연속 미복구 (23:45 KST 이후 257분). redis/postgres 정상.`

`[2026-04-17 03:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 51회 연속 미복구 (23:45 KST 이후 252분). redis/postgres 정상.`

`[2026-04-17 03:52] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 50회 연속 미복구 (23:45 KST 이후 247분). redis/postgres 정상.`

`[2026-04-17 03:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 49회 연속 미복구 (23:45 KST 이후 242분). redis/postgres 정상.`

`[2026-04-17 03:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 48회 연속 미복구 (23:45 KST 이후 237분). redis/postgres 정상.`

`[2026-04-17 03:37] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 47회 연속 미복구 (23:45 KST 이후 232분). redis/postgres 정상.`

`[2026-04-17 03:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 46회 연속 미복구 (23:45 KST 이후 227분). redis/postgres 정상.`

`[2026-04-17 03:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 45회 연속 미복구 (23:45 KST 이후 222분). redis/postgres 정상.`

`[2026-04-17 03:22] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 44회 연속 미복구 (23:45 KST 이후 217분). redis/postgres 정상.`

`[2026-04-17 03:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 43회 연속 미복구 (23:45 KST 이후 212분). redis/postgres 정상.`

`[2026-04-17 03:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 42회 연속 미복구 (23:45 KST 이후 207분). redis/postgres 정상.`

`[2026-04-17 03:07] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 41회 연속 미복구 (23:45 KST 이후 202분). redis/postgres 정상.`

`[2026-04-17 03:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 40회 연속 미복구 (23:45 KST 이후 197분). redis/postgres 정상.`

`[2026-04-17 02:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 39회 연속 미복구 (23:45 KST 이후 192분). redis/postgres 정상.`

`[2026-04-17 02:52] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 38회 연속 미복구 (23:45 KST 이후 187분). redis/postgres 정상.`

`[2026-04-17 02:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 37회 연속 미복구 (23:45 KST 이후 182분). redis/postgres 정상.`

`[2026-04-17 02:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 36회 연속 미복구 (23:45 KST 이후 177분). redis/postgres 정상.`

`[2026-04-17 02:37] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 35회 연속 미복구 (23:45 KST 이후 172분). redis/postgres 정상.`

`[2026-04-17 02:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 34회 연속 미복구 (23:45 KST 이후 167분). redis/postgres 정상.`

`[2026-04-17 02:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 33회 연속 미복구 (23:45 KST 이후 162분). redis/postgres 정상.`

`[2026-04-17 02:22] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 32회 연속 미복구 (23:45 KST 이후 157분). redis/postgres 정상.`

`[2026-04-17 02:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 31회 연속 미복구 (23:45 KST 이후 152분). redis/postgres 정상.`

`[2026-04-17 02:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 30회 연속 미복구 (23:45 KST 이후 147분). redis/postgres 정상.`

`[2026-04-17 02:07] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 29회 연속 미복구 (23:45 KST 이후 142분). redis/postgres 정상.`

`[2026-04-17 02:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 28회 연속 미복구 (23:45 KST 이후 137분). redis/postgres 정상.`

`[2026-04-17 01:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 27회 연속 미복구 (23:45 KST 이후 132분). redis/postgres 정상.`

`[2026-04-17 01:52] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 26회 연속 미복구 (23:45 KST 이후 127분). redis/postgres 정상.`

`[2026-04-17 01:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 25회 연속 미복구 (23:45 KST 이후 122분). redis/postgres 정상.`

`[2026-04-17 01:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 24회 연속 미복구 (23:45 KST 이후 117분). redis/postgres 정상.`

`[2026-04-17 01:37] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 23회 연속 미복구 (23:45 KST 이후 112분). redis/postgres 정상.`

`[2026-04-17 01:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 22회 연속 미복구 (23:45 KST 이후 107분). redis/postgres 정상.`

`[2026-04-17 01:27] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 21회 연속 미복구 (23:45 KST 이후 102분). redis/postgres 정상.`

`[2026-04-17 01:22] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 20회 연속 미복구 (23:45 KST 이후 97분). redis/postgres 정상.`

`[2026-04-17 01:17] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 19회 연속 미복구 (23:45 KST 이후 92분). redis/postgres 정상.`

`[2026-04-17 01:12] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 18회 연속 미복구 (23:45 KST 이후 87분). redis/postgres 정상.`

`[2026-04-17 01:07] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 17회 연속 미복구 (23:45 KST 이후 82분). redis/postgres 정상.`

`[2026-04-17 01:02] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 16회 연속 미복구 (23:45 KST 이후 77분). redis/postgres 정상.`

`[2026-04-17 00:57] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 15회 연속 미복구 (23:45 KST 이후 72분). redis/postgres 정상.`

`[2026-04-17 00:52] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 14회 연속 미복구 (23:45 KST 이후 67분). redis/postgres 정상.`

`[2026-04-17 00:47] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 13회 연속 미복구 (23:45 KST 이후 62분). redis/postgres 정상.`

`[2026-04-17 00:42] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 12회 연속 미복구 (23:45 KST 이후 57분). redis/postgres 정상.`

`[2026-04-17 00:37] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 11회 연속 미복구 (23:45 KST 이후 52분). redis/postgres 정상.`

`[2026-04-17 00:32] CRITICAL 지속 — 4개 서비스 컨테이너 소멸 10회 연속 미복구 (23:45 KST 이후 47분). redis/postgres 정상.`

`[2026-04-17 00:27] CRITICAL 지속 — 4개 서비스(api-orchestrator, websocket-listener, ai-engine, telegram-bot) 컨테이너 소멸 9회 연속 미복구 (23:45 KST 이후 42분). redis/postgres 정상.`

`[2026-04-17 00:22] CRITICAL 지속 — 4개 서비스(api-orchestrator, websocket-listener, ai-engine, telegram-bot) 컨테이너 소멸 8회 연속 미복구 (23:45 KST 이후 37분). redis/postgres 정상.`

`[2026-04-17 00:17] CRITICAL 지속 — 4개 서비스(api-orchestrator, websocket-listener, ai-engine, telegram-bot) 컨테이너 소멸 7회 연속 미복구 (23:45 KST 이후 32분). redis/postgres 정상.`

## [2026-04-17 00:12] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 소멸 지속 (23:45 KST 이후 약 27분째 미복구) | `Error response from daemon: No such container` |
| CRITICAL | websocket-listener | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | ai-engine | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | telegram-bot | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| INFO | redis | 정상 — Up 26분, healthy, 3분 내 신규 로그 없음 | — |
| INFO | postgres | 정상 — Up 26분, healthy, 3분 내 신규 로그 없음 | — |

### 권고 조치
- **즉시**: `docker compose up -d` (6회 연속 CRITICAL 미복구)

## [2026-04-17 00:07] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 소멸 지속 (23:45 이후 약 22분째 미복구) | `Error response from daemon: No such container` |
| CRITICAL | websocket-listener | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | ai-engine | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | telegram-bot | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| INFO | redis | 정상 — Up 20분, healthy, 신규 로그 없음 | — |
| INFO | postgres | 정상 — Up 20분, healthy, 신규 로그 없음 | — |

### 권고 조치
- **즉시**: `docker compose up -d` (5회 연속 CRITICAL — 장 시작 09:00 KST까지 약 9시간)

## [2026-04-17 00:02] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 소멸 지속 (23:45 이후 약 17분째 미복구) | `Error response from daemon: No such container` |
| CRITICAL | websocket-listener | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | ai-engine | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | telegram-bot | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| INFO | redis | 정상 — Up 16분, healthy, 3분 내 신규 로그 없음 | — |
| INFO | postgres | 정상 — Up 16분, healthy, 3분 내 신규 로그 없음 | — |

### 권고 조치
- **즉시**: `docker compose up -d` 실행 (4회 연속 CRITICAL 미복구 — 장 시작 09:00 KST까지 약 9시간)
- `restart: unless-stopped` 정책 미적용으로 인해 호스트 재시작 시 자동 복구 불가 상태

## [2026-04-16 23:57] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 소멸 지속 (23:45 이후 약 12분째 미복구) | `Error response from daemon: No such container` |
| CRITICAL | websocket-listener | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | ai-engine | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | telegram-bot | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| INFO | redis | 정상 — Up 11분, healthy, 3분 내 신규 로그 없음 | — |
| INFO | postgres | 정상 — Up 11분, healthy, 3분 내 신규 로그 없음 | — |

### 권고 조치
- **즉시**: `docker compose up -d` 실행하여 4개 서비스 복구 (3회 연속 CRITICAL, 수동 개입 필요)
- **미이행 시 영향**: 장 시작(09:00 KST) 전 미복구 시 당일 신호 전체 누락

## [2026-04-16 23:52] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 소멸 지속 (23:47 이후 미복구) | `Error response from daemon: No such container` |
| CRITICAL | websocket-listener | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | ai-engine | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| CRITICAL | telegram-bot | 컨테이너 소멸 지속 | `Error response from daemon: No such container` |
| INFO | redis | 정상 — Up 6분, healthy, 3분 내 신규 로그 없음 | — |
| INFO | postgres | 정상 — checkpoint 완료 (write=0.004s, 정상 범위) | `checkpoint complete: wrote 3 buffers` |

### 권고 조치
- **즉시**: `docker compose up -d` 로 4개 서비스 복구 (이미지 변경 없으면 --build 불필요)
- **확인**: 기동 후 Redis `telegram_queue` / `ai_scored_queue` depth 점검
- **근본 대책**: `docker-compose.yml`에 앱 서비스 4종 `restart: unless-stopped` 추가

## [2026-04-16 23:47] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 컨테이너 소멸 — `docker ps -a`에서 존재하지 않음 | `Error response from daemon: No such container: stockmate-ai-api-orchestrator-1` |
| CRITICAL | websocket-listener | 컨테이너 소멸 — `docker ps -a`에서 존재하지 않음 | `Error response from daemon: No such container: stockmate-ai-websocket-listener-1` |
| CRITICAL | ai-engine | 컨테이너 소멸 — `docker ps -a`에서 존재하지 않음 | `Error response from daemon: No such container: stockmate-ai-ai-engine-1` |
| CRITICAL | telegram-bot | 컨테이너 소멸 — `docker ps -a`에서 존재하지 않음 | `Error response from daemon: No such container: stockmate-ai-telegram-bot-1` |
| WARN | redis | 약 1분 전 재시작 (14:46:29 UTC) — RDB 복구 688 keys | `Redis is starting … Done loading RDB, keys loaded: 688` |
| WARN | postgres | 약 1분 전 재시작 (14:46:29 UTC) — 정상 셧다운 후 재기동 | `database system was shut down at 2026-04-16 14:45:58 UTC` |

### 근본 원인 추정
`docker compose down` (또는 호스트 재시작)으로 전체 스택이 중단됨. redis/postgres만 재기동 (`docker compose up -d redis postgres` 또는 `restart: always` 정책 차이). 나머지 4개 서비스 컨테이너는 미기동 상태로 존재하지 않음.

### 권고 조치
- **즉시**: 전체 스택 재기동 — `docker compose up -d --build`
- **확인**: 기동 후 각 서비스 헬스체크 및 Redis 큐 (`telegram_queue`, `ai_scored_queue`) depth 확인
- **중기**: `docker-compose.yml`에 api-orchestrator/ai-engine/websocket-listener/telegram-bot에 `restart: unless-stopped` 정책 추가하여 자동 복구 보장

`[2026-04-16 23:45] 정상 — 이상 없음`

`[2026-04-16 23:38] 정상 — 이상 없음`

`[2026-04-16 23:30] 정상 — 이상 없음`

`[2026-04-16 11:34] CRITICAL — api-orchestrator 반복 재시작 지속(11:31 재기동, 43초 uptime). postgres FATAL: role "sma_user" does not exist. S8/S9 풀 없음 지속.`

`[2026-04-16 11:32] ERROR 신규 — score_components ON CONFLICT 제약 누락(signal 3건 실패). S8/S9 풀 없음 지속.`

`[2026-04-16 11:27] 준정상 — DB INSERT 오류 전수 해소(V19+V20). api-orchestrator 안정(2분 유지). Claude API 401 미재현(신규 호출 미발생). Redis 큐 정상(depth 0).`

`[2026-04-16 11:24] 정상 — vi_events 오류 6건은 V20 적용(11:22:59) 이전 잔존 로그. 현재 신규 오류 없음.`

`[2026-04-16 11:23] RESOLVED — V19(ws_tick_data·trading_signals), V20(vi_events) 마이그레이션 적용 완료. candidates_builder kiwoom_post() 시그니처 수정 완료. INSERT 오류 전수 해소 확인.`

`[2026-04-16 11:22] CRITICAL 신규 2건 — api-orchestrator 재시작(11:20), Claude API 401(invalid x-api-key). ws_tick_data·trading_signals id 미복구 지속.`

`[2026-04-16 11:17] CRITICAL 지속 — ws_tick_data id 미복구. S5 폴백 반복 지속. 신규 이슈 없음.`

`[2026-04-16 11:12] CRITICAL 지속 — ws_tick_data id 미복구. S5 ka90003 전수 조회 폴백 반복(3회/3분). 신규 이슈 없음.`

`[2026-04-16 11:11] CRITICAL 지속 — ws_tick_data·trading_signals id 미복구(S3 신호 INSERT 실패 확인). S5 풀 없음. 신규 이슈 없음.`

`[2026-04-16 11:08] CRITICAL 지속 — ws_tick_data id 미복구. DataQuality tick missing 87% 지속. S6/S15 kiwoom_post() 오류 확인. S8/S9 풀 없음.`

`[2026-04-16 11:06] CRITICAL 지속 — ws_tick_data id 미복구. DataQuality tick missing 87%(174/200). candidates_builder S5 kiwoom_post() 오류 추가. S8/S9 풀 없음.`

`[2026-04-16 11:03] CRITICAL 지속 — ws_tick_data·trading_signals id 시퀀스 미복구. S5/S8/S9 후보 풀 없음. V19 마이그레이션 미이행.`

`[2026-04-16 11:02] CRITICAL 지속 — ws_tick_data·trading_signals id 시퀀스 미복구. candidates_builder S6/S15 kiwoom_post() 오류 지속. V19 미이행. 신규 이슈 없음.`

`[2026-04-16 10:58] CRITICAL 지속 — ws_tick_data·trading_signals id 시퀀스 미복구. S8/S9 후보 풀 없음 추가 확인. V19 마이그레이션 미이행.`

`[2026-04-16 10:53] CRITICAL 지속 — ws_tick_data id 시퀀스 미복구. 권고 조치 미이행. 매초 수십 건 INSERT 실패 반복 중.`

## [2026-04-16 10:47] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | websocket-listener | `ws_tick_data.id` NOT NULL 위반 — 모든 틱 INSERT 실패 (0B, 0D 타입) | `[DB] ws_tick_data insert failed [0D 0010F0_AL]: null value in column "id" of relation "ws_tick_data" violates not-null constraint` |
| CRITICAL | postgres | 동일 원인 — 매초 수십 건 ERROR 발생 | `DETAIL: Failing row contains (3.98..., null, null, null, null, 0D, null, null, 2026-04-16 01:47:11.78289, null, 4184, 16666, 0010F0_AL)` |

### 근본 원인
Hibernate `ddl-auto: update`가 V1 마이그레이션의 `id BIGSERIAL PRIMARY KEY` 컬럼을 재생성하면서 `BIGSERIAL` 시퀀스(DEFAULT)를 제거함.  
현재 테이블 상태: `id bigint NOT NULL` (DEFAULT 없음) → 모든 INSERT 실패.

### 권고 조치
- **즉시**: Flyway V19 마이그레이션으로 시퀀스 복구  
  ```sql
  CREATE SEQUENCE IF NOT EXISTS ws_tick_data_id_seq;
  ALTER TABLE ws_tick_data ALTER COLUMN id SET DEFAULT nextval('ws_tick_data_id_seq');
  SELECT setval('ws_tick_data_id_seq', COALESCE((SELECT MAX(id) FROM ws_tick_data), 0) + 1, false);
  ```
- **중기**: `ddl-auto: validate` 또는 `none`으로 전환하여 Hibernate 스키마 자동 변경 방지

---

## [2026-04-16 10:57] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | websocket-listener | `ws_tick_data.id` NOT NULL 위반 지속 — V19 미적용 | `[DB] ws_tick_data insert failed [0B 011790]: null value in column "id"...` |
| CRITICAL | ai-engine / postgres | `trading_signals.id` NOT NULL 위반 추가 발견 — 영향 테이블 확대 | `[DBWriter] insert_python_signal 오류 [000020_AL S3_INST_FRGN]: null value in column "id" of relation "trading_signals"` |
| ERROR | ai-engine | `candidates_builder` S15/S6 빌드 실패 — `kiwoom_post()` 시그니처 불일치 | `[builder] 장중 S15 101 빌드 오류: kiwoom_post() missing 4 required positional arguments: 'url', 'headers', 'json_body', and 'api_id'` |
| WARN | ai-engine | S3 ka10055 페이지 상한(50) 도달 — 루프 강제 종료 | `[S3] ka10055 000150_AL/2 페이지 상한(50) 도달, 루프 강제 종료` |

### 신규 근본 원인
1. **trading_signals.id 시퀀스 소실**: `ws_tick_data`와 동일하게 Hibernate `ddl-auto: update`로 인해 `trading_signals.id`의 BIGSERIAL DEFAULT 제거 → ai-engine 신호 INSERT 전체 실패.
2. **kiwoom_post() 시그니처 불일치**: M-8 리팩토링 후 `candidates_builder.py`가 구형 호출 방식 유지 → S6/S15 후보 풀 미적재.

### 권고 조치
- **즉시 (1)**: V19 마이그레이션에 `trading_signals` 시퀀스 복구 구문 추가 후 api-orchestrator 재기동
  ```sql
  CREATE SEQUENCE IF NOT EXISTS trading_signals_id_seq;
  ALTER TABLE trading_signals ALTER COLUMN id SET DEFAULT nextval('trading_signals_id_seq');
  SELECT setval('trading_signals_id_seq', COALESCE((SELECT MAX(id) FROM trading_signals WHERE id IS NOT NULL), 0) + 1, false);
  ```
- **즉시 (2)**: `candidates_builder.py` 내 `kiwoom_post()` 호출부를 신규 시그니처로 수정
- **확인 필요**: Hibernate 영향받은 테이블 전수 점검 — 모든 `id` 컬럼 DEFAULT 확인

---

## [2026-04-16 11:22] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | ai-engine | Claude API 401 — `invalid x-api-key`. news_analyzer 비기능, confirm_worker 영향 미확인 | `[NewsAnalyzer] Claude API 오류: Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}}` |
| CRITICAL | api-orchestrator | 11:20:53 재시작 확인 — JpaBaseConfiguration WARN, ApplicationStartupRunner `=== Startup Complete ===` 출력, 신규 Kiwoom 토큰 발급(만료: 2026-04-17T06:49:56). 재시작 원인 미특정 | `[Startup] === Startup Complete === [2026-04-16 11:20:55]` |
| CRITICAL | websocket-listener / postgres | `ws_tick_data.id` NOT NULL 위반 지속 — V19 미적용 (35분 이상 지속) | `[DB] ws_tick_data insert failed: null value in column "id"` |
| CRITICAL | ai-engine / postgres | `trading_signals.id` NOT NULL 위반 지속 — V19 미적용 | `[DBWriter] insert_python_signal 오류: null value in column "id" of relation "trading_signals"` |
| ERROR | ai-engine | S5 `ka90003` 전수 조회 폴백 반복 — 후보 풀 미적재 지속 | `[S5] 후보 풀 없음, ka90003 전수 조회 폴백` |

### 신규 근본 원인

1. **Claude API 401**: `ai-engine/.env`의 `CLAUDE_API_KEY`가 무효(만료·교체·오기입). request-id: `req_011Ca6emB5oHDYXePWY7ZhiQ`, model: `claude-sonnet-4-20250514`.
2. **api-orchestrator 재시작**: OOM, 수동 재시작, 또는 헬스체크 실패에 의한 Docker 재시작 추정. 직전 ERROR 로그 없음.

### 권고 조치

- **즉시 (1)**: `ai-engine/.env`의 `CLAUDE_API_KEY` 확인 및 유효한 키로 교체 후 `docker compose up -d --build ai-engine`
- **즉시 (2)**: api-orchestrator 재시작 원인 파악 — `docker compose logs --since 11:19 api-orchestrator` 로 직전 로그 확인, OOM이면 메모리 제한 상향
- **긴급 미해결**: V19 Flyway 마이그레이션 (`ws_tick_data` + `trading_signals` 시퀀스 복구) 미적용 상태 35분 이상 지속 — 즉시 적용 필요

---

## [2026-04-16 11:32] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| ERROR | ai-engine / postgres | `score_components` ON CONFLICT 제약 누락 — signal 3건 INSERT 실패 | `[DBWriter] insert_score_components 오류 signal_id=1: there is no unique or exclusion constraint matching the ON CONFLICT specification` |
| WARN | ai-engine | S8/S9 후보 풀 없음 — `candidates:s8:001/101`, `candidates:s9:001/101` 미적재 | `[S8] candidates:s8:001/101 풀 없음 – candidates_builder 기동 확인 필요` |

### 근본 원인

1. **score_components ON CONFLICT 실패**: `score_components` 테이블에 `ON CONFLICT (signal_id, ...)` 절이 참조하는 UNIQUE 제약이 존재하지 않음. Hibernate `ddl-auto: update`가 이전 마이그레이션이 생성한 UNIQUE 제약을 제거했을 가능성 높음. 또는 해당 제약을 생성한 마이그레이션이 미적용 상태.
2. **S8/S9 풀 없음**: `candidates_builder`가 S8/S9 풀을 아직 적재하지 못했거나, api-orchestrator 재시작 후 풀 재빌드 주기 미도달.

### 권고 조치

- **즉시**: Flyway V21 마이그레이션 생성 — `score_components` 테이블에 UNIQUE 제약 복구
  ```sql
  -- score_components 테이블 UNIQUE 제약 확인 후 필요 시 추가
  -- 예: ON CONFLICT (signal_id) 를 사용한다면:
  ALTER TABLE score_components ADD CONSTRAINT uq_score_components_signal_id UNIQUE (signal_id);
  ```
- **확인**: `db_writer.py`의 `insert_score_components` ON CONFLICT 절 컬럼 확인 후 대상 컬럼에 UNIQUE 제약 추가
- **모니터링**: S8/S9 풀 — 다음 전략 주기(~5분) 이후에도 미적재 시 `candidates_builder.py` S8/S9 빌드 로직 점검

---

## [2026-04-16 11:34] 수집 결과

| 심각도 | 서비스 | 문제 요약 | 로그 발췌 |
|--------|--------|-----------|-----------|
| CRITICAL | api-orchestrator | 반복 재시작 지속 — 11:31 재기동, uptime 43초. 재시작 원인 ERROR 로그 없음(OOM 또는 헬스체크 실패 추정) | `StartedAt: 2026-04-16T02:31:06Z, RestartCount: 0(수동 재기동)` |
| ERROR | postgres | `role "sma_user" does not exist` FATAL — 미등록 역할로 DB 접속 시도 | `FATAL: role "sma_user" does not exist` |
| WARN | ai-engine | S8/S9 후보 풀 없음 지속 — 전략 주기 초과에도 미적재 | `[S8] candidates:s8:001/101 풀 없음`, `[S9] candidates:s9:001/101 풀 없음` |

### 근본 원인

1. **api-orchestrator 반복 재시작**: 11:20, 11:22, 11:31 세 차례 재시작. ERROR 로그 없이 종료 → JVM OOM 또는 Docker 헬스체크 실패(Kiwoom 토큰 발급 지연 등)로 추정. `docker inspect` RestartCount=0 은 `docker compose up` 수동 재기동으로 리셋된 것.
2. **`sma_user` 역할 미존재**: PostgreSQL에 `sma_user` 역할이 없음. Docker Compose healthcheck가 `pg_isready -U sma_user` 형태로 설정되어 있거나, 외부 모니터링 도구가 해당 역할로 접속 시도. postgres 자체는 `(healthy)` 상태이므로 핵심 기능 차단은 없으나 healthcheck 설정 오류.
3. **S8/S9 풀 미적재**: api-orchestrator 재시작으로 인해 candidates_builder 주기가 초기화되어 S8/S9 풀 재빌드 지연.

### 권고 조치

- **즉시 (1)**: api-orchestrator 재시작 원인 확정 — `docker stats stockmate-ai-api-orchestrator-1` 로 메모리 사용량 모니터링, OOM이면 `docker-compose.yml` 메모리 제한 상향 또는 JVM 힙 축소
- **즉시 (2)**: docker-compose.yml healthcheck 확인 — postgres healthcheck의 `-U` 옵션을 실제 존재하는 역할(예: `postgres`)로 교정
- **모니터링**: S8/S9 풀 — api-orchestrator 안정화 후 다음 전략 주기(~5분) 에 자동 적재 예상, 미적재 시 `candidates_builder.py` 직접 확인
