다음 버전 Flyway 마이그레이션 SQL 파일을 생성합니다.

사용법:
- `/new-migration add_tp_sl_columns`
- `/new-migration create_news_events_table`

인자 (파일명 설명부): $ARGUMENTS

다음 단계를 순서대로 수행하세요:

1. `api-orchestrator/src/main/resources/db/migration/` 에서 기존 마이그레이션 파일 목록 조회
2. 현재 최신 버전 번호 확인 (예: V15가 최신이면 신규는 V16)
3. 파일명: `V{N+1}__{인자}.sql` 형식으로 생성
   - 예: `V16__add_tp_sl_columns.sql`

4. 파일 내용은 다음 템플릿 구조로 작성:
```sql
-- V{N}__{설명}.sql
-- 생성일: {오늘날짜}
-- 설명: {변경 내용 한 줄 요약}

-- 여기에 SQL 작성
-- 컬럼 추가: ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...
-- 테이블 생성: CREATE TABLE IF NOT EXISTS ...
-- 인덱스: CREATE INDEX IF NOT EXISTS ...
```

인자가 없으면 사용법을 안내하고 어떤 마이그레이션을 만들지 물어보세요.

주의사항:
- `IF NOT EXISTS` / `IF EXISTS` 방어 구문 필수
- `ddl-auto: update`와 병행 운영 중이므로 기존 테이블 구조와 충돌 여부 확인
- 인덱스는 별도 CREATE INDEX 문으로 분리
