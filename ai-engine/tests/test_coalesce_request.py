"""http_utils.coalesce_request 동시 중복 요청 합치기 테스트."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.asyncio
async def test_concurrent_same_key_issues_single_call():
    from http_utils import coalesce_request

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return "result"

    results = await asyncio.gather(*[
        coalesce_request(("tr", "005930"), factory) for _ in range(5)
    ])

    assert calls["n"] == 1
    assert results == ["result"] * 5


@pytest.mark.asyncio
async def test_different_keys_are_not_merged():
    from http_utils import coalesce_request

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return calls["n"]

    await asyncio.gather(
        coalesce_request(("tr", "A"), factory),
        coalesce_request(("tr", "B"), factory),
    )
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_kill_shared_fetch():
    """전략 타임아웃으로 한 호출자가 취소돼도 나머지 대기자는 정상 응답을 받아야 한다.

    shield 없이 Task를 그대로 await 하면 취소가 안쪽 Task까지 전파되어
    같은 데이터를 기다리던 다른 전략의 요청까지 함께 죽는다. S8(500s)/S9(450s)
    타임아웃이 일상적인 이 저장소에서는 실제로 발생 가능한 시나리오다.
    """
    from http_utils import coalesce_request

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        await asyncio.sleep(0.15)
        return "survived"

    key = ("tr", "cancel-test")
    victim = asyncio.ensure_future(coalesce_request(key, factory))
    survivor = asyncio.ensure_future(coalesce_request(key, factory))

    await asyncio.sleep(0.02)          # 두 호출자가 같은 Task를 공유하도록 대기
    victim.cancel()                     # 전략 타임아웃 상황 재현

    with pytest.raises(asyncio.CancelledError):
        await victim

    assert await survivor == "survived"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_exception_propagates_and_key_is_released():
    from http_utils import coalesce_request
    import http_utils

    async def failing():
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    key = ("tr", "err")
    with pytest.raises(RuntimeError):
        await coalesce_request(key, failing)

    # 실패한 요청이 in-flight 맵에 남아 이후 조회를 영구 오염시키면 안 된다.
    await asyncio.sleep(0)
    assert key not in http_utils._INFLIGHT_REQUESTS

    async def ok():
        return "recovered"

    assert await coalesce_request(key, ok) == "recovered"


@pytest.mark.asyncio
async def test_sequential_calls_after_completion_refetch():
    """완료된 요청은 공유되지 않는다 (캐시가 아니라 in-flight 합치기이므로)."""
    from http_utils import coalesce_request

    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return calls["n"]

    first = await coalesce_request(("tr", "seq"), factory)
    second = await coalesce_request(("tr", "seq"), factory)

    assert (first, second) == (1, 2)
