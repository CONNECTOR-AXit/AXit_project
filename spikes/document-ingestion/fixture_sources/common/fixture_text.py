"""Project-authored Korean text shared by deterministic G0 fixtures."""

from __future__ import annotations

import unicodedata


CLEAN_LINES = (
    "회의 사전 브리핑 자료",
    "참석자 김민수 이서연 박준호",
    "안건 고객 피드백과 출시 일정",
    "결론 다음 주 월요일까지 검토",
)

TEXT_PDF_LINES = (
    "회의 준비 문서",
    "참석자 의견과 결정 사항을 확인합니다",
    "다음 회의 전까지 실행 계획을 검토합니다",
)

LOW_CONFIDENCE_LINES = (
    "회 의  자 료",
    "일 정  확 인",
)


def nfc_text(lines: tuple[str, ...]) -> str:
    """Return the canonical expected fixture text."""

    return unicodedata.normalize("NFC", "\n".join(lines))


FONT_TEXT = "\n".join((*CLEAN_LINES, *TEXT_PDF_LINES, *LOW_CONFIDENCE_LINES))
