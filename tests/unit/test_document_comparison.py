from app.document_comparison import _semantic_similarity
from app.local_embeddings import is_conservative_duplicate


def test_semantic_similarity_normalizes_case_spacing_and_compatibility() -> None:
    assert _semantic_similarity("API  비용 절감", "api 비용 절감") == 1.0


def test_semantic_similarity_detects_related_korean_phrasing() -> None:
    assert _semantic_similarity("예산 검토 결과를 공유합니다", "예산 검토 결과 공유") >= 0.72


def test_semantic_similarity_keeps_unrelated_items_separate() -> None:
    assert _semantic_similarity("예산 검토 결과", "서버 배포 일정") < 0.5


def test_semantic_similarity_uses_meeting_domain_concepts_for_paraphrases() -> None:
    assert _semantic_similarity("회의 일정을 다음 주로 연기", "미팅 날짜를 일주일 뒤로 미룸") >= 0.72
    assert _semantic_similarity("담당자는 김민수", "김민수가 업무를 맡음") >= 0.72


def test_duplicate_predicate_preserves_conflicting_facts() -> None:
    assert not is_conservative_duplicate("예산 증액을 승인", "예산 증액을 승인하지 않음")
    assert not is_conservative_duplicate("담당자는 김민수", "담당자는 김민수가 아님")
    assert not is_conservative_duplicate("회의 일정 취소", "회의 일정 확정")
    assert not is_conservative_duplicate("담당자는 김민수", "담당자는 이영희")
    assert not is_conservative_duplicate("예산은 10억", "예산은 20억")
    assert not is_conservative_duplicate("회의 날짜는 월요일", "회의 날짜는 화요일")
    assert not is_conservative_duplicate("회의를 다음 주로 연기", "회의를 다음 달로 연기")
    assert not is_conservative_duplicate("예산은 확정했습니다", "예산은 10억원으로 확정했습니다")
    assert not is_conservative_duplicate("회의 날짜를 확정했습니다", "회의 날짜는 월요일로 확정했습니다")
    assert is_conservative_duplicate("회의 일정을 다음 주로 연기", "미팅 날짜를 일주일 뒤로 미룸")
