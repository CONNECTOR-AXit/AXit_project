#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SIDECAR=$(CDPATH= cd -- "$SCRIPT_DIR/../../hwp-sidecar" && pwd)
OUTPUT_ROOT=${1:-"$SCRIPT_DIR/../../../../tests/fixtures/document-ingestion"}
JAVA_SPEC=$(java -XshowSettings:properties -version 2>&1 |
  sed -n 's/^[[:space:]]*java\.specification\.version[[:space:]]*=[[:space:]]*//p' |
  head -n 1)
if [ "$JAVA_SPEC" != "17" ]; then
  echo "Deterministic HWP fixture generation requires Java 17; found Java ${JAVA_SPEC:-unknown}." >&2
  exit 1
fi

mvn --file "$SIDECAR/pom.xml" --quiet -DskipTests package
exec java -cp "$SIDECAR/target/axit-hwp-sidecar-0.1.0.jar:$SIDECAR/target/dependency/*" \
  com.axit.ingestion.hwp.Main generate \
  --output-root "$OUTPUT_ROOT" \
  --metadata "$SCRIPT_DIR/generated-fixtures.json"
