from __future__ import annotations

from typing import Any, Callable

from scoring_pipeline.persistence_payloads import (
    build_cancel_shadow_detail,
    resolve_market_flu_rt,
    resolve_shadow_prices,
)


async def persist_processed_signal(
    *,
    pg_pool: Any,
    signal_id: Any,
    signal: dict,
    enriched: dict,
    ctx: dict,
    strategy: str,
    stk_cd: str,
    action: str,
    confidence: Any,
    reason: str | None,
    display_reason: str | None,
    cancel_reason: str | None,
    cancel_type: str | None,
    r_score: float,
    ai_score_val: Any,
    threshold: float,
    components: dict,
    rule_only_payload: dict | None,
    insert_python_signal_fn: Callable[..., Any],
    update_signal_score_fn: Callable[..., Any],
    insert_score_components_fn: Callable[..., Any],
    confirm_open_position_fn: Callable[..., Any],
    create_shadow_trade_fn: Callable[..., Any],
    shadow_persistence_enabled: bool,
    insert_rule_cancel_signal_fn: Callable[..., Any],
    insert_ai_cancel_signal_fn: Callable[..., Any],
    insert_signal_freshness_log_fn: Callable[..., Any] | None = None,
    cancel_open_position_by_signal_fn: Callable[..., Any],
    normalize_market_type_fn: Callable[[str], str],
    fv_fn: Callable[..., Any],
    logger: Any,
) -> bool:
    if enriched.get("hold_monitor_recheck") and not signal_id and action != "ENTER":
        if logger:
            logger.info(
                "[Queue] hold-monitor recheck not persisted as a new signal [%s %s action=%s]",
                stk_cd,
                strategy,
                action,
            )
        return False

    if rule_only_payload is not None and not signal_id:
        if cancel_type is None:
            await insert_ai_cancel_signal_fn(
                pg_pool,
                signal_id=None,
                stk_cd=stk_cd,
                strategy=strategy,
                ai_score=ai_score_val,
                confidence=confidence,
                reason=display_reason,
                cancel_reason="RULE_ONLY_ALERT",
                raw_payload=rule_only_payload,
            )
        else:
            await insert_rule_cancel_signal_fn(
                pg_pool,
                signal_id=None,
                stk_cd=stk_cd,
                strategy=strategy,
                rule_score=r_score,
                cancel_type=cancel_type,
                reason=display_reason,
                raw_payload=rule_only_payload,
            )
        return True

    db_id = signal_id
    if not db_id:
        db_id = await insert_python_signal_fn(
            pg_pool,
            enriched,
            action=action,
            confidence=confidence,
            rule_score=r_score,
            ai_score=ai_score_val,
            ai_reason=display_reason,
            skip_entry=(action != "ENTER"),
        )

    if not db_id:
        raise RuntimeError(f"signal persistence failed [{stk_cd} {strategy}]")

    if insert_signal_freshness_log_fn is not None:
        await insert_signal_freshness_log_fn(
            pg_pool,
            signal_id=db_id,
            stk_cd=stk_cd,
            strategy=strategy,
            action=action,
            freshness_status=enriched.get("freshness_status"),
            snapshot=enriched.get("market_data_observability"),
        )

    market_flu_rt = resolve_market_flu_rt(
        signal,
        ctx,
        normalize_market_type_fn=normalize_market_type_fn,
    )
    await update_signal_score_fn(
        pg_pool,
        db_id,
        rule_score=r_score,
        ai_score=ai_score_val,
        rr_ratio=fv_fn(enriched.get("rr_ratio")),
        action=action,
        confidence=confidence,
        ai_reason=display_reason,
        tp_method=enriched.get("tp_method"),
        sl_method=enriched.get("sl_method"),
        skip_entry=(action != "ENTER"),
        ma5=signal.get("ma5"),
        ma20=signal.get("ma20"),
        ma60=signal.get("ma60"),
        rsi14=signal.get("rsi"),
        bb_upper=signal.get("bb_upper"),
        bb_lower=signal.get("bb_lower"),
        atr=signal.get("atr"),
        market_flu_rt=market_flu_rt,
        news_sentiment=enriched.get("news_sentiment") or signal.get("news_sentiment"),
        news_ctrl=enriched.get("news_ctrl") or signal.get("news_ctrl"),
        raw_rr=fv_fn(enriched.get("raw_rr")),
        single_tp_rr=fv_fn(enriched.get("single_tp_rr")),
        effective_rr=fv_fn(enriched.get("effective_rr")),
        min_rr_ratio=fv_fn(enriched.get("min_rr_ratio")),
        rr_skip_reason=enriched.get("rr_skip_reason"),
        stop_max_pct=fv_fn(enriched.get("stop_max_pct")),
        tp_policy_version=enriched.get("tp_policy_version"),
        sl_policy_version=enriched.get("sl_policy_version"),
        exit_policy_version=enriched.get("exit_policy_version"),
        allow_overnight=enriched.get("allow_overnight"),
        allow_reentry=enriched.get("allow_reentry"),
        time_stop_deadline_at=None,
        stk_nm=enriched.get("stk_nm") or signal.get("stk_nm"),
        shadow_features=enriched.get("shadow_features"),
        confirmed_by_family_ids=enriched.get("confirmed_by_family_ids"),
        setup_version=enriched.get("setup_version") or enriched.get("strategy_version"),
        rule_score_version=enriched.get("rule_score_version"),
        prompt_version=enriched.get("prompt_version"),
        data_source=enriched.get("data_source"),
        source_timestamp=enriched.get("source_timestamp"),
        source_age_ms=enriched.get("source_age_ms"),
        fallback_reason=enriched.get("fallback_reason"),
    )
    await insert_score_components_fn(
        pg_pool,
        db_id,
        strategy,
        components,
        total_score=r_score,
        threshold=threshold,
    )

    if action == "ENTER":
        shadow_prices = resolve_shadow_prices(enriched, signal=signal, fv_fn=fv_fn)
        position_confirmed = await confirm_open_position_fn(
            pg_pool,
            db_id,
            ai_score=ai_score_val,
            tp1_price=shadow_prices["tp1_price"],
            tp2_price=shadow_prices["tp2_price"],
            sl_price=shadow_prices["sl_price"],
            rr_ratio=fv_fn(enriched.get("rr_ratio")),
            trailing_pct=fv_fn(enriched.get("trailing_pct")),
            trailing_activation=fv_fn(enriched.get("trailing_activation")),
            trailing_basis=enriched.get("trailing_basis"),
            strategy_version=enriched.get("strategy_version"),
            time_stop_type=enriched.get("time_stop_type"),
            time_stop_minutes=enriched.get("time_stop_minutes"),
            time_stop_session=enriched.get("time_stop_session"),
            raw_rr=fv_fn(enriched.get("raw_rr")),
            single_tp_rr=fv_fn(enriched.get("single_tp_rr")),
            effective_rr=fv_fn(enriched.get("effective_rr")),
            min_rr_ratio=fv_fn(enriched.get("min_rr_ratio")),
            rr_skip_reason=enriched.get("rr_skip_reason"),
            stop_max_pct=fv_fn(enriched.get("stop_max_pct")),
            tp_policy_version=enriched.get("tp_policy_version"),
            sl_policy_version=enriched.get("sl_policy_version"),
            exit_policy_version=enriched.get("exit_policy_version"),
            allow_overnight=enriched.get("allow_overnight"),
            allow_reentry=enriched.get("allow_reentry"),
        )
        if position_confirmed and shadow_persistence_enabled:
            await create_shadow_trade_fn(
                pg_pool,
                signal_id=db_id,
                payload=enriched,
                entry_price=shadow_prices["entry_price"],
                tp1_price=shadow_prices["tp1_price"],
                tp2_price=shadow_prices["tp2_price"],
                sl_price=shadow_prices["sl_price"],
                data_quality="OK",
            )
        elif not position_confirmed:
            logger.warning("[Queue] shadow trade skipped because position confirm failed signal_id=%s", db_id)
        return False

    if cancel_type:
        await insert_rule_cancel_signal_fn(
            pg_pool,
            signal_id=db_id,
            stk_cd=stk_cd,
            strategy=strategy,
            rule_score=r_score,
            cancel_type=cancel_type,
            reason=display_reason,
            raw_payload=enriched,
        )
    elif action == "CANCEL":
        await insert_ai_cancel_signal_fn(
            pg_pool,
            signal_id=db_id,
            stk_cd=stk_cd,
            strategy=strategy,
            ai_score=ai_score_val,
            confidence=confidence,
            reason=reason,
            cancel_reason=cancel_reason,
            raw_payload=enriched,
        )

    if shadow_persistence_enabled:
        shadow_prices = resolve_shadow_prices(enriched, fv_fn=fv_fn)
        await create_shadow_trade_fn(
            pg_pool,
            signal_id=db_id,
            payload=enriched,
            entry_price=shadow_prices["entry_price"],
            tp1_price=shadow_prices["tp1_price"],
            tp2_price=shadow_prices["tp2_price"],
            sl_price=shadow_prices["sl_price"],
            data_quality="CANCEL_SHADOW",
            initial_status="CANCELLED",
            data_quality_detail=build_cancel_shadow_detail(
                enriched,
                cancel_type=cancel_type,
                cancel_reason=cancel_reason,
                fv_fn=fv_fn,
            ),
        )
    await cancel_open_position_by_signal_fn(pg_pool, db_id)
    return False
