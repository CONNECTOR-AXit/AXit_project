import Upload from './Upload'

/**
 * 이미 분석이 끝난 프로젝트에 자료를 더하는 화면 — /projects/:projectId/augment.
 * 이 라우트에 도착한 시점엔 세션이 이미 재분석/증강 버튼 클릭으로 reopen되어
 * 있으므로, 업로드 화면과 동일한 흐름(문서 큐, 분석 시작)을 그대로 재사용하고
 * 문구만 "증강" 맥락으로 바꿉니다.
 */
export default function Augment() {
  return <Upload mode="augment" />
}
