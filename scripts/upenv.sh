#!/usr/bin/env bash
# Source this script from each shell that runs Archer.
if [[ -n "${ZSH_VERSION:-}" ]]; then
  ARCHER_SCRIPT_DIR="$(cd "$(dirname "${(%):-%N}")" && pwd)"
elif [[ -n "${BASH_VERSION:-}" ]]; then
  ARCHER_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  echo "Use bash or zsh to source this script."
  return 1
fi
export ARCHER_HOME_DIR="$(cd "$ARCHER_SCRIPT_DIR/.." && pwd)"
export LAB_RUST_BUILD_DIR="${LAB_RUST_BUILD_DIR:-$ARCHER_HOME_DIR/build/rust}"
export LAB_MIRI_TOOLCHAIN="${LAB_MIRI_TOOLCHAIN:-nightly}"
if ! command -v rustup >/dev/null 2>&1 && [[ -x /opt/homebrew/opt/rustup/bin/rustup ]]; then
  export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
fi
if command -v rustup >/dev/null 2>&1; then
  export RUSTUP="$(command -v rustup)"
  _archer_nightly_rustc="$("$RUSTUP" which rustc --toolchain "$LAB_MIRI_TOOLCHAIN" 2>/dev/null || true)"
  if [[ -n "$_archer_nightly_rustc" ]]; then
    export PATH="$(dirname "$_archer_nightly_rustc"):$PATH"
  fi
fi
if [[ -f "$ARCHER_HOME_DIR/environments" ]]; then
  set -a
  source "$ARCHER_HOME_DIR/environments"
  set +a
fi
