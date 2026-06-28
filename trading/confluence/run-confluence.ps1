[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Symbol,
    [switch] $Json
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $scriptDir "..\.venv\Scripts\python.exe"

$argsList = @(
    (Join-Path $scriptDir "confluence.py")
    "--symbol", $Symbol
)
if ($Json) { $argsList += "--json" }

& $venvPython @argsList
exit $LASTEXITCODE
