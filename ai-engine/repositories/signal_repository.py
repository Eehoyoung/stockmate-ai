from __future__ import annotations


def _db_writer():
    import db_writer

    return db_writer


async def insert_python_signal(*args, **kwargs):
    return await _db_writer().insert_python_signal(*args, **kwargs)


async def update_signal_score(*args, **kwargs):
    return await _db_writer().update_signal_score(*args, **kwargs)


async def insert_score_components(*args, **kwargs):
    return await _db_writer().insert_score_components(*args, **kwargs)


async def confirm_open_position(*args, **kwargs):
    return await _db_writer().confirm_open_position(*args, **kwargs)


async def cancel_open_position_by_signal(*args, **kwargs):
    return await _db_writer().cancel_open_position_by_signal(*args, **kwargs)


async def insert_rule_cancel_signal(*args, **kwargs):
    return await _db_writer().insert_rule_cancel_signal(*args, **kwargs)


async def insert_ai_cancel_signal(*args, **kwargs):
    return await _db_writer().insert_ai_cancel_signal(*args, **kwargs)
