param(
    [string]$AiFrameworkDir = $env:AI_FRAMEWORK_DIR,
    [string]$Python = $env:PYTHON
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if (-not $AiFrameworkDir -or -not (Test-Path -LiteralPath $AiFrameworkDir)) {
    throw "Set AI_FRAMEWORK_DIR or pass -AiFrameworkDir pointing to an Orbit Runtime 0.5.0 checkout."
}

if ($Python -and (Test-Path -LiteralPath $Python -PathType Container)) {
    $Python = Join-Path $Python "python.exe"
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $ProjectPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $ProjectPython) { $Python = $ProjectPython }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand -and (Test-Path -LiteralPath $PythonCommand.Source -PathType Leaf)) { $Python = $PythonCommand.Source }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python 3.11+ with PyInstaller is required to build the MIDI tool service."
}

$Sdk = Join-Path $AiFrameworkDir "sdk\rpctools\python"
$Proto = Join-Path $AiFrameworkDir "corework\proto\corework_agent_tool_v1.proto"
$ToolSource = Join-Path $RepoRoot "services\midi-tools\src"
$Entry = Join-Path $RepoRoot "services\midi-tools\packaging_entry.py"
$BuildRoot = Join-Path $RepoRoot "build\midi-tools-sidecar"
$Dist = Join-Path $BuildRoot "dist"
$Work = Join-Path $BuildRoot "work"
$Spec = Join-Path $BuildRoot "spec"

foreach ($Path in @($Sdk, $Proto, $ToolSource, $Entry)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required MIDI tool build input is missing: $Path" }
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name reidom-midi-tools `
    --paths $Sdk `
    --paths $ToolSource `
    --add-data "$Proto;." `
    --collect-all grpc_tools `
    --collect-all google.protobuf `
    --distpath $Dist `
    --workpath $Work `
    --specpath $Spec `
    $Entry
if ($LASTEXITCODE -ne 0) { throw "MIDI tool service packaging failed." }

$Built = Join-Path $Dist "reidom-midi-tools.exe"
$Target = Join-Path $RepoRoot "apps\studio-web\src-tauri\binaries\reidom-midi-tools-x86_64-pc-windows-msvc.exe"
if (-not (Test-Path -LiteralPath $Built)) { throw "MIDI tool service executable was not produced." }
Copy-Item -LiteralPath $Built -Destination $Target -Force
Write-Output "MIDI tool service ready: $Target"
