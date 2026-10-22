#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
command -v node >/dev/null || { echo "Install Node.js 22.19 or newer first."; exit 1; }
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 19)) process.exit(1)' || { echo "Node.js 22.19 or newer is required."; exit 1; }
command -v npm >/dev/null || { echo "Install npm first."; exit 1; }
RUSTUP_BIN="$(command -v rustup || true)"
if [[ -z "$RUSTUP_BIN" && -x /opt/homebrew/opt/rustup/bin/rustup ]]; then
  RUSTUP_BIN=/opt/homebrew/opt/rustup/bin/rustup
fi
[[ -n "$RUSTUP_BIN" ]] || { echo "Install Rust using https://rustup.rs first."; exit 1; }
"$RUSTUP_BIN" toolchain install nightly --component miri --component rust-src
"$RUSTUP_BIN" component add rust-src --toolchain nightly
(cd "$SCRIPT_DIR/.." && npm ci && npm run build)
echo "Node dependencies, the TypeScript CLI, Rust nightly and Miri are ready."
