[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Symbol,
    [string] $Period = "2y",
    [switch] $Json
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $scriptDir "..\.venv\Scripts\python.exe"

$argsList = @(
    (Join-Path $scriptDir "regime.py")
    "--symbol", $Symbol
    "--period", $Period
)
if ($Json) { $argsList += "--json" }

& $venvPython @argsList
exit $LASTEXITCODE
