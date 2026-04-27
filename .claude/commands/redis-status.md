Redis 큐 깊이와 전략별 후보 풀 크기를 조회합니다.

다음 정보를 한 번에 출력합니다:
1. 주요 큐 적체 현황 (telegram_queue, ai_scored_queue, vi_watch_queue)
2. S1–S15 전략별 후보 풀 크기 (KOSPI 001 / KOSDAQ 101)

아래 Bash 명령들을 순서대로 실행하고 결과를 표 형태로 정리해 출력하세요:

```bash
# 큐 깊이
docker compose exec redis redis-cli -a cv93523827 llen telegram_queue
docker compose exec redis redis-cli -a cv93523827 llen ai_scored_queue
docker compose exec redis redis-cli -a cv93523827 llen vi_watch_queue
```

```bash
# 전략별 후보 풀 (S1~S15, KOSPI=001 / KOSDAQ=101)
for N in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  K=$(docker compose exec redis redis-cli -a cv93523827 llen "candidates:s${N}:001" 2>/dev/null | tr -d '\r')
  Q=$(docker compose exec redis redis-cli -a cv93523827 llen "candidates:s${N}:101" 2>/dev/null | tr -d '\r')
  echo "S${N}  KOSPI:${K}  KOSDAQ:${Q}"
done
```

풀이 0인 전략은 별도로 강조해서 표시하세요. 0이면 해당 전략에서 신호가 발생하지 않습니다.
