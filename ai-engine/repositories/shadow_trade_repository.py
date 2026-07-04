from __future__ import annotations


def _db_writer():
    import db_writer

    return db_writer


async def create_shadow_trade(*args, **kwargs):
    """Persist a shadow trade through the current db_writer implementation."""
    return await _db_writer().create_shadow_trade(*args, **kwargs)

