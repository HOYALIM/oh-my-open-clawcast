#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/HOYALIM/oh-my-open-clawcast.git}"
REF="${REF:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.oh-my-open-clawcast}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Missing $PYTHON_BIN. Install Python 3.10+ first."
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

"$PYTHON_BIN" -m venv "$INSTALL_DIR"
# shellcheck disable=SC1091
source "$INSTALL_DIR/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install "git+$REPO_URL@$REF" >/dev/null

cat >"$BIN_DIR/clawcast" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/bin/clawcast" "\$@"
EOF
chmod +x "$BIN_DIR/clawcast"

echo "Installed clawcast at: $BIN_DIR/clawcast"
if ! command -v clawcast >/dev/null 2>&1; then
  echo "Add to PATH if needed:"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi

echo "Run:"
echo "  clawcast --help"
