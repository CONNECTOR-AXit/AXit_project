"""Live xAI-backed project description elaboration, interview-style.

Approved for repeated production use in a narrow scope only: see
``docs/provider-experiment-description-assist-amendment.md``. Only the
user-typed project title/description/interview answers are ever sent —
never uploaded documents or meeting content.

The interview mechanics are adapted from OMX's real `deep-interview` skill
(``plugins/oh-my-codex/skills/deep-interview/SKILL.md`` in
github.com/Yeachan-Heo/oh-my-codex), not guessed from scratch. That skill is
built for a full agentic CLI — it drives tmux panes, an `omx question` tool,
`.omx/state` and `.omx/context` files, and a multi-phase pipeline spanning
several other skills — none of which exist in this single-endpoint xAI call,
so it cannot be dropped in verbatim. What *is* ported faithfully is its core
mechanic: a numeric clarity score across weighted dimensions instead of a
binary guess, a mandatory "non-goals" readiness gate before concluding, a
forced minimum of one round before early exit, and a "pressure ladder" that
prefers digging one layer deeper into the latest answer (concrete example,
hidden assumption, explicit boundary) over hopping to a fresh topic each
round. The round count is decided by the model each turn against that score,
not a fixed count — a caller-side cap only exists as a runaway-cost safety
net, never as the normal stop condition.

Once the model judges the draft + interview answers sufficient, it returns a
single, longer description that *extends* the existing draft with everything
learned so far, rather than replacing it with an unrelated rewrite or a
handful of short alternatives to pick between. The caller shows it as one
preview to accept or discard. Clicking the button again after accepting it
continues the interview on top of the now-longer draft, so the description
keeps growing across rounds instead of resetting each time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from app.grok_provider import GrokProviderError, GrokTransport

_STEP_SCHEMA_NAME: Final = "axit_description_step"
_FINAL_SCHEMA_NAME: Final = "axit_description_final"
_MAX_TITLE_CHARS: Final = 200
_MAX_DRAFT_CHARS: Final = 4_000
_MAX_HISTORY_TURNS: Final = 5

# OMX's deep-interview stops at ambiguity <= threshold (default 0.20, i.e.
# clarity >= 0.80) plus mandatory Non-goals/Decision-boundary gates. We use
# the same 0.80 bar and fold "decision boundaries" into "non-goals" since
# there's only one artifact (a short description) to gate, not a full spec.
_CLARITY_THRESHOLD: Final = 0.8

_STEP_SYSTEM_PROMPT: Final = (
    "당신은 OMX의 deep-interview 방식을 본떠 만든, 문서 통합 협업 도구의 "
    "프로젝트 설명 작성을 돕는 소크라테스식 인터뷰어입니다.\n\n"
    "제목, 지금까지의 설명 초안, 이전 질문/답변 이력을 보고 명확도(clarity, "
    "0.0=매우 모호함 ~ 1.0=완전히 명확함)를 가중 평균으로 스스로 채점하세요: "
    "의도(Intent — 왜 이 프로젝트가 필요한지) 40%, 범위(Scope — 무엇을 "
    "다루는지) 30%, 비범위(Non-goals — 명시적으로 다루지 않는 것) 30%.\n\n"
    "다음 두 조건을 모두 만족하기 전에는 sufficient를 true로 하지 마세요: "
    "(1) clarity >= 0.8, (2) 답변 이력에서 Non-goals(이 프로젝트가 다루지 "
    "않는 것)가 최소 한 번은 명시적으로 다뤄졌음. 이력이 비어 있다면(아직 "
    "한 번도 질문한 적이 없다면) 초안이 아무리 자세해 보여도 반드시 "
    "sufficient를 false로 하세요 — 최소 1라운드는 항상 거쳐야 합니다.\n\n"
    "다음 질문을 만들 때는 이 우선순위를 따르세요:\n"
    "1. 직전 답변을 더 깊이 압박(pressure-test)하는 것을 새 주제로 넘어가는 "
    "것보다 우선하세요 — 구체적 예시/근거를 요구하거나, 숨은 전제를 "
    "캐묻거나, 명시적 경계(무엇을 하지 않을지)를 강제하거나, 애매한 표현을 "
    "더 명확한 말로 재정의시키세요.\n"
    "2. 다만 Non-goals가 아직 한 번도 다뤄지지 않았다면, 그것이 항상 "
    "최우선 다음 질문입니다.\n"
    "3. 이력에서 이미 다룬 내용은 다시 묻지 마세요.\n\n"
    "질문에 대한 답으로 고를 수 있는 짧고 구체적인 선택지를 2~4개 "
    "제시하세요. 정답이 하나로 정해지지 않는 질문이니 '기타'나 '직접 "
    "입력' 같은 자유 응답 placeholder는 선택지에 넣지 마세요 — 자유 입력 "
    "UI는 화면에 별도로 항상 제공됩니다.\n\n"
    "sufficient가 true면 question/options 필드는 사용되지 않으니 형식만 "
    "맞춰 아무 값이나 채우면 됩니다."
)
_FINAL_SYSTEM_PROMPT: Final = (
    "당신은 문서 통합 협업 도구의 프로젝트 설명 작성을 돕는 도우미입니다. "
    "프로젝트명, 기존 설명 초안, 인터뷰 질문/답변 이력을 모두 반영해 완성된 "
    "설명 문구를 **딱 하나만** 작성하세요 (여러 개를 제안하지 마세요 — "
    "사용자가 직접 확인하고 적용 여부를 결정합니다).\n\n"
    "기존 초안을 대체하는 게 아니라 그 내용을 문장 단위로 그대로 살리면서, "
    "인터뷰에서 얻은 모든 답변을 하나도 빠짐없이 자연스러운 문장으로 풀어 "
    "덧붙여 확장하세요. 결과는 항상 기존 초안보다 훨씬 더 길고 구체적이어야 "
    "합니다 — 짧은 한두 문장 요약은 절대 안 되고, 최소 4~6문장 이상의 "
    "충분히 풍부한 문단으로 작성해서 읽는 사람이 이 프로젝트의 의도, 범위, "
    "다루지 않는 것까지 바로 파악할 수 있게 하세요. 초안이 비어 있으면 "
    "인터뷰 답변만으로 이 정도 분량의 완성된 설명을 작성하세요. 사용자가 "
    "제공하지 않은 사실을 지어내지 마세요."
)


@dataclass(frozen=True, slots=True)
class DescriptionInterviewTurn:
    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class DescriptionQuestion:
    question: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DescriptionInterviewStep:
    """The model's own judgment for this round: keep asking, or wrap up."""

    sufficient: bool
    clarity: float
    question: DescriptionQuestion | None


def _normalize_inputs(
    *, title: str, draft: str, history: tuple[DescriptionInterviewTurn, ...]
) -> tuple[str, str]:
    normalized_title = title.strip()
    normalized_draft = draft.strip()
    if not normalized_title:
        raise GrokProviderError("description_assist_title_required", retryable=False)
    if len(normalized_title) > _MAX_TITLE_CHARS or len(normalized_draft) > _MAX_DRAFT_CHARS:
        raise GrokProviderError("description_assist_input_too_long", retryable=False)
    if len(history) > _MAX_HISTORY_TURNS:
        raise GrokProviderError("description_assist_input_too_long", retryable=False)
    return normalized_title, normalized_draft


def _history_payload(history: tuple[DescriptionInterviewTurn, ...]) -> list[dict[str, str]]:
    return [{"question": turn.question, "answer": turn.answer} for turn in history]


def advance_description_interview(
    transport: GrokTransport,
    *,
    title: str,
    draft: str,
    history: tuple[DescriptionInterviewTurn, ...],
    model: str,
) -> DescriptionInterviewStep:
    """One round of the interview, with the model deciding whether to stop.

    Mirrors OMX deep-interview's own gate: even if the model reports
    ``sufficient=True``, we force ``False`` on the very first round (empty
    history) here, matching OMX's "no early exit before the first pressure
    pass" rule — the model's self-report alone isn't trusted for that case.
    """
    normalized_title, normalized_draft = _normalize_inputs(title=title, draft=draft, history=history)
    payload = {
        "model": model,
        "store": False,
        "tools": [],
        "max_output_tokens": 600,
        "input": [
            {"role": "system", "content": _STEP_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"title": normalized_title, "draft": normalized_draft, "history": _history_payload(history)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": _STEP_SCHEMA_NAME,
                "strict": True,
                "schema": _step_schema(),
            }
        },
    }
    response = transport.create_response(payload)
    step = _parse_step_response(response)
    if not history and step.sufficient:
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    return step


def finalize_description(
    transport: GrokTransport,
    *,
    title: str,
    draft: str,
    history: tuple[DescriptionInterviewTurn, ...],
    model: str,
) -> str:
    normalized_title, normalized_draft = _normalize_inputs(title=title, draft=draft, history=history)
    payload = {
        "model": model,
        "store": False,
        "tools": [],
        "max_output_tokens": 1_500,
        "input": [
            {"role": "system", "content": _FINAL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"title": normalized_title, "draft": normalized_draft, "history": _history_payload(history)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": _FINAL_SCHEMA_NAME,
                "strict": True,
                "schema": _final_schema(),
            }
        },
    }
    response = transport.create_response(payload)
    return _parse_final_response(response)


def _step_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "sufficient": {"type": "boolean"},
            "clarity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "question": {"type": "string", "minLength": 1, "maxLength": 300},
            "options": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 80},
                "minItems": 2,
                "maxItems": 4,
            },
        },
        "required": ["sufficient", "clarity", "question", "options"],
        "additionalProperties": False,
    }


def _final_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            # minLength는 "최소 몇 문장 이상"을 강제로 보장할 수는 없지만,
            # 짧은 한 줄짜리 응답을 걸러내는 대략적인 하한선 역할을 합니다.
            "description": {"type": "string", "minLength": 120, "maxLength": 2_000},
        },
        "required": ["description"],
        "additionalProperties": False,
    }


def _parse_step_response(response: Any) -> DescriptionInterviewStep:
    document = _parse_json_output(response)
    if not isinstance(document, dict) or set(document) != {
        "sufficient",
        "clarity",
        "question",
        "options",
    }:
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    sufficient = document["sufficient"]
    clarity = document["clarity"]
    if not isinstance(sufficient, bool):
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    if not isinstance(clarity, (int, float)) or isinstance(clarity, bool) or not 0.0 <= clarity <= 1.0:
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    if sufficient:
        return DescriptionInterviewStep(sufficient=True, clarity=float(clarity), question=None)
    question, options = document["question"], document["options"]
    if not isinstance(question, str) or not question.strip():
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    if not isinstance(options, list) or not 2 <= len(options) <= 4:
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    cleaned: list[str] = []
    for option in options:
        if not isinstance(option, str) or not option.strip():
            raise GrokProviderError("description_assist_malformed_output", retryable=False)
        cleaned.append(option.strip())
    return DescriptionInterviewStep(
        sufficient=False,
        clarity=float(clarity),
        question=DescriptionQuestion(question=question.strip(), options=tuple(cleaned)),
    )


def _parse_final_response(response: Any) -> str:
    document = _parse_json_output(response)
    if not isinstance(document, dict) or set(document) != {"description"}:
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    description = document["description"]
    if not isinstance(description, str) or not description.strip():
        raise GrokProviderError("description_assist_malformed_output", retryable=False)
    return description.strip()


def _parse_json_output(response: Any) -> Any:
    if response.get("status") != "completed":
        raise GrokProviderError("description_assist_incomplete_response", retryable=True)
    output_text = _response_output_text(response)
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        raise GrokProviderError(
            "description_assist_malformed_output", retryable=False
        ) from None


def _response_output_text(response: Any) -> str:
    found: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    found.append(text)
    if len(found) != 1:
        raise GrokProviderError("description_assist_malformed_response", retryable=False)
    return found[0]
