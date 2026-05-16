#!/usr/bin/env bash
# Run the canonical Harness-framing smoke matrix.
#
# Forces both tools onto the same shared model so the model variable is
# held constant and any remaining gap is attributable to scaffolding.
# Spends real API budget — claude pays per token; copilot just uses your seat.
# Shows the planned scope and prompts for confirmation before invoking the
# matrix; pass `-y` / `--yes` to skip the prompt for automation.
#
# Usage:
#   scripts/run_harness_smoke.sh [--model NAME]
#                                [--model-for claude=NAME] [--model-for copilot=NAME]
#                                [--budget-seconds N] [--run-id ID] [-y|--yes]
#
# Model selection — the Harness framing has no meaning without choosing
# which shared model to force. You must supply enough information for
# the script to resolve a model for EACH tool that will run:
#
#   --model NAME        applied as the default for every tool that lacks
#                       a --model-for override. Use when the same model
#                       name works for both `claude` and `copilot`.
#   --model-for TOOL=NAME  per-tool override. Use when the two CLIs use
#                       different names for the same underlying model —
#                       e.g. claude wants `claude-sonnet-4-6` (dashes)
#                       while copilot wants `claude-sonnet-4.6` (dots).
#                       Repeatable (one per tool). Takes precedence over
#                       --model for the named tool.
#
# Examples:
#   # Same name works for both:
#   scripts/run_harness_smoke.sh --model claude-sonnet-4-6
#
#   # Different names per tool (the common real-world case):
#   scripts/run_harness_smoke.sh --model-for claude=claude-sonnet-4-6 --model-for copilot=claude-sonnet-4.6
#
#   # Default + override for the one diverging tool:
#   scripts/run_harness_smoke.sh \
#     --model claude-sonnet-4-6 \
#     --model-for copilot=claude-sonnet-4.6
#
# Defaults:
#   --budget-seconds  600   (10 minutes per cell)
#   --run-id          smoke-harness-<UTC-ISO-TIMESTAMP>
#
# Exit codes:
#   0   matrix ran; every cell succeeded
#   1   matrix ran; one or more cells failed (timeout, retry-exhaustion, crash)
#   2   user aborted at the prompt OR bad CLI argument (incl. no model resolved)
#   3   prerequisite missing (tasks/swebench_smoke.yaml not found, uv not on PATH, ...)

set -uo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

YES=0
BUDGET=600
RUN_ID=""
MODEL=""
MODEL_FOR_CLAUDE=""
MODEL_FOR_COPILOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)         YES=1; shift ;;
    --budget-seconds) BUDGET="$2"; shift 2 ;;
    --run-id)         RUN_ID="$2"; shift 2 ;;
    --model)          MODEL="$2"; shift 2 ;;
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
    -h|--help)        sed -n '2,52p' "$0" >&2; exit 0 ;;
    *) echo "unknown argument: $1" >&2; echo "Try --help" >&2; exit 2 ;;
  esac
done

# Resolve per-tool model: --model-for wins over --model. Either path must
# yield a non-empty value for every tool in the matrix; otherwise we'd
# silently regress to product framing for any unresolved tool.
CLAUDE_MODEL="${MODEL_FOR_CLAUDE:-$MODEL}"
COPILOT_MODEL="${MODEL_FOR_COPILOT:-$MODEL}"

if [[ -z "$CLAUDE_MODEL" || -z "$COPILOT_MODEL" ]]; then
  cat >&2 <<EOF
Could not resolve a model for every tool. Harness framing requires that
EACH tool runs on a chosen model; missing tools resolved so far:

  claude  → ${CLAUDE_MODEL:-(not resolved)}
  copilot → ${COPILOT_MODEL:-(not resolved)}

You supply models in one of three patterns:

  1. Same name for both tools:
       $0 --model claude-sonnet-4-6

  2. Different name per tool (when the two CLIs use different conventions
     for the same underlying model — common case for Claude models, where
     claude uses dashes and copilot uses dots):
       $0 --model-for claude=claude-sonnet-4-6 \\
                              --model-for copilot=claude-sonnet-4.6

  3. Default + per-tool override (shortcut when only one tool diverges):
       $0 --model claude-sonnet-4-6 \\
                              --model-for copilot=claude-sonnet-4.6

Common Claude-family model names (your actual availability depends on
your Anthropic API access and Copilot subscription):

  Anthropic-canonical (claude CLI):  copilot-relabeled (copilot CLI):
    claude-sonnet-4-6                   claude-sonnet-4.6
    claude-opus-4-7                     claude-opus-4.7
    claude-haiku-4-5                    claude-haiku-4.5

Authoritative model lists per tool (vary with CLI version):
  claude --help  | grep -A2 -- '--model'
  copilot --help | grep -A2 -- '--model'

Pre-flight tip (cheapest — strongly recommended): confirm both tools
accept the chosen model names in ~30 seconds, no API budget burned
on rejection. The pre-flight supports the same --model-for flags:

  ./scripts/verify_wrappers.sh \\
    --model-for claude=claude-sonnet-4-6 \\
    --model-for copilot=claude-sonnet-4.6

If you want to additionally verify the full agent pipeline on one tool
before paying for the full matrix (this DOES burn ~one cell's worth
of API time/budget):
  uv run python -m harness run \\
    --task pytest-dev__pytest-10051 --tool claude \\
    --model <name> --budget-seconds 120 --run-id harness-preflight

See docs-generated-by-claude/13-product-vs-harness-modes.md for context.
EOF
  exit 2
fi

if [[ -z "$RUN_ID" ]]; then
  TS=$(date -u +"%Y-%m-%dT%H-%M-%S")
  RUN_ID="smoke-harness-${TS}"
fi

TASKS_YAML="$REPO_ROOT/tasks/swebench_smoke.yaml"
if [[ ! -f "$TASKS_YAML" ]]; then
  echo "smoke YAML not found at $TASKS_YAML" >&2
  exit 3
fi
if ! command -v uv >/dev/null; then
  echo "uv not on PATH; install uv first (see scripts/check_prereqs.sh)" >&2
  exit 3
fi

# Count tasks via the project's own loader.
N_TASKS=$(
  cd "$REPO_ROOT" && uv run --quiet python -c "
from harness.providers.swebench import load_task_ids_from_yaml
print(len(load_task_ids_from_yaml('$TASKS_YAML')))
" 2>/dev/null
)
if ! [[ "$N_TASKS" =~ ^[0-9]+$ ]]; then
  echo "could not count tasks in $TASKS_YAML" >&2
  exit 3
fi

TOOLS="claude,copilot"
N_TOOLS=2
N_SEEDS=1
N_CELLS=$(( N_TASKS * N_TOOLS * N_SEEDS ))
MAX_WALL_MIN=$(( N_CELLS * BUDGET / 60 ))

cat <<EOF
Harness framing — smoke run

  Tasks:        ${N_TASKS} (from ${TASKS_YAML#"$REPO_ROOT"/})
  Tools:        ${TOOLS//,/, }
  claude model:  ${CLAUDE_MODEL}
  copilot model: ${COPILOT_MODEL}
  Seeds:  ${N_SEEDS}
  Cells:  ${N_CELLS}
  Budget: ${BUDGET}s per cell (worst-case total wall-clock: ~${MAX_WALL_MIN} min if every cell hits its budget)
  Run-id: ${RUN_ID}

Cost (rough estimate, per claude cell × ${N_TASKS} claude cells):
  - claude:  ~\$0.50–\$2.00 per cell — Anthropic API spend, paid per token (varies by model)
  - copilot: \$0 incremental — uses your existing Copilot seat

Note: each tool must accept its model name. If either tool rejects its
model, every cell of that tool will burn 3 retries before being marked
failed (the driver classifies non-zero exits as transient and retries).
To avoid that, pre-flight your model choice cheaply BEFORE the prompt:

    ./scripts/verify_wrappers.sh \\
      --model-for claude=${CLAUDE_MODEL} \\
      --model-for copilot=${COPILOT_MODEL}

That runs both wrappers against a trivial prompt with the same per-tool
model overrides; each rejection costs ~4 seconds and no API spend.
Either tool's rejection shows up immediately in the Results section.

EOF

if (( YES == 0 )); then
  printf "Proceed? [y/N] "
  read -r REPLY
  if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 2
  fi
fi

cd "$REPO_ROOT" || exit 3
# Always pass --model-for explicitly for each tool. This is unambiguous
# regardless of whether the user supplied --model, --model-for, or a mix
# — by this point we've already resolved CLAUDE_MODEL and COPILOT_MODEL
# and validated they're both set.
exec uv run python -m harness run-matrix \
  --tasks "$TASKS_YAML" \
  --tools "$TOOLS" \
  --model-for "claude=$CLAUDE_MODEL" \
  --model-for "copilot=$COPILOT_MODEL" \
  --run-id "$RUN_ID" \
  --budget-seconds "$BUDGET"
