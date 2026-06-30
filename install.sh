#!/bin/bash
# ccwhat installer script
set -e

ACTION="${1:-install}"
OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
CCWHAT_PACKAGE_URL="git+https://github.com/PacemakerG/CCWhat.git"

echo "=================================================="
echo "  ccwhat installer"
echo "=================================================="
echo ""

case "$OS_NAME" in
  Darwin|Linux) ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "This Bash installer is for macOS, Linux, and WSL."
    echo "For native Windows PowerShell, install with:"
    echo "  uv tool install git+https://github.com/PacemakerG/CCWhat.git"
    echo "  uv tool install mitmproxy"
    exit 1
    ;;
  *)
    echo "Unsupported OS: $OS_NAME"
    echo "Supported: macOS, Linux, WSL"
    exit 1
    ;;
esac

PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "$candidate")"
      break
    fi
  fi
done
if [ -z "$PYTHON_BIN" ]; then
  echo "Python not found. Please install Python 3.10+ first."
  exit 1
fi
PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
echo "Python: $PYTHON_VERSION  ($PYTHON_BIN)"

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10+ is required."
  exit 1
fi

if [ "$ACTION" = "uninstall" ]; then
  echo "Uninstalling ccwhat..."
  if command -v pipx &>/dev/null; then
    pipx uninstall ccwhat 2>/dev/null || true
  fi
  "$PYTHON_BIN" -m pip uninstall -y ccwhat 2>/dev/null || true
  echo "Uninstall complete. Local logs/config are kept at ~/.ccwhat"
  exit 0
fi

if [ "$ACTION" != "install" ]; then
  echo "Unknown action: $ACTION"
  echo "Usage: install.sh [uninstall]"
  exit 1
fi

PIP_FLAGS=()
if "$PYTHON_BIN" -m pip install --help 2>&1 | grep -q -- '--break-system-packages'; then
  PIP_FLAGS+=(--break-system-packages)
fi

# Install mitmproxy if needed
if ! command -v mitmdump &>/dev/null; then
  if [ "$OS_NAME" = "Darwin" ] && command -v brew &>/dev/null; then
    echo "Installing mitmproxy via Homebrew..."
    brew install mitmproxy
  elif command -v pipx &>/dev/null; then
    echo "Installing mitmproxy via pipx..."
    pipx install mitmproxy || pipx upgrade mitmproxy
  else
    echo "Installing mitmproxy via pip..."
    "$PYTHON_BIN" -m pip install --user "${PIP_FLAGS[@]}" mitmproxy
  fi
fi

echo ""
echo "Installing ccwhat..."
if command -v pipx &>/dev/null; then
  pipx install --force "$CCWHAT_PACKAGE_URL"
else
  "$PYTHON_BIN" -m pip install --user --upgrade "${PIP_FLAGS[@]}" "$CCWHAT_PACKAGE_URL"
fi

echo ""
if command -v ccwhat &>/dev/null && command -v mitmdump &>/dev/null; then
  echo "Install complete! Run: ccwhat --help"
else
  USER_BIN=$("$PYTHON_BIN" -m site --user-base 2>/dev/null)/bin
  echo "Install complete!"
  echo ""
  echo "Note: ccwhat or mitmdump is not on PATH yet. Add to your shell config:"
  echo "  export PATH=\"$USER_BIN:\$PATH\""
  echo ""
  echo "Then open a new shell and run: ccwhat --help"
fi
