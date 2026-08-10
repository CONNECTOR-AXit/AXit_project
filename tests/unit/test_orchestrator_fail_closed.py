from __future__ import annotations

import pytest

from app.orchestrator import _generation_runner
from app.provider_errors import GenerationProviderFailure


def test_generation_runner_does_not_fall_back_to_mock_without_xai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    runner = _generation_runner()

    with pytest.raises(GenerationProviderFailure) as raised:
        runner._provider.generate_summary([], fixture_id="unused", attempt=1)
    assert raised.value.code == "grok_api_key_missing"
    assert raised.value.retryable is True
    assert runner._provider.provider == "grok"


def test_generation_runner_uses_live_grok_for_summary_when_key_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "synthetic-test-key")

    runner = _generation_runner()

    assert runner._provider.summary_generator.__self__.__class__.__name__ == "GrokProvider"
    assert runner._provider.provider == "grok"
