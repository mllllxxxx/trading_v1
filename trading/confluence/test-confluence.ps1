[CmdletBinding()]
param(
    [string] $Symbol = "BTC-USDT"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[TEST] MTF Confluence for $Symbol" -ForegroundColor Cyan
Write-Host ""

& (Join-Path $scriptDir "run-confluence.ps1") -Symbol $Symbol
exit $LASTEXITCODE
