[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Symbol,
    [Parameter(Mandatory)] [ValidateSet("buy","sell","long","short")] [string] $Side,
    [Parameter(Mandatory)] [double] $Entry,
    [Parameter(Mandatory)] [double] $StopLoss,
    [Parameter(Mandatory)] [double] $TakeProfit,
    [Parameter(Mandatory)] [double] $Capital,
    [switch] $DryRun,
    [switch] $Yes
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $scriptDir "..\.venv\Scripts\python.exe"

# Load .env
$envFile = Join-Path $env:USERPROFILE ".vibe-trading\.env"
if (Test-Path -LiteralPath $envFile) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -match "=") {
            $parts = $line -split "=", 2
            $key = $parts[0].Trim()
            $val = $parts[1].Trim()
            if ($val -and $val -notlike "PASTE_*") {
                [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            }
        }
    }
}

$argsList = @(
    (Join-Path $scriptDir "okx_bracket.py")
    "--symbol", $Symbol
    "--side", $Side
    "--entry", $Entry
    "--stop-loss", $StopLoss
    "--take-profit", $TakeProfit
    "--capital", $Capital
)
if ($DryRun) { $argsList += "--dry-run" }
if ($Yes)    { $argsList += "--yes" }

& $venvPython @argsList
exit $LASTEXITCODE
