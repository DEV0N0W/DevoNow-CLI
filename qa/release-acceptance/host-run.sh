#!/bin/bash
# Run checks in the Ubuntu VM and copy their reports to this harness directory.
set -euo pipefail
MODE="${1:-pending}"
case "$MODE" in
  pending|report|retry-bubblewrap|extended|build) ;;
  *) echo "Usage: $0 [pending|report|retry-bubblewrap|extended|build]" >&2; exit 2 ;;
esac

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VM="devonow-ubuntu2404"
HOST_REPORTS="$SCRIPT_DIR/reports"

if ! command -v limactl >/dev/null 2>&1; then
  echo "ERROR: Lima (limactl) not found on your macOS PATH." >&2
  exit 2
fi

GUEST_HOME="$(limactl shell "$VM" -- sh -c 'printf %s "$HOME"')"
if [[ "$GUEST_HOME" != /* || "$GUEST_HOME" == *$'\n'* ]]; then
  echo "ERROR: Could not determine the Ubuntu guest home directory." >&2
  exit 2
fi
GUEST_SUITE="$GUEST_HOME/devonow-acceptance-suite"
GUEST_STATE="$GUEST_HOME/.local/state/devonow-acceptance"

echo "=== Confirm Ubuntu VM and source snapshot ==="
if ! limactl shell "$VM" -- bash -lc 'test -f "$HOME/devonow-linux-test/devnow-rs/Cargo.toml" && test -x "$HOME/devonow-linux-test/devnow-rs/target/debug/codex"'; then
  echo "ERROR: Ubuntu VM/source/binary not ready. No changes were made to your host repository." >&2
  exit 2
fi

echo "=== Install/update harness ONLY inside Ubuntu user HOME ==="
limactl shell "$VM" -- bash -lc 'mkdir -p "$HOME/devonow-acceptance-suite"'
limactl copy -r "$SCRIPT_DIR/suite/." "$VM:$GUEST_SUITE/"

echo "=== Execute $MODE inside $VM ==="
run_code=0
if limactl shell "$VM" -- python3 "$GUEST_SUITE/runner.py" --mode "$MODE"; then
  echo "=== Harness run finished ==="
else
  run_code=$?
  echo "=== Harness returned exit code $run_code; collecting reports ==="
fi

mkdir -p "$HOST_REPORTS" "$HOST_REPORTS/logs"
echo "=== Copy acceptance reports to $HOST_REPORTS ==="
if ! limactl copy -r "$VM:$GUEST_STATE/reports/." "$HOST_REPORTS/"; then
  echo "WARNING: Could not copy guest reports; existing guest state remains preserved." >&2
fi
if ! limactl copy -r "$VM:$GUEST_STATE/logs/." "$HOST_REPORTS/logs/"; then
  echo "WARNING: Could not copy per-test logs; guest logs remain preserved." >&2
fi

printf '\nReport on your Mac: %s/latest-summary.md\n' "$HOST_REPORTS"
printf 'Structured results: %s/latest-results.json\n' "$HOST_REPORTS"
printf 'Original macOS repository: not modified by this harness.\n'
exit "$run_code"
