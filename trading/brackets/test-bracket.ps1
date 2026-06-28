[CmdletBinding()]
param(
    [string] $Scenario = "good"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$cases = @{
    good = @{
        Symbol     = "BTC-USDT"
        Side       = "buy"
        Entry      = 65000
        StopLoss   = 64000
        TakeProfit = 68000
        Capital    = 10000
    }
    bad_rr = @{
        Symbol     = "BTC-USDT"
        Side       = "buy"
        Entry      = 65000
        StopLoss   = 64500
        TakeProfit = 65500
        Capital    = 10000
    }
    bad_size = @{
        Symbol     = "BTC-USDT"
        Side       = "buy"
        Entry      = 65000
        StopLoss   = 64500
        TakeProfit = 70000
        Capital    = 1000
    }
    short_good = @{
        Symbol     = "ETH-USDT"
        Side       = "sell"
        Entry      = 3500
        StopLoss   = 3600
        TakeProfit = 3300
        Capital    = 5000
    }
}

if (-not $cases.ContainsKey($Scenario)) {
    Write-Host "Unknown scenario '$Scenario'. Options: $($cases.Keys -join ', ')"
    exit 1
}

$c = $cases[$Scenario]
Write-Host "[TEST] Scenario: $Scenario" -ForegroundColor Cyan
Write-Host ""

& (Join-Path $scriptDir "run-bracket.ps1") `
    -Symbol $c.Symbol `
    -Side $c.Side `
    -Entry $c.Entry `
    -StopLoss $c.StopLoss `
    -TakeProfit $c.TakeProfit `
    -Capital $c.Capital `
    -DryRun
exit $LASTEXITCODE
