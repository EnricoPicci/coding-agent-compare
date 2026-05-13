#!/usr/bin/env bash
# Invoke Claude Code headlessly inside a prepared worktree.
#
# Contract: identical between scripts/run_claude.sh and scripts/run_copilot.sh.
#   --workdir <dir>      directory the agent treats as its working tree
#   --run-dir <dir>      directory this script writes output into
#   --prompt-file <file> file whose contents are passed as the prompt
#   --model <name>       optional; passed straight through to the tool
#
# Writes to <run-dir>:
#   stdout.log           full stdout (with --output-format stream-json this IS the trace)
#   stderr.log           full stderr
#   exit_code            single integer line — the tool's exit status
#   wall_clock_seconds   single integer line — elapsed seconds end-to-end in this script
#   tool_info.json       resolved binary path + version (for the run manifest)
#
# Wall-clock timeout (SIGTERM/SIGKILL) is the Python supervisor's job, not this
# script's. This script just exec's the tool.

set -euo pipefail

WORKDIR=""; RUN_DIR=""; PROMPT_FILE=""; MODEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)     WORKDIR="$2"; shift 2 ;;
    --run-dir)     RUN_DIR="$2"; shift 2 ;;
    --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
    --model)       MODEL="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,18p' "$0" >&2; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

for v in WORKDIR RUN_DIR PROMPT_FILE; do
  if [[ -z "${!v}" ]]; then
    echo "missing required --$(echo $v | tr 'A-Z_' 'a-z-')" >&2
    exit 2
  fi
done
[[ -d "$WORKDIR" ]]    || { echo "workdir does not exist: $WORKDIR" >&2; exit 2; }
[[ -f "$PROMPT_FILE" ]] || { echo "prompt file not readable: $PROMPT_FILE" >&2; exit 2; }
mkdir -p "$RUN_DIR"

# Resolve the binary: project-local node_modules first, then PATH. Mirrors the
# resolution order documented in the plan's Step 5 "Tool resolution note".
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

resolve_bin() {
  local name="$1"
  local local_bin="$REPO_ROOT/node_modules/.bin/$name"
  if [[ -x "$local_bin" ]]; then echo "$local_bin"; return 0; fi
  command -v "$name" || return 1
}

CLAUDE_BIN="$(resolve_bin claude)" || { echo "claude not found on PATH or in ./node_modules/.bin" >&2; exit 3; }

# Reject stubs: a binary that doesn't print a recognizable version string is
# either the VS Code Copilot stub variant for this tool or otherwise unusable.
VERSION_OUT="$("$CLAUDE_BIN" --version 2>&1 || true)"
if ! grep -qE '[0-9]+\.[0-9]+' <<< "$VERSION_OUT"; then
  echo "$CLAUDE_BIN did not return a recognizable version: $VERSION_OUT" >&2
  exit 3
fi
VERSION_LINE="$(printf '%s' "$VERSION_OUT" | head -n1)"

# Read prompt safely — quoted assignment, no command substitution re-expansion.
PROMPT="$(<"$PROMPT_FILE")"

# Build invocation. --output-format=stream-json requires --verbose with --print.
args=( -p "$PROMPT" --output-format stream-json --verbose --dangerously-skip-permissions )
[[ -n "$MODEL" ]] && args+=( --model "$MODEL" )

python3 -c '
import json, sys
print(json.dumps({"tool": sys.argv[1], "binary": sys.argv[2], "version": sys.argv[3]}))
' claude "$CLAUDE_BIN" "$VERSION_LINE" > "$RUN_DIR/tool_info.json"

start=$(date +%s)
set +e
( cd "$WORKDIR" && "$CLAUDE_BIN" "${args[@]}" ) >"$RUN_DIR/stdout.log" 2>"$RUN_DIR/stderr.log"
status=$?
set -e
end=$(date +%s)

printf '%d\n' "$status"      > "$RUN_DIR/exit_code"
printf '%d\n' "$(( end - start ))" > "$RUN_DIR/wall_clock_seconds"
exit "$status"
