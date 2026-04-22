import asyncio

import pytest


@pytest.fixture(autouse=True)
def ensure_event_loop():
    """Keep a live default event loop for legacy tests using get_event_loop()."""
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
