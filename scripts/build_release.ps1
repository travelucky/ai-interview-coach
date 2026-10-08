param(
    [string]$Output = 'dist\ai-interview-mvp.zip'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run scripts\setup.ps1 first.' }

& $venvPython scripts\verify_release.py
if ($LASTEXITCODE -ne 0) { throw 'Pre-release verification failed.' }

git diff --quiet --exit-code
if ($LASTEXITCODE -ne 0) { throw 'The working tree has uncommitted changes. Commit them before building a reproducible release.' }

$outputPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Output))
$outputDirectory = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
git archive --format=zip --prefix=ai-interview-mvp/ -o $outputPath HEAD
if ($LASTEXITCODE -ne 0) { throw 'Git archive failed.' }

& $venvPython scripts\verify_release.py --archive $outputPath
if ($LASTEXITCODE -ne 0) { throw 'The generated ZIP failed release verification.' }
Write-Host "Release package created: $outputPath" -ForegroundColor Green
