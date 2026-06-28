# Activates the trading venv, loads .env from user home, runs vibe-trading
# Usage:  .\trading\run.ps1 <vibe-trading-args>
# Example: .\trading\run.ps1 --version
#          .\trading\run.ps1 provider doctor
#          .\trading\run.ps1 connector list
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $scriptDir ".venv\Scripts\python.exe"

# Load .env from user home (Vibe-Trading's standard location)
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

& $venvPython -m cli $args
