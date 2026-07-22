import type { AiSuggestion, DocumentComment, DocumentVersion, MergedDocument } from '@/types'

/** 에디터에서 여는 통합 문서. */
export const mergedDocument: MergedDocument = {
  id: 'm-1',
  projectId: 'p-1',
  title: '마케팅 캠페인 기획안 (통합 문서)',
  updatedAt: '2024-05-15T14:32:00',
  wordCount: 2480,
  version: 'v1.4',
  blocks: [
    { id: 'b-1', type: 'heading', level: 2, text: '1. 캠페인 개요' },
    {
      id: 'b-2',
      type: 'paragraph',
      text: '본 캠페인은 브랜드 인지도 향상과 신규 고객 유치를 목표로 진행됩니다. 5개 부서에서 작성한 기획안의 공통 내용을 기준으로 재구성했습니다.',
      tag: '통합',
    },
    { id: 'b-3', type: 'heading', level: 2, text: '2. 캠페인 목표 (공통)' },
    {
      id: 'b-4',
      type: 'list',
      tag: '공통',
      items: ['브랜드 인지도 20% 향상', '신규 고객 10,000명 확보', '고객 참여율 15% 달성'],
    },
    { id: 'b-5', type: 'heading', level: 2, text: '3. 타겟 분석 (공통)' },
    {
      id: 'b-6',
      type: 'list',
      tag: '공통',
      items: [
        '20~30대 여성',
        '온라인 쇼핑 및 SNS 활동이 활발한 사용자',
        '가격보다 브랜드 경험을 중시하는 소비층',
      ],
    },
    { id: 'b-7', type: 'heading', level: 2, text: '4. 예산 계획 (통합)' },
    {
      id: 'b-8',
      type: 'table',
      tag: '차이 조정',
      columns: ['항목', '예산(평균)', '주요 내용'],
      rows: [
        ['광고비', '5,000만원', '온라인 광고 집행'],
        ['콘텐츠 제작비', '2,000만원', '이미지, 영상 콘텐츠 제작'],
        ['프로모션 비용', '1,500만원', '이벤트 및 할인 프로모션'],
        ['예비비', '850만원', '집행 편차 대응'],
      ],
    },
    {
      id: 'b-9',
      type: 'callout',
      tag: 'AI 보완',
      text: '문서마다 총 예산이 7,000만원 ~ 1억원으로 상이합니다. 위 표에는 평균값을 반영했으며, 확정 전 담당자 검토가 필요합니다.',
    },
    { id: 'b-10', type: 'heading', level: 2, text: '5. 실행 채널 전략' },
    {
      id: 'b-11',
      type: 'paragraph',
      tag: '차이 조정',
      text: 'SNS(인스타그램·유튜브)를 1차 채널로, 검색 광고를 2차 채널로 운영합니다. 채널 우선순위에 이견이 있어 성과 데이터 기반으로 4주 후 재조정합니다.',
    },
    { id: 'b-12', type: 'heading', level: 2, text: '6. 일정 계획' },
    {
      id: 'b-13',
      type: 'list',
      tag: '통합',
      items: [
        '5월 4주차 — 크리에이티브 제작 완료',
        '6월 1주차 — 캠페인 런칭',
        '6월 ~ 8월 — 주간 성과 리포팅 및 최적화',
      ],
    },
    { id: 'b-14', type: 'heading', level: 2, text: '7. 성과 지표' },
    {
      id: 'b-15',
      type: 'paragraph',
      tag: 'AI 보완',
      text: '1차 KPI는 노출수·도달률, 2차 KPI는 전환율·CAC로 계층화하여 문서 간 지표 정의 차이를 해소했습니다.',
    },
  ],
}

/** 에디터 우측 레일에 표시되는 AI 추천. */
export const aiSuggestions: AiSuggestion[] = [
  {
    id: 's-1',
    kind: 'add',
    title: '캠페인 일정 섹션 추가를 제안해요.',
    detail: '문서 B와 D에만 존재하는 상세 일정표가 통합 문서에 빠져 있습니다.',
    targetSection: '6. 일정 계획',
  },
  {
    id: 's-2',
    kind: 'add',
    title: '성과 지표 항목을 보완해보세요.',
    detail: 'CAC 산출 기준이 명시되어 있지 않아 측정이 어려울 수 있습니다.',
    targetSection: '7. 성과 지표',
  },
  {
    id: 's-3',
    kind: 'edit',
    title: '문장 표현을 더 간결하게 수정할 수 있어요.',
    detail: "'본 캠페인은 ~를 목표로 진행됩니다' → '본 캠페인의 목표는 ~입니다'",
    targetSection: '1. 캠페인 개요',
  },
  {
    id: 's-4',
    kind: 'edit',
    title: '용어 통일을 제안해요.',
    detail: "'고객 확보' → '신규 고객 확보' 로 4곳을 일괄 변경합니다.",
    targetSection: '2. 캠페인 목표',
  },
  {
    id: 's-5',
    kind: 'remove',
    title: '중복된 내용이 있어 삭제를 제안해요.',
    detail: "'타겟 분석' 섹션의 2번째 문단이 1번째 문단과 92% 중복됩니다.",
    targetSection: '3. 타겟 분석',
  },
]

/** 버전 히스토리. */
export const documentVersions: DocumentVersion[] = [
  {
    id: 'v-5',
    label: 'v1.4',
    author: '김AXit',
    createdAt: '2024-05-15T14:32:00',
    summary: '예산 표에 예비비 항목 추가',
    current: true,
  },
  {
    id: 'v-4',
    label: 'v1.3',
    author: '이영희',
    createdAt: '2024-05-15T13:05:00',
    summary: '실행 채널 전략 문단 재작성',
  },
  {
    id: 'v-3',
    label: 'v1.2',
    author: 'AXit AI',
    createdAt: '2024-05-15T11:40:00',
    summary: 'KPI 계층화 제안 반영',
  },
  {
    id: 'v-2',
    label: 'v1.1',
    author: '박민수',
    createdAt: '2024-05-15T10:12:00',
    summary: '타겟 분석 중복 문단 정리',
  },
  {
    id: 'v-1',
    label: 'v1.0',
    author: 'AXit AI',
    createdAt: '2024-05-15T09:30:00',
    summary: '5개 문서 기반 통합 문서 최초 생성',
  },
]

/** 문서 댓글. section 은 mergedDocument 의 heading 텍스트와 일치시킵니다. */
export const documentComments: DocumentComment[] = [
  {
    id: 'dc-1',
    author: '박민수',
    section: '4. 예산 계획 (통합)',
    body: '예비비 비율을 10%로 올리는 게 안전해 보입니다.',
    createdAt: '2024-05-15T13:48:00',
  },
  {
    id: 'dc-2',
    author: '이영희',
    section: '5. 실행 채널 전략',
    body: '채널 우선순위는 첫 성과 리포트 이후 다시 정하는 걸로 할까요?',
    createdAt: '2024-05-15T11:22:00',
  },
  {
    id: 'dc-3',
    author: '최지우',
    section: '7. 성과 지표',
    body: 'CAC 산출식이 문서마다 달라서 정의를 붙여두면 좋겠어요.',
    createdAt: '2024-05-14T17:05:00',
  },
]

/** 통합 문서에 반영된 원본 문서별 비중. */
export const documentSources = [
  { name: '캠페인 개요.docx', percent: 32 },
  { name: '채널별 홍보 전략.pdf', percent: 24 },
  { name: '예산 계획.xlsx', percent: 20 },
  { name: '기대 효과 및 KPI.hwp', percent: 16 },
  { name: '참고 자료.txt', percent: 8 },
] as const
