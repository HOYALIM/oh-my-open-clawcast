# PRD: Oh My Open Clawcast (Execution Version)

## 0) Product Thesis
People using OpenClaw in Telegram/Slack need a single `/clawcast` response that answers:
- what was used today and month-to-date,
- how much it likely costs,
- whether usage is healthy,
- what month-end will look like.

If this answer is wrong or late, users lose trust and stop using it.

## 1) Non-Negotiable User Outcome
Within 3 seconds, `/clawcast` returns a reliable summary message that includes:
1. Daily usage by model (local day boundary)
2. MTD usage by model (local month boundary)
3. Cost and auth mode split (API vs OAuth)
4. Month-end forecast
5. Quota status confidence
6. Alerts (token/latency/failure anomalies)

## 2) Target User
- OpenClaw power users running cron jobs and bot workflows
- Team operators in Telegram/Slack channels
- Solo builders tracking spend and reliability on local machines

## 3) Scope
### In Scope (v1)
- CLI entrypoint (`clawcast message`, `clawcast report`, `clawcast table`)
- OpenClaw cron run ingestion from local state directory
- Token/cost/latency/forecast/anomaly pipeline
- Telegram/Slack posting scripts
- Homebrew installation path

### Out of Scope (v1)
- Direct billing API integrations for every provider
- Server-side multi-tenant dashboard
- Historical backfill from non-OpenClaw data sources

## 4) "Garry Tan" Success Metrics
- Activation: 80% of new installs run `clawcast message` successfully on day 0
- Reliability: >= 99% successful `/clawcast` generation on valid input
- Latency: p95 message generation <= 3s on typical local datasets
- Retention signal: users scheduling daily post in Telegram/Slack within 7 days
- Trust: < 2% support reports about "wrong cost/month forecast"

## 5) Karpathy 4-Principle Review Gate
Reference basis:
- https://github.com/forrestchang/andrej-karpathy-skills/blob/main/README.md
- https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md

Principles used:
1. Keep files small (target <= 200 lines)
2. Single responsibility per function/class
3. Delete dead paths and avoid stale compatibility layers
4. Think-first design before coding

Current compliance snapshot:
- PASS: clear modular split by domain (`loader`, `forecast`, `aggregator`, `formatter`, `quota`)
- PASS: test suite exists for core analytics/message paths
- FAIL: oversized files
  - `oh_my_open_clawcast/forecast.py` (~297 lines)
  - `oh_my_open_clawcast/cli.py` (~242 lines)
  - `tests/test_clawcast_message.py` (~332 lines)
- PARTIAL: runtime scripts still carry mixed concerns (generate/report/send/fallback logic in one place)

## 6) P0/P1 Gaps To Close Before "Production-Trusted"
### P0
1. Forecast timezone consistency
   - Daily/MTD uses local timezone, but forecast math is UTC-based.
   - Fix: make forecast period/day aggregation timezone-aware and consistent with message timezone.

2. Auth-mode billing policy contract hardening
   - OAuth default-zero billing is implemented, but contract should be explicit in output schema/docs/tests.
   - Fix: expose both `estimated_cost_usd` and `theoretical_api_cost_usd` in summary/report tables.

3. Delivery truthfulness in scripts
   - Telegram/Slack APIs can return HTTP 200 with failure payload.
   - Fix: parse response JSON and fail when `ok=false`.

### P1
1. Refactor oversized files
   - Split `cli.py` into command modules.
   - Split `forecast.py` into `cost.py`, `latency.py`, `forecasting.py`, `anomaly.py`.

2. Alert ordering correctness
   - Severity sorting is string-based and can mis-prioritize.
   - Fix: use explicit severity rank (`high > medium > low`).

3. Script test coverage
   - Add smoke/integration checks for send scripts with mocked HTTP responses.

## 7) Functional Requirements
### FR-1 Data Ingestion
- Read `~/.openclaw/cron/runs/*.jsonl` (or configured dir)
- Normalize records with strict schema:
  - timestamp, status, provider, model, tokens, duration, auth_mode, run_id

### FR-2 Cost Model
- Resolve model rates by provider/model key
- Compute:
  - `theoretical_api_cost_usd`
  - `estimated_cost_usd` (policy-aware)

### FR-3 Time-Bounded Summaries
- Daily and MTD must use user timezone
- Forecast must use same timezone boundaries as summary

### FR-4 Quota Resolution
- Fallback chain: snapshot file -> cache -> manual file
- Return confidence marker for each quota row

### FR-5 Chat Output
- `/clawcast` default message has fixed section contract:
  - Today / MTD / Forecast / Quota / Latency / Alerts

### FR-6 Delivery Automation
- Telegram and Slack scripts post message and optional report artifact
- Must hard-fail on provider API failure payloads

## 8) Non-Functional Requirements
- Performance: p95 `clawcast message` <= 3s on 30 days of logs
- Reliability: command returns valid output for empty datasets (graceful zero state)
- Observability: explicit stderr errors on data load, formatting, or network failures
- Compatibility: Python 3.10+; deterministic install path through Homebrew formula

## 9) Release Plan (Execution Order)
1. Patch timezone-consistent forecast
2. Harden Telegram/Slack API response validation
3. Split oversized modules (no behavior change refactor)
4. Add script integration tests + edge-case fixtures
5. Cut `v0.2.0` release with migration notes

## 10) Acceptance Criteria (Ship Gate)
- All existing tests pass
- New tests added for:
  - timezone-consistent forecast windowing
  - chat API failure payload handling
  - alert severity ordering
- Manual checks:
  - `clawcast message --dir <empty>` exits 0 with zero-state output
  - Telegram/Slack dry-run and live-path success
  - Homebrew install and `clawcast --help` success

## 11) Kill Criteria (Brutal but Necessary)
If after two iterations we cannot keep p95 latency <= 3s and trust error reports under 2%, de-scope HTML/report features and keep only `/clawcast` message pipeline until reliability is met.
