#!/usr/bin/env bash
# Prerequisite checker for coding-agent-compare.
# Runs on Linux, macOS, and Windows via Git Bash or WSL.
# Native Windows PowerShell users: see scripts/check_prereqs.ps1.

set -uo pipefail

if [[ -t 1 ]]; then
    RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    RED=""; GREEN=""; YELLOW=""; BOLD=""; RESET=""
fi

failures=0
warnings=0
MISSING_TOOLS=()

# Resolve repo root from this script's location (scripts/ -> repo root).
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_ROOT="$( cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd )"
NODE_BIN="${REPO_ROOT}/node_modules/.bin"

# Resolve a tool, preferring a project-local npm install (./node_modules/.bin)
# before falling back to PATH. Mirrors npm/npx resolution order. Echoes the
# resolved path on stdout; returns 1 if not found.
resolve_tool() {
    local name=$1
    if [[ -x "${NODE_BIN}/${name}" ]]; then
        echo "${NODE_BIN}/${name}"
        return 0
    fi
    local path
    path=$(command -v "$name" 2>/dev/null) || return 1
    echo "$path"
    return 0
}

detect_platform() {
    case "$(uname -s 2>/dev/null)" in
        Darwin*) echo "macos" ;;
        Linux*)
            if [[ -n "${WSL_DISTRO_NAME:-}" ]] || grep -qi microsoft /proc/version 2>/dev/null; then
                echo "wsl"
            else
                echo "linux"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows-bash" ;;
        *) echo "unknown" ;;
    esac
}

PLATFORM=$(detect_platform)

check_tool() {
    local name=$1
    local version_arg=${2:---version}
    local resolved
    resolved=$(resolve_tool "$name") || {
        printf "  ${RED}[MISS]${RESET} %-10s not found in PATH or ./node_modules/.bin\n" "$name"
        failures=$((failures + 1))
        MISSING_TOOLS+=("$name")
        return
    }
    local output rc first
    output=$("$resolved" "$version_arg" </dev/null 2>&1)
    rc=$?
    first=$(printf '%s\n' "$output" | grep -v '^[[:space:]]*$' | head -n1)
    [[ -z "$first" ]] && first="(no output)"
    if [[ $rc -ne 0 ]]; then
        printf "  ${RED}[MISS]${RESET} %-10s '%s %s' exited %d: %s\n" "$name" "$resolved" "$version_arg" "$rc" "$first"
        failures=$((failures + 1))
        MISSING_TOOLS+=("$name")
        return
    fi
    if ! [[ "$output" =~ [0-9]+\.[0-9]+ ]]; then
        # Binary exists but doesn't look like the real tool (e.g., VS Code's 'copilot' stub on PATH).
        printf "  ${RED}[MISS]${RESET} %-10s output lacks a version number — likely a stub or wrong binary (%s): %s\n" "$name" "$resolved" "$first"
        failures=$((failures + 1))
        MISSING_TOOLS+=("$name")
        return
    fi
    # Annotate when we resolved via a project-local npm install.
    local suffix=""
    [[ "$resolved" == "${NODE_BIN}/"* ]] && suffix="  (via ./node_modules/.bin)"
    printf "  ${GREEN}[OK]${RESET}   %-10s %s%s\n" "$name" "$first" "$suffix"
}

# Per-tool install hints. Each prints 1-2 platform-appropriate commands and a
# docs link. We prefer a detected package manager when one is available.
hint_git() {
    case "$PLATFORM" in
        macos)
            command -v brew >/dev/null 2>&1 && echo "    brew install git"
            echo "    xcode-select --install   # Apple Command Line Tools (no Homebrew needed)"
            ;;
        linux|wsl)
            if command -v apt-get >/dev/null 2>&1; then
                echo "    sudo apt-get update && sudo apt-get install -y git"
            elif command -v dnf >/dev/null 2>&1; then
                echo "    sudo dnf install -y git"
            elif command -v pacman >/dev/null 2>&1; then
                echo "    sudo pacman -S --noconfirm git"
            elif command -v zypper >/dev/null 2>&1; then
                echo "    sudo zypper install -y git"
            else
                echo "    install via your distro's package manager"
            fi
            ;;
        windows-bash)
            command -v winget >/dev/null 2>&1 && echo "    winget install --id Git.Git -e"
            command -v choco  >/dev/null 2>&1 && echo "    choco install git -y"
            echo "    or installer: https://git-scm.com/download/win"
            ;;
        *)
            echo "    https://git-scm.com/downloads"
            ;;
    esac
}

hint_uv() {
    case "$PLATFORM" in
        macos)
            command -v brew >/dev/null 2>&1 && echo "    brew install uv"
            echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
            ;;
        linux|wsl)
            echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
            ;;
        windows-bash)
            command -v winget >/dev/null 2>&1 && echo "    winget install --id astral-sh.uv -e"
            echo "    or PowerShell: irm https://astral.sh/uv/install.ps1 | iex"
            ;;
        *)
            echo "    https://docs.astral.sh/uv/getting-started/installation/"
            ;;
    esac
    echo "    docs: https://docs.astral.sh/uv/"
}

hint_claude() {
    echo "    npm install -g @anthropic-ai/claude-code"
    echo "    docs: https://docs.claude.com/en/docs/claude-code"
    echo "    After install: run 'claude' once interactively to log in."
}

hint_copilot() {
    echo "    npm install -g @github/copilot"
    echo "    docs: https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli"
    echo "    After install: 'gh auth login' (requires an active Copilot subscription)."
    if command -v copilot >/dev/null 2>&1; then
        local where
        where=$(command -v copilot)
        echo "    Note: a 'copilot' binary already exists at: $where"
        echo "          It appears to be a stub (VS Code's Copilot Chat ships one). Either"
        echo "          remove it from PATH or ensure the npm install path shadows it."
    fi
}

print_install_hints() {
    local tool
    for tool in "${MISSING_TOOLS[@]}"; do
        echo
        echo "  ${BOLD}${tool}${RESET}:"
        case "$tool" in
            git)     hint_git ;;
            uv)      hint_uv ;;
            claude)  hint_claude ;;
            copilot) hint_copilot ;;
            *)       echo "    (no install hint defined for $tool)" ;;
        esac
    done
}

check_disk() {
    local needed_gb=5
    # -P forces POSIX output: "Filesystem 1024-blocks Used Available Capacity Mounted on"
    local avail_kb
    avail_kb=$(df -Pk . 2>/dev/null | awk 'NR==2 {print $4}')
    if [[ -z "$avail_kb" ]]; then
        printf "  ${YELLOW}[WARN]${RESET} %-10s could not determine free space\n" "disk"
        warnings=$((warnings + 1))
        return
    fi
    local avail_gb=$((avail_kb / 1024 / 1024))
    if [[ $avail_gb -ge $needed_gb ]]; then
        printf "  ${GREEN}[OK]${RESET}   %-10s %s GB free (need %s)\n" "disk" "$avail_gb" "$needed_gb"
    else
        printf "  ${YELLOW}[WARN]${RESET} %-10s %s GB free (need %s)\n" "disk" "$avail_gb" "$needed_gb"
        warnings=$((warnings + 1))
    fi
}

check_optional_env() {
    local name=$1
    local desc=$2
    if [[ -n "${!name:-}" ]]; then
        printf "  ${GREEN}[OK]${RESET}   %-10s set (%s)\n" "$name" "$desc"
    else
        printf "  ${YELLOW}[WARN]${RESET} %-10s unset — %s\n" "$name" "$desc"
    fi
}

echo "${BOLD}Checking prerequisites for coding-agent-compare...${RESET}"
echo

echo "Required tools:"
check_tool git
check_tool uv
check_tool claude
check_tool copilot
echo

echo "Disk space (project root):"
check_disk
echo

echo "Optional:"
check_optional_env HF_TOKEN "HuggingFace token; only needed if dataset access becomes gated"
echo

if [[ $failures -gt 0 ]]; then
    echo "${RED}${failures} required tool(s) missing on this ${PLATFORM} host.${RESET}"
    echo "${BOLD}To install:${RESET}"
    print_install_hints
    exit 1
fi

if [[ $warnings -gt 0 ]]; then
    echo "${YELLOW}${warnings} warning(s). Review above.${RESET}"
fi

echo "${GREEN}All required prerequisites present.${RESET}"
echo
echo "${BOLD}Note:${RESET} this script does not verify CLI authentication."
echo "Before running the harness, ensure each CLI is logged in:"
echo "  - claude:  run 'claude' once interactively, then '/login' if needed"
echo "  - copilot: confirm Copilot access via 'copilot' or 'gh auth status'"
