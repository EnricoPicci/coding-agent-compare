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
# Usage:
#   scripts/verify_wrappers.sh [--tool claude|copilot|both]
#                              [--model NAME]
#                              [--model-for claude=NAME] [--model-for copilot=NAME]
#
# --tool       which wrapper(s) to exercise (default: both)
# --model      optional shared model name forwarded to the wrapper(s) as
#              --model NAME. Used as the default for any tool not given a
#              --model-for override.
# --model-for  per-tool model override, repeatable. Use when the two CLIs
#              use different names for the same underlying model — e.g.
#              `claude` wants `claude-sonnet-4-6` (dashes) while `copilot`
#              wants `claude-sonnet-4.6` (dots). Takes precedence over
#              --model for the named tool. Format: claude=NAME or
#              copilot=NAME.
#
# When neither --model nor --model-for is given, each tool runs on its
# built-in default model.
#
# Examples:
#
#   # 1. Default — both tools on their built-in default models. Useful as
#   #    a general sanity check after a CLI update.
#   scripts/verify_wrappers.sh
#
#   # 2. Just claude on its default model (skip copilot).
#   scripts/verify_wrappers.sh --tool claude
#
#   # 3. Just claude with a specific Anthropic model name. The wrapper
#   #    passes --model claude-sonnet-4-6 through to `claude -p ...`.
#   scripts/verify_wrappers.sh --tool claude --model claude-sonnet-4-6
#
#   # 4. Just copilot, probing whether your Copilot subscription accepts
#   #    a particular model name. Fast diagnostic: ~10-20s if accepted,
#   #    ~4s with "Error: Model … not available" if not. No API budget
#   #    burned on rejection.
#   scripts/verify_wrappers.sh --tool copilot --model claude-sonnet-4.6
#   scripts/verify_wrappers.sh --tool copilot --model gpt-5.4
#
#   # 5. Both tools with the same model — pre-flight for the simple case
#   #    where one name happens to work for both. (Often it doesn't —
#   #    see example 6.)
#   scripts/verify_wrappers.sh --model claude-sonnet-4-6
#
#   # 6. Both tools with DIFFERENT names per tool — the realistic case
#   #    when claude wants the Anthropic-canonical name (with dashes) and
#   #    copilot wants its own re-labeled name (with dots) for the same
#   #    underlying Claude Sonnet 4.6 model. This is the canonical
#   #    PRE-FLIGHT before a Harness-framing smoke matrix.
#   scripts/verify_wrappers.sh --model-for claude=claude-sonnet-4-6 --model-for copilot=claude-sonnet-4.6
#
#   # 7. Mixed: --model as a default, --model-for to override one tool.
#   #    Equivalent to example 6 in this case but shorter when only one
#   #    tool needs a different name.
#   scripts/verify_wrappers.sh \
#     --model claude-sonnet-4-6 \
#     --model-for copilot=claude-sonnet-4.6
#
# Output goes to runs/wrapper-verify/ (gitignored). The directory is wiped on
# each invocation. Exits with the worst exit code of the wrappers that ran.

set -uo pipefail

TOOL=both
MODEL=""
MODEL_FOR_CLAUDE=""
MODEL_FOR_COPILOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)  TOOL="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --model-for)
      ENTRY="$2"; shift 2
      case "$ENTRY" in
        claude=*)  MODEL_FOR_CLAUDE="${ENTRY#claude=}" ;;
        copilot=*) MODEL_FOR_COPILOT="${ENTRY#copilot=}" ;;
        *)
          echo "--model-for: expected claude=NAME or copilot=NAME, got: $ENTRY" >&2
          exit 2
          ;;
      esac
      ;;
    -h|--help) sed -n '2,72p' "$0" >&2; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[[ "$TOOL" =~ ^(claude|copilot|both)$ ]] \
  || { echo "--tool must be claude|copilot|both" >&2; exit 2; }

# Resolve per-tool model: --model-for wins over --model. Empty string means
# "no model override — use the tool's default."
CLAUDE_MODEL="${MODEL_FOR_CLAUDE:-$MODEL}"
COPILOT_MODEL="${MODEL_FOR_COPILOT:-$MODEL}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
ROOT="$REPO_ROOT/runs/wrapper-verify"

echo "==> Cleaning $ROOT"
rm -rf "$ROOT"
mkdir -p "$ROOT"
if [[ -n "$CLAUDE_MODEL$COPILOT_MODEL" ]]; then
  echo "==> Models being forced (empty = use tool's default):"
  [[ "$TOOL" == claude  || "$TOOL" == both ]] \
    && echo "    claude  → ${CLAUDE_MODEL:-<tool default>}"
  [[ "$TOOL" == copilot || "$TOOL" == both ]] \
    && echo "    copilot → ${COPILOT_MODEL:-<tool default>}"
fi

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

  local resolved_model=""
  case "$tool" in
    claude)  resolved_model="$CLAUDE_MODEL" ;;
    copilot) resolved_model="$COPILOT_MODEL" ;;
  esac
  local model_args=()
  if [[ -n "$resolved_model" ]]; then
    model_args=(--model "$resolved_model")
    echo "==> $tool: invoking scripts/run_${tool}.sh with --model $resolved_model"
  else
    echo "==> $tool: invoking scripts/run_${tool}.sh (default model)"
  fi
  "$SCRIPT_DIR/run_${tool}.sh" \
    --workdir "$workdir" \
    --run-dir "$rundir" \
    --prompt-file "$prompt" \
    "${model_args[@]}"
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
  local exit_code
  exit_code="$(cat "$rundir/exit_code" 2>/dev/null || true)"
  echo
  echo "--- $tool ---"
  printf "  exit_code:           %s\n" "${exit_code:-(missing)}"
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

  # If the wrapper exited non-zero AND stderr has content, surface it
  # inline so the user doesn't have to open the file separately. Common
  # case this catches: a probed --model NAME was rejected and copilot
  # / claude wrote a short error to stderr explaining why.
  if [[ -n "$exit_code" && "$exit_code" != "0" && -s "$rundir/stderr.log" ]]; then
    echo "  stderr.log contents (exit_code=$exit_code — showing for diagnosis):"
    sed 's/^/    | /' "$rundir/stderr.log"
  fi

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
