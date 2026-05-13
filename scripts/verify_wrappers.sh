#!/usr/bin/env bash
# End-to-end check that scripts/run_claude.sh and scripts/run_copilot.sh both
# work on this machine: resolves the right binaries, exec's the tools with a
# trivial prompt ("create a file called HELLO.txt"), and shows every artifact
# the wrappers produce.
#
# Costs real money / seat usage (cents per run). Requires `claude` and
# `copilot` to be authenticated. Run it after the prereq checker passes and
# whenever a CLI updates, to catch flag-surface drift early.
#
# Usage: scripts/verify_wrappers.sh [--tool claude|copilot|both]
#
# Output goes to runs/wrapper-verify/ (gitignored). The directory is wiped on
# each invocation. Exits with the worst exit code of the wrappers that ran.

set -uo pipefail

TOOL=both
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool) TOOL="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0" >&2; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[[ "$TOOL" =~ ^(claude|copilot|both)$ ]] \
  || { echo "--tool must be claude|copilot|both" >&2; exit 2; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
ROOT="$REPO_ROOT/runs/wrapper-verify"

echo "==> Cleaning $ROOT"
rm -rf "$ROOT"
mkdir -p "$ROOT"

setup_workdir() {
  local w="$1"
  mkdir -p "$w"
  git -C "$w" init -q --initial-branch=main
  git -C "$w" config user.email verify@example.com
  git -C "$w" config user.name "wrapper-verify"
  ( cd "$w" && echo "v1" > seed.txt && git add . && git commit -q -m seed )
}

OVERALL=0

run_one() {
  local tool="$1"
  local workdir="$ROOT/workdir-$tool"
  local rundir="$ROOT/$tool-run"
  local prompt="$ROOT/prompt-$tool.txt"

  echo
  echo "==> $tool: setting up workdir + prompt"
  setup_workdir "$workdir"
  printf "Create a file named HELLO.txt in the current directory containing the single line 'hi from %s'.\n" "$tool" \
    > "$prompt"
  mkdir -p "$rundir"

  echo "==> $tool: invoking scripts/run_${tool}.sh"
  "$SCRIPT_DIR/run_${tool}.sh" \
    --workdir "$workdir" \
    --run-dir "$rundir" \
    --prompt-file "$prompt"
  local rc=$?
  if (( rc != 0 )); then
    echo "==> $tool: wrapper exited $rc (continuing so the other tool still runs)"
    (( rc > OVERALL )) && OVERALL=$rc
  fi
}

summarize_one() {
  local tool="$1"
  local rundir="$ROOT/$tool-run"
  local workdir="$ROOT/workdir-$tool"
  echo
  echo "--- $tool ---"
  printf "  exit_code:           %s\n" "$(cat "$rundir/exit_code" 2>/dev/null || echo '(missing)')"
  printf "  wall_clock_seconds:  %s\n" "$(cat "$rundir/wall_clock_seconds" 2>/dev/null || echo '(missing)')"
  if [[ -s "$rundir/tool_info.json" ]]; then
    printf "  tool_info.json:      %s\n" "$(cat "$rundir/tool_info.json")"
  else
    printf "  tool_info.json:      (missing)\n"
  fi
  if [[ -s "$rundir/stdout.log" ]]; then
    printf "  stdout.log:          %s lines, %s bytes\n" \
      "$(wc -l < "$rundir/stdout.log" | tr -d ' ')" \
      "$(wc -c < "$rundir/stdout.log" | tr -d ' ')"
  else
    printf "  stdout.log:          (empty or missing)\n"
  fi
  printf "  stderr.log:          %s bytes\n" \
    "$(wc -c < "$rundir/stderr.log" 2>/dev/null | tr -d ' ' || echo 0)"
  if [[ -f "$workdir/HELLO.txt" ]]; then
    printf "  agent diff:          HELLO.txt = %s\n" "$(cat "$workdir/HELLO.txt")"
  else
    printf "  agent diff:          (no HELLO.txt — diff is empty)\n"
  fi
}

[[ "$TOOL" == claude  || "$TOOL" == both ]] && run_one claude
[[ "$TOOL" == copilot || "$TOOL" == both ]] && run_one copilot

echo
echo "==> Results"
[[ "$TOOL" == claude  || "$TOOL" == both ]] && summarize_one claude
[[ "$TOOL" == copilot || "$TOOL" == both ]] && summarize_one copilot

echo
echo "Artifacts: $ROOT"
echo "  - <tool>-run/{exit_code, wall_clock_seconds, tool_info.json, stdout.log, stderr.log}"
echo "  - workdir-<tool>/HELLO.txt  ← the agent's diff"
echo "  - prompt-<tool>.txt         ← the prompt that was sent"

exit "$OVERALL"
