import asyncio

import pytest


@pytest.fixture(autouse=True)
def ensure_event_loop(monkeypatch):
    """Keep a live default event loop for legacy tests using get_event_loop()."""
    # Unit tests must not inherit live-canary switches from the developer .env.
    # Individual live-policy tests opt in explicitly with patch.dict/monkeypatch.
    monkeypatch.setenv("ENABLE_STRATEGY_FAMILY_LINEAGE", "false")
    monkeypatch.setenv("ENABLE_STRATEGY_FAMILY_SHADOW_SCORING", "false")
    monkeypatch.setenv("ENABLE_STRATEGY_FAMILY_LIVE_ROUTING", "false")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed loop")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    yield

    try:
        current = asyncio.get_event_loop()
        if current.is_closed():
            asyncio.set_event_loop(asyncio.new_event_loop())
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
