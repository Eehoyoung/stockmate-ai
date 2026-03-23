"""
WebSocket 수신 데이터를 Redis 에 저장하는 전담 모듈.

키 규약 (Java api-orchestrator 와 공유):
  ws:tick:{stkCd}        TTL 30s  – 0B 체결
  ws:expected:{stkCd}    TTL 60s  – 0H 예상체결
  ws:hoga:{stkCd}        TTL 30s  – 0D 호가잔량
  ws:strength:{stkCd}    TTL 300s – 체결강도 리스트 (최근 10개)
  vi:{stkCd}             TTL 3600s – VI 이벤트 상태
  vi_watch_queue                   – VI 눌림목 감시 큐 (TTL 7200s)
  ws:py_heartbeat           TTL 30s  – WebSocket 연결 상태 heartbeat
"""

import json
import logging
import time

logger = logging.getLogger(__name__)


async def write_heartbeat(rdb, grp_status: dict):
    """
    WebSocket 연결 상태 heartbeat 갱신.
    ws:py_heartbeat (Hash, TTL 30s): updated_at + 각 그룹 상태
    """
    try:
        mapping = {"updated_at": str(time.time())}
        mapping.update(grp_status)
        await rdb.hset("ws:py_heartbeat", mapping=mapping)
        await rdb.expire("ws:py_heartbeat", 30)
    except Exception as e:
        logger.debug("[Redis] heartbeat 저장 실패: %s", e)


async def write_tick(rdb, values: dict, stk_cd: str):
    """0B 체결 데이터 저장.
    values 는 키움 숫자키 dict:
      10:현재가, 11:전일대비, 12:등락율, 13:누적거래량, 14:누적거래대금, 20:체결시간, 228:체결강도
    """
    if not stk_cd:
        return
    key = f"ws:tick:{stk_cd}"
    try:
        mapping = {
            "cur_prc":        values.get("10", ""),
            "pred_pre":       values.get("11", ""),
            "flu_rt":         values.get("12", ""),
            "acc_trde_qty":   values.get("13", ""),
            "acc_trde_prica": values.get("14", ""),
            "cntr_tm":        values.get("20", ""),
            "cntr_str":       values.get("228", ""),
        }
        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 30)

        # 체결강도 리스트 (최근 10개)
        cntr_str = values.get("228", "").strip()
        if cntr_str:
            sk = f"ws:strength:{stk_cd}"
            await rdb.lpush(sk, cntr_str)
            await rdb.ltrim(sk, 0, 9)
            await rdb.expire(sk, 300)

    except Exception as e:
        logger.warning("[Redis] tick 저장 실패 [%s]: %s", stk_cd, e)


async def write_expected(rdb, values: dict, stk_cd: str):
    """0H 예상체결 데이터 저장.
    values 숫자키: 10:예상체결가, 12:예상등락율, 15:예상체결수량, 20:예상체결시간
    pred_pre_pric(전일종가) = exp_cntr_pric / (1 + exp_flu_rt/100) 로 역산
    """
    if not stk_cd:
        return
    key = f"ws:expected:{stk_cd}"
    try:
        exp_cntr_pric = values.get("10", "")
        exp_flu_rt    = values.get("12", "")
        exp_cntr_qty  = values.get("15", "")
        exp_cntr_tm   = values.get("20", "")

        mapping = {
            "exp_cntr_pric": exp_cntr_pric,
            "exp_flu_rt":    exp_flu_rt,
            "exp_cntr_qty":  exp_cntr_qty,
            "exp_cntr_tm":   exp_cntr_tm,
        }

        # pred_pre_pric 역산: 전일종가 = exp_cntr_pric / (1 + exp_flu_rt/100)
        if exp_cntr_pric and exp_flu_rt:
            try:
                pric = float(str(exp_cntr_pric).replace(",", "").replace("+", "").replace("-", ""))
                flu  = float(str(exp_flu_rt).replace("+", "").replace(",", ""))
                if pric > 0 and flu != -100:
                    mapping["pred_pre_pric"] = str(round(pric / (1 + flu / 100)))
            except Exception:
                pass

        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 60)
    except Exception as e:
        logger.warning("[Redis] expected 저장 실패 [%s]: %s", stk_cd, e)


async def write_hoga(rdb, values: dict, stk_cd: str):
    """0D 호가잔량 데이터 저장.
    values 숫자키: 21:호가시간, 41:매도1호가, 51:매수1호가, 61:매도1수량, 71:매수1수량,
                  121:매도호가총잔량, 125:매수호가총잔량
    """
    if not stk_cd:
        return
    key = f"ws:hoga:{stk_cd}"
    try:
        mapping = {
            "total_buy_bid_req": values.get("125", ""),
            "total_sel_bid_req": values.get("121", ""),
            "buy_bid_pric_1":    values.get("51", ""),
            "sel_bid_pric_1":    values.get("41", ""),
            "buy_bid_req_1":     values.get("71", ""),
            "sel_bid_req_1":     values.get("61", ""),
            "bid_req_base_tm":   values.get("21", ""),
        }
        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 30)
    except Exception as e:
        logger.warning("[Redis] hoga 저장 실패 [%s]: %s", stk_cd, e)


async def write_vi(rdb, values: dict, stk_cd: str):
    """1h VI 발동/해제 데이터 저장.
    values 숫자키: 9001:종목코드, 9068:VI발동구분(1발동/2해제), 1225:VI적용구분,
                  1221:VI발동가격, 9008:시장구분
    stk_cd 는 values["9001"] 이 있으면 그것을 우선 사용.

    vi_watch_queue 등록은 api-orchestrator(ViWatchService)가 단독 담당한다.
    이 함수는 vi:{stk_cd} 상태 해시만 기록하여 역할 중복을 방지한다.
    """
    # values.9001 우선 사용 (item 필드와 다를 수 있음)
    real_stk_cd = values.get("9001", stk_cd)
    if not real_stk_cd:
        return

    vi_stat  = values.get("9068", "")   # "1"=발동, "2"=해제
    vi_price = values.get("1221", "0")
    vi_type  = values.get("1225", "")   # "정적"/"동적"/"동적+정적"

    key = f"vi:{real_stk_cd}"
    try:
        mapping = {
            "vi_price": vi_price,
            "vi_type":  vi_type,
            "status":   "active" if vi_stat == "1" else "released",
            "mrkt_cls": values.get("9008", ""),
        }
        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 3600)

        status_str = "발동" if vi_stat == "1" else "해제"
        logger.debug("[VI] %s [%s] type=%s price=%s", status_str, real_stk_cd, vi_type, vi_price)

    except Exception as e:
        logger.warning("[Redis] VI 저장 실패 [%s]: %s", real_stk_cd, e)
