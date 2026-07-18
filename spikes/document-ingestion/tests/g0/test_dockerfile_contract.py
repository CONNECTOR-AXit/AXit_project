from __future__ import annotations

from pathlib import Path


SPIKE_ROOT = Path(__file__).resolve().parents[2]


def test_parser_image_pins_the_approved_runtime_and_offline_korean_model() -> None:
    dockerfile = (SPIKE_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "python:3.12.11-slim-bookworm" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.11.29" in dockerfile
    assert "maven:3.9.11-eclipse-temurin-17" in dockerfile
    assert "TESSERACT_VERSION=5.3.0-2" in dockerfile
    assert "LEPTONICA_VERSION=1.82.0-3+b3" in dockerfile
    assert "e12c65a915945e4c28e237a9b52bc4a8f39a0cec" in dockerfile
    assert "f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff" in dockerfile
    assert "sha256sum --check --strict" in dockerfile
    assert "tesseract-ocr-kor" not in dockerfile


def test_parser_image_contains_only_the_isolated_runtime_and_runs_non_root() -> None:
    dockerfile = (SPIKE_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "uv sync --locked --only-group ingestion-g0" in dockerfile
    assert "COPY spikes/document-ingestion/src ./src" in dockerfile
    assert "COPY apps/api" not in dockerfile
    assert "COPY .env" not in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'CMD ["python", "-m", "axit_ingestion_spike.worker"]' in dockerfile
