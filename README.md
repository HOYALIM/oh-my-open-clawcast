# Oh My Open Clawcast

Standalone analytics/forecast toolkit for OpenClaw cron logs.

This project is intentionally **outside core OpenClaw** so it can move faster as a community extension/tool.

## What it computes

1. `p50/p95` response latency (`duration_ms`) by provider/model
2. Daily token usage + moving average (`7d`, `30d`)
3. Model-level cost estimation using token-rate table
4. Month-end forecast for tokens/cost (based on recent `N`-day trend)
5. Anomaly detection
   - token spikes via z-score
   - latency spikes via z-score
   - failure-rate surges via mean + sigma

## Install

```bash
cd oh-my-open-clawcast
pip install -r requirements.txt
pip install -e .
```

## Quick usage

```bash
# show rate table
clawcast table rates

# model latency table
clawcast table latency --dir ~/.openclaw

# full HTML report
clawcast report --dir ~/.openclaw --out examples/forecast_report.html
```

## Custom price table

Create `rates.json`:

```json
{
  "openai/gpt-4o": {
    "input_per_1m": 5.0,
    "output_per_1m": 15.0,
    "cache_read_per_1m": 1.25,
    "cache_write_per_1m": 0.0
  },
  "anthropic/claude-sonnet-4-5": {
    "input_per_1m": 3.0,
    "output_per_1m": 15.0
  }
}
```

Then:

```bash
clawcast report --rates rates.json --out examples/forecast_report_custom_rates.html
```

## Output preview options

- HTML report: `examples/forecast_report.html`
- Notebook workflow: `notebooks/forecast_demo.ipynb`

## Telegram / Slack delivery

Use helper scripts to generate a report and post it to chat.

```bash
chmod +x scripts/send_telegram_report.sh scripts/send_slack_report.sh
```

Telegram:

```bash
export TELEGRAM_BOT_TOKEN="123456:abc..."
export TELEGRAM_CHAT_ID="-100xxxxxxxxxx"   # group/channel/chat id
./scripts/send_telegram_report.sh
```

Slack (webhook summary):

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
./scripts/send_slack_report.sh
```

Slack (file upload):

```bash
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_CHANNEL="C0123456789"
./scripts/send_slack_report.sh
```

Notes:

1. If live OpenClaw logs are missing, scripts fall back to demo report generation by default.
2. Set `ALLOW_DEMO_FALLBACK=0` to force live-log-only behavior.
3. Set `DRY_RUN=1` to test end-to-end without sending any external requests.

## Recommended multi-AI workflow (you + Codex + Claude Code + Gemini)

### Role split

1. **Codex**
   - scaffolding, implementation, refactor, CI wiring
   - bulk edits and deterministic transforms
2. **Claude Code**
   - architecture review, data-model decisions, edge-case design
   - writing strict acceptance criteria and test plans
3. **Gemini (reviewer)**
   - adversarial code review
   - highlight correctness gaps and maintainability risks before merge

### Branch policy

1. `main`: always releasable
2. `feat/*`: implementation branches (Codex)
3. `design/*`: architecture/doc branches (Claude Code)
4. merge only after Gemini review + tests pass

### PR checklist

1. One feature per PR
2. Include before/after output snippet (table or HTML section)
3. Add/update tests for each new metric
4. Include known limits (e.g., estimated cost depends on rate table quality)

## Forecast details (for your next iteration)

1. Weighted trend model
   - combine 7d and 30d MA (`0.7 * MA7 + 0.3 * MA30`)
2. Confidence bands
   - monthly forecast low/base/high using daily variance
3. Seasonality
   - weekday/weekend split forecast (cron workloads often differ)
4. Budget guardrails
   - alert if projected month cost exceeds budget threshold
5. Model-mix drift
   - detect cost risk from expensive model share increase

## Current assumptions/limits

1. Cost is estimated from token pricing table (not provider billing API truth)
2. Forecast extrapolates recent behavior; sudden policy/model changes can break projection
3. Missing `duration_ms` / token fields reduce signal quality
