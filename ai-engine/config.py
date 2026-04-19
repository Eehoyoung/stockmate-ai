"""
config.py
ai-engine 환경변수·공통 설정 허브.

원칙:
  - os.getenv 호출은 가급적 이 파일에서만.
  - 각 모듈은 필요한 상수를 from config import ... 로 사용.
  - 키움 공통 필터 등 하드코딩 상수는 Const 섹션에 둔다.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── Kiwoom REST/WS ────────────────────────────────────────────
KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
WS_URL          = os.getenv("KIWOOM_WS_URL",   "wss://api.kiwoom.com:10000")

# ── Redis ──────────────────────────────────────────────────────
REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None

# ── PostgreSQL ─────────────────────────────────────────────────
PG_HOST     = os.getenv("POSTGRES_HOST",     "localhost")
PG_PORT     = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB       = os.getenv("POSTGRES_DB",       "SMA")
PG_USER     = os.getenv("POSTGRES_USER",     "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
PG_ENABLED  = os.getenv("PG_WRITER_ENABLED", "true").lower() == "true"

# ── Claude ─────────────────────────────────────────────────────
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL",   "claude-sonnet-4-6")

# ── Const (정적) ───────────────────────────────────────────────
# Kiwoom 시장 코드 (dict 형태: 기존 호환)
MARKETS = {"kospi": "001", "kosdaq": "101", "all": "000"}

# 전략 스캔·후보 풀에서 순회하는 실질 시장 코드 (list 형태)
MARKET_LIST = ["001", "101"]

# Kiwoom 조건식 공통 필터 (순위/등락률 API 계열에서 재사용)
COMMON_FILTERS = {
    "stk_cnd": "1",        # 관리종목 제외
    "updown_incls": "0",   # 상하한 미포함
    "trde_qty_tp": "10",   # 만주 이상
    "stex_tp": "3",        # KRX
}
