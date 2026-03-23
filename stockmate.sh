#!/usr/bin/env bash
# stockmate.sh – StockMate AI 통합 진입점
#
# 실행 순서:
#   1. api-orchestrator (Java JAR) 기동
#   2. Java /health 응답 대기
#   3. Python ws-listener, ai-engine + Node telegram-bot (PM2)
#
# 사용법:
#   ./stockmate.sh          # 전체 시작
#   ./stockmate.sh stop     # 전체 중지
#   ./stockmate.sh restart  # 전체 재시작
#   ./stockmate.sh status   # 상태 확인
#   ./stockmate.sh logs     # 통합 로그 (pm2)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAR="$ROOT_DIR/api-orchestrator/build/libs/api-orchestrator-0.0.1-SNAPSHOT.jar"
JAVA_HEALTH="http://localhost:8080/api/trading/health"
JAVA_PID_FILE="$ROOT_DIR/.java.pid"
JAVA_LOG="$ROOT_DIR/logs/api-orchestrator.log"
MAX_WAIT=120   # Java 기동 최대 대기 초

mkdir -p "$ROOT_DIR/logs"

# ── 헬퍼 ────────────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
die()  { echo "❌ $*" >&2; exit 1; }

# ── Java 기동 ────────────────────────────────────────────────────
start_java() {
    if [[ ! -f "$JAR" ]]; then
        log "JAR 없음 → Gradle 빌드 시작..."
        (cd "$ROOT_DIR/api-orchestrator" && ./gradlew bootJar -q) \
            || die "Gradle 빌드 실패"
    fi

    log "api-orchestrator 시작..."
    nohup java -jar "$JAR" \
        --spring.profiles.active=prod \
        >> "$JAVA_LOG" 2>&1 &
    echo $! > "$JAVA_PID_FILE"
    log "api-orchestrator PID=$(cat "$JAVA_PID_FILE")"
}

wait_java_health() {
    log "Java /health 응답 대기 (최대 ${MAX_WAIT}초)..."
    local elapsed=0
    until curl -sf "$JAVA_HEALTH" > /dev/null 2>&1; do
        if (( elapsed >= MAX_WAIT )); then
            die "api-orchestrator 기동 타임아웃 (${MAX_WAIT}s)"
        fi
        sleep 5
        (( elapsed += 5 ))
        log "  대기 중... (${elapsed}s)"
    done
    log "✅ api-orchestrator 준비 완료"
}

# ── PM2 기동 ─────────────────────────────────────────────────────
start_pm2() {
    if ! command -v pm2 &> /dev/null; then
        die "PM2 미설치 – 'npm install -g pm2' 실행 후 재시도"
    fi
    log "PM2 서비스 시작 (ws-listener, ai-engine, telegram-bot)..."
    pm2 start "$ROOT_DIR/ecosystem.config.js"
    pm2 save
    log "✅ PM2 서비스 시작 완료"
    pm2 list
}

# ── 중지 ─────────────────────────────────────────────────────────
stop_all() {
    log "전체 서비스 중지..."

    # PM2 프로세스 중지
    if command -v pm2 &> /dev/null; then
        pm2 stop ecosystem.config.js 2>/dev/null || true
        log "PM2 서비스 중지됨"
    fi

    # Java 프로세스 중지
    if [[ -f "$JAVA_PID_FILE" ]]; then
        local pid; pid=$(cat "$JAVA_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            log "api-orchestrator (PID=$pid) 중지됨"
        fi
        rm -f "$JAVA_PID_FILE"
    fi
}

# ── 상태 확인 ─────────────────────────────────────────────────────
show_status() {
    echo ""
    echo "=== api-orchestrator ==="
    if [[ -f "$JAVA_PID_FILE" ]]; then
        local pid; pid=$(cat "$JAVA_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "  ✅ Running (PID=$pid)"
            curl -sf "$JAVA_HEALTH" 2>/dev/null && echo "" || echo "  ⚠️  /health 응답 없음"
        else
            echo "  ❌ 프로세스 없음 (PID=$pid)"
        fi
    else
        echo "  ❌ PID 파일 없음"
    fi

    echo ""
    echo "=== PM2 서비스 ==="
    if command -v pm2 &> /dev/null; then
        pm2 list
    else
        echo "  PM2 미설치"
    fi
}

# ── 메인 ─────────────────────────────────────────────────────────
CMD="${1:-start}"

case "$CMD" in
    start)
        log "======================================"
        log "  StockMate AI – 전체 서비스 시작"
        log "======================================"
        start_java
        wait_java_health
        start_pm2
        log ""
        log "🚀 모든 서비스가 시작되었습니다."
        log "   로그: ./stockmate.sh logs"
        log "   중지: ./stockmate.sh stop"
        ;;
    stop)
        stop_all
        log "✅ 모든 서비스 중지 완료"
        ;;
    restart)
        stop_all
        sleep 2
        start_java
        wait_java_health
        start_pm2
        log "✅ 재시작 완료"
        ;;
    status)
        show_status
        ;;
    logs)
        if command -v pm2 &> /dev/null; then
            pm2 logs
        else
            die "PM2 미설치"
        fi
        ;;
    *)
        echo "사용법: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
