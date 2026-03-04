#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ACTIVATE="${ROOT_DIR}/.venv/bin/activate"

if [[ ! -f "${VENV_ACTIVATE}" ]]; then
  echo "Missing virtualenv at ${VENV_ACTIVATE}"
  echo "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -e ."
  exit 1
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first."
  exit 1
fi

OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/out}"
RATES_FILE="${RATES_FILE:-}"
ALLOW_DEMO_FALLBACK="${ALLOW_DEMO_FALLBACK:-1}"
DRY_RUN="${DRY_RUN:-0}"
TZ_NAME="${TZ_NAME:-UTC}"
QUOTA_LIVE_FILE="${QUOTA_LIVE_FILE:-}"
QUOTA_MANUAL_FILE="${QUOTA_MANUAL_FILE:-}"
SEND_REPORT_DOC="${SEND_REPORT_DOC:-1}"
STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_HTML="${REPORT_HTML:-${OUT_DIR}/clawcast_${STAMP}.html}"

mkdir -p "${OUT_DIR}"
source "${VENV_ACTIVATE}"

REPORT_CMD=(clawcast report --dir "${OPENCLAW_DIR}" --out "${REPORT_HTML}")
MESSAGE_CMD=(clawcast message --dir "${OPENCLAW_DIR}" --tz "${TZ_NAME}")
if [[ -n "${RATES_FILE}" ]]; then
  REPORT_CMD+=(--rates "${RATES_FILE}")
  MESSAGE_CMD+=(--rates "${RATES_FILE}")
fi
if [[ -n "${QUOTA_LIVE_FILE}" ]]; then
  MESSAGE_CMD+=(--quota-live-file "${QUOTA_LIVE_FILE}")
fi
if [[ -n "${QUOTA_MANUAL_FILE}" ]]; then
  MESSAGE_CMD+=(--quota-manual-file "${QUOTA_MANUAL_FILE}")
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

MESSAGE_TEXT="$("${MESSAGE_CMD[@]}" 2>&1 || true)"
if [[ -z "${MESSAGE_TEXT}" ]]; then
  MESSAGE_TEXT="[Clawcast] no output"
fi

if [[ "${REPORT_MODE}" == "demo" ]]; then
  MESSAGE_TEXT="${MESSAGE_TEXT}

Note: demo fallback mode (live logs missing)"
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[DRY_RUN] Would send Telegram message to chat ${TELEGRAM_CHAT_ID}"
  echo "[DRY_RUN] Message preview:"
  echo "${MESSAGE_TEXT}" | sed -n '1,40p'
  echo "[DRY_RUN] Report file: ${REPORT_HTML}"
  exit 0
fi

curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${MESSAGE_TEXT}" >/tmp/clawcast_tg_message_resp.json

if [[ "${SEND_REPORT_DOC}" == "1" ]]; then
  curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
    -F "chat_id=${TELEGRAM_CHAT_ID}" \
    -F "document=@${REPORT_HTML}" >/tmp/clawcast_tg_doc_resp.json
fi

echo "Sent Telegram report: ${REPORT_HTML}"
