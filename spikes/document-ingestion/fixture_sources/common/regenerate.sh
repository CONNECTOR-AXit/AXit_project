#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../../../.." && pwd)
image="axit-g0-fixture-generator:python3.12.11-pillow11.3.0"
fixture_root="/workspace/tests/fixtures/document-ingestion"

docker build --platform linux/amd64 --file "$script_dir/Dockerfile" --tag "$image" "$script_dir"
docker run --rm --platform linux/amd64 --network none \
  --mount "type=bind,source=$repo_root,target=/workspace" \
  --workdir /workspace \
  "$image" --output-root "$fixture_root"
docker run --rm --platform linux/amd64 --network none \
  --mount "type=bind,source=$repo_root,target=/workspace" \
  --workdir /workspace \
  "$image" --output-root "$fixture_root" --verify-existing
