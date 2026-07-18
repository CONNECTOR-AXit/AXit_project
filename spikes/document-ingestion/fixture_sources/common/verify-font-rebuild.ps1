$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$recipe = Join-Path $PSScriptRoot "font-build.Dockerfile"
$image = "axit-g0-font-builder:python3.12.11-fonttools4.59.2"
$sourceUrl = "https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/Sans/Variable/TTF/Subset/NotoSansKR-VF.ttf"
$sourceHash = "9e1d729e7e2b36f9ef439da102f8c134c10aabe46f1c843bf0aca5c043b86f76"
$subsetHash = "a2c4986eabb2296fe733b90c4a6c8911c1c7bf7dd6d2b47675139e1afa0eb1bb"
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("axit-font-" + [guid]::NewGuid())
$source = Join-Path $temporary "NotoSansKR-VF.ttf"
$output = Join-Path $temporary "output"

[System.IO.Directory]::CreateDirectory($output) | Out-Null
try {
  Invoke-WebRequest -Uri $sourceUrl -OutFile $source
  if ((Get-FileHash $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) {
    throw "upstream font SHA-256 mismatch"
  }

  docker build --platform linux/amd64 --file $recipe --tag $image $PSScriptRoot
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  docker run --rm --platform linux/amd64 --network none `
    --mount "type=bind,source=$repoRoot,target=/workspace,readonly" `
    --mount "type=bind,source=$source,target=/source/NotoSansKR-VF.ttf,readonly" `
    --mount "type=bind,source=$output,target=/output" `
    $image /source/NotoSansKR-VF.ttf /output/NotoSansKR-FixtureSubset.ttf
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  $rebuilt = Join-Path $output "NotoSansKR-FixtureSubset.ttf"
  $actualHash = (Get-FileHash $rebuilt -Algorithm SHA256).Hash.ToLowerInvariant()
  $committedHash = (
    Get-FileHash (Join-Path $PSScriptRoot "font\NotoSansKR-FixtureSubset.ttf") `
      -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  if ($actualHash -ne $subsetHash -or $committedHash -ne $subsetHash) {
    throw "font subset reproducibility check failed"
  }
  Write-Output "font subset byte-for-byte rebuild verified: $actualHash"
}
finally {
  if ([System.IO.Directory]::Exists($temporary)) {
    [System.IO.Directory]::Delete($temporary, $true)
  }
}
