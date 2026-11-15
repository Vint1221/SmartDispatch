$ErrorActionPreference = 'Stop'

Write-Host 'Checking Python...' -ForegroundColor Cyan
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $pythonVersion = & python --version 2>&1
    Write-Host "Found $pythonVersion; skipping Python installation." -ForegroundColor Green
} else {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Python is missing and winget is unavailable. Install Python 3.12 from https://www.python.org/downloads/windows/.'
    }
    winget install --id Python.Python.3.12 -e --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. Install it from https://www.python.org/downloads/windows/ and rerun.' }
}

Write-Host 'Checking Node.js and npm...' -ForegroundColor Cyan
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($nodeCmd -and $npmCmd) {
    Write-Host "Found Node.js $(& node --version) and npm $(& npm.cmd --version); skipping installation." -ForegroundColor Green
} else {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Node.js/npm is missing and winget is unavailable. Install Node.js LTS from https://nodejs.org/.'
    }
    winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Node.js installation failed. Install it from https://nodejs.org/en/download/ and rerun.' }
}

Write-Host ''
Write-Host 'Required tools are available.' -ForegroundColor Green
Write-Host 'Close and reopen VS Code only if commands are not recognized.'
Write-Host 'Verify with: python --version; node --version; npm.cmd --version'
