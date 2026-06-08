$ErrorActionPreference = "Stop"

param(
    [string]$InstallDir = "$HOME\deckpilot",
    [string]$RepoUrl = "https://github.com/JulesMellot/deckpilot.git",
    [switch]$Yes
)

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "[DeckPilot] $Message"
}

function Confirm-Step {
    param(
        [string]$Prompt,
        [bool]$DefaultYes = $true
    )
    if ($Yes) { return $true }
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) {
        return $DefaultYes
    }
    return $answer.ToLowerInvariant().StartsWith("y")
}

function Require-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Install-WithWinget {
    param(
        [string]$Id,
        [string]$Label
    )
    Write-Step "Installing $Label with winget."
    winget install --id $Id --accept-package-agreements --accept-source-agreements --silent
}

function Ensure-WindowsDependencies {
    if (-not (Require-Command "winget")) {
        throw "winget is required on Windows to auto-install dependencies."
    }

    if (-not (Require-Command "git")) {
        Install-WithWinget -Id "Git.Git" -Label "Git"
    }
    if (-not (Require-Command "python")) {
        Install-WithWinget -Id "Python.Python.3.12" -Label "Python"
    }
    if (-not (Require-Command "ffmpeg")) {
        Install-WithWinget -Id "Gyan.FFmpeg" -Label "FFmpeg"
    }
    if (-not (Require-Command "mpv")) {
        Install-WithWinget -Id "Mpv.net" -Label "mpv"
    }
}

function Clone-OrUpdateRepo {
    if (Test-Path (Join-Path $InstallDir ".git")) {
        Write-Step "Updating existing DeckPilot checkout in $InstallDir."
        git -C $InstallDir pull --ff-only
        return
    }

    if ((Test-Path $InstallDir) -and (Get-ChildItem -Force $InstallDir | Select-Object -First 1)) {
        throw "Install directory '$InstallDir' exists and is not empty."
    }

    Write-Step "Cloning DeckPilot into $InstallDir."
    git clone $RepoUrl $InstallDir
}

function Write-DeckPilotConfig {
    $configPath = Join-Path $InstallDir "config.json"
    $examplePath = Join-Path $InstallDir "config.json.example"
    $runtimeDir = Join-Path $InstallDir "runtime"
    $clipsDir = Join-Path $runtimeDir "clips"
    $dataDir = Join-Path $runtimeDir "data"
    $thumbsDir = Join-Path $dataDir "thumbnails"

    $json = Get-Content $examplePath -Raw | ConvertFrom-Json
    $json.clips_dir = $clipsDir
    $json.data_dir = $dataDir
    $json.db_path = Join-Path $dataDir "pideck.db"
    $json.thumbnails_dir = $thumbsDir
    $json.mpv_socket_path = "\\.\pipe\deckpilot-mpv"

    $json | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $configPath
}

function Setup-PythonEnv {
    Write-Step "Creating Python virtual environment."
    python -m venv (Join-Path $InstallDir ".venv")
    & (Join-Path $InstallDir ".venv\Scripts\python.exe") -m pip install --upgrade pip
    & (Join-Path $InstallDir ".venv\Scripts\pip.exe") install -r (Join-Path $InstallDir "requirements.txt")
}

Write-Step "Starting installer for DeckPilot."
Write-Step "Detected platform: Windows"

Ensure-WindowsDependencies
Clone-OrUpdateRepo
Setup-PythonEnv
Write-DeckPilotConfig

Write-Step "Windows support is still marked as experimental in the current runtime, especially for mpv IPC."

Write-Host ""
Write-Host "DeckPilot installation complete."
Write-Host ""
Write-Host "Install directory:"
Write-Host "  $InstallDir"
Write-Host ""
Write-Host "Run manually:"
Write-Host "  cd `"$InstallDir`""
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python -m app.main"
Write-Host ""
Write-Host "Web UI:"
Write-Host "  http://127.0.0.1:8080"
