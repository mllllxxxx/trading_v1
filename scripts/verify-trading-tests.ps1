$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$tmpRoot = Join-Path $repoRoot ".test-runs"
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null

$tmpDir = Join-Path $tmpRoot ("pytest-" + $PID)
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

$env:TMP = $tmpDir
$env:TEMP = $tmpDir

& ".\trading\.venv\Scripts\python.exe" "trading\schemas\export_json_schemas.py" --check
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

& ".\trading\.venv\Scripts\python.exe" "trading\rulebook\compile_rulebook.py" --check
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

& ".\trading\.venv\Scripts\python.exe" -m pytest -x -o cache_dir="$tmpDir\pytest-cache"
exit $LASTEXITCODE
