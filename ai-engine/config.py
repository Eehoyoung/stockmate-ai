import os

KIWOOM_BASE_URL = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
WS_URL = os.getenv("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000")

MARKETS = {"kospi": "001", "kosdaq": "101", "all": "000"}
COMMON_FILTERS = {
    "stk_cnd": "1",        # 관리종목 제외
    "updown_incls": "0",   # 상하한 미포함
    "trde_qty_tp": "10",   # 만주 이상
    "stex_tp": "3",        # KRX
}
