param(
    [switch]$CreateAdmin
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host '[1/4] Creating Python virtual environment .venv ...'
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            & $launcher.Source -3 -m venv .venv
        }
    } else {
        $python = Get-Command python -ErrorAction Stop
        & $python.Source -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create .venv. Install Python 3.11 or 3.12 first.' }
}

Write-Host '[2/4] Installing dependencies ...'
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and pip configuration.' }

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host '[3/4] Created .env from .env.example. Add optional API settings when needed.'
} else {
    Write-Host '[3/4] Keeping the existing .env file.'
}

Write-Host '[4/4] Initializing database and seed data ...'
$arguments = @('scripts\init_db.py', '--seed')
if ($CreateAdmin) { $arguments += '--create-admin' }
& $venvPython @arguments
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }

Write-Host 'Setup complete. Run .\scripts\start.ps1 to start the application.' -ForegroundColor Green
