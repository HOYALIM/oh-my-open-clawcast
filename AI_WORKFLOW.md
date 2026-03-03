# AI Collaboration Workflow (Codex + Claude Code + Gemini)

## Goal
Ship fast without losing correctness:
- Codex: build and refactor quickly
- Claude Code: architecture and edge-case hardening
- Gemini: strict final review gate

## Ownership

1. Codex (implementation owner)
- Convert requirements to code
- Add/maintain tests
- Keep PR scope tight

2. Claude Code (design owner)
- Validate data model and forecast assumptions
- Stress-test edge cases (missing fields, sparse days, clock skew, provider naming drift)
- Propose simplification when complexity grows

3. Gemini (review gate)
- Review every PR for correctness/regression risk
- Flag ambiguous assumptions and hidden coupling
- Require explicit evidence for forecast quality claims

## Branch model

- `main`: always releasable
- `feat/*`: implementation
- `design/*`: architecture/docs
- `exp/*`: prototype/ablation only

## PR rules

1. One PR = one change set (e.g., only anomaly logic)
2. Include:
- before/after table snippet
- test output
- known limitations
3. Block merge unless:
- tests green
- Gemini review addressed
- no unresolved TODOs

## Forecast quality gates

For any forecast logic change, include:

1. Backtest on historical window
- Use trailing N days to predict next K days
- Report MAPE / MAE for tokens and cost

2. Sensitivity checks
- compare 7d vs 14d vs 30d lookback
- compare with/without anomaly filtering

3. Drift checks
- model-mix shift impact
- day-of-week effect impact

## Suggested backlog split

1. Codex
- confidence bands (low/base/high)
- budget threshold alerts
- JSON export endpoint

2. Claude Code
- robust seasonality (weekday/weekend)
- structural break detection
- fallback strategy for sparse data

3. Gemini
- review all statistical assumptions
- verify alert thresholds to reduce false alarms
