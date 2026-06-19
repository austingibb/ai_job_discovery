<#
.SYNOPSIS
    Launch Google Chrome with remote debugging enabled for the ai_job_discovery pipeline.

.DESCRIPTION
    This is the Windows equivalent of the macOS command in the README:

        /Applications/Google Chrome.app/Contents/MacOS/Google Chrome \
            --remote-debugging-port=9222 --user-data-dir="$HOME/ChromeDebug"

    It opens Chrome against a SEPARATE user-data-dir (%USERPROFILE%\ChromeDebug by
    default) so it never touches your normal Chrome profile. The pipeline connects to
    this instance over CDP at http://localhost:9222 (see cdp_url in config/config.json).

    After it launches, log in to any sites the pipeline needs in THIS window:
      - linkedin.com   (for the LinkedIn scraper)
      - claude.ai      (for the Claude browser scorer)

    The login session lives in the ChromeDebug user-data-dir, so you only need to log
    in once; it persists across relaunches.

.PARAMETER Port
    Remote debugging port. Must match cdp_url in config/config.json. Default: 9222.

.PARAMETER UserDataDir
    Chrome user-data-dir to use. Default: %USERPROFILE%\ChromeDebug.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_chrome_debug.ps1
#>
param(
    [int]$Port = 9222,
    [string]$UserDataDir = (Join-Path $env:USERPROFILE "ChromeDebug")
)

$ErrorActionPreference = "Stop"

# Locate chrome.exe across the common install locations.
$candidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Error "Could not find chrome.exe. Install Google Chrome or pass the path manually."
    exit 1
}

if (-not (Test-Path $UserDataDir)) {
    New-Item -ItemType Directory -Path $UserDataDir | Out-Null
}

Write-Host "Launching Chrome with remote debugging:"
Write-Host "  chrome        : $chrome"
Write-Host "  port          : $Port"
Write-Host "  user-data-dir : $UserDataDir"
Write-Host ""
Write-Host "Once Chrome opens, log in to linkedin.com and claude.ai in THIS window."
Write-Host "Leave it running, then start the pipeline in a separate terminal."

& $chrome "--remote-debugging-port=$Port" "--user-data-dir=$UserDataDir"
