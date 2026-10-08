param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Runtime is missing. Running first-time setup ...' -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot 'setup.ps1')
}

$customDatabase = Select-String -Path '.env' -Pattern '^\s*DATABASE_(URL|URI)\s*=\s*\S+' -Quiet -ErrorAction SilentlyContinue
if ((-not $customDatabase) -and (-not (Test-Path -LiteralPath 'instance\interview.db'))) {
    Write-Host 'Default database is missing. Importing seed data ...' -ForegroundColor Yellow
    & $venvPython scripts\init_db.py --seed
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
} else {
    & $venvPython scripts\init_db.py
    if ($LASTEXITCODE -ne 0) { throw 'Database schema check failed.' }
}

if (-not $NoBrowser) {
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        '-NoProfile',
        '-Command',
        'Start-Sleep -Seconds 2; Start-Process ''http://127.0.0.1:5001'''
    )
}

Write-Host 'Application URL: http://127.0.0.1:5001 (press Ctrl+C to stop)' -ForegroundColor Green
& $venvPython run.py
