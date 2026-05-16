#!/usr/bin/env bash
# Run the canonical Product-framing smoke matrix.
#
# Spends real API budget — claude pays per token; copilot just uses your seat.
# Shows the planned scope and prompts for confirmation before invoking the
# matrix; pass `-y` / `--yes` to skip the prompt for automation.
#
# Usage:
#   scripts/run_product_smoke.sh [--budget-seconds N] [--run-id ID] [-y|--yes]
#
# Defaults:
#   --budget-seconds  600   (10 minutes per cell)
#   --run-id          smoke-product-<UTC-ISO-TIMESTAMP>
#
# Exit codes:
#   0   matrix ran; every cell succeeded
#   1   matrix ran; one or more cells failed (timeout, retry-exhaustion, crash)
#   2   user aborted at the prompt OR bad CLI argument
#   3   prerequisite missing (tasks/swebench_smoke.yaml not found, uv not on PATH, ...)

set -uo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

YES=0
BUDGET=600
RUN_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)         YES=1; shift ;;
    --budget-seconds) BUDGET="$2"; shift 2 ;;
    --run-id)         RUN_ID="$2"; shift 2 ;;
    -h|--help)        sed -n '2,19p' "$0" >&2; exit 0 ;;
    *) echo "unknown argument: $1" >&2; echo "Try --help" >&2; exit 2 ;;
  esac
done

if [[ -z "$RUN_ID" ]]; then
  TS=$(date -u +"%Y-%m-%dT%H-%M-%S")
  RUN_ID="smoke-product-${TS}"
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

# Count tasks via the project's own loader so the number tracks the YAML's
# real contents (comments, formatting changes can't mislead us).
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
Product framing — smoke run

  Tasks:  ${N_TASKS} (from ${TASKS_YAML#"$REPO_ROOT"/})
  Tools:  ${TOOLS//,/, }
  Seeds:  ${N_SEEDS}
  Cells:  ${N_CELLS}
  Budget: ${BUDGET}s per cell (worst-case total wall-clock: ~${MAX_WALL_MIN} min if every cell hits its budget)
  Run-id: ${RUN_ID}

Cost (rough estimate, per claude cell × ${N_TASKS} claude cells):
  - claude:  ~\$0.50–\$2.00 per cell — Anthropic API spend, paid per token
  - copilot: \$0 incremental — uses your existing Copilot seat

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
exec uv run python -m harness run-matrix \
  --tasks "$TASKS_YAML" \
  --tools "$TOOLS" \
  --run-id "$RUN_ID" \
  --budget-seconds "$BUDGET"
