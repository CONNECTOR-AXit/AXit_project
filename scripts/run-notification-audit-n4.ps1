[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Start', 'Verify', 'Stop')]
    [string]$Action,
    [int]$WebPort = 0,
    [int]$ApiPort = 0,
    [string]$ManifestPath = '.\.omx\state\notification-audit-settings\compose-run.json'
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([System.IO.Path]::IsPathRooted($ManifestPath)) {
    $Manifest = [System.IO.Path]::GetFullPath($ManifestPath)
}
else {
    $Manifest = [System.IO.Path]::GetFullPath((Join-Path $Root $ManifestPath))
}
$Arguments = @(
    'run', 'python', 'scripts/n4_compose_lifecycle.py',
    $Action.ToLowerInvariant(), '--root', $Root, '--manifest', $Manifest,
    '--web-port', $WebPort, '--api-port', $ApiPort
)

Push-Location $Root
try {
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "N4 lifecycle action failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
