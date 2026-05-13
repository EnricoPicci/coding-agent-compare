# Prompt
Implement Step 5

# Claude Response


## Summary

Implements Step 5 of [`docs-generated-by-claude/02-implementation-plan-step-by-step.md`](../docs-generated-by-claude/02-implementation-plan-step-by-step.md) — *Tool wrappers (bash)*.

## Verifications

Live end-to-end against a throwaway git workdir with the trivial prompt
"create a file named HELLO.txt containing 'hi from <tool>'":

```
$ scripts/run_claude.sh --workdir <tmp> --run-dir <tmp/claude-run> --prompt-file <tmp/prompt.txt>
  → exit_code=0, wall_clock_seconds=8, stdout.log=5.6 KB stream-json,
    stderr.log empty, HELLO.txt present in workdir ✓

$ scripts/run_copilot.sh --workdir <tmp> --run-dir <tmp/copilot-run> --prompt-file <tmp/prompt-copilot.txt>
  → exit_code=0, wall_clock_seconds=19, stdout.log=73-line JSONL,
    stderr.log empty, HELLO.txt present in workdir ✓

$ uv run pytest harness/ -q -m "not integration"
  → 28 passed in 3.16s ✓
```

The Copilot wrapper also passed a negative test on first attempt (auth missing
on this machine): wrapper resolved the local-install binary, exec'd it, captured
`Error: No authentication information found.` to `stderr.log`, propagated exit
code 1, and wrote all five output files correctly. After the user authenticated
via `copilot /login`, the positive path completed as above.

`shellcheck` is not installed on this machine — bash linting was skipped. Worth
adding to the prereq checker if we keep growing the script count, but for two
small scripts the cost/benefit isn't there yet.

## Files created

- `scripts/run_claude.sh` — headless Claude Code wrapper.
- `scripts/run_copilot.sh` — headless GitHub Copilot CLI wrapper.

Both share the same CLI contract: `--workdir`, `--run-dir`, `--prompt-file`,
optional `--model`. Both write `stdout.log`, `stderr.log`, `exit_code`,
`wall_clock_seconds`, `tool_info.json` to the run dir. Both resolve the binary
project-local-first (`./node_modules/.bin/<tool>` before `PATH`) and refuse to
run a binary that doesn't print a recognizable version string (catches the VS
Code Copilot Chat stub the plan warned about).

## Design decisions worth flagging

- **Trace lives in `stdout.log`, not a separate `trace.raw`.** With the
  structured-output flags the plan already mandates (`--output-format stream-json`
  for claude, `--output-format json` for copilot), the trace IS stdout — a
  second identical file would be pure duplication. Step 7 parsers will read
  `stdout.log`. Plan deviation logged in the Changes section under Step 5.
- **`tool_info.json` written by the bash wrapper.** Single-line JSON with the
  resolved binary path and version. The plan's note required these in the
  manifest; having the wrapper write them means the Step 6/7 manifest writer
  just merges a known file. Robust JSON quoting via a `python3 -c` one-liner —
  bash `printf` would break on a path containing a quote.
- **Wall-clock timeout stays with the Python supervisor.** Bash just `exec`s
  the binary; `wall_clock_seconds` is recorded on normal exit. When Step 6's
  supervisor delivers SIGTERM/SIGKILL it will overwrite the wall-clock file
  itself; the wrapper's value is the happy-path value useful for ad-hoc runs.
- **Stub detection via version regex** (`[0-9]+\.[0-9]+`). Same logic the prereq
  checker already uses. The VS Code Copilot Chat stub prints "Cannot find
  GitHub Copilot CLI... Install? [y/N]" and exits 0 — the regex catches it.
- **Prompt read via `PROMPT="$(<"$FILE")"`**, not `$(cat file)` interpolated into
  the CLI arg directly. Quoted assignment guarantees the prompt is treated as a
  single opaque string with no further shell expansion of `$`, backticks, etc.
- **Copilot uses `-C "$WORKDIR"`**, claude uses a subshell with `cd`. Claude
  has no equivalent `-C` flag; the subshell scopes the directory change to the
  one invocation and keeps the rest of the wrapper running from the script's
  own cwd.

## Flag-surface details locked in against live CLIs

Verified against `claude 2.1.140` and `copilot 1.0.46`:

```
claude   -p "<prompt>" --output-format stream-json --verbose --dangerously-skip-permissions [--model M]
copilot  -p "<prompt>" --allow-all-tools --output-format json --no-auto-update --no-color -C "<workdir>" [--model M]
```

`--verbose` is required by claude when combining `-p` with stream-json output.
`--no-auto-update` on copilot prevents mid-run version drift; `--no-color`
keeps stdout free of ANSI escapes for the future parser.



## Project-local resolution + stub refusal explanation

Two separate guards stacked together in both wrappers, both motivated by the
same failure mode the plan called out:

1. **Project-local first.** Before searching `$PATH`, each wrapper checks
   `./node_modules/.bin/<tool>` relative to the repo root. This matches the
   npm convention (`npx`-style resolution) and is necessary because the user
   installed `@github/copilot` as a project-local dependency — so the real
   binary lives at `coding-agent-compare/node_modules/.bin/copilot`, not on
   PATH. Without this lookup, the wrapper would fall through to whatever
   `copilot` shows up first in `$PATH`.
2. **Stub refusal.** Even when a `copilot` binary is found, the wrapper runs
   `<binary> --version` and requires the output to contain a version-number
   pattern (regex `[0-9]+\.[0-9]+`). This catches a specific failure mode the
   plan warned about: VS Code's Copilot Chat extension installs a shell script
   at `~/Library/Application Support/Code/User/globalStorage/github.copilot-chat/copilotCli/copilot`
   which, when run with `--version`, prints
   `"Cannot find GitHub Copilot CLI ... Install? [y/N]"` and exits 0. A naive
   wrapper would think this is a real CLI, pass it `-p "<prompt>"`, and the
   stub would hang waiting for user input — silently corrupting every run.
   The regex check makes the wrapper exit 3 with a clear error instead. We
   verified during this step that PATH's `copilot` is exactly this stub on
   the user's machine.

## Locked-in flag surfaces explanation

Each tool has flags the plan didn't specify but that turned out to be required
(or strongly recommended) once I ran `--help` against the live CLIs.

**Claude (`scripts/run_claude.sh`):**

- `--verbose` — when combined with `-p` (print/headless mode) and
  `--output-format stream-json`, claude rejects the invocation unless
  `--verbose` is also set. The plan listed `-p` and `--output-format stream-json`
  but not `--verbose`; without it the wrapper would error out at startup.

**Copilot (`scripts/run_copilot.sh`):**

- `-C "<workdir>"` — copilot's built-in way to set its working directory.
  The plan implied wrappers would `cd` into the workdir before exec'ing the
  tool; `-C` is cleaner because it keeps the wrapper running from its own cwd
  while telling copilot where to operate. (Claude has no `-C` equivalent, so
  its wrapper does use a subshell `cd`.)
- `--no-auto-update` — by default, copilot checks for a new version and
  silently downloads it before processing the prompt. This is dangerous for
  reproducibility: the version recorded in `tool_info.json` is the one we
  measured *before* the run started, but the binary that actually ran could
  be a different version after the silent update. Disabling auto-update means
  the version we record is the version we ran.
- `--no-color` — disables ANSI escape codes in stdout. Since stdout is the
  structured JSON trace that Step 7's parser will read, ANSI codes leaking
  into JSON strings would create parser headaches. Belt-and-suspenders:
  `--output-format json` should already produce clean output, but `--no-color`
  makes it explicit.

## Side effects on this machine

- Two new executable scripts under `scripts/`. No new Python dependencies, no
  changes to `pyproject.toml` or `harness/`.
- One auth event: user logged copilot in via `copilot /login`. Captured the
  resulting version bump (1.0.45 → 1.0.46) in the deviation log.
- Tmp verification dir at `/tmp/step5-verify-snaL3/` is now safe to delete.

## Step 6 readiness

Step 6 (single-run executor) depends on Steps 3, 4, 5 — all complete. The
wrapper contract is stable; the supervisor can shell out to either script with
the same argument shape and consume the same five output files.
