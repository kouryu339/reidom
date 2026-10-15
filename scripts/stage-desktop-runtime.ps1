param(
    [string]$AiFrameworkDir = $env:AI_FRAMEWORK_DIR,
    [string]$OrbitRuntimeLibrary = $env:AGENT_RUNTIME_LIBRARY,
    [switch]$RebuildMidiTools
)

$ErrorActionPreference = "Stop"
$ExpectedVersion = "0.5.0"
$ExpectedAbi = "1.3"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BinDir = Join-Path $RepoRoot "bin"
$TargetRuntime = Join-Path $BinDir "agent_runtime.dll"
$TargetRelease = Join-Path $BinDir "orbit-runtime-release.json"
$ToolTarget = Join-Path $RepoRoot "apps\studio-web\src-tauri\binaries\reidom-midi-tools-x86_64-pc-windows-msvc.exe"

if (-not $OrbitRuntimeLibrary -and $AiFrameworkDir) {
    $OrbitRuntimeLibrary = Join-Path $AiFrameworkDir "target\release\agent_runtime.dll"
}

$SourceManifest = if ($AiFrameworkDir) { Join-Path $AiFrameworkDir "sdk\runtime\release_manifest.json" } else { $null }
$ExistingRelease = if (Test-Path -LiteralPath $TargetRelease) { Get-Content -Raw $TargetRelease | ConvertFrom-Json } else { $null }
$AlreadyStaged = (Test-Path -LiteralPath $TargetRuntime) -and $ExistingRelease -and $ExistingRelease.runtime_version -eq $ExpectedVersion -and $ExistingRelease.abi_version -eq $ExpectedAbi

if (-not $AlreadyStaged) {
    if (-not $SourceManifest -or -not (Test-Path -LiteralPath $SourceManifest)) {
        throw "Orbit Runtime release manifest is missing. Set AI_FRAMEWORK_DIR to the v$ExpectedVersion checkout."
    }
    $Manifest = Get-Content -Raw $SourceManifest | ConvertFrom-Json
    if ($Manifest.runtime_version -ne $ExpectedVersion -or $Manifest.abi_version -ne $ExpectedAbi) {
        throw "Expected Orbit Runtime $ExpectedVersion / ABI $ExpectedAbi, got $($Manifest.runtime_version) / $($Manifest.abi_version)."
    }
    if (-not $OrbitRuntimeLibrary -or -not (Test-Path -LiteralPath $OrbitRuntimeLibrary)) {
        throw "Orbit Runtime $ExpectedVersion library is missing: $OrbitRuntimeLibrary"
    }
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    Copy-Item -LiteralPath $OrbitRuntimeLibrary -Destination $TargetRuntime -Force
    $Hash = (Get-FileHash -LiteralPath $TargetRuntime -Algorithm SHA256).Hash.ToLowerInvariant()
    [ordered]@{
        schema = "reidom-orbit-runtime-release/v1"
        runtime_version = $ExpectedVersion
        release_tag = "v$ExpectedVersion"
        abi_version = $ExpectedAbi
        library = "agent_runtime.dll"
        sha256 = $Hash
    } | ConvertTo-Json | Set-Content -LiteralPath $TargetRelease -Encoding UTF8
}

if ($RebuildMidiTools -or -not (Test-Path -LiteralPath $ToolTarget)) {
    & (Join-Path $PSScriptRoot "build-midi-tools-sidecar.ps1") -AiFrameworkDir $AiFrameworkDir
}
if (-not (Test-Path -LiteralPath $ToolTarget)) {
    throw "MIDI tool service has not been staged: $ToolTarget"
}

Write-Output "Orbit Runtime v$ExpectedVersion staged for Reidom desktop."
Write-Output "MIDI tool service staged for Reidom desktop."
