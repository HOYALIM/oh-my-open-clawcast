#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ACTIVATE="${ROOT_DIR}/.venv/bin/activate"

if [[ ! -f "${VENV_ACTIVATE}" ]]; then
  echo "Missing virtualenv at ${VENV_ACTIVATE}"
  echo "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -e ."
  exit 1
fi

if [[ -z "${SLACK_WEBHOOK_URL:-}" && ( -z "${SLACK_BOT_TOKEN:-}" || -z "${SLACK_CHANNEL:-}" ) ]]; then
  echo "Set SLACK_WEBHOOK_URL or (SLACK_BOT_TOKEN + SLACK_CHANNEL)."
  exit 1
fi

OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/out}"
RATES_FILE="${RATES_FILE:-}"
ALLOW_DEMO_FALLBACK="${ALLOW_DEMO_FALLBACK:-1}"
DRY_RUN="${DRY_RUN:-0}"
STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_HTML="${REPORT_HTML:-${OUT_DIR}/clawcast_${STAMP}.html}"
REPORT_PUBLIC_URL="${REPORT_PUBLIC_URL:-}"

mkdir -p "${OUT_DIR}"
source "${VENV_ACTIVATE}"

REPORT_CMD=(clawcast report --dir "${OPENCLAW_DIR}" --out "${REPORT_HTML}")
ANOMALY_CMD=(clawcast table anomaly --dir "${OPENCLAW_DIR}")
if [[ -n "${RATES_FILE}" ]]; then
  REPORT_CMD+=(--rates "${RATES_FILE}")
  ANOMALY_CMD+=(--rates "${RATES_FILE}")
fi

REPORT_MODE="live"
if ! "${REPORT_CMD[@]}" >/tmp/clawcast_report_stdout.txt 2>/tmp/clawcast_report_stderr.txt; then
  if [[ "${ALLOW_DEMO_FALLBACK}" == "1" ]]; then
    python "${ROOT_DIR}/examples/generate_demo.py" >/tmp/clawcast_report_stdout.txt 2>/tmp/clawcast_report_stderr.txt
    REPORT_HTML="${ROOT_DIR}/examples/demo_forecast_report.html"
    REPORT_MODE="demo"
  else
    echo "Report generation failed:"
    cat /tmp/clawcast_report_stderr.txt
    exit 1
  fi
fi

ANOMALY_TEXT="$("${ANOMALY_CMD[@]}" 2>&1 || true)"
if [[ -z "${ANOMALY_TEXT}" ]]; then
  ANOMALY_TEXT="(No anomaly rows or no run logs found.)"
fi

MSG_HEADER="[Clawcast] ${REPORT_MODE} report ready on $(hostname) at $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
if [[ -n "${REPORT_PUBLIC_URL}" ]]; then
  MSG_HEADER="${MSG_HEADER}\nReport: ${REPORT_PUBLIC_URL}"
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[DRY_RUN] Would send Slack report."
  echo "[DRY_RUN] Report file: ${REPORT_HTML}"
  exit 0
fi

if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
  ESCAPED_TEXT="${MSG_HEADER}\n\nAnomaly summary:\n\`\`\`${ANOMALY_TEXT}\`\`\`"
  curl -fsS -X POST -H "Content-type: application/json" \
    --data "{\"text\":\"${ESCAPED_TEXT//$'\n'/\\n}\"}" \
    "${SLACK_WEBHOOK_URL}" >/tmp/clawcast_slack_webhook_resp.txt
fi

if [[ -n "${SLACK_BOT_TOKEN:-}" && -n "${SLACK_CHANNEL:-}" ]]; then
  curl -fsS "https://slack.com/api/files.upload" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    -F "channels=${SLACK_CHANNEL}" \
    -F "initial_comment=${MSG_HEADER}" \
    -F "file=@${REPORT_HTML}" >/tmp/clawcast_slack_upload_resp.json
fi

echo "Sent Slack report: ${REPORT_HTML}"
