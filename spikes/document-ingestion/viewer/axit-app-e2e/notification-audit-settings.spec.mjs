import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { evidenceDirectory } from "./evidence-reporter.mjs";

test.describe.configure({ mode: "serial" });
const shots = {
  settings: path.join(evidenceDirectory, "alice-settings-relogin.png"),
  comment: path.join(evidenceDirectory, "bob-comment-mention.png"),
  outbox: path.join(evidenceDirectory, "alice-notifications-outbox.png"),
  evidence: path.join(evidenceDirectory, "alice-notifications-history-outbox.png"),
  denied: path.join(evidenceDirectory, "eve-access-denied.png"),
};

function makeAccount(role, suffix, password) {
  return {
    name: `${role}-${suffix}`,
    email: `${role.toLowerCase()}-${suffix}@notification-audit.invalid`,
    password,
  };
}

function runStaleCompletionProbe(sessionId, recipientIds) {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuid.test(sessionId) || recipientIds.length !== 2 || recipientIds.some((id) => !uuid.test(id))) {
    throw new Error("stale probe identifiers are invalid");
  }
  const root = process.env.AXIT_N4_ROOT;
  const manifest = process.env.AXIT_N4_MANIFEST;
  const uv = process.env.AXIT_N4_PROBE_UV;
  const script = process.env.AXIT_N4_PROBE_SCRIPT;
  if (![root, manifest, uv, script].every((value) => value && path.isAbsolute(value))) {
    throw new Error("stale probe lifecycle environment is invalid");
  }
  const result = spawnSync(
    uv,
    [
      "run", "python", script, "probe-stale", "--root", root, "--manifest", manifest,
      "--session-id", sessionId,
      "--recipient-id", recipientIds[0],
      "--recipient-id", recipientIds[1],
    ],
    { cwd: root, encoding: "utf8", timeout: 30_000, windowsHide: true },
  );
  if (result.status !== 0) throw new Error("owned stale probe failed");
  const value = JSON.parse(result.stdout);
  expect(value).toEqual({ stale: true, in_app_rows: 0, outbox_rows: 0 });
  return value;
}

async function register(page, user) {
  await page.goto("/signup");
  await page.getByLabel("이름").fill(user.name);
  await page.getByLabel("이메일").fill(user.email);
  await page.getByLabel("비밀번호", { exact: true }).fill(user.password);
  await page.getByLabel("비밀번호 확인").fill(user.password);
  const response = page.waitForResponse((r) => r.url().endsWith("/api/auth/register") && r.status() === 201);
  await page.getByRole("button", { name: "회원가입" }).click();
  const result = await response;
  await expect(page).toHaveURL(/\/login$/);
  return result.json();
}

async function login(page, user) {
  await page.goto("/login");
  await page.getByLabel("이메일").fill(user.email);
  await page.getByLabel("비밀번호").fill(user.password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function logout(page) {
  if (!(await page.getByRole("button", { name: "프로필 메뉴" }).count())) return;
  await page.getByRole("button", { name: "프로필 메뉴" }).click();
  const response = page.waitForResponse((r) => r.url().endsWith("/api/auth/logout") && r.status() === 204);
  await page.getByRole("menuitem", { name: "로그아웃" }).click();
  await response;
  await expect(page).toHaveURL(/\/landing$/);
}

async function api(page, method, apiPath, body) {
  return page.evaluate(async ({ method, apiPath, body }) => {
    const headers = { "Content-Type": "application/json" };
    if (method !== "GET") {
      const csrfResponse = await fetch("/api/csrf", { credentials: "include" });
      if (!csrfResponse.ok) throw new Error(`csrf failed ${csrfResponse.status}`);
      headers["X-CSRF-Token"] = (await csrfResponse.json()).csrf_token;
    }
    const response = await fetch(`/api${apiPath}`, {
      method, credentials: "include", headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    const value = text ? JSON.parse(text) : null;
    if (!response.ok) throw new Error(`${method} ${apiPath}: ${response.status} ${text}`);
    return { status: response.status, value };
  }, { method, apiPath, body });
}

async function setSwitch(row, index) {
  const control = row.getByRole("switch").nth(index);
  if ((await control.getAttribute("aria-checked")) !== "true") await control.click();
  await expect(control).toHaveAttribute("aria-checked", "true");
}

async function closeWithInFlightRetry(page, sessionId) {
  return page.evaluate(async (id) => {
    const csrfResponse = await fetch("/api/csrf", { credentials: "include" });
    if (!csrfResponse.ok) throw new Error(`csrf failed ${csrfResponse.status}`);
    const csrf = await csrfResponse.json();
    const request = (suffix, body) => fetch(`/api/sessions/${id}/${suffix}`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf.csrf_token,
      },
      body: JSON.stringify(body),
    });

    const closePromise = request("close", { exclusions: [] });
    let retryValue;
    for (let attempt = 0; attempt < 50 && retryValue === undefined; attempt += 1) {
      const response = await request("retry", {});
      const value = await response.json();
      if (response.ok) retryValue = value;
      else if (response.status !== 409) throw new Error(`retry failed ${response.status}`);
      else await new Promise((resolve) => setTimeout(resolve, 5));
    }
    const closeResponse = await closePromise;
    if (!closeResponse.ok) throw new Error(`close failed ${closeResponse.status}`);
    if (retryValue === undefined) throw new Error("generation completed before in-flight retry was observed");
    return { close: await closeResponse.json(), retry: retryValue };
  }, sessionId);
}

test("G007 public UI and API notification audit evidence", async ({ page, baseURL }) => {
  fs.mkdirSync(evidenceDirectory, { recursive: true });
  for (const target of Object.values(shots)) fs.rmSync(target, { force: true });
  const allowedOrigin = new URL(baseURL).origin;
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (["http:", "https:"].includes(url.protocol) && url.origin !== allowedOrigin) return route.abort("blockedbyclient");
    return route.continue();
  });

  const suffix = crypto.randomUUID().replaceAll("-", "").slice(0, 12);
  const password = `N4-${crypto.randomBytes(18).toString("base64url")}`;
  const alice = makeAccount("Alice", suffix, password);
  const bob = makeAccount("Bob", suffix, password);
  const eve = makeAccount("Eve", suffix, password);
  let loggedIn = false;
  let session;

  try {
    const aliceRecord = await register(page, alice);
    const bobRecord = await register(page, bob);
    await register(page, eve);

    await login(page, alice); loggedIn = true;
    await page.goto("/settings");
    await page.getByLabel("이름").fill(`${alice.name}-persisted`);
    await page.getByLabel("직무").fill("감사 검증 담당");
    await page.getByRole("button", { name: "변경사항 저장" }).first().click();
    await expect(page.getByRole("status")).toHaveText("서버에 저장되었습니다.");
    await page.getByRole("tab", { name: "알림", exact: true }).click();
    for (const label of ["AI 분석 완료", "멘션", "댓글"]) {
      const row = page.getByText(label, { exact: true }).locator("..");
      await setSwitch(row, 0); await setSwitch(row, 1);
    }
    await page.getByRole("button", { name: "변경사항 저장" }).last().click();
    await expect(page.getByRole("status")).toHaveText("서버에 저장되었습니다.");
    await logout(page); loggedIn = false;

    await login(page, alice); loggedIn = true;
    await page.goto("/settings");
    await expect(page.getByLabel("이름")).toHaveValue(`${alice.name}-persisted`);
    await expect(page.getByLabel("직무")).toHaveValue("감사 검증 담당");
    await page.getByRole("tab", { name: "알림", exact: true }).click();
    for (const label of ["AI 분석 완료", "멘션", "댓글"]) {
      const row = page.getByText(label, { exact: true }).locator("..");
      await expect(row.getByRole("switch").nth(0)).toHaveAttribute("aria-checked", "true");
      await expect(row.getByRole("switch").nth(1)).toHaveAttribute("aria-checked", "true");
    }
    await page.screenshot({ path: shots.settings, fullPage: true });
    await page.getByRole("tab", { name: "범위 외 기능" }).click();
    for (const label of ["프로필 이미지 변경", "AI 동작 개인화", "플랜·결제·사용량", "공개 공유"]) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
    await logout(page); loggedIn = false;

    await login(page, bob); loggedIn = true;
    await api(page, "POST", "/friend-requests", { addressee_id: aliceRecord.id });
    await logout(page); loggedIn = false;
    await login(page, alice); loggedIn = true;
    await page.goto("/notifications");
    await expect(page.getByRole("button", { name: "수락" })).toBeVisible();
    const accepted = page.waitForResponse((r) => /\/api\/friend-requests\/.+\/accept$/.test(r.url()) && r.ok());
    await page.getByRole("button", { name: "수락" }).click(); await accepted;
    const room = (await api(page, "POST", "/rooms", { name: `N4-${suffix}` })).value;
    await api(page, "POST", `/rooms/${room.id}/invitations`, { invitee_id: bobRecord.id });
    session = (await api(page, "POST", `/rooms/${room.id}/sessions`, {
      topic: `Notification audit ${suffix}`, description: "Disposable G007 browser evidence",
    })).value;
    for (const [index, text] of ["회의 목표는 알림과 감사 원장을 검증하는 것입니다.", "분석 결과는 참가자 근거를 포함합니다."].entries()) {
      await api(page, "POST", `/sessions/${session.id}/submissions/text`, { title: `G007 source ${index + 1}`, text });
    }
    const closeRetry = await closeWithInFlightRetry(page, session.id);
    expect(closeRetry.close.state).toBe("processing");
    expect(closeRetry.retry).toEqual({ snapshot_id: closeRetry.close.snapshot_id, state: "processing" });
    await expect.poll(async () => (await api(page, "GET", `/sessions/${session.id}`)).value.state, { timeout: 60_000 }).toBe("ready");
    const analysisFor = async () => (await api(page, "GET", "/notifications?limit=100")).value.items.filter(
      (item) => item.kind === "analysis_completed" && item.resource_id === session.id,
    );
    const analysisOutboxFor = async () => (await api(page, "GET", "/me/email-outbox?limit=100")).value.items.filter(
      (item) => item.notification_kind === "analysis_completed" && item.template_data.session_id === session.id,
    );
    expect(await analysisFor()).toHaveLength(1);
    expect(await analysisOutboxFor()).toHaveLength(1);
    expect((await api(page, "POST", `/sessions/${session.id}/close`, { exclusions: [] })).value.idempotent).toBe(true);
    expect(await analysisFor()).toHaveLength(1);
    const completedRetry = await page.evaluate(async (sessionId) => {
      const csrfResponse = await fetch("/api/csrf", { credentials: "include" });
      const csrf = await csrfResponse.json();
      const response = await fetch(`/api/sessions/${sessionId}/retry`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf.csrf_token,
        },
        body: "{}",
      });
      return { status: response.status, value: await response.json() };
    }, session.id);
    expect(completedRetry).toMatchObject({ status: 409, value: { code: "conflict" } });
    expect(await analysisFor()).toHaveLength(1);
    expect(await analysisOutboxFor()).toHaveLength(1);
    await logout(page); loggedIn = false;

    await login(page, bob); loggedIn = true;
    expect((await api(page, "GET", "/notifications?limit=100")).value.items.filter(
      (item) => item.kind === "analysis_completed" && item.resource_id === session.id,
    )).toHaveLength(1);
    await logout(page); loggedIn = false;

    expect(runStaleCompletionProbe(session.id, [aliceRecord.id, bobRecord.id])).toEqual({
      stale: true, in_app_rows: 0, outbox_rows: 0,
    });

    await login(page, alice); loggedIn = true;
    expect(await analysisFor()).toHaveLength(1);
    expect(await analysisOutboxFor()).toHaveLength(1);
    await logout(page); loggedIn = false;

    await login(page, bob); loggedIn = true;
    expect((await api(page, "GET", "/notifications?limit=100")).value.items.filter(
      (item) => item.kind === "analysis_completed" && item.resource_id === session.id,
    )).toHaveLength(1);
    await page.goto(`/projects/${session.id}/editor`);
    await page.getByRole("tab", { name: /댓글/ }).click();
    const commentText = `@${alice.name} 공개 브라우저 멘션 검증`;
    await page.getByLabel("댓글 내용").fill(commentText);
    await page.getByLabel("멘션할 멤버 UUID 선택").selectOption(aliceRecord.id);
    await page.getByRole("button", { name: "등록" }).click();
    await expect(page.getByText(commentText)).toBeVisible();
    await expect(page.getByText("멘션 1명")).toBeVisible();
    await expect(page.getByRole("button", { name: "내보내기" })).toBeVisible();
    await expect(page.getByRole("button", { name: "내보내기" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "공유 · 범위 외" })).toBeDisabled();
    await page.screenshot({ path: shots.comment, fullPage: true });
    await logout(page); loggedIn = false;

    await login(page, alice); loggedIn = true;
    const feed = (await api(page, "GET", "/notifications?limit=100")).value;
    expect(feed.items.find((item) => item.kind === "friend_request" && item.actor_id === bobRecord.id)).toMatchObject({ resource_type: "friend_request", action_kind: "respond_friend_request" });
    const mention = feed.items.find((item) =>
      item.kind === "mention" && item.resource_type === "comment" && item.actor_id === bobRecord.id,
    );
    const analysis = feed.items.find((item) =>
      item.kind === "analysis_completed" && item.resource_id === session.id,
    );
    expect(mention).toMatchObject({ action_kind: "open_comment" });
    expect(analysis).toBeTruthy();
    expect(mention.href).toMatch(new RegExp(`^/projects/${session.id}/editor\\?comment=`));
    await page.goto("/notifications");
    await expect(page.getByText(mention.title, { exact: true })).toBeVisible();
    await expect(page.getByText(analysis.title, { exact: true })).toBeVisible();
    await expect(page.locator('a[href="/notifications"]').first()).toContainText(String(feed.unread_count));
    await page.getByRole("button", { name: "알림", exact: true }).click();
    await expect(page.getByText(`읽지 않음 ${feed.unread_count}`)).toBeVisible();
    await page.keyboard.press("Escape");
    const openComment = page.locator(`a[href="${mention.href}"]`, { hasText: "열기" });
    await expect(openComment).toBeVisible(); await openComment.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${session.id}/editor\\?comment=`));
    await page.goto("/notifications");
    const readAll = page.waitForResponse((r) => r.url().endsWith("/api/notifications/read-all") && r.ok());
    await page.getByRole("button", { name: "모두 읽음 처리" }).click(); await readAll;
    await expect(page.getByRole("tab", { name: "읽지 않음 (0)" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("tab", { name: "읽지 않음 (0)" })).toBeVisible();
    await page.getByRole("tab", { name: /이메일 큐/ }).click();
    await expect(page.getByText("queued_local", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/외부로 발송되지 않았습니다/).first()).toBeVisible();
    await page.screenshot({ path: shots.outbox, fullPage: true });
    await page.goto("/history");
    await expect(page.getByText(/감사 원장은 .*부터 기록됩니다/)).toBeVisible();
    for (const label of ["알림 설정 변경", "댓글 작성", "분석 완료"]) await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(`${alice.name}-persisted`, { exact: true }).first()).toBeVisible();
    await expect(page.locator("time").first()).toHaveText(/^\d{2}:\d{2}$/);
    const activityFilter = page.getByRole("combobox", { name: "활동 유형 필터" });
    await expect(activityFilter).toContainText("전체 활동");
    await activityFilter.click();
    await page.getByRole("option", { name: "AI 분석" }).click();
    await expect(activityFilter).toContainText("AI 분석");
    await expect(page.getByText("분석 완료", { exact: true }).first()).toBeVisible();
    await page.getByLabel("히스토리 검색").fill("분석");
    await expect(page.getByText("분석 완료", { exact: true }).first()).toBeVisible();
    await page.getByLabel("히스토리 검색").clear();
    await activityFilter.click();
    await page.getByRole("option", { name: "전체 활동" }).click();
    await page.screenshot({ path: shots.evidence, fullPage: true });
    await logout(page); loggedIn = false;

    await login(page, eve); loggedIn = true;
    const denied = await page.evaluate(async (id) => (await fetch(`/api/sessions/${id}`, { credentials: "include" })).status, session.id);
    expect([403, 404]).toContain(denied);
    await page.goto(`/projects/${session.id}`);
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByText(`Notification audit ${suffix}`, { exact: true })).toHaveCount(0);
    await expect(page.getByText(`@${alice.name} 공개 브라우저 멘션 검증`, { exact: true })).toHaveCount(0);
    await page.screenshot({ path: shots.denied, fullPage: true });
  } finally {
    if (loggedIn) await logout(page).catch(() => {});
  }
  for (const target of Object.values(shots)) expect(fs.existsSync(target)).toBe(true);
});
