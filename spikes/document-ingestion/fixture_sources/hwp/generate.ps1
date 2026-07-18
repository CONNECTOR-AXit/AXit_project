param(
  [string]$OutputRoot = (Join-Path $PSScriptRoot '..\..\..\..\tests\fixtures\document-ingestion')
)

$ErrorActionPreference = 'Stop'
$javaSpec = (& java -XshowSettings:properties -version 2>&1 |
  Select-String -Pattern '^\s*java\.specification\.version\s*=\s*(.+)$' |
  Select-Object -First 1).Matches.Groups[1].Value.Trim()
if ($javaSpec -ne '17') {
  throw "Deterministic HWP fixture generation requires Java 17; found Java $javaSpec."
}
$sidecar = (Resolve-Path (Join-Path $PSScriptRoot '..\..\hwp-sidecar')).Path
mvn --file (Join-Path $sidecar 'pom.xml') --quiet -DskipTests package
$classpath = @(
  (Join-Path $sidecar 'target\axit-hwp-sidecar-0.1.0.jar'),
  (Join-Path $sidecar 'target\dependency\*')
) -join ';'
java -cp $classpath com.axit.ingestion.hwp.Main generate `
  --output-root $OutputRoot `
  --metadata (Join-Path $PSScriptRoot 'generated-fixtures.json')
