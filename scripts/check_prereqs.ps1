#!/usr/bin/env pwsh
# Prerequisite checker for coding-agent-compare (PowerShell).
# Runs on Windows PowerShell 5.1+ and PowerShell Core on Linux/macOS.
# Bash users on Linux/macOS/Git-Bash: see scripts/check_prereqs.sh.

$ErrorActionPreference = 'Continue'
$script:failures = 0
$script:warnings = 0
$script:missingTools = @()

# Resolve repo root from this script's location (scripts/ -> repo root).
$script:scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$script:repoRoot  = Split-Path -Parent $script:scriptDir
$script:nodeBin   = Join-Path $script:repoRoot 'node_modules/.bin'

# Resolve a tool, preferring a project-local npm install (./node_modules/.bin)
# before falling back to PATH. Mirrors npm/npx resolution order. Returns the
# resolved path, or $null if not found. On Windows, npm creates '.cmd' shims;
# check both.
function Resolve-Tool {
    param([string]$Name)
    foreach ($leaf in @("$Name.cmd", "$Name.ps1", $Name)) {
        $candidate = Join-Path $script:nodeBin $leaf
        if (Test-Path $candidate -PathType Leaf) { return $candidate }
    }
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-Platform {
    # PowerShell Core sets $IsWindows / $IsMacOS / $IsLinux. Windows PowerShell 5.1 doesn't,
    # but if we're running 5.1 we're definitionally on Windows.
    if ($PSVersionTable.PSEdition -eq 'Desktop') { return 'windows' }
    if ($IsWindows) { return 'windows' }
    if ($IsMacOS)   { return 'macos' }
    if ($IsLinux)   { return 'linux' }
    return 'unknown'
}

$script:platform = Get-Platform

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Status {
    param([string]$Tag, [string]$Name, [string]$Detail, [string]$Color)
    Write-Host ("  [{0}] {1,-10} {2}" -f $Tag, $Name, $Detail) -ForegroundColor $Color
}

function Test-Tool {
    param([string]$Name, [string]$VersionArg = '--version')
    $resolved = Resolve-Tool $Name
    if (-not $resolved) {
        Write-Status 'MISS' $Name 'not found in PATH or ./node_modules/.bin' 'Red'
        $script:failures++
        $script:missingTools += $Name
        return
    }
    $output = ''
    $exitCode = 0
    try {
        $raw = & $resolved $VersionArg 2>&1
        $exitCode = $LASTEXITCODE
        if ($raw) { $output = ($raw | Out-String).Trim() }
    } catch {
        Write-Status 'MISS' $Name ("'{0} {1}' threw: {2}" -f $resolved, $VersionArg, $_.Exception.Message) 'Red'
        $script:failures++
        $script:missingTools += $Name
        return
    }
    $first = ($output -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
    if (-not $first) { $first = '(no output)' }
    if ($exitCode -ne 0) {
        Write-Status 'MISS' $Name ("'{0} {1}' exited {2}: {3}" -f $resolved, $VersionArg, $exitCode, $first) 'Red'
        $script:failures++
        $script:missingTools += $Name
        return
    }
    if ($output -notmatch '\d+\.\d+') {
        # Binary exists but doesn't look like the real tool (e.g., VS Code's 'copilot' stub on PATH).
        Write-Status 'MISS' $Name ("output lacks a version number - likely a stub or wrong binary ({0}): {1}" -f $resolved, $first) 'Red'
        $script:failures++
        $script:missingTools += $Name
        return
    }
    $suffix = ''
    if ($resolved.StartsWith($script:nodeBin)) { $suffix = '  (via ./node_modules/.bin)' }
    Write-Status 'OK' $Name ("{0}{1}" -f $first, $suffix) 'Green'
}

# Per-tool install hints. Each prints 1-2 platform-appropriate commands and a
# docs link. We prefer a detected package manager when one is available.
function Show-HintGit {
    switch ($script:platform) {
        'macos' {
            if (Test-Command 'brew') { Write-Host '    brew install git' }
            Write-Host '    xcode-select --install   # Apple Command Line Tools'
        }
        'linux' {
            if (Test-Command 'apt-get') {
                Write-Host '    sudo apt-get update && sudo apt-get install -y git'
            } elseif (Test-Command 'dnf') {
                Write-Host '    sudo dnf install -y git'
            } elseif (Test-Command 'pacman') {
                Write-Host '    sudo pacman -S --noconfirm git'
            } elseif (Test-Command 'zypper') {
                Write-Host '    sudo zypper install -y git'
            } else {
                Write-Host "    install via your distro's package manager"
            }
        }
        'windows' {
            if (Test-Command 'winget') { Write-Host '    winget install --id Git.Git -e' }
            if (Test-Command 'choco')  { Write-Host '    choco install git -y' }
            Write-Host '    or installer: https://git-scm.com/download/win'
        }
        default {
            Write-Host '    https://git-scm.com/downloads'
        }
    }
}

function Show-HintUv {
    switch ($script:platform) {
        'macos' {
            if (Test-Command 'brew') { Write-Host '    brew install uv' }
            Write-Host '    curl -LsSf https://astral.sh/uv/install.sh | sh'
        }
        'linux' {
            Write-Host '    curl -LsSf https://astral.sh/uv/install.sh | sh'
        }
        'windows' {
            if (Test-Command 'winget') { Write-Host '    winget install --id astral-sh.uv -e' }
            Write-Host '    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        }
        default {
            Write-Host '    https://docs.astral.sh/uv/getting-started/installation/'
        }
    }
    Write-Host '    docs: https://docs.astral.sh/uv/'
}

function Show-HintClaude {
    Write-Host '    npm install -g @anthropic-ai/claude-code'
    Write-Host '    docs: https://docs.claude.com/en/docs/claude-code'
    Write-Host "    After install: run 'claude' once interactively to log in."
}

function Show-HintCopilot {
    Write-Host '    npm install -g @github/copilot'
    Write-Host '    docs: https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli'
    Write-Host "    After install: 'gh auth login' (requires an active Copilot subscription)."
    $existing = Get-Command 'copilot' -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host ("    Note: a 'copilot' binary already exists at: {0}" -f $existing.Source)
        Write-Host "          It appears to be a stub (VS Code's Copilot Chat ships one). Either"
        Write-Host '          remove it from PATH or ensure the npm install path shadows it.'
    }
}

function Show-InstallHints {
    foreach ($tool in $script:missingTools) {
        Write-Host ''
        Write-Host ("  {0}:" -f $tool) -ForegroundColor White
        switch ($tool) {
            'git'     { Show-HintGit }
            'uv'      { Show-HintUv }
            'claude'  { Show-HintClaude }
            'copilot' { Show-HintCopilot }
            default   { Write-Host "    (no install hint defined for $tool)" }
        }
    }
}

function Test-Disk {
    $neededGb = 5
    try {
        $drive = (Get-Item -Path '.').PSDrive
        $availGb = [math]::Floor($drive.Free / 1GB)
        if ($availGb -ge $neededGb) {
            Write-Status 'OK'   'disk' ("{0} GB free (need {1})" -f $availGb, $neededGb) 'Green'
        } else {
            Write-Status 'WARN' 'disk' ("{0} GB free (need {1})" -f $availGb, $neededGb) 'Yellow'
            $script:warnings++
        }
    } catch {
        Write-Status 'WARN' 'disk' 'could not determine free space' 'Yellow'
        $script:warnings++
    }
}

function Test-OptionalEnv {
    param([string]$Name, [string]$Desc)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) {
        Write-Status 'OK'   $Name ("set ({0})" -f $Desc) 'Green'
    } else {
        Write-Status 'WARN' $Name ("unset - {0}" -f $Desc) 'Yellow'
    }
}

Write-Host 'Checking prerequisites for coding-agent-compare...' -ForegroundColor White
Write-Host ''

Write-Host 'Required tools:'
Test-Tool 'git'
Test-Tool 'uv'
Test-Tool 'claude'
Test-Tool 'copilot'
Write-Host ''

Write-Host 'Disk space (project root):'
Test-Disk
Write-Host ''

Write-Host 'Optional:'
Test-OptionalEnv 'HF_TOKEN' 'HuggingFace token; only needed if dataset access becomes gated'
Write-Host ''

if ($script:failures -gt 0) {
    Write-Host ("{0} required tool(s) missing on this {1} host." -f $script:failures, $script:platform) -ForegroundColor Red
    Write-Host 'To install:'
    Show-InstallHints
    exit 1
}

if ($script:warnings -gt 0) {
    Write-Host ("{0} warning(s). Review above." -f $script:warnings) -ForegroundColor Yellow
}

Write-Host 'All required prerequisites present.' -ForegroundColor Green
Write-Host ''
Write-Host 'Note: this script does not verify CLI authentication.'
Write-Host 'Before running the harness, ensure each CLI is logged in:'
Write-Host "  - claude:  run 'claude' once interactively, then '/login' if needed"
Write-Host "  - copilot: confirm Copilot access via 'copilot' or 'gh auth status'"
