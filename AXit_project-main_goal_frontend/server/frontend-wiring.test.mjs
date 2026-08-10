import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

const source = (relative) =>
  readFile(new URL(`../src/${relative}`, import.meta.url), "utf8");
const generatedClient = () =>
  readFile(new URL("../../packages/api-client/src/generated.ts", import.meta.url), "utf8");

describe("G006 server-backed frontend wiring", () => {
  it("uses generated operation paths for every new recipient-owned API", async () => {
    const queries = await source("api/queries.ts");
    for (const operation of [
      "listNotifications", "readNotification", "readAllNotifications",
      "listAuditEvents", "listMyEmailOutbox", "getMyProfile", "updateProfile",
      "getMyNotificationPreferences", "updateNotificationPreferences",
      "listSessionComments", "createComment", "updateComment", "deleteComment",
    ]) assert.match(queries, new RegExp(`operationPath\\('${operation}'`));
    const notificationHook = queries.slice(queries.indexOf("export function useNotifications"), queries.indexOf("export function useNotificationReadActions"));
    assert.doesNotMatch(notificationHook, /refetchInterval|localStorage/);
    assert.match(notificationHook, /unreadCount: firstPage\.unread_count/);
    assert.match(queries, /collectCursorPages/);
    assert.match(queries, /item\.actor_display_name\?\.trim\(\) \|\| \(item\.actor_id \? '삭제된 사용자' : '시스템'\)/);
    for (const pageType of ["AuditEventPageResponse", "NotificationPageResponse", "EmailOutboxPageResponse", "CommentPageResponse"])
      assert.match(queries, new RegExp(`get<${pageType}>[\\s\\S]{0,250}cursor`));
    assert.match(queries, /seenCursors\.has\(page\.next_cursor\)/);
  });

  it("keeps every manually exposed frontend path equal to the generated operation value", async () => {
    const client = await source("api/client.ts");
    const generated = await generatedClient();
    const exposed = client.slice(
      client.indexOf("const operationPaths ="),
      client.indexOf("export function operationPath"),
    );
    const manual = new Map(
      [...exposed.matchAll(/^\s{2}(\w+): '([^']+)',$/gm)].map((match) => [match[1], match[2]]),
    );
    const operations = new Map(
      [...generated.matchAll(/^\s{2}"([^"]+)": \{ method: "[A-Z]+", path: "([^"]+)" \},$/gm)]
        .map((match) => [match[1], match[2].replace(/^\/api/, "")]),
    );
    assert.ok(manual.size > 0);
    for (const [operation, path] of manual) assert.equal(path, operations.get(operation), operation);
  });

  it("keeps audit ordering and forward-only coverage truthful", async () => {
    const history = await source("pages/History.tsx");
    assert.match(history, /b\.ledgerSequence - a\.ledgerSequence/);
    assert.match(history, /그 이전 활동은 이 목록이 완전하지 않을 수 있습니다/);
    assert.doesNotMatch(history, /userByName|new Date\(b\.createdAt\)|new Map<string, HistoryEntry\[\]>/);
    assert.match(history, /entries\.map\(\(entry, index\)/);
  });

  it("shows weekday project integration completion rates as a fixed-scale bar chart", async () => {
    const dashboard = await source("pages/Dashboard.tsx");
    const queries = await source("api/queries.ts");
    const chart = await source("components/charts/ProjectCompletionBarChart.tsx");
    assert.match(dashboard, /title="프로젝트 통합 완료율"/);
    assert.match(dashboard, /<ProjectCompletionBarChart data=\{data\.projectCompletionByWeekday\}/);
    assert.match(queries, /WEEKDAY_LABELS = \['월', '화', '수', '목', '금', '토', '일'\] as const/);
    assert.match(queries, /projectCompletionByWeekday: buildProjectCompletionByWeekday\(recentProjects\)/);
    assert.match(chart, /<XAxis dataKey="label"/);
    assert.match(chart, /ticks=\{INTEGRATION_PROGRESS_STEPS\}/);
    assert.match(chart, /domain=\{\[0, 100\]\}/);
    assert.match(chart, /<Bar[\s\S]*dataKey="progress"/);
    assert.doesNotMatch(dashboard, /data\.projectCompletion\.map/);
  });

  it("links the navigation brand to the dashboard root", async () => {
    const sidebar = await source("components/layout/Sidebar.tsx");
    const landing = await source("pages/Landing.tsx");
    assert.match(sidebar, /<Link[\s\S]{0,80}to="\/"[\s\S]{0,260}<Logo compact=\{collapsed\} \/>/);
    assert.match(sidebar, /aria-label="AXit 홈으로 이동"/);
    assert.match(landing, /<Link[\s\S]{0,80}to="\/"[\s\S]{0,220}<Logo \/>/);
  });

  it("shows role-specific working project removal actions", async () => {
    const projects = await source("pages/Projects.tsx");
    const card = await source("components/project/ProjectCard.tsx");
    const queries = await source("api/queries.ts");
    assert.match(projects, /useProjectMembershipActions\(\)/);
    assert.match(card, /project\.currentUserRole === 'owner'/);
    assert.match(card, /프로젝트 제거하기/);
    assert.match(card, /프로젝트 탈퇴/);
    assert.match(queries, /operationPath\('archiveTalkSession'/);
    assert.match(queries, /operationPath\('leaveRoom'/);
    assert.match(queries, /mutate<BackendRoom>\('post', '\/rooms', \{ name \}\)/);
    assert.doesNotMatch(queries, /targetRoom = rooms\[0\]/);
  });

  it("exports the current merged document as Markdown", async () => {
    const markdown = await source("lib/markdown.ts");
    const editor = await source("pages/Editor.tsx");
    const result = await source("pages/AnalysisResult.tsx");
    const detail = await source("pages/ProjectDetail.tsx");
    assert.match(markdown, /mergedDocumentToMarkdown/);
    assert.match(markdown, /text\/markdown;charset=utf-8/);
    assert.match(markdown, /\.md/);
    assert.match(markdown, /case 'heading'/);
    assert.match(markdown, /case 'table'/);
    assert.match(editor, /downloadMergedDocument\(doc\)/);
    assert.match(result, /downloadMergedDocument\(mergedDocumentData\.document\)/);
    assert.match(detail, /downloadMergedDocument\(mergedDocumentData\.document\)/);
    assert.doesNotMatch(editor, /다운로드 · 범위 외/);
    assert.doesNotMatch(result, /내보내기 · 범위 외/);
    assert.doesNotMatch(detail, /내보내기 · 범위 외/);
  });

  it("offers the merged document directly beside the analysis tabs", async () => {
    const result = await source("pages/AnalysisResult.tsx");
    assert.match(result, /\{ value: 'summary', label: '요약' \},\s*\{ value: 'merged-document', label: '통합 문서' \}/);
    assert.match(result, /<TabsContent value="merged-document">/);
    assert.match(result, /onSelectRagAnchor=\{setSelectedRagAnchorId\}/);
    assert.match(result, /ragAnchorLabels=\{ragAnchorLabels\}/);
    assert.match(result, /buildRagAnchorLabels\(mergedDocumentData\.document\.blocks\)/);
    assert.match(result, /for \(const anchorId of anchorIds\)/);
    assert.match(result, /api\.get<[\s\S]{0,180}`\/source-anchors\/\$\{anchorId\}\/resolve`/);
    assert.match(result, /document\.revisionId === target\.source_revision_id/);
    assert.doesNotMatch(result, /Promise\.all\([\s\S]{0,500}source-anchors/);
    assert.match(result, /<RagEvidenceDialog[\s\S]{0,240}anchorId=\{selectedRagAnchorId\}/);
    assert.match(result, /<DocumentPreviewDialog[\s\S]{0,160}target=\{originalPreview\}/);
    assert.match(result, /to=\{`\/projects\/\$\{projectId\}\/editor`\}[\s\S]{0,160}편집하기/);
  });

  it("hydrates versioned settings and labels local-only email intent exactly", async () => {
    const settings = await source("pages/Settings.tsx");
    assert.match(settings, /expected_version: profile\.data\.profile_version/);
    assert.match(settings, /expected_version: preferences\.data\.preferences_version/);
    assert.match(settings, /setProfileDraft\(\{ display_name: profile\.data\.display_name/);
    assert.match(settings, /structuredClone\(preferences\.data\.values\)/);
    assert.match(settings, /로컬 큐에만 저장되었으며 외부로 발송되지 않았습니다/);
    assert.match(settings, /value=\{profile\.data\.email\} readOnly disabled aria-readonly="true"/);
    assert.doesNotMatch(settings, /setProfileDraft\(\{[^}]*email/);
  });

  it("uses member UUIDs and versioned comment CRUD without realtime claims", async () => {
    const editor = await source("pages/Editor.tsx");
    assert.match(editor, /value=\{member\.id\}/);
    assert.match(editor, /mentioned_user_ids/);
    assert.match(editor, /expected_version: comment\.version/);
    assert.match(editor, /commentActions\.(create|update|remove)/);
    assert.match(editor, /useState\(\(\) => crypto\.randomUUID\(\)\)/);
    assert.match(editor, /client_request_id: commentRequestId/);
    assert.match(editor, /commentActions\.create\.isError/);
    assert.match(editor, /projectQuery\.(isLoading|isError)/);
    assert.match(editor, /commentActions\.(update|remove)\.isPending/);
    assert.doesNotMatch(editor, /documentComments|typing|presence|WebSocket/);
  });

  it("runs grounded Grok edit tasks below the document outline", async () => {
    const editor = await source("pages/Editor.tsx");
    const editAgent = await source("components/editor/GrokEditAgent.tsx");
    const queries = await source("api/queries.ts");
    assert.match(editor, /<OutlinePanel[\s\S]{0,900}<GrokEditAgent/);
    assert.match(editor, /onSuggestionsCreated=\{refreshGrokSuggestions\}/);
    assert.match(queries, /\/sessions\/\$\{projectId\}\/grok-edit-suggestions/);
    assert.match(editAgent, /AI에게 수정 요청/);
    assert.doesNotMatch(editAgent, /Grok에게 수정 요청/);
    assert.doesNotMatch(editor, /WebSocket|실시간 채팅/);
  });

  it("removes virtual markdown markers before handling a line-start Backspace", async () => {
    const editor = await source("components/upload/NotionTextEditor.tsx");
    assert.match(editor, /const activeMarkerLength = markerLenOf\(lineDivs\[lineIndex\]\)/);
    assert.match(editor, /if \(activeMarkerLength > 0\) \{[\s\S]{0,700}event\.preventDefault\(\)/);
    assert.match(editor, /const lines = lineDivs\.map\(lineText\)/);
    assert.match(editor, /lines\[lineIndex\] = currentText\.slice\(activeMarkerLength\)/);
    assert.match(editor, /setCaretWithin\(rebuilt\[lineIndex\], 0\)/);
  });

  it("disables reviewed non-goals instead of accepting ignored input", async () => {
    const dialog = await source("components/project/NewProjectDialog.tsx");
    const progress = await source("components/dashboard/AiProgressPanel.tsx");
    const detail = await source("pages/ProjectDetail.tsx");
    const documents = await source("components/project/DocumentTable.tsx");
    // 업로드 후 자동 분석 토글은 비활성 표시가 아니라 아예 제거됐습니다
    // (기능이 없으면 화면에 남기지 않는 게 낫다는 명시적 제품 결정).
    assert.doesNotMatch(dialog, /setAutoAnalyze|onCheckedChange=\{setAutoAnalyze\}|자동 분석/);
    assert.match(progress, /플랜 관리 · 범위 외/);
    assert.match(detail, /멤버 초대 · 범위 외/);
    assert.match(documents, /title="원본 다운로드"/);
    assert.doesNotMatch(documents, /다운로드 \(범위 외\)|다운로드 · 범위 외/);
    assert.match(documents, /\$\{doc\.name\} 미리보기/);
    assert.match(documents, /\$\{doc\.name\} 삭제/);
    assert.doesNotMatch(documents, /MoreHorizontal|<DropdownMenu/);
  });

  it("opens the Grok summary for an analyzed uploaded document", async () => {
    const table = await source("components/project/DocumentTable.tsx");
    const dialog = await source("components/project/DocumentSummaryDialog.tsx");
    assert.match(table, /doc\.status === 'analyzed'/);
    assert.match(table, /Grok 요약 보기/);
    assert.match(table, /<DocumentSummaryDialog/);
    assert.match(dialog, /\/sessions\/\$\{document\.projectId\}\/summary/);
    assert.match(dialog, /\/source-anchors\/\$\{anchorId\}\/resolve/);
    assert.match(dialog, /target\.source_revision_id === document\.revisionId/);
    assert.match(dialog, /Grok 문서 요약/);
  });

  it("keeps upload progress separate from Grok analysis", async () => {
    const upload = await source("pages/Upload.tsx");
    const queue = await source("hooks/useUploadQueue.ts");
    const list = await source("components/upload/UploadList.tsx");
    assert.match(upload, /이 단계에서는 파일만 업로드합니다\. Grok은 실행되지 않으며/);
    assert.match(upload, /AI 분석 시작 버튼을[\s\S]{0,80}이후에만/);
    assert.match(queue, /const isReadyImmediately = meta\?\.submissionKind === 'text'/);
    assert.match(queue, /progress: isReadyImmediately \? 100 : 50/);
    assert.match(queue, /status: isReadyImmediately \? 'analyzed' : 'queued'/);
    assert.match(list, /return '업로드 완료'/);
    assert.doesNotMatch(list, /return '분석 완료'/);
    assert.match(upload, /item\.status === 'analyzed' && Boolean\(item\.revisionId\)/);
    assert.match(upload, /item\.status === 'queued' \|\| item\.status === 'uploading'/);
    assert.match(upload, /const canAnalyze = readyCount >= 2 && !isUploading && !isProcessing/);
    assert.doesNotMatch(upload, /const extractionReady/);
  });

  it("collapses and expands the direct-write upload block", async () => {
    const upload = await source("pages/Upload.tsx");
    assert.match(upload, /useState\(true\)/);
    assert.match(upload, /aria-expanded=\{isDirectWriteOpen\}/);
    assert.match(upload, /aria-controls="direct-write-content"/);
    assert.match(upload, /setIsDirectWriteOpen\(\(open\) => !open\)/);
    assert.match(upload, /hidden=\{!isDirectWriteOpen\}/);
    assert.match(upload, /문서 직접 작성 접기/);
    assert.match(upload, /문서 직접 작성 펼치기/);
  });

  it("downloads originals and confirms document deletion from project detail", async () => {
    const detail = await source("pages/ProjectDetail.tsx");
    const table = await source("components/project/DocumentTable.tsx");
    assert.match(detail, /useDeleteSubmission\(projectId \?\? ''\)/);
    assert.match(detail, /onDelete=\{\(submissionId\) => deleteSubmission\.mutateAsync\(submissionId\)\}/);
    assert.match(table, /\/source-revisions\/\$\{doc\.revisionId\}\/original/);
    assert.match(table, /responseType: 'blob'/);
    assert.match(table, /link\.download = filename/);
    assert.match(table, /문서를 정말 삭제하시겠습니까/);
    assert.match(table, /되돌릴 수 없습니다/);
    assert.match(table, /await onDelete\(deleteTarget\.id\)/);
  });

  it("clears query and legacy user-scoped state on auth boundaries", async () => {
    const auth = await source("hooks/useAuth.tsx");
    const client = await source("api/client.ts");
    assert.ok((auth.match(/queryClient\.clear\(\)/g) ?? []).length >= 3);
    assert.match(client, /clearUserScopedClientState\(\)/);
    assert.match(client, /removeItem\('axit\.read-notification-ids'\)/);
  });
});
