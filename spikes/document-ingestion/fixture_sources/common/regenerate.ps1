$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$recipe = Join-Path $PSScriptRoot "Dockerfile"
$image = "axit-g0-fixture-generator:python3.12.11-pillow11.3.0"
$fixtureRoot = "/workspace/tests/fixtures/document-ingestion"

docker build --platform linux/amd64 --file $recipe --tag $image $PSScriptRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker run --rm --platform linux/amd64 --network none `
  --mount "type=bind,source=$repoRoot,target=/workspace" `
  --workdir /workspace `
  $image --output-root $fixtureRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker run --rm --platform linux/amd64 --network none `
  --mount "type=bind,source=$repoRoot,target=/workspace" `
  --workdir /workspace `
  $image --output-root $fixtureRoot --verify-existing
exit $LASTEXITCODE
