# Redis 연결 복구 가이드

## 원인 분석

`REDIS_HOST=localhost`, 포트 `6379` → Docker가 `6379:6379`로 매핑 중이므로 설정 자체는 올바름.
연결 실패 원인은 **Redis 컨테이너가 실행되지 않았거나**, **비밀번호 불일치** 가능성이 높음.

---

## ⚠️ .env 파일 버그 (즉시 수정 필요)

`api-orchestrator/.env` 12번째 줄에 오타가 있음:

```
# 현재 (잘못됨)
CLAUDE_MODEL=claude-sonnet-4-20250514docker compose ps

# 수정 필요
CLAUDE_MODEL=claude-sonnet-4-20250514
```

`docker compose ps` 명령어가 값에 붙어있어 CLAUDE_MODEL이 잘못된 값으로 설정됨.

---

## 진단 순서

### Step 1. Docker 컨테이너 상태 확인

프로젝트 루트(docker-compose.yml이 있는 폴더)에서 실행:

```bash
docker compose ps
```

**정상 출력 예시:**
```
NAME       STATUS    PORTS
redis      running   0.0.0.0:6379->6379/tcp
postgres   running   0.0.0.0:5432->5432/tcp
```

**redis가 없거나 exited 상태이면 → Step 2로**

---

### Step 2. 컨테이너 시작

```bash
# 루트 디렉토리에 .env 파일이 있는지 확인
ls .env

# 없으면 docker-compose용 .env 생성 (아래 내용으로)
# REDIS_PASSWORD=cv93523827
# POSTGRES_DB=SMA
# POSTGRES_USER=postgres
# POSTGRES_PASSWORD=cv93523827

docker compose up -d redis postgres
```

---

### Step 3. Redis 연결 테스트

```bash
# Redis 컨테이너 내부에서 ping 테스트
docker compose exec redis redis-cli -a cv93523827 ping
# → PONG 이 나오면 정상

# 외부(로컬)에서 연결 테스트
docker compose exec redis redis-cli -a cv93523827 -h localhost -p 6379 ping
```

---

### Step 4. Redis 로그 확인

```bash
docker compose logs redis --tail=50
```

인증 오류나 포트 충돌이 있으면 여기서 확인 가능.

---

### Step 5. 포트 충돌 확인 (Windows)

로컬에서 6379 포트를 이미 사용 중인 프로세스가 있으면 Docker가 바인딩 실패:

```bash
netstat -ano | findstr :6379
```

출력이 있으면 해당 PID를 종료하거나 docker-compose.yml의 포트를 변경해야 함.

---

## docker-compose.yml 루트 .env 파일 예시

`docker-compose.yml`과 **같은 폴더**에 `.env` 파일이 있어야 환경변수가 주입됨:

```env
REDIS_PASSWORD=cv93523827
POSTGRES_DB=SMA
POSTGRES_USER=postgres
POSTGRES_PASSWORD=cv93523827
```

---

## 모든 것이 정상인데도 연결 실패 시

api-orchestrator를 IntelliJ에서 실행 중이라면 `.env` 로딩 방식 확인:

1. IntelliJ → Run Configuration → `EnvFile` 플러그인으로 `.env` 로드 여부 확인
2. 또는 Run Configuration → Environment variables에 직접 `REDIS_HOST=localhost`, `REDIS_PORT=6379`, `REDIS_PASSWORD=cv93523827` 입력
