# Portfolio Blocking Policy TODO

Status: TODO, monitoring-only until automated trading is connected.

- Daily loss, max open position count, sector exposure, and strategy exposure limits are valid risk policies, but they are not active buy-signal blockers yet.
- Until automated order execution is integrated, portfolio limit breaches must not suppress Telegram buy recommendation alerts.
- When auto-trading is enabled, connect these limits to the new-entry blocking path and keep Telegram notification behavior explicitly configurable.
