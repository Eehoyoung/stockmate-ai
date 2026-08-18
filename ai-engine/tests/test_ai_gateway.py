from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ai_gateway


class _Acquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *_): return None


@pytest.mark.asyncio
async def test_gateway_records_tokens_and_cost():
    conn = SimpleNamespace(execute=AsyncMock())
    ai_gateway.configure(SimpleNamespace(acquire=lambda: _Acquire(conn)))
    response = SimpleNamespace(
        id="msg_1", content=[],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=20, cache_read_input_tokens=30),
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response)))

    assert await ai_gateway.create_message(client, purpose="test", model="claude-sonnet-4-6", messages=[]) is response
    args = conn.execute.await_args.args
    assert args[5:9] == (1000, 100, 20, 30)
    assert args[9] == Decimal("0.004584")


@pytest.mark.asyncio
async def test_gateway_records_api_errors_and_reraises():
    conn = SimpleNamespace(execute=AsyncMock())
    ai_gateway.configure(SimpleNamespace(acquire=lambda: _Acquire(conn)))
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("down"))))

    with pytest.raises(RuntimeError, match="down"):
        await ai_gateway.create_message(client, purpose="test", model="claude-sonnet-4-6", messages=[])
    assert conn.execute.await_args.args[4] == "ERROR"
    assert conn.execute.await_args.args[-2:] == ("RuntimeError", "down")


def test_all_production_claude_calls_use_gateway():
    root = Path(__file__).parents[1]
    offenders = [p.name for p in root.glob("*.py") if p.name != "ai_gateway.py" and ".messages.create(" in p.read_text(encoding="utf-8")]
    assert offenders == []
