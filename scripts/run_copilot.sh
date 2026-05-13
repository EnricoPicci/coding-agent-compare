#!/usr/bin/env bash
# Invoke GitHub Copilot CLI headlessly inside a prepared worktree.
#
# Contract: identical between scripts/run_claude.sh and scripts/run_copilot.sh.
#   --workdir <dir>      directory the agent treats as its working tree
#   --run-dir <dir>      directory this script writes output into
#   --prompt-file <file> file whose contents are passed as the prompt
#   --model <name>       optional; passed straight through to the tool
#
# Writes to <run-dir>:
#   stdout.log           full stdout (with --output-format json this IS the trace)
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

# Resolve the binary: project-local node_modules first, then PATH. The VS Code
# Copilot Chat extension installs a stub `copilot` that often lives earlier in
# PATH; the local resolution is what makes that stub avoidable.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

resolve_bin() {
  local name="$1"
  local local_bin="$REPO_ROOT/node_modules/.bin/$name"
  if [[ -x "$local_bin" ]]; then echo "$local_bin"; return 0; fi
  command -v "$name" || return 1
}

COPILOT_BIN="$(resolve_bin copilot)" || { echo "copilot not found on PATH or in ./node_modules/.bin" >&2; exit 3; }

# Reject stubs. The VS Code Copilot Chat stub prints an "Install GitHub Copilot
# CLI? [y/N]" prompt with no version string and exits 0 — fatal if not caught.
VERSION_OUT="$("$COPILOT_BIN" --version 2>&1 || true)"
if ! grep -qE '[0-9]+\.[0-9]+' <<< "$VERSION_OUT"; then
  echo "$COPILOT_BIN did not return a recognizable version: $VERSION_OUT" >&2
  echo "(likely the VS Code Copilot Chat stub; install @github/copilot locally or globally)" >&2
  exit 3
fi
VERSION_LINE="$(printf '%s' "$VERSION_OUT" | head -n1)"

PROMPT="$(<"$PROMPT_FILE")"

args=( -p "$PROMPT" --allow-all-tools --output-format json --no-auto-update --no-color -C "$WORKDIR" )
[[ -n "$MODEL" ]] && args+=( --model "$MODEL" )

python3 -c '
import json, sys
print(json.dumps({"tool": sys.argv[1], "binary": sys.argv[2], "version": sys.argv[3]}))
' copilot "$COPILOT_BIN" "$VERSION_LINE" > "$RUN_DIR/tool_info.json"

start=$(date +%s)
set +e
"$COPILOT_BIN" "${args[@]}" >"$RUN_DIR/stdout.log" 2>"$RUN_DIR/stderr.log"
status=$?
set -e
end=$(date +%s)

printf '%d\n' "$status"      > "$RUN_DIR/exit_code"
printf '%d\n' "$(( end - start ))" > "$RUN_DIR/wall_clock_seconds"
exit "$status"
