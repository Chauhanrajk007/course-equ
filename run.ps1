<#
  Start the Course Equivalence app on localhost.
  .\run.ps1
#>
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host 'Creating virtual environment...' -ForegroundColor Cyan
    python -m venv .venv
}
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

Write-Host ''
Write-Host '  Course Equivalence  ->  http://127.0.0.1:5000' -ForegroundColor Green
Write-Host ''

& $py -m pip install -q -r requirements.txt
& $py app.py