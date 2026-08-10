# RAG 회의 사전 브리핑 — 결정론적 실험 결과

> **실험 경계:** xAI/Grok을 호출하지 않았으며 API 키를 저장하지 않았다. 아래 결과는 검토 가능한 MockProvider 개발 fixture다.

- **회의 주제:** RAG의 발전과 회의 사전 브리핑 프로토타입
- **출력 언어:** ko-KR
- **Provider:** `mock`
- **Fixture:** `rag-meeting-briefing-ko-001`

## 참가자 준비 자료

| 참가자 | 담당 자료 | 근거 anchor |
|---|---|---|
| 민서 | RAG 역사 조사 | `anchor-history-001`, `anchor-history-002` |
| 준호 | RAG 유형 조사 | `anchor-types-001` |
| 서연 | 구현 저장소 조사 | `anchor-code-001` |
| 도윤 | 프로토타입 기획안 | `anchor-prototype-001` |

## 참가자 원문 기반 요약

- 민서는 2020년 주요 연구를 중심으로 RAG의 발전 흐름을 조사했다. **[민서 · `anchor-history-001`]**
- 준호는 기본형, Self-RAG, GraphRAG의 특징을 비교했다. **[준호 · `anchor-types-001`]**
- 서연은 구현을 검토할 수 있는 세 가지 GitHub 저장소를 정리했다. **[서연 · `anchor-code-001`]**
- 도윤은 출처 연결형 회의 사전 브리핑 프로토타입을 제안했다. **[도윤 · `anchor-prototype-001`]**

## 외부 자료 조사

### 역사

REALM은 2020년 2월 검색기를 언어모델 사전학습에 결합하는 방식을 발표했고, Lewis 등의 논문은 같은 해 5월 검색 증강 생성 모델을 두 가지 형태로 제시했다.

- 참가자 근거: `anchor-history-001`, `anchor-history-002`
- 외부 근거: [REALM: Retrieval-Augmented Language Model Pre-Training](https://arxiv.org/abs/2002.08909), [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)

### 유형

초기 RAG는 검색된 문서를 전체 출력 또는 토큰 단위 생성에 조건으로 사용한다. Self-RAG는 필요할 때 검색하고 생성 결과를 비평하며, GraphRAG는 그래프 기반 메모리 구조를 활용한다.

- 참가자 근거: `anchor-types-001`
- 외부 근거: [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401), [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511), [Microsoft GraphRAG](https://github.com/microsoft/graphrag)

### 구현 참고

Hugging Face 연구 프로젝트에는 RAG 예제가 있고, Self-RAG 저장소는 원 논문의 구현을 제공한다. Microsoft GraphRAG 저장소는 그래프 기반 방법론의 데모 코드이며 공식 지원 제품은 아니라고 명시한다.

- 참가자 근거: `anchor-code-001`
- 외부 근거: [Hugging Face Transformers Research Projects — RAG](https://github.com/huggingface/transformers-research-projects/tree/main/rag), [Self-RAG original implementation](https://github.com/AkariAsai/self-rag), [Microsoft GraphRAG](https://github.com/microsoft/graphrag)

## 팩트체크

- **주장:** Lewis 등이 2020년 논문에서 RAG라는 명칭과 두 가지 생성 방식을 제시했다.
- **판정:** `supported`
- **설명:** 원 논문의 제목과 초록은 RAG를 명시하고, 동일 검색 문서를 전체 출력에 사용하는 방식과 토큰별로 다른 문서를 사용할 수 있는 방식을 비교한다.
- **근거:** [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)

## 프로토타입: 회의 전 RAG 브리핑 보드

- **문제:** 참가자가 서로 다른 형식으로 준비한 자료를 회의 직전에 모두 읽기 어렵다.
- **해결:** 참가자 제출만 압축한 요약과 외부 검증 자료를 분리해 보여주고, 각 항목에서 원문 또는 웹 출처로 이동하게 한다.
- **최소 구현 순서:**
  1. 네 참가자의 자료를 제출 항목과 불변 anchor로 저장한다.
  2. 참가자 원문만 사용하는 요약본을 생성한다.
  3. 외부 자료 조사와 팩트체크를 별도 조사본으로 생성한다.
  4. 모든 결과 항목에 원문 또는 웹 근거 링크를 표시한다.

## 출처 바로가기

- [REALM: Retrieval-Augmented Language Model Pre-Training](https://arxiv.org/abs/2002.08909)
- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)
- [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511)
- [Hugging Face Transformers Research Projects — RAG](https://github.com/huggingface/transformers-research-projects/tree/main/rag)
- [Self-RAG original implementation](https://github.com/AkariAsai/self-rag)
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag)

## 자동 검증 결과

- ✅ 요약 항목마다 정확한 참가자 원문 근거가 있음
- ✅ 요약본에는 웹 URL 또는 팩트체크 판정이 없음
- ✅ 조사·팩트체크 항목마다 참가자 anchor와 HTTPS 외부 근거가 있음
- ✅ 사용자 대상 결과가 한국어로 작성됨
- ✅ 외부 Provider 호출 및 credential 저장이 비활성화됨
