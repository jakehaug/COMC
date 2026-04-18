#!/usr/bin/env bash
# One-time setup for the COMC trading agent on macOS.
#
# Usage: ./setup.sh
#
# What it does:
#   1. Installs Homebrew if it's missing.
#   2. Installs Python 3.11+ via Homebrew if the system Python is too old.
#   3. Creates a local Python virtual environment in .venv/
#   4. Installs the agent and its dependencies.
#   5. Downloads the Chromium browser that the agent drives.
#
# Idempotent - safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "$SCRIPT_DIR"

say() { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m %s\n" "$*" >&2; }

# 1. Homebrew
# If brew is installed but not on the PATH in this shell, pull it onto PATH
# so we don't accidentally reinstall.
for brewpath in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$brewpath" ] && ! command -v brew >/dev/null 2>&1; then
        eval "$($brewpath shellenv)"
        break
    fi
done

if ! command -v brew >/dev/null 2>&1; then
    say "Installing Homebrew (you may be asked for your password)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to the current shell's PATH for the rest of this run.
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    say "Homebrew already installed."
fi

# 2. Python 3.11+
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
        major=${ver%%.*}
        minor=${ver##*.}
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON_BIN="$(command -v "$candidate")"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    say "Installing Python 3.12 via Homebrew..."
    brew install python@3.12
    PYTHON_BIN="$(brew --prefix)/opt/python@3.12/bin/python3.12"
fi
say "Using Python at: $PYTHON_BIN"

# 3. Virtual environment
if [ ! -d .venv ]; then
    say "Creating virtual environment in .venv/"
    "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 4. Install the project
say "Installing the agent and dependencies (this can take a minute)..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -e ".[dev]"

# 5. Browsers (both Playwright's and Patchright's Chromium builds)
say "Downloading the browsers the agent will drive..."
python -m playwright install chromium
# Patchright uses its own patched Chromium. The install step is idempotent.
python -m patchright install chromium 2>/dev/null || true

say "Done!"
cat <<'EOF'

Next steps:
  ./comc login      - open a browser, sign into COMC once; the session is saved
  ./comc doctor     - check that the agent can read COMC's pages
  ./comc scan       - dry-run: find buy candidates without actually buying
  ./comc scan --live - really buy (start with this only after doctor passes)
  ./comc portfolio  - show your inventory and P&L
  ./comc run        - start the hourly/daily loop

EOF
