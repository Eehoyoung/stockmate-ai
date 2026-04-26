# StockMate AI 모니터링 로그

---
### [2026-04-24 10:18 KST] 점검 회차 1
**컨테이너 상태**: 정상 (6/6 Running)
- stockmate-ai-api-orchestrator-1: Up 15분
- stockmate-ai-ai-engine-1: Up 17분
- stockmate-ai-websocket-listener-1: Up 17분
- stockmate-ai-postgres-1: Up 17분 (healthy)
- stockmate-ai-telegram-bot-1: Up 33분
- stockmate-ai-redis-1: Up 9시간 (healthy)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=44

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [경보] vi_watch_queue 44건 적체 — S2 VI 이벤트가 소비되지 않고 누적 중. api-orchestrator의 ViWatchService 처리 여부 확인 필요
- [WARNING] S8 골든크로스 후보 풀 없음 (candidates:s8:001/101) — candidates_builder 미기동 또는 풀 미적재
- [WARNING] S9 눌림목 후보 풀 없음 (candidates:s8:001/101 참조) — S9가 S8 풀 키를 잘못 참조하는 버그 가능성
- [신호 없음 경보] 최근 10분 trading_signals 0건 — 장 중(10:18 KST)임에도 신호 미발생

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_8_golden_cross – [S8] candidates:s8:001/101 풀 없음 – candidates_builder 기동 확인 필요
ai-engine | [WARNING] strategy_9_pullback – [S9] candidates:s8:001/101 풀 없음 – candidates_builder 기동 확인 필요
```
---

---
### [2026-04-24 10:22 KST] 점검 회차 2
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=43

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [CRITICAL] db_writer INSERT 오류 — `[000250 S2_VI_PULLBACK]: INSERT has more target columns than expressions` → S2 신호가 DB에 저장되지 않음. trading_signals 테이블 컬럼 수와 INSERT 쿼리 불일치. 스키마 변경 후 db_writer.py 미동기화 의심
- [경보] vi_watch_queue 43건 적체 — 전 회차(44건) 대비 1건 감소에 불과. S2 DB 오류로 처리 차단 가능성
- [WARNING] S3 기관/외인 페이지 상한 반복 도달 — ka10055 API 50페이지 상한 강제 종료 (074600, 330860, 394280 다수)
- [WARNING] S3 느린 실행 감지 — 235.1초 소요 (timeout=300s 임박)
- [신호 없음 경보] 최근 10분 trading_signals 0건 — S2 DB 오류 영향 가능성

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [000250 S2_VI_PULLBACK]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 330860/1 페이지 상한(50) 도달, 루프 강제 종료
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 394280/2 페이지 상한(50) 도달, 루프 강제 종료
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (235.1s, timeout=300s)
```
---

---
### [2026-04-24 10:26 KST] 점검 회차 3
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=42

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [경보] vi_watch_queue 42건 적체 — 회차별 추이: 44→43→42, 사실상 소비 정지 상태
- [WARNING] S3 느린 실행 악화 — 291.7초 소요 (timeout=300s), 전 회차 235.1s → 악화 추세, 거의 타임아웃 수준
- [WARNING] S3 페이지 상한 반복 — 074600/330860/394280 동일 종목 반복 도달
- [신호 없음 경보] 최근 10분 trading_signals 0건 (3회 연속)
- 전 회차 CRITICAL(db_writer INSERT 오류) 재발 여부: 이번 3분 창에서는 미관측 (vi_watch_queue 적체 지속으로 근본 원인 미해결 추정)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 074600/1 페이지 상한(50) 도달, 루프 강제 종료
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 330860/2 페이지 상한(50) 도달, 루프 강제 종료
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 394280/2 페이지 상한(50) 도달, 루프 강제 종료
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (291.7s, timeout=300s)
```
---

---
### [2026-04-24 10:31 KST] 점검 회차 4
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=44

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [경보] vi_watch_queue 44건 — 추이: 44→43→42→44, 소비보다 유입이 많아 큐 증가 반전. S2 INSERT 오류로 소비 차단 확정
- [WARNING] S3 느린 실행 지속 — 237.3s (3·4회차 모두 ~235-292s 범위, 구조적 문제)
- [WARNING] S3 페이지 상한 — 000210/014620/074600/330860/394280 (종목 다양화, 매 사이클 동일 패턴)
- [WARNING] S5 프로그램매수 느린 실행 신규 — 84.9s 감지 (S3 장기 선점에 따른 연쇄 지연 의심)
- [WARNING] S15 모멘텀정렬 느린 실행 신규 — 30.8s 감지
- [신호 없음 경보] 최근 10분 trading_signals 0건 (4회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (84.9s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (30.8s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 394280/2 페이지 상한(50) 도달, 루프 강제 종료
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (237.3s, timeout=300s)
```
---

---
### [2026-04-24 10:36 KST] 점검 회차 5
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=4

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [개선] vi_watch_queue 44→4 급감 — api-orchestrator 10:35 intraday preload 타이밍에 소비된 것으로 추정. 근본 원인(db_writer 오류)은 미해결
- [CRITICAL] db_writer INSERT 오류 확산 — 2회차 S2_VI_PULLBACK에 이어 이번엔 S3_INST_FRGN도 동일 오류. `trading_signals` INSERT 컬럼 불일치가 전략 전반에 걸친 구조적 버그로 확인
- [WARNING] S3 느린 실행 지속 — 247.6s (매 사이클 235~292s, 5회 연속)
- [WARNING] S5 느린 실행 지속 — 84.5s (2회 연속)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (5회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [000210 S3_INST_FRGN]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (84.5s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 394280/2 페이지 상한(50) 도달, 루프 강제 종료
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (247.6s, timeout=300s)
```
---

---
### [2026-04-24 10:41 KST] 점검 회차 6
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=37

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [CRITICAL] db_writer INSERT 오류 3개 전략으로 확산 확정 — S2_VI_PULLBACK(2회차) + S3_INST_FRGN(5회차) + **S15_MOMENTUM_ALIGN(6회차)** → insert_python_signal()이 모든 전략 공통 실패. trading_signals 테이블에 컬럼 추가 후 INSERT 쿼리 미동기화
- [경보] vi_watch_queue 4→37 재증가 — 5회차 일시 감소는 vi 이벤트 유입 공백이었던 것으로 확인. 근본 원인 미해결
- [WARNING] S3 느린 실행 6회 연속 (~235~292s 구조적 반복)
- [WARNING] S5 느린 실행 3회 연속 — 85.9s
- [WARNING] S15 느린 실행 2회 연속 — 30.4s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (6회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [092220 S15_MOMENTUM_ALIGN]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (85.9s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (30.4s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 330860/2 페이지 상한(50) 도달, 루프 강제 종료
```
---

---
### [2026-04-24 10:45 KST] 점검 회차 7
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=41

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [경보] vi_watch_queue 37→41 재증가 — 계속 유입 중, 소비 차단 지속
- [WARNING] S8 골든크로스 / S9 눌림목 후보 풀 없음 재등장 — candidates:s8:001/101 미적재 (1회차 이후 반복 패턴)
- [WARNING] S3 느린 실행 7회 연속 — 이번 창에서도 5개 종목 페이지 상한 도달, 사이클 점유 지속
- [WARNING] S5 느린 실행 4회 연속 — 84.5s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (7회 연속)
- db_writer INSERT 오류: 이번 4분 창에서는 미관측 (S3 사이클 진행 중으로 아직 INSERT 단계 미도달 추정)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_8_golden_cross – [S8] candidates:s8:001/101 풀 없음 – candidates_builder 기동 확인 필요
ai-engine | [WARNING] strategy_9_pullback – [S9] candidates:s8:001/101 풀 없음 – candidates_builder 기동 확인 필요
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (84.5s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 330860/2 페이지 상한(50) 도달, 루프 강제 종료
```
---

---
### [2026-04-24 10:50 KST] 점검 회차 8
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=4

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [패턴 확인] vi_watch_queue 급감 원인 규명 — 10:35·10:50 두 차례 api-orchestrator `[Pool] intraday preload complete` 직후 →4 패턴. preload가 약 15분 주기로 큐를 부분 소비하나 완전 소화 못함(잔여 ~4건). 근본 원인(db_writer INSERT 오류) 여전히 미해결
- [WARNING] S3 느린 실행 8회 연속 — 238.0s
- [WARNING] S5 느린 실행 악화 — 113.2s (전 회차 84.5s 대비 33% 증가)
- [WARNING] S15 느린 실행 3회 연속 — 37.8s
- [WARNING] S8/S9 후보 풀 없음 지속
- [신호 없음 경보] 최근 10분 trading_signals 0건 (8회 연속)

**관련 로그 발췌**:
```
api-orchestrator | [Pool] intraday preload complete (10:50:02 KST) → vi_watch_queue 41→4
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (238.0s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (113.2s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (37.8s, timeout=300s)
ai-engine | [WARNING] strategy_8_golden_cross – [S8] candidates:s8:001/101 풀 없음
ai-engine | [WARNING] strategy_9_pullback – [S9] candidates:s8:001/101 풀 없음
```
---

---
### [2026-04-24 10:55 KST] 점검 회차 9
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=35

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [CRITICAL] db_writer INSERT 오류 4번째 전략 확산 — S8_GOLDEN_CROSS [090430] 신규 추가. 누적 확인: S2·S3·S8·S15 → insert_python_signal() 전략 무관 공통 실패 확정
- [경보] vi_watch_queue 4→35 재증가 — preload 직후 ~15분 만에 31건 유입, 사이클 반복
- [WARNING] S3 느린 실행 9회 연속 — 265.6s (전 회차 238.0s 대비 재증가)
- [WARNING] S5 느린 실행 5회 연속 — 90.2s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (9회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [090430 S8_GOLDEN_CROSS]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (265.6s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (90.2s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 394280/2 페이지 상한(50) 도달, 루프 강제 종료
```
---

---
### [2026-04-24 11:00 KST] 점검 회차 10
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=34

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [CRITICAL] db_writer INSERT 오류 재발 — S2_VI_PULLBACK [014620] (2회차 000250에 이어 동일 전략 다른 종목). 전략·종목 무관 공통 실패 재확인
- [경보] vi_watch_queue 34건 — preload 후 계속 재적체 중 (다음 preload까지 ~5분 남음)
- [WARNING] S3 느린 실행 10회 연속 — 247.0s
- [WARNING] S5 느린 실행 6회 연속 — 96.6s (84→85→84→113→90→96, 증가 추세)
- [WARNING] S15 느린 실행 4회 연속 — 33.7s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (10회 연속)
- [INFO] api-orchestrator expired old signals count=1 — 만료 신호 1건 정리 (정상 동작)

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [014620 S2_VI_PULLBACK]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (247.0s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (96.6s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (33.7s, timeout=300s)
```
---

---
### [2026-04-24 11:04 KST] 점검 회차 11
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=30

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [CRITICAL] db_writer INSERT 오류 재발 — S2_VI_PULLBACK [003030] (S2 세 번째 종목: 000250→014620→003030). 매 사이클 반복
- [경고] S3 느린 실행 역대 최고 — 289.4s (타임아웃 300s까지 10.6s 남음, 11회 연속)
- [경보] vi_watch_queue 30건 — 11:05:00 preload 완료 직전 측정. 이전 preload 후 잔여량(30건)은 이전 패턴(4건 잔여)보다 많음
- [INFO] api-orchestrator 토큰 갱신 완료 (11:02:17, 만료 2026-04-25 07:19:56) — 정상
- [INFO] intraday preload complete (11:05:00) — 15분 주기 정상 동작
- [신호 없음 경보] 최근 10분 trading_signals 0건 (11회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [003030 S2_VI_PULLBACK]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (289.4s, timeout=300s) ← 역대 최고
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 394280/2 페이지 상한(50) 도달, 루프 강제 종료
api-orchestrator | 토큰 갱신 완료 - 만료: 2026-04-25T07:19:56
```
---

---
### [2026-04-24 11:09 KST] 점검 회차 12
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=30

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [CRITICAL] db_writer INSERT 오류 2건 연속 발생 — S3_INST_FRGN [000210] 11:05:48 + [394280] 11:08:29. 한 사이클 내 2건 오류, 신호 생성 자체는 되고 있으나 저장 전부 실패
- [경보] vi_watch_queue 30건 — 11:05:00 preload 후에도 30건 유지. 이전 패턴(→4건) 대비 처리량 감소 또는 VI 유입 급증
- [WARNING] S14 과매도반등 느린 실행 신규 — 41.8s (처음 감지. S3 연쇄 지연이 더 많은 전략으로 확산)
- [WARNING] S3 느린 실행 12회 연속 — 267.0s
- [WARNING] S5 느린 실행 7회 연속 — 99.6s (증가 추세: 84→99.6s)
- [WARNING] S15 느린 실행 5회 연속 — 40.8s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (12회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [000210 S3_INST_FRGN]: INSERT has more target columns than expressions
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [394280 S3_INST_FRGN]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (267.0s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (99.6s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S14] 느린 실행 감지 (41.8s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (40.8s, timeout=300s)
```
---

---
### [2026-04-24 11:14 KST] 점검 회차 13
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=29

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [CRITICAL] db_writer INSERT 오류 — S2_VI_PULLBACK [023160] (S2 4번째 종목). 매 사이클 반복
- [경고] S3 292.4s — 타임아웃(300s)까지 7.6초. 역대 두 번째 최고값 (최고: 11회차 289.4s와 근사)
- [경보] vi_watch_queue 29건 — 거의 변화 없음 (30→29). 다음 preload는 11:20 예상
- [WARNING] S9 후보 풀 없음 재등장
- [WARNING] S5 느린 실행 8회 연속 — 91.6s
- [WARNING] S15 느린 실행 6회 연속 — 31.7s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (13회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [023160 S2_VI_PULLBACK]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S3] 느린 실행 감지 (292.4s, timeout=300s) ← 타임아웃 7.6초 전
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (91.6s, timeout=300s)
ai-engine | [WARNING] strategy_9_pullback – [S9] candidates:s8:001/101 풀 없음
```
---

---
### [2026-04-24 11:19 KST] 점검 회차 14
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=27

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [주목] S3 후보 종목 교체 확인 — 이전 고정 5종목(000210/074600/330860/394280/014620)에서 005440/008770/034020/014620/027360/036540으로 변경. 11:05 intraday preload 후 후보 풀 갱신. 페이지 상한 패턴 동일, 종목 수는 6개로 증가
- [WARNING] S3 느린 실행 14회 연속 — 이번 사이클 진행 중 (6종목 진행, 이전 5종목보다 1개 추가)
- [WARNING] S8/S9 후보 풀 없음 반복
- [WARNING] S5 느린 실행 9회 연속 — 87.6s
- [WARNING] S15 느린 실행 7회 연속 — 30.1s
- db_writer INSERT 오류: 이번 5분 창 미관측 (S3 사이클 아직 INSERT 단계 미도달)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (14회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_8_golden_cross – [S8] candidates:s8:001/101 풀 없음
ai-engine | [WARNING] strategy_9_pullback – [S9] candidates:s8:001/101 풀 없음
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (87.6s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (30.1s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 036540/1 페이지 상한(50) 도달 (신규 6번째 종목)
```
---

---
### [2026-04-24 11:23 KST] 점검 회차 15
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=27

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 최초 발생 — `[Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s` (11:20:17). 14회차 예상대로 종목 6개로 증가 후 300s 초과. 타임아웃 후 즉시 다음 사이클에서 S3 재시작 중
- [경보] vi_watch_queue 27건 — 11:20:02 preload 후에도 27건 유지 (이전 패턴과 달리 preload가 큐 미소비). vi_watch_queue 처리 방식 변화 또는 유입량 급증
- [WARNING] S3 15회 연속 — 타임아웃 후 재시작, 현재 진행 중
- [WARNING] S5 느린 실행 10회 연속 — 91.9s
- [WARNING] S15 느린 실행 8회 연속 — 31.5s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (15회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s ← 최초 타임아웃
api-orchestrator | [Pool] intraday preload complete (11:20:02 KST)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (91.9s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (31.5s, timeout=300s)
```
---

---
### [2026-04-24 11:28 KST] 점검 회차 16
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=25

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 2회 연속 — 11:26:17 `전략 실행 타임아웃 (300s) - 강제 취소`. 15·16회차 연속 타임아웃, 매 사이클 반복 확정
- [주목] S3 타임아웃 후 INSERT 오류 미발생 — 타임아웃 시 INSERT 단계 미도달. 역설적으로 INSERT 오류가 안 보이는 것은 S3가 신호를 생성조차 못하고 있음을 의미
- [경보] vi_watch_queue 25건 — 완만 감소 (27→25). 자연 소비 중이나 근본 원인 미해결
- [WARNING] S5 느린 실행 11회 연속 — 88.9s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (16회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (11:26:17 - 2회 연속)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (88.9s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 036540/1 페이지 상한(50) 도달, 루프 강제 종료 (6번째 종목)
```
---

---
### [2026-04-24 11:33 KST] 점검 회차 17
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=1(측정시) / vi_watch_queue=30

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 3회 연속 — 11:32:17 `전략 실행 타임아웃 (300s) - 강제 취소`. 15·16·17회차 매 사이클 타임아웃 확정
- [주목] ai_scored_queue 최초 1건 감지 — 측정 시 1건 존재, LRANGE 확인 시 이미 소비됨. telegram-bot이 신호를 수신했으나 trading_signals DB에는 0건 → db_writer INSERT 오류로 DB 저장 실패 확인
- [CRITICAL] db_writer INSERT 오류 재발 — S2_VI_PULLBACK [010060] 11:33:25 (S2 5번째 종목). S3 타임아웃 후 S2가 처리되어 신호 생성됐으나 저장 실패
- [경보] vi_watch_queue 25→30 재증가 — 새 VI 이벤트 유입 중
- [WARNING] S5 느린 실행 12회 연속 — 88.9s (전 회차와 동일)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (17회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (11:32:17 - 3회 연속)
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [010060 S2_VI_PULLBACK]: INSERT has more target columns than expressions
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (88.9s, timeout=300s)
```
---

---
### [2026-04-24 11:38 KST] 점검 회차 18
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=8

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 4회 연속 — 11:38:17 `전략 실행 타임아웃 (300s) - 강제 취소`. 15~18회차 매 사이클 타임아웃 확정
- [확인] vi_watch_queue 30→8 — 11:35:00 preload(5번째: 10:35/10:50/11:05/11:20/11:35) 직후 소비. 15분 주기 정확 확정
- [WARNING] S3 INSERT 오류: 이번 창 미관측 (타임아웃으로 INSERT 미도달)
- [WARNING] S5 느린 실행 13회 연속 — 96.6s
- [WARNING] S15 느린 실행 9회 연속 — 36.6s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (18회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (11:38:17 - 4회 연속)
api-orchestrator | [Pool] intraday preload complete (11:35:00 KST) → vi_watch_queue 30→8
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (96.6s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (36.6s, timeout=300s)
```
---

---
### [2026-04-24 11:42 KST] 점검 회차 19
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=2

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 5회 연속 진행 중 — 11:38:17 4회차 완료, 현 사이클 11:40:28~진행 중 (027360/2 완료, 036540/061970/074600 잔여. ~11:44:30 타임아웃 예상)
- [확인] vi_watch_queue 8→2 — 11:35 preload 이후 자연 감소. 거의 소진 (다음 preload 11:50 예정)
- [WARNING] S5 느린 실행 14회 연속 — 92.9s
- db_writer INSERT 오류: 이번 창 미관측 (S3 타임아웃으로 INSERT 미도달)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (19회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (11:38:17)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (92.9s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 027360/2 페이지 상한(50) 도달, 루프 강제 종료 (5번째 종목 완료, 타임아웃 진행 중)
```
---

---
### [2026-04-24 11:47 KST] 점검 회차 20
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=16

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 5회 연속 완료 — 11:44:17 타임아웃 (15~19회차 연속). 현 사이클 재시작 중 (~11:50:30 6번째 타임아웃 예상)
- [경보] vi_watch_queue 2→16 재증가 — 11:44 이후 새 VI 이벤트 유입. 다음 preload(11:50) 전 누적 중
- [WARNING] S8/S9 후보 풀 없음 반복
- [WARNING] S5 느린 실행 15회 연속 — 98.6s
- [WARNING] S15 느린 실행 10회 연속 — 31.1s
- [신호 없음 경보] 최근 10분 trading_signals 0건 (20회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (11:44:17 - 5회 연속)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (98.6s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (31.1s, timeout=300s)
ai-engine | [WARNING] strategy_8_golden_cross – [S8] candidates:s8:001/101 풀 없음
```
---

---

---
### [2026-04-24 11:52 KST] 점검 회차 21
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=16

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 6회 연속 — 11:50:17 타임아웃. 15~20회차 연속
- [CRITICAL] db_writer INSERT 오류 재발 — S8_GOLDEN_CROSS [092220] 11:52:13. 타임아웃 틈새에 S8 신호 생성됐으나 저장 실패
- [경보] vi_watch_queue 16건 — 11:50:02 preload 후에도 16건 유지 (이번 preload는 큐 미소비)
- [WARNING] S3 6번째 사이클 재시작 중 — 11:52:26 005440/2부터 진행
- [신호 없음 경보] 최근 10분 trading_signals 0건 (21회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (11:50:17 - 6회 연속)
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [092220 S8_GOLDEN_CROSS]: INSERT has more target columns than expressions
api-orchestrator | [Pool] intraday preload complete (11:50:02 KST) — vi_watch_queue 미소비(16건 유지)
```
---

---
### [2026-04-24 11:57 KST] 점검 회차 22
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=15

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 7회 연속 — 11:56:17 타임아웃. 15~21회차 연속. 이번 사이클 종목 순서: 005440→008770→034020→014620→027360→036540→061970→074600(타임아웃)
- [확인] vi_watch_queue 15건 — 16→15, 자연 감소 중. 다음 preload 12:05 예정
- [WARNING] S5 느린 실행 16회 연속 — 88.5s
- db_writer INSERT 오류: 이번 창 미관측 (타임아웃으로 INSERT 미도달)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (22회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (11:56:17 - 7회 연속)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (88.5s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 074600/1 페이지 상한(50) 도달, 루프 강제 종료 (타임아웃)
```
---

---
### [2026-04-24 12:02 KST] 점검 회차 23
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=15

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 8회 연속 타임아웃 진행 중 — 036540/1 진행 중, ~12:03:30 타임아웃 예상
- [WARNING] S5 느린 실행 악화 — 103.6s (전 회차 88.5s에서 급증, 100s 돌파)
- [WARNING] S15 느린 실행 11회 연속 — 34.1s
- [확인] vi_watch_queue 15건 — 변화 없음. 다음 preload 12:05 예정
- [신호 없음 경보] 최근 10분 trading_signals 0건 (23회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (103.6s, timeout=300s) ← 100s 돌파
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (34.1s, timeout=300s)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 036540/1 페이지 상한(50) 도달, 루프 강제 종료 (8번째 타임아웃 진행 중)
```
---

---
### [2026-04-24 12:06 KST] 점검 회차 24
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=17

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 8회 연속 완료 — 12:02:17 타임아웃. 15~22회차 연속. 9번째 사이클 027360/2까지 진행 중
- [경보] vi_watch_queue 15→17 증가 — 12:05:00 preload 후에도 증가. 새 VI 이벤트 유입이 preload 소비를 초과
- [WARNING] S5 느린 실행 17회 연속 — 86.6s (전 회차 103.6s에서 감소)
- [INFO] 12:05:00 intraday preload complete (7번째, 정상)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (24회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:02:17 - 8회 연속)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (86.6s, timeout=300s)
api-orchestrator | [Pool] intraday preload complete (12:05:00 KST) — vi_watch_queue 미소비(15→17 증가)
```
---

---
### [2026-04-24 12:11 KST] 점검 회차 25
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=17

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 9회 연속 — 12:08:17 타임아웃. 15~23회차 연속. 10번째 사이클 진행 중
- [경고] S5 느린 실행 악화 — 114.9s (역대 최고치. 직전 최고: 113.2s 8회차)
- [경고] S15 느린 실행 급등 — 64.1s (기존 30~40s에서 거의 2배 급등, 심각한 연쇄 지연)
- [WARNING] S9 후보 풀 없음 재등장
- [경보] vi_watch_queue 17건 — 유지, preload 미소비 패턴 지속
- [신호 없음 경보] 최근 10분 trading_signals 0건 (25회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:08:17 - 9회 연속)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (114.9s, timeout=300s) ← 역대 최고
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (64.1s, timeout=300s) ← 급등
```
---

---
### [2026-04-24 12:16 KST] 점검 회차 26
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=2

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 10회 연속 — 12:14:17 타임아웃. 15~24회차 연속. 11번째 사이클 005440/2~진행 중
- [확인] vi_watch_queue 17→2 자연 감소 — preload 없이 15→2 감소. VI 이벤트 유입 감소 또는 자연 소진
- [개선] S15 느린 실행 완화 — 64.1s(25회차)→33.1s(회복). 일시적 변동
- [WARNING] S8/S9 후보 풀 없음 반복
- db_writer INSERT 오류: 이번 창 미관측 (타임아웃으로 INSERT 미도달)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (26회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:14:17 - 10회 연속)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (33.1s, timeout=300s)
ai-engine | [WARNING] strategy_8_golden_cross – [S8] candidates:s8:001/101 풀 없음
ai-engine | [WARNING] strategy_9_pullback – [S9] candidates:s8:001/101 풀 없음
```
---

---
### [2026-04-24 12:18 KST] 점검 회차 27
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=10

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 11회 연속 — 12:14:17 타임아웃 후 재시작. 014620/2 페이지 상한 도달 중(12:18:22). 11번째 사이클 진행 중
- [WARNING] S5 느린 실행 — 87.6s (12:16:44)
- [WARNING] S15 느린 실행 — 33.1s (12:16:16)
- [WARNING] S8/S9 후보 풀 없음 반복 (12:15:43)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (27회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:14:17 - 11회 연속)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 014620/2 페이지 상한(50) 도달 (12:18:22)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (87.6s, timeout=300s)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (33.1s, timeout=300s)
```
---

---
### [2026-04-24 12:21 KST] 점검 회차 28
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=10

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 12회 연속 — 12:20:17 타임아웃. 74600 종목 1페이지 상한 도달 후 300s 초과
- [WARNING] S8/S9 후보 풀 없음 지속
- [신호 없음 경보] 최근 10분 trading_signals 0건 (28회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:20:17 - 12회 연속)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 074600/1 페이지 상한(50) 도달 (12:20:12)
```
---

---
### [2026-04-24 12:25 KST] 점검 회차 29
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=10

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 13회 연속 진행 중 — 12:20:17 타임아웃 후 재시작, 008770→034020→014620→027360 순회 중 (12:25:44 현재)
- [WARNING] S5 느린 실행 — 106.3s (12:23:03, 악화 추세)
- [WARNING] S14 느린 실행 — 50.2s (12:23:12)
- [WARNING] S15 느린 실행 — 32.8s (12:23:36)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (29회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (106.3s, timeout=300s) (12:23:03)
ai-engine | [WARNING] strategy_runner – [Runner] [S14] 느린 실행 감지 (50.2s, timeout=300s) (12:23:12)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (32.8s, timeout=300s) (12:23:36)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 027360/1 페이지 상한(50) 도달 (12:25:44)
```
---

---
### [2026-04-24 12:30 KST] 점검 회차 30
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=13

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 13회 연속 진행 중 — 재시작 후 005440→008770→034020→014620→027360 순회 중 (12:30:40 현재)
- [WARNING] S5 느린 실행 — 87.9s (12:28:45, 전회 106.3s → 완화)
- [WARNING] S15 느린 실행 — 30.4s (12:28:48)
- [경보] vi_watch_queue 10→13 소폭 증가 — 새 VI 이벤트 유입
- [신호 없음 경보] 최근 10분 trading_signals 0건 (30회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (87.9s, timeout=300s) (12:28:45)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (30.4s, timeout=300s) (12:28:48)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 027360/1 페이지 상한(50) 도달 (12:30:40)
```
---

---
### [2026-04-24 12:35 KST] 점검 회차 31
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=13

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 14회 연속 진행 중 — 재시작 후 005440→008770 순회 중 (12:35:13 현재)
- [WARNING] S5 느린 실행 — 94.2s (12:34:51)
- [WARNING] S15 느린 실행 — 35.4s (12:34:51)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (31회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (94.2s, timeout=300s) (12:34:51)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (35.4s, timeout=300s) (12:34:51)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 008770/1 페이지 상한(50) 도달 (12:35:13)
```
---

---
### [2026-04-24 12:40 KST] 점검 회차 32
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=10

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 14회 연속 확정 — 12:38:17 타임아웃 (036540/1 페이지 상한 후 300s 초과)
- [경보] vi_watch_queue 13→10 소폭 감소
- [신호 없음 경보] 최근 10분 trading_signals 0건 (32회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:38:17 - 14회 연속)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 036540/1 페이지 상한(50) 도달 (12:38:05)
```
---

---
### [2026-04-24 12:44 KST] 점검 회차 33
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=10

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 15회 연속 확정 — 12:44:17 타임아웃 (061970/1 페이지 상한 후 300s 초과)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (33회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:44:17 - 15회 연속)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 061970/1 페이지 상한(50) 도달 (12:44:00)
```
---

---
### [2026-04-24 12:49 KST] 점검 회차 34
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=9

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 16회 연속 진행 중 — 재시작 후 008770→034020→014620→027360 순회 중 (12:49:27 현재)
- [WARNING] S5 느린 실행 — 94.9s (12:46:52)
- [경보] vi_watch_queue 10→9 소폭 감소
- [신호 없음 경보] 최근 10분 trading_signals 0건 (34회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (94.9s, timeout=300s) (12:46:52)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 027360/1 페이지 상한(50) 도달 (12:49:27)
```
---

---
### [2026-04-24 12:54 KST] 점검 회차 35
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=13

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 16회 연속 진행 중 — 재시작 후 005440→008770→034020→014620 순회 중 (12:54:27 현재)
- [WARNING] S5 느린 실행 — 89.2s (12:52:46)
- [경보] vi_watch_queue 9→13 소폭 증가 — 새 VI 이벤트 유입
- [신호 없음 경보] 최근 10분 trading_signals 0건 (35회 연속)

**관련 로그 발췌**:
```
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (89.2s, timeout=300s) (12:52:46)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 014620/2 페이지 상한(50) 도달 (12:54:27)
```
---

---
### [2026-04-24 12:59 KST] 점검 회차 36
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=4

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 17회 연속 확정 — 12:56:17 타임아웃
- [ERROR] db_writer INSERT 오류 재관측 — 12:57:57 S8_GOLDEN_CROSS 090430 종목: "INSERT has more target columns than expressions"
- [WARNING] S5 느린 실행 — 99.9s (12:58:57)
- [WARNING] S15 느린 실행 — 31.8s (12:58:47)
- [주목] vi_watch_queue 13→4 대폭 감소 — preload 또는 S2 처리로 드레인
- [신호 없음 경보] 최근 10분 trading_signals 0건 (36회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (12:56:17 - 17회 연속)
ai-engine | [ERROR] db_writer – [DBWriter] insert_python_signal error [090430 S8_GOLDEN_CROSS]: INSERT has more target columns than expressions (12:57:57)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (99.9s, timeout=300s) (12:58:57)
ai-engine | [WARNING] strategy_runner – [Runner] [S15] 느린 실행 감지 (31.8s, timeout=300s) (12:58:47)
```
---

---
### [2026-04-24 13:03 KST] 점검 회차 37
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=13

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 18회 연속 확정 — 13:02:17 타임아웃 (036540/1 페이지 상한 후 300s 초과)
- [경보] vi_watch_queue 4→13 재증가 — 새 VI 이벤트 유입
- [신호 없음 경보] 최근 10분 trading_signals 0건 (37회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (13:02:17 - 18회 연속)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 036540/1 페이지 상한(50) 도달 (13:02:04)
```
---

---
### [2026-04-24 13:08 KST] 점검 회차 38
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=13

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 19회 연속 확정 — 13:08:17 타임아웃 (074600/1 페이지 상한 후 300s 초과)
- [신호 없음 경보] 최근 10분 trading_signals 0건 (38회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] strategy_runner – [Runner] [S3] 전략 실행 타임아웃 (300s) - 강제 취소 elapsed=300.0s (13:08:17 - 19회 연속)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 074600/1 페이지 상한(50) 도달 (13:08:14)
```
---

---
### [2026-04-24 13:13 KST] 점검 회차 39
**컨테이너 상태**: 정상 (6/6 Running)

**Redis 큐**: telegram_queue=0 / ai_scored_queue=0 / vi_watch_queue=20

**DB**: 최근10분 신호=0건 / open_positions=20건 / ai_cancel=0건

**감지된 이슈**:
- [ERROR] S3 타임아웃 20회 연속 진행 중 — 재시작 후 005440→008770→034020→014620→027360 순회 중 (13:13:20 현재)
- [ERROR] http_utils ka10032 서버 연결 끊김 — 13:11:07 "Server disconnected without sending a response." (Kiwoom API 일시 불안정)
- [WARNING] S5 느린 실행 — 97.2s (13:10:54)
- [경보] vi_watch_queue 13→20 증가 — 새 VI 이벤트 다수 유입
- [신호 없음 경보] 최근 10분 trading_signals 0건 (39회 연속)

**관련 로그 발췌**:
```
ai-engine | [ERROR] http_utils – [http_utils] ka10032 요청 오류: Server disconnected without sending a response. (13:11:07)
ai-engine | [WARNING] strategy_runner – [Runner] [S5] 느린 실행 감지 (97.2s, timeout=300s) (13:10:54)
ai-engine | [WARNING] strategy_3_inst_foreign – [S3] ka10055 027360/1 페이지 상한(50) 도달 (13:13:20)
```
---

---
## 모니터링 세션 종료: [2026-04-24 13:18 KST] (사용자 요청)
총 39회차 점검 완료 (10:18 ~ 13:18 KST, 약 3시간).

### 주요 이슈 요약:

**[CRITICAL] S3 전략 타임아웃 연속 발생 — 전 세션 미해결**
- 회차 15 (약 10:50)부터 회차 39 (13:18)까지 **매 사이클 300s 타임아웃** 반복
- 원인: `strategy_3_inst_foreign.py` ka10055 API 페이지 상한(50) 반복 도달 → 종목당 ~17s × 최대 8종목 × 2페이지 = 300s 초과
- 영향: S5(프로그램 매수) 80~106s 지연, S14(과매도 반등) 50s 지연, S15(모멘텀 정렬) 30~35s 지연 유발

**[CRITICAL] db_writer INSERT 컬럼 불일치 — 전 세션 미해결**
- 모든 전략 신호의 DB 저장 실패: "INSERT has more target columns than expressions"
- 확인 전략: S2_VI_PULLBACK, S3_INST_FRGN, S8_GOLDEN_CROSS, S15_MOMENTUM_ALIGN
- 결과: trading_signals 0건 **39회 연속** (10:18~13:18 전 기간)

**[HIGH] S8/S9 후보 풀 공백 — 전 세션 미해결**
- `candidates:s8:001`, `candidates:s8:101` 키 지속 미적재
- S8(골든크로스), S9(눌림목) 전략 스킵 반복

**[MEDIUM] vi_watch_queue 진동 — 10~44건 반복 증감**
- websocket-listener 신규 VI 이벤트 지속 유입
- TradingScheduler 15분 preload 시 부분 드레인 반복

**[MEDIUM] Kiwoom API 서버 연결 끊김 1회**
- 13:11:07 ka10032 "Server disconnected without sending a response" (1회, 자동 복구)
---

---
### [2026-04-25 00:02 KST] 점검 회차 40
**컨테이너 상태**: 이상 — 전체 6개 컨테이너 Exited
- stockmate-ai-api-orchestrator-1: Exited (143)
- stockmate-ai-ai-engine-1: Exited (0)
- stockmate-ai-websocket-listener-1: Exited (0)
- stockmate-ai-postgres-1: Exited (0)
- stockmate-ai-telegram-bot-1: Exited (1)
- stockmate-ai-redis-1: Exited (0)
**Redis 큐**: 측정 불가 (컨테이너 중지)
**DB**: 측정 불가 (컨테이너 중지)
**감지된 이슈**:
- 전체 스택 다운 — 코드 수정 후 재기동 대기 상태
- 마지막 정상 운영: 2026-04-24 23:45 KST (api-orchestrator 종료 시각 기준)
- 장 외 시간대 (00:02 KST) — 오전 장 전 재기동 필요
---
