# 전략군 통합 실행용 JSON 프롬프트

아래 JSON은 후속 구현 에이전트가 사용하는 작업 계약이다. 코드 블록 자체는 유효한 JSON이어야 하며, 구현자는 작업 시작 전 `strategy_family_consolidation_work_plan_2026-08-16.md`와 실제 현재 코드를 다시 대조해야 한다.

```json
{
  "schema_version": "1.0.0",
  "prompt_id": "stockmate-strategy-family-consolidation-2026-08-16",
  "mode": "implementation_and_live_canary_approved",
  "language": "ko-KR",
  "objective": "기존 S1~S16 setup의 성과 계보와 고유 진입 논리를 보존하면서 7개 G 전략군 운용 계층을 구현하고 Kiwoom과 Toss 조회 데이터를 안전하게 배합한다.",
  "authoritative_plan": "docs/strategy_family_consolidation_work_plan_2026-08-16.md",
  "current_turn_restriction": {
    "code_changes_allowed": true,
    "database_changes_allowed": true,
    "runtime_changes_allowed_after_completion_gates": true,
    "documentation_only": false
  },
  "future_implementation_preconditions": [
    "사용자의 별도 코드 구현 승인",
    "git status와 기존 변경사항 보존 확인",
    "현재 테스트 및 가용 과거 데이터 기준선 확보",
    "정책 레지스트리 수치 재승인",
    "Toss는 조회 분석 전용이고 주문 API는 범위 밖임을 확인"
  ],
  "non_negotiable_rules": [
    "기존 S1~S16 식별자를 삭제하거나 재사용하지 않는다.",
    "G 전략군은 family_id이고 기존 전략은 setup_id로 영구 보존한다.",
    "모든 producer와 consumer가 전환되기 전 additive schema와 dual-read-write를 사용한다.",
    "필수 Kiwoom 실시간 데이터 결측 또는 stale이면 fail closed한다.",
    "Toss 결측을 음수 사실로 추론하지 않고 DEGRADED와 무가점으로 기록한다.",
    "Kiwoom과 Toss 캔들을 부분 봉 단위로 병합하지 않는다.",
    "AI는 hard gate, RR, 손실 cap, 포트폴리오 제한을 우회할 수 없다.",
    "Claude HOLD는 WATCH이며 점수만으로 ENTER로 승격하지 않는다.",
    "복수 setup 점수와 주문 수량을 단순 합산하지 않는다.",
    "ACTIVE, PARTIAL_TP, OVERNIGHT 포지션이 있으면 같은 종목 신규 주문을 만들지 않는다.",
    "실패한 테스트를 삭제하거나 조건을 완화해 통과시키지 않는다.",
    "불충분한 성과 표본을 PASS로 보고하지 않는다."
  ],
  "families": [
    {
      "family_no": "G01",
      "family_name": "SESSION_EVENT",
      "display_name_ko": "세션·이벤트",
      "setups": ["S1_GAP_OPEN", "S2_VI_PULLBACK", "S12_CLOSING"],
      "merge_type": "orchestration_only",
      "rule_threshold": 70,
      "rr_by_setup": {"S1_GAP_OPEN": 1.5, "S2_VI_PULLBACK": 1.8, "S12_CLOSING": 1.5},
      "notes": "S2는 VI 이벤트 경로이고 S12는 overnight이므로 단일 schedule과 exit policy를 금지한다."
    },
    {
      "family_no": "G02",
      "family_name": "FLOW_TREND",
      "display_name_ko": "수급추세",
      "setups": ["S3_INST_FRGN", "S5_PROG_FRGN", "S11_FRGN_CONT"],
      "merge_type": "shared_features_and_confirmation",
      "rule_threshold": 70,
      "rr_by_setup": {"S3_INST_FRGN": 1.5, "S5_PROG_FRGN": 1.5, "S11_FRGN_CONT": 1.55}
    },
    {
      "family_no": "G03",
      "family_name": "ACCUMULATION_CONFIRM",
      "display_name_ko": "축적확인",
      "setups": ["S16_ACCUMULATION_SHADOW"],
      "merge_type": "state_machine_wrapper",
      "rule_threshold": 78,
      "rr_by_setup": {"S16_ACCUMULATION_SHADOW": 1.8},
      "initial_mode": "LIVE_CANARY_TRIGGERED_ONLY"
    },
    {
      "family_no": "G04",
      "family_name": "TREND_PHASE",
      "display_name_ko": "추세단계",
      "setups": ["S8_GOLDEN_CROSS", "S9_PULLBACK_SWING", "S15_MOMENTUM_ALIGN"],
      "merge_type": "stateful_setup_router",
      "rule_threshold": 70,
      "rr_by_setup": {"S8_GOLDEN_CROSS": 1.5, "S9_PULLBACK_SWING": 1.55, "S15_MOMENTUM_ALIGN": 1.55}
    },
    {
      "family_no": "G05",
      "family_name": "STRUCTURAL_BREAKOUT",
      "display_name_ko": "구조돌파",
      "setups": ["S7_ICHIMOKU_BREAKOUT", "S10_NEW_HIGH", "S13_BOX_BREAKOUT"],
      "merge_type": "shared_breakout_engine",
      "rule_threshold": 74,
      "rr_by_setup": {"S7_ICHIMOKU_BREAKOUT": 1.8, "S10_NEW_HIGH": 1.55, "S13_BOX_BREAKOUT": 1.55}
    },
    {
      "family_no": "G06",
      "family_name": "INTRADAY_THEME_MOMENTUM",
      "display_name_ko": "장중급등·테마",
      "setups": ["S4_BIG_CANDLE", "S6_THEME_LAGGARD"],
      "merge_type": "shared_intraday_risk_budget",
      "rule_threshold": 72,
      "rr_by_setup": {"S4_BIG_CANDLE": 1.7, "S6_THEME_LAGGARD": 1.6},
      "allow_overnight": false
    },
    {
      "family_no": "G07",
      "family_name": "REVERSAL_BOUNCE",
      "display_name_ko": "역추세반등",
      "setups": ["S14_OVERSOLD_BOUNCE"],
      "merge_type": "independent_wrapper",
      "rule_threshold": 75,
      "rr_by_setup": {"S14_OVERSOLD_BOUNCE": 1.5}
    }
  ],
  "rule_scoring_contract": {
    "max_score": 100,
    "components": {
      "setup_edge": 35,
      "execution_quality": 20,
      "regime_timing": 15,
      "liquidity_data_quality": 10,
      "risk_structure": 20
    },
    "confirmation_bonus_max": 8,
    "correlated_confirmation_bonus": [4, 2],
    "formula": "clamp(sum(component_scores) + confirmation_bonus, 0, 100)",
    "missing_required_data": "BLOCK",
    "missing_optional_data": "DEGRADED_NO_BONUS"
  },
  "ai_scoring_contract": {
    "display_formula": "round(0.70 * rule_score + 0.30 * ai_score, 2)",
    "enter_requires": [
      "hard_gates_passed",
      "freshness_passed",
      "effective_rr_passed",
      "portfolio_arbitration_passed",
      "ai_action_is_ENTER"
    ],
    "hold_semantics": "WATCH",
    "failure_semantics": "FAIL_CLOSED",
    "output_schema": {
      "action": "ENTER|HOLD|CANCEL",
      "ai_score": "number_0_100",
      "confidence": "HIGH|MEDIUM|LOW",
      "reason": "korean_string",
      "cancel_reason": "korean_string_or_null",
      "validated_family_id": "G01_to_G07",
      "validated_setup_id": "legacy_setup_id",
      "independent_confirmations": "array",
      "data_quality": "OK|DEGRADED|BLOCKED",
      "risk_flags": "array",
      "tp1_price": "integer",
      "tp2_price": "integer_or_null",
      "sl_price": "integer",
      "effective_rr": "number"
    }
  },
  "tp_sl_rr_contract": {
    "entry_basis": "latest_executable_quote_with_source_timestamp",
    "sl_basis": "primary_setup_structural_invalidation_with_max_loss_cap",
    "tp1_basis": "nearest_valid_resistance",
    "tp2_basis": "next_structural_resistance_or_valid_extension",
    "store": ["raw_rr", "single_tp_rr", "effective_rr", "cost_model_version", "tp_policy_version", "sl_policy_version", "exit_policy_version"],
    "costs": ["commission", "tax_if_applicable", "spread", "slippage", "market_impact_assumption"],
    "partial_tp_target_pct": 50,
    "partial_tp_activation": "only_after_ACTIVE_to_PARTIAL_TP_runtime_test_passes"
  },
  "data_source_policy": {
    "kiwoom": {
      "role": "primary_realtime_and_strategy_specific_market_source",
      "uses": ["0B_tick", "0D_orderbook", "0H_expected", "1h_VI", "strategy_rankings", "intraday_candles", "daily_candles", "intraday_flow"],
      "validation": "validate_http_status_and_application_body",
      "required_for_live_entry": true
    },
    "toss": {
      "role": "read_only_supplement_and_risk_context",
      "uses": ["rankings", "full_series_candle_fallback", "market_indicators", "investor_trading", "program_trades", "short_selling", "credit_trades", "securities_lending", "warnings", "market_calendar"],
      "token_owner": "api-orchestrator_java_only",
      "orders_in_scope": false,
      "required_for_live_entry": false
    },
    "conflict_policy": "WATCH_SOURCE_CONFLICT",
    "candle_policy": "never_partial_merge; replace_only_with_more_complete_full_series",
    "freshness_policy": "use_source_timestamp_and_updated_at_ms_not_TTL_alone"
  },
  "required_lineage_fields": [
    "family_id",
    "family_name",
    "primary_setup_id",
    "matched_setup_ids",
    "confirmed_by_family_ids",
    "setup_version",
    "family_policy_version",
    "rule_score_version",
    "tp_policy_version",
    "sl_policy_version",
    "exit_policy_version",
    "prompt_version",
    "data_source",
    "source_timestamp",
    "source_age_ms",
    "fallback_reason",
    "correlation_id",
    "signal_id",
    "decision_stage"
  ],
  "known_preimplementation_defects": [
    "trading_signals.strategy CHECK and Java StrategyType do not accept G family ids",
    "candidates_builder live catalog iteration can exclude S16 through range_1_16",
    "claude_analyst candidate pool iteration can exclude S16 through range_1_16",
    "strategy catalog is duplicated across Python Java Redis Telegram and reports",
    "TP1 documentation and ACTIVE position runtime may disagree on partial versus full close",
    "strategy_meta RR gates and tp_sl_engine policy values are not a single canonical registry"
  ],
  "work_packages": [
    {"id": "WP-00", "name": "baseline_and_freeze", "requires": [], "deliverables": ["git_status", "baseline_tests", "20_day_signal_and_outcome_snapshot", "lineage_gap_report"]},
    {"id": "WP-01", "name": "versioned_policy_registry", "requires": ["WP-00"], "deliverables": ["family_setup_mapping", "score_policy", "tp_sl_rr_policy", "failure_first_tests"]},
    {"id": "WP-02", "name": "additive_schema", "requires": ["WP-01"], "deliverables": ["flyway_plan", "entity_dto_plan", "dual_write_contract", "rollback_sql_plan"]},
    {"id": "WP-03", "name": "candidate_and_api_layer", "requires": ["WP-01"], "deliverables": ["kiwoom_toss_matrix", "freshness_contract", "rate_budget_tests", "fallback_tests"]},
    {"id": "WP-04", "name": "family_router", "requires": ["WP-02", "WP-03"], "deliverables": ["compatibility_adapters", "family_state_machines", "legacy_equivalence_tests"]},
    {"id": "WP-05", "name": "normalized_rule_scorer", "requires": ["WP-04"], "deliverables": ["component_scorer", "correlation_discount", "shadow_dual_score_report"]},
    {"id": "WP-06", "name": "tp_sl_rr_and_position_state", "requires": ["WP-05"], "deliverables": ["canonical_policy", "cost_adjusted_rr", "partial_tp_failure_first_tests", "position_state_replay"]},
    {"id": "WP-07", "name": "ai_prompt_and_post_validation", "requires": ["WP-05", "WP-06"], "deliverables": ["family_prompt", "setup_rubrics", "json_schema", "price_rr_validator", "fail_closed_tests"]},
    {"id": "WP-08", "name": "portfolio_arbitration", "requires": ["WP-04", "WP-06"], "deliverables": ["stock_level_reservation", "family_dedup", "theme_sector_limits", "concurrency_tests"]},
    {"id": "WP-09", "name": "consumer_migration", "requires": ["WP-02", "WP-07", "WP-08"], "deliverables": ["db_api_telegram_dual_read", "legacy_and_family_queries", "formatter_tests"]},
    {"id": "WP-10", "name": "replay_and_live_canary_validation", "requires": ["WP-09"], "deliverables": ["predeploy_replay_report", "5_trading_day_live_report", "regime_market_breakdown", "overlap_correlation", "net_expectancy", "MFE_MAE", "duplicate_and_stale_audit"]},
    {"id": "WP-11", "name": "live_activation_and_rollback", "requires": ["WP-10"], "deliverables": ["live_canary_gate", "kill_switch", "rollback_rehearsal", "docker_deployment_evidence"]},
    {"id": "WP-12", "name": "documentation_and_handoff", "requires": ["WP-11"], "deliverables": ["api_docs", "redis_db_docs", "runbook", "sample_telegram_output", "residual_risk_report"]}
  ],
  "mandatory_tests": [
    "all_16_setups_map_to_exactly_one_family",
    "unknown_family_or_setup_fails_closed",
    "S2_event_path_is_not_replaced_by_schedule",
    "S12_overnight_policy_is_not_applied_to_S1_or_S2",
    "same_stock_multi_setup_creates_one_order_plan",
    "active_partial_tp_overnight_blocks_new_order",
    "required_stale_kiwoom_data_never_enters",
    "toss_absence_never_creates_positive_or_negative_fact",
    "kiwoom_http_200_error_body_fails",
    "toss_and_kiwoom_candles_are_not_partially_merged",
    "rule_components_are_clamped",
    "correlated_confirmation_is_discounted",
    "ai_hold_stays_watch",
    "ai_cannot_override_hard_gate_or_rr",
    "tp1_partial_state_transition_matches_persistence",
    "queue_db_api_telegram_lineage_is_complete",
    "legacy_S_queries_and_new_G_queries_both_work_during_migration",
    "rollback_restores_legacy_decision_path_without_data_loss"
  ],
  "acceptance_gates": {
    "lineage_missing_count": 0,
    "duplicate_new_order_count": 0,
    "stale_required_data_enter_count": 0,
    "hard_gate_override_count": 0,
    "live_canary_trading_days": 5,
    "target_evaluable_signals_per_family": 200,
    "target_signals_per_setup": 30,
    "low_frequency_analysis_floor_per_family": 60,
    "low_frequency_analysis_floor_per_setup": 15,
    "performance": "report_net_expectancy_profit_factor_MFE_MAE_drawdown_with_confidence_intervals",
    "insufficient_sample_result": "INSUFFICIENT_SAMPLE",
    "activation_mode": "LIVE_CANARY_NO_EXPOSURE_INCREASE"
  },
  "reporting_requirements": [
    "각 WP별 변경 파일과 테스트 증거",
    "기존 dirty worktree 중 보존한 사용자 변경",
    "실행하지 못한 테스트와 이유",
    "Kiwoom Toss API별 실제 source status와 rate-limit 증거",
    "DB Redis queue API Telegram end-to-end lineage",
    "기존 S별 성과와 신규 G별 성과를 함께 표시",
    "잔여 위험과 rollback 가능 여부"
  ],
  "stop_conditions": [
    "필수 데이터 계약을 코드에서 확인할 수 없음",
    "기존 사용자 변경과 안전하게 분리할 수 없음",
    "스키마 producer consumer 동시 호환 계획 없음",
    "중복 주문 가능성을 원자적으로 차단할 설계 없음",
    "shadow 표본이 승격 기준에 미달",
    "실주문 또는 외부 상태 변경에 대한 추가 승인이 필요함"
  ]
}
```

## 실행 지시

구현과 완료 후 Docker live canary가 승인됐다. WP 순서를 건너뛰지 않고 각 단계에서 실패 테스트→수정→통과 증거를 남긴다. 5거래일 동안 기존보다 노출을 키우지 않으며, 전략군 수가 7개로 줄었다는 사실을 기존 setup 성과 삭제나 주문 비중 합산으로 해석하면 안 된다.
