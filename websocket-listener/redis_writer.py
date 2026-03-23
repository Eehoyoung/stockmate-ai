"""
WebSocket 수신 데이터를 Redis 에 저장하는 전담 모듈.

키 규약 (Java api-orchestrator 와 공유):
  ws:tick:{stkCd}        TTL 30s  – 0B 체결
  ws:expected:{stkCd}    TTL 60s  – 0H 예상체결
  ws:hoga:{stkCd}        TTL 30s  – 0D 호가잔량
  ws:strength:{stkCd}    TTL 300s – 체결강도 리스트 (최근 10개)
  vi:{stkCd}             TTL 3600s – VI 이벤트 상태
  vi_watch_queue                   – VI 눌림목 감시 큐 (TTL 7200s)
  ws:heartbeat           TTL 30s  – WebSocket 연결 상태 heartbeat
"""

import json
import logging
import time

logger = logging.getLogger(__name__)


async def write_heartbeat(rdb, grp_status: dict):
    """
    WebSocket 연결 상태 heartbeat 갱신.
    ws:heartbeat (Hash, TTL 30s): updated_at + 각 그룹 상태
    """
    try:
        mapping = {"updated_at": str(time.time())}
        mapping.update(grp_status)
        await rdb.hset("ws:heartbeat", mapping=mapping)
        await rdb.expire("ws:heartbeat", 30)
    except Exception as e:
        logger.debug("[Redis] heartbeat 저장 실패: %s", e)


async def write_tick(rdb, data: dict, stk_cd: str):
    """0B 체결 데이터 저장"""
    if not stk_cd:
        return
    key = f"ws:tick:{stk_cd}"
    try:
        mapping = {
            "cur_prc":        data.get("cur_prc", ""),
            "pred_pre":       data.get("pred_pre", ""),
            "flu_rt":         data.get("flu_rt", ""),
            "acc_trde_qty":   data.get("acc_trde_qty", ""),
            "acc_trde_prica": data.get("acc_trde_prica", ""),
            "cntr_str":       data.get("cntr_str", ""),
            "cntr_tm":        data.get("cntr_tm", ""),
        }
        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 30)

        # 체결강도 리스트 (최근 10개)
        cntr_str = data.get("cntr_str", "").strip()
        if cntr_str:
            sk = f"ws:strength:{stk_cd}"
            await rdb.lpush(sk, cntr_str)
            await rdb.ltrim(sk, 0, 9)
            await rdb.expire(sk, 300)

    except Exception as e:
        logger.warning("[Redis] tick 저장 실패 [%s]: %s", stk_cd, e)


async def write_expected(rdb, data: dict, stk_cd: str):
    """0H 예상체결 데이터 저장.
    필드 10: exp_cntr_pric, 필드 12: exp_flu_rt, 필드 15: exp_cntr_qty, 필드 20: exp_cntr_tm.
    exp_flu_rt 와 exp_cntr_pric 가 있으면 pred_pre_pric 역산 저장.
    """
    if not stk_cd:
        return
    key = f"ws:expected:{stk_cd}"
    try:
        exp_cntr_pric = data.get("exp_cntr_pric") or data.get("10", "")
        exp_flu_rt    = data.get("exp_flu_rt")    or data.get("12", "")
        exp_cntr_qty  = data.get("exp_cntr_qty")  or data.get("15", "")
        exp_cntr_tm   = data.get("exp_cntr_tm")   or data.get("20", "")

        mapping = {
            "exp_cntr_pric": exp_cntr_pric,
            "exp_flu_rt":    exp_flu_rt,
            "exp_cntr_qty":  exp_cntr_qty,
            "exp_cntr_tm":   exp_cntr_tm,
        }

        # pred_pre_pric 역산: 전일종가 = exp_cntr_pric / (1 + exp_flu_rt/100)
        pred_pre_pric = data.get("pred_pre_pric", "")
        if not pred_pre_pric and exp_cntr_pric and exp_flu_rt:
            try:
                pric = float(str(exp_cntr_pric).replace(",", ""))
                flu  = float(str(exp_flu_rt).replace("+", "").replace(",", ""))
                if pric > 0 and flu != -100:
                    pred_pre_pric = str(round(pric / (1 + flu / 100)))
            except Exception:
                pred_pre_pric = ""

        if pred_pre_pric:
            mapping["pred_pre_pric"] = pred_pre_pric

        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 60)
    except Exception as e:
        logger.warning("[Redis] expected 저장 실패 [%s]: %s", stk_cd, e)


async def write_hoga(rdb, data: dict, stk_cd: str):
    """0D 호가잔량 데이터 저장"""
    if not stk_cd:
        return
    key = f"ws:hoga:{stk_cd}"
    try:
        mapping = {
            "total_buy_bid_req": data.get("total_buy_bid_req", ""),
            "total_sel_bid_req": data.get("total_sel_bid_req", ""),
            "buy_bid_pric_1":    data.get("buy_bid_pric_1", ""),
            "sel_bid_pric_1":    data.get("sel_bid_pric_1", ""),
            "buy_bid_req_1":     data.get("buy_bid_req_1", ""),
            "sel_bid_req_1":     data.get("sel_bid_req_1", ""),
            "bid_req_base_tm":   data.get("bid_req_base_tm", ""),
        }
        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 30)
    except Exception as e:
        logger.warning("[Redis] hoga 저장 실패 [%s]: %s", stk_cd, e)


async def write_vi(rdb, data: dict, stk_cd: str):
    """1h VI 발동/해제 데이터 저장.

    vi_watch_queue 등록은 api-orchestrator(ViWatchService)가 단독 담당한다.
    이 함수는 vi:{stk_cd} 상태 해시만 기록하여 역할 중복을 방지한다.
    """
    if not stk_cd:
        return
    vi_stat  = data.get("vi_stat", "")
    vi_price = data.get("vi_pric", "0")
    vi_type  = data.get("vi_type", "")

    key = f"vi:{stk_cd}"
    try:
        mapping = {
            "vi_price": vi_price,
            "vi_type":  vi_type,
            "status":   "active" if vi_stat == "1" else "released",
            "mrkt_cls": data.get("mrkt_cls", ""),
        }
        await rdb.hset(key, mapping=mapping)
        await rdb.expire(key, 3600)

        status_str = "발동" if vi_stat == "1" else "해제"
        logger.debug("[VI] %s [%s] type=%s price=%s", status_str, stk_cd, vi_type, vi_price)

    except Exception as e:
        logger.warning("[Redis] VI 저장 실패 [%s]: %s", stk_cd, e)
