[CmdletBinding()]
param(
    [string] $Symbol = "BTC-USDT",
    [string] $Period = "2y"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[TEST] Regime detection for $Symbol ($Period)" -ForegroundColor Cyan
Write-Host ""

& (Join-Path $scriptDir "run-regime.ps1") -Symbol $Symbol -Period $Period
exit $LASTEXITCODE
