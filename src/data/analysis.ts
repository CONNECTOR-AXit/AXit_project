import type { AnalysisResult } from '@/types'

/** 대표 데모 프로젝트(p-1)의 AI 분석 결과. */
export const analysisResult: AnalysisResult = {
  projectId: 'p-1',
  documentCount: 5,
  commonCount: 12,
  differenceCount: 8,
  overlapRate: 87,
  completedAt: '2024-05-15T14:22:00',
  headline:
    "모든 문서가 '캠페인 목표'와 '타겟 분석'에 대해 일치하고 있으며, 예산 규모와 실행 채널에서 가장 큰 차이를 보이고 있습니다.",

  commonTopics: [
    {
      id: 'c-1',
      label: '캠페인 목표',
      matched: 5,
      total: 5,
      summary: '브랜드 인지도 향상과 신규 고객 유치를 공통 목표로 설정하고 있습니다.',
      excerpts: [
        { document: '캠페인 개요.docx', text: '브랜드 인지도 20% 향상을 1차 목표로 한다.' },
        {
          document: '채널별 홍보 전략.pdf',
          text: '신규 고객 10,000명 확보를 목표로 채널을 배분한다.',
        },
        { document: '기대 효과 및 KPI.hwp', text: '인지도 및 신규 유입이 핵심 성과 지표이다.' },
      ],
    },
    {
      id: 'c-2',
      label: '타겟 분석',
      matched: 5,
      total: 5,
      summary: '20~30대 여성, 온라인 쇼핑 및 SNS 활동이 활발한 사용자로 정의됩니다.',
      excerpts: [
        { document: '캠페인 개요.docx', text: '핵심 타겟은 20~30대 여성으로 설정한다.' },
        { document: '채널별 홍보 전략.pdf', text: 'SNS 활동량이 높은 사용자군을 우선 공략한다.' },
      ],
    },
    {
      id: 'c-3',
      label: '예산 계획',
      matched: 4,
      total: 5,
      summary: '광고비 중심의 예산 배분에 동의하나, 총액은 문서마다 다릅니다.',
      excerpts: [
        { document: '예산 계획.xlsx', text: '광고비 5,000만원, 콘텐츠 제작비 2,000만원.' },
        { document: '캠페인 개요.docx', text: '전체 예산의 절반 이상을 광고 집행에 사용한다.' },
      ],
    },
    {
      id: 'c-4',
      label: '채널 전략',
      matched: 4,
      total: 5,
      summary: '온라인 광고와 SNS를 주요 채널로 삼는 점은 공통적입니다.',
      excerpts: [
        { document: '채널별 홍보 전략.pdf', text: '인스타그램·유튜브를 주력 채널로 운영한다.' },
      ],
    },
    {
      id: 'c-5',
      label: '일정 계획',
      matched: 3,
      total: 5,
      summary: '3개월 단위 캠페인 운영을 전제로 하나, 시작 시점이 다릅니다.',
      excerpts: [
        { document: '캠페인 개요.docx', text: '6월 첫째 주 런칭을 목표로 한다.' },
        { document: '참고 자료.txt', text: '7월 성수기 직전 시작이 유리하다는 의견.' },
      ],
    },
    {
      id: 'c-6',
      label: '성과 측정 주기',
      matched: 3,
      total: 5,
      summary: '주 단위 리포팅에 대체로 합의되어 있습니다.',
      excerpts: [{ document: '기대 효과 및 KPI.hwp', text: '매주 금요일 성과 리포트를 공유한다.' }],
    },
  ],

  differences: [
    {
      id: 'df-1',
      label: '예산 규모',
      severity: 'high',
      summary: '문서마다 예산 규모와 배분 방식에 차이가 있습니다.',
      clusters: [
        { documents: ['문서 A', '문서 B'], stance: '총 1억원 규모 · 광고비 중심' },
        { documents: ['문서 C'], stance: '총 7,000만원 규모 · 콘텐츠 중심' },
        { documents: ['문서 D', '문서 E'], stance: '예산 미확정 · 단계별 집행' },
      ],
    },
    {
      id: 'df-2',
      label: '실행 채널',
      severity: 'medium',
      summary: '활용 채널과 우선순위에 차이가 있습니다.',
      clusters: [
        { documents: ['문서 A', '문서 D'], stance: 'SNS 우선 · 인스타그램 집중' },
        { documents: ['문서 B', '문서 C', '문서 E'], stance: '검색 광고 + 유튜브 병행' },
      ],
    },
    {
      id: 'df-3',
      label: '성과 지표',
      severity: 'medium',
      summary: '측정하려는 성과 지표(KPI)에 차이가 있습니다.',
      clusters: [
        { documents: ['문서 A', '문서 B'], stance: '노출수·도달률 중심' },
        { documents: ['문서 C', '문서 D'], stance: '전환율·CAC 중심' },
        { documents: ['문서 E'], stance: '브랜드 서베이 기반 인지도' },
      ],
    },
    {
      id: 'df-4',
      label: '캠페인 시작 시점',
      severity: 'low',
      summary: '런칭 시점이 6월과 7월로 갈립니다.',
      clusters: [
        { documents: ['문서 A', '문서 B', '문서 D'], stance: '6월 첫째 주 런칭' },
        { documents: ['문서 C', '문서 E'], stance: '7월 성수기 직전 런칭' },
      ],
    },
  ],

  breakdown: [
    {
      documentId: 'd-1',
      name: '캠페인 개요.docx',
      contribution: 32,
      uniqueSections: 3,
      overlapRate: 91,
      sentiment: '적극적',
      highlights: ['전체 캠페인 목표를 가장 명확히 정의', '타겟 페르소나 상세 기술'],
    },
    {
      documentId: 'd-2',
      name: '채널별 홍보 전략.pdf',
      contribution: 24,
      uniqueSections: 5,
      overlapRate: 84,
      sentiment: '적극적',
      highlights: ['채널별 예상 성과 수치 포함', '경쟁사 채널 운영 사례 인용'],
    },
    {
      documentId: 'd-3',
      name: '예산 계획.xlsx',
      contribution: 20,
      uniqueSections: 4,
      overlapRate: 76,
      sentiment: '보수적',
      highlights: ['항목별 예산 표 제공', '예비비 10% 편성 제안'],
    },
    {
      documentId: 'd-4',
      name: '기대 효과 및 KPI.hwp',
      contribution: 16,
      uniqueSections: 2,
      overlapRate: 88,
      sentiment: '중립적',
      highlights: ['KPI 정의가 가장 구체적', '측정 주기 명시'],
    },
    {
      documentId: 'd-5',
      name: '참고 자료.txt',
      contribution: 8,
      uniqueSections: 1,
      overlapRate: 62,
      sentiment: '중립적',
      highlights: ['외부 시장 데이터 인용', '런칭 시점에 대한 반대 의견 포함'],
    },
  ],

  keywords: [
    { term: '브랜드 인지도', weight: 98, documents: 5, trend: 'up' },
    { term: '신규 고객', weight: 92, documents: 5, trend: 'up' },
    { term: 'SNS 마케팅', weight: 86, documents: 4, trend: 'up' },
    { term: '전환율', weight: 74, documents: 4, trend: 'flat' },
    { term: '광고 예산', weight: 71, documents: 5, trend: 'down' },
    { term: '타겟 페르소나', weight: 68, documents: 3, trend: 'up' },
    { term: '콘텐츠 제작', weight: 61, documents: 4, trend: 'flat' },
    { term: '인플루언서', weight: 54, documents: 2, trend: 'up' },
    { term: '리타게팅', weight: 47, documents: 2, trend: 'flat' },
    { term: 'CAC', weight: 43, documents: 2, trend: 'down' },
    { term: '성수기', weight: 38, documents: 3, trend: 'flat' },
    { term: '예비비', weight: 24, documents: 1, trend: 'flat' },
  ],

  insights: [
    {
      id: 'i-1',
      tone: 'positive',
      title: '목표와 타겟은 완전히 일치합니다',
      body: '5개 문서 전부가 브랜드 인지도 향상과 20~30대 여성 타겟을 동일하게 정의하고 있습니다. 이 두 항목은 별도 조율 없이 통합 문서에 그대로 반영해도 안전합니다.',
    },
    {
      id: 'i-2',
      tone: 'caution',
      title: '예산 규모는 합의가 필요합니다',
      body: '총 예산이 7,000만원에서 1억원까지 3배 가까이 벌어져 있습니다. 통합 문서에는 평균값을 임시 반영했으니, 확정 전 담당자 확인을 권장합니다.',
    },
    {
      id: 'i-3',
      tone: 'neutral',
      title: 'KPI 정의를 하나로 모으면 좋겠습니다',
      body: '노출수 중심과 전환율 중심 지표가 혼재되어 있습니다. 두 지표를 1차·2차 KPI로 계층화하면 대부분의 차이가 해소됩니다.',
    },
  ],
}

/** AI 분석 진행 5단계. endsAt 은 해당 단계가 끝나는 전체 진행률(%). */
export const analysisSteps = [
  { id: 'upload', label: '문서 업로드', caption: '파일을 안전하게 저장했어요', endsAt: 12 },
  { id: 'extract', label: '내용 추출', caption: '문서에서 텍스트와 표를 읽는 중', endsAt: 38 },
  { id: 'common', label: '공통점 분석', caption: '문서 간 겹치는 내용을 찾는 중', endsAt: 62 },
  { id: 'difference', label: '차이점 분석', caption: '상충하는 서술을 비교하는 중', endsAt: 84 },
  { id: 'merge', label: '통합 문서 생성', caption: '하나의 문서로 재구성하는 중', endsAt: 100 },
] as const

export type AnalysisStepId = (typeof analysisSteps)[number]['id']
