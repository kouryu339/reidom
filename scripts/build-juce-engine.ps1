param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VsWhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$VisualStudio = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $VisualStudio) {
    throw "Visual Studio C++ tools are required to build the JUCE engine."
}

$CMake = Join-Path $VisualStudio "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$Ninja = Join-Path $VisualStudio "Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
$DevCmd = Join-Path $VisualStudio "Common7\Tools\VsDevCmd.bat"
$BuildDir = Join-Path $RepoRoot "build\engine-ninja"
$EngineSource = Join-Path $RepoRoot "engine"

$Configure = "call `"$DevCmd`" -arch=x64 -host_arch=x64 && `"$CMake`" -S `"$EngineSource`" -B `"$BuildDir`" -G Ninja -DCMAKE_MAKE_PROGRAM=`"$Ninja`" -DCMAKE_BUILD_TYPE=$Configuration"
cmd.exe /d /s /c $Configure
if ($LASTEXITCODE -ne 0) { throw "JUCE engine configuration failed." }

$Build = "call `"$DevCmd`" -arch=x64 -host_arch=x64 && `"$CMake`" --build `"$BuildDir`" --parallel 4"
cmd.exe /d /s /c $Build
if ($LASTEXITCODE -ne 0) { throw "JUCE engine build failed." }

$Binary = Join-Path $BuildDir "reidom-engine_artefacts\$Configuration\reidom-engine.exe"
if (-not (Test-Path -LiteralPath $Binary)) {
    throw "JUCE engine binary was not produced: $Binary"
}

$SidecarDir = Join-Path $RepoRoot "apps\studio-web\src-tauri\binaries"
New-Item -ItemType Directory -Path $SidecarDir -Force | Out-Null
$Sidecar = Join-Path $SidecarDir "reidom-engine-x86_64-pc-windows-msvc.exe"
Copy-Item -LiteralPath $Binary -Destination $Sidecar -Force
Write-Output "JUCE engine ready: $Binary"
Write-Output "Tauri sidecar staged: $Sidecar"
