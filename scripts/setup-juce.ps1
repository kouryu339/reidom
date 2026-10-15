$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $RepoRoot "third_party\JUCE"
$Revision = "f8f8864172464b9adf9eba6101e1f784838d1597"
$Upstream = "https://github.com/juce-framework/JUCE.git"

if (Test-Path -LiteralPath $Target) {
    if (-not (Test-Path -LiteralPath (Join-Path $Target '.git'))) {
        throw "JUCE directory already exists without Git metadata. Set JUCE_PATH explicitly in CMake or inspect this directory manually."
    }
    $Current = git -C $Target rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $Current -ne $Revision) {
        throw "Existing JUCE checkout is not the pinned revision. It was left unchanged."
    }
    $Changes = git -C $Target status --porcelain
    if ($LASTEXITCODE -ne 0 -or $Changes) {
        throw "Existing JUCE checkout has local changes or could not be inspected. It was left unchanged."
    }
    Write-Output "Pinned JUCE checkout is already ready."
    return
}

# Only create a new dependency checkout; never reset or remove an existing one.
New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
git clone --no-checkout $Upstream $Target
if ($LASTEXITCODE -ne 0) { throw "JUCE clone failed. No existing files were removed." }
git -C $Target checkout --detach $Revision
if ($LASTEXITCODE -ne 0) { throw "Unable to check out the pinned JUCE revision." }
Write-Output "JUCE is ready. Review third_party/JUCE/LICENSE.md before building or distributing."
