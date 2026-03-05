class Clawcast < Formula
  desc "Messenger-first telemetry summary for OpenClaw usage"
  homepage "https://github.com/HOYALIM/oh-my-open-clawcast"
  url "https://github.com/HOYALIM/oh-my-open-clawcast/archive/86a4f63.tar.gz"
  sha256 "9329081571dfd67841ad602883f99d4378931ab1e71d859bf01f21a18fc403c5"
  license "MIT"

  depends_on "python@3.13"

  def install
    (bin/"clawcast").write <<~SH
      #!/usr/bin/env bash
      set -euo pipefail

      INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/oh-my-open-clawcast"
      VENV_DIR="$INSTALL_ROOT/venv"
      REPO_URL="https://github.com/HOYALIM/oh-my-open-clawcast.git"
      REF="main"

      if [[ ! -x "$VENV_DIR/bin/clawcast" ]]; then
        mkdir -p "$INSTALL_ROOT"
        "#{Formula["python@3.13"].opt_bin}/python3.13" -m venv "$VENV_DIR"
        "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
        "$VENV_DIR/bin/python" -m pip install "git+$REPO_URL@$REF" >/dev/null
      fi

      exec "$VENV_DIR/bin/clawcast" "$@"
    SH
  end

  test do
    assert_match "usage: clawcast", shell_output("#{bin}/clawcast --help")
  end
end
