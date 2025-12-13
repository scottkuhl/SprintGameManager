$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "Missing venv python at $python. Create venv first (see README)."
}

# Ensure PyInstaller is available
& $python -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
  & $python -m pip install --upgrade pyinstaller
}

# Clean prior outputs
if (Test-Path "$root\dist") { Remove-Item -Recurse -Force "$root\dist" }
if (Test-Path "$root\build") { Remove-Item -Recurse -Force "$root\build" }

$icon = Join-Path $root "resources\icon.ico"
if (-not (Test-Path $icon)) {
  throw "Missing icon at $icon"
}

# Windows add-data separator is ';'
$addData = "resources;resources"

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "SprintGameManager" `
  --icon "$icon" `
  --paths "src" `
  --add-data "$addData" `
  "main.py"

Write-Host "Built: $root\dist\SprintGameManager.exe"
