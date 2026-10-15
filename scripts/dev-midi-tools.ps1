param(
    [string]$AiFrameworkDir = $env:AI_FRAMEWORK_DIR
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if (-not $AiFrameworkDir) {
    throw "Set AI_FRAMEWORK_DIR or pass -AiFrameworkDir."
}

$env:REIDOM_BRIDGE_DIR = Join-Path $RepoRoot "data\bridge"
$env:REIDOM_ENGINE_ENDPOINT = if ($env:REIDOM_ENGINE_ENDPOINT) { $env:REIDOM_ENGINE_ENDPOINT } else { "127.0.0.1:47120" }
$env:COREWORK_AGENT_TOOL_PROTO = Join-Path $AiFrameworkDir "corework\proto\corework_agent_tool_v1.proto"
$ToolSdk = Join-Path $AiFrameworkDir "sdk\rpctools\python"
$env:PYTHONPATH = @(
    $ToolSdk,
    (Join-Path $RepoRoot "services\midi-tools\src"),
    $env:PYTHONPATH
) -join [IO.Path]::PathSeparator

uv run --with-editable $ToolSdk --package reidom-midi-tools reidom-midi-tools
