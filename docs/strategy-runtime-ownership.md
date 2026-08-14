# Strategy runtime ownership

This boundary prevents Java and Python from making competing decisions for the
same strategy feature.

| Concern | Owner | Contract |
|---|---|---|
| Kiwoom REST DTOs and typed clients | Java | Preserve the official wire contract and normalize stock codes. |
| Candidate pools and freshness-aware snapshots | Java | Cache, bound calls, expose source/status, and transport diagnostic features used by live scoring. |
| Strategy gates, risk penalties, and final scoring | Python | Apply one canonical decision per strategy. |
| Live signal validation and publishing decision | Python | Every publishable candidate is evaluated by the live gate; non-live candidates fail closed and paper/shadow execution modes are prohibited. |

## Strategy-specific routing

- **S2 VI pullback:** the active runtime is Python `vi_watch_worker` and
  `strategy_2_vi_pullback`. Java `ka10054` support is an API adapter and bounded
  snapshot source only; Java must not duplicate VI risk scoring.
- **S3 and S11 intraday investor flow:** Java may enrich only the final top-N
  candidates with cached `ka10064` features. These fields are diagnostic transport,
  identified by `strategy_evaluation_owner=python` and
  `java_enrichment_mode=live_feature_transport`. Python applies the bounded
  live score adjustment and hard-reject policy; Java remains transport-only.

Every bounded REST snapshot must expose one of `REMOTE_SUCCESS`, `CACHE_HIT`,
`BUDGET_EXHAUSTED`, `API_EMPTY`, or `API_ERROR` so Python and operations tooling
can distinguish missing data from throttling and upstream failure.
