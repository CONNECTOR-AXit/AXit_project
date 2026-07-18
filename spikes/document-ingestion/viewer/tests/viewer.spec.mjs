import { expect, test } from "@playwright/test";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  cleanupEvidencePath,
  readFixtureAttestation,
  resolveEvidencePath,
  resolveRunAttestation
} from "./attestation.mjs";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const LOCAL_ORIGIN = "http://127.0.0.1:4173";
const MANIFEST_PATH = join(
  resolve(ROOT, "../../.."),
  "tests",
  "fixtures",
  "document-ingestion",
  "manifest.v1.json"
);
const PROVENANCE_PATH = join(ROOT, "fixtures", "provenance.v1.json");
const TABLE_PATH = "hwp/table-footnote.hwp";
const evidence = new Map();
let evidencePath;
let runAttestation;

test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

async function jsonFile(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function fixture(name) {
  return jsonFile(join(ROOT, "fixtures", name));
}

async function provenance() {
  return jsonFile(PROVENANCE_PATH);
}

async function goldenManifestPaths() {
  const manifest = await jsonFile(MANIFEST_PATH);
  expect(manifest.schema_version).toBe(1);
  expect(Array.isArray(manifest.fixtures)).toBe(true);
  return manifest.fixtures
    .filter((entry) => entry.classification === "golden")
    .map((entry) => entry.path)
    .sort((left, right) => left.localeCompare(right));
}

async function installNetworkGuard(context) {
  const blocked = [];
  await context.route("**/*", async (route) => {
    const requestUrl = route.request().url();
    const parsed = new URL(requestUrl);
    if (parsed.protocol === "data:" || parsed.origin === LOCAL_ORIGIN) {
      await route.continue();
      return;
    }
    blocked.push({ method: route.request().method(), url: requestUrl });
    await route.abort("blockedbyclient");
  });
  return blocked;
}

async function openPayload(page, name, anchorHash = null) {
  const hash = anchorHash ? `#anchor=${anchorHash}` : "";
  await page.goto(`/index.html?payload=/fixtures/${name}${hash}`);
  await expect(page.locator("[data-viewer-status]")).toHaveText("Ready");
}

async function normalizedGeometryMatches(page, block) {
  const target = page.locator(`[data-anchor-hash="${block.anchor_hash}"]`);
  const surface = target.locator("xpath=ancestor::*[@data-normalized-surface][1]");
  const [targetBox, surfaceBox] = await Promise.all([
    target.boundingBox(),
    surface.boundingBox()
  ]);
  expect(targetBox).not.toBeNull();
  expect(surfaceBox).not.toBeNull();
  const [left, top, right, bottom] = block.anchor.locator.bbox;
  const expected = {
    x: surfaceBox.x + surfaceBox.width * left,
    y: surfaceBox.y + surfaceBox.height * top,
    width: surfaceBox.width * (right - left),
    height: surfaceBox.height * (bottom - top)
  };
  for (const key of ["x", "y", "width", "height"]) {
    expect(Math.abs(targetBox[key] - expected[key]), `${key} geometry`).toBeLessThanOrEqual(1);
  }
  return true;
}

async function structuredPathMatches(page, block) {
  const locator = block.anchor.locator;
  const target = page.locator(`[data-anchor-hash="${block.anchor_hash}"]`);
  await expect(target).toHaveAttribute("data-parser", locator.parser);
  await expect(target).toHaveAttribute("data-parser-version", locator.parser_version);
  await expect(target).toHaveAttribute("data-section", String(locator.section));
  await expect(target).toHaveAttribute("data-paragraph", String(locator.paragraph));
  if (locator.table) {
    const path = locator.table;
    await expect(target).toHaveAttribute("data-table-index", String(path.index));
    await expect(target).toHaveAttribute("data-table-block", String(path.block));
    await expect(target).toHaveAttribute("data-table-row", String(path.row));
    await expect(target).toHaveAttribute("data-table-cell", String(path.cell));
    await expect(target).toHaveAttribute("data-table-paragraph", String(path.paragraph));
    await expect(target.locator("xpath=ancestor::table[1]")).toHaveAttribute(
      "data-table-index",
      String(path.index)
    );
    await expect(target.locator("xpath=ancestor::table[1]")).toHaveAttribute(
      "data-table-block",
      String(path.block)
    );
    await expect(target.locator("xpath=ancestor::tr[1]")).toHaveAttribute(
      "data-row",
      String(path.row)
    );
    await expect(target.locator("xpath=ancestor::td[1]")).toHaveAttribute(
      "data-cell",
      String(path.cell)
    );
    await expect(target.locator("xpath=ancestor::td[1]")).toHaveAttribute(
      "data-cell-paragraph",
      String(path.paragraph)
    );
  }
  if (locator.footnote) {
    const path = locator.footnote;
    await expect(target).toHaveAttribute("data-footnote-index", String(path.index));
    await expect(target).toHaveAttribute("data-footnote-paragraph", String(path.paragraph));
    await expect(target.locator("xpath=ancestor::aside[1]")).toHaveAttribute(
      "data-footnote-index",
      String(path.index)
    );
    await expect(target.locator("xpath=ancestor::aside[1]")).toHaveAttribute(
      "data-footnote-paragraph",
      String(path.paragraph)
    );
  }
  return true;
}

async function assertSingleHighlight(page, anchorHash) {
  await expect(page.locator("[data-source-target].is-selected")).toHaveCount(1);
  await expect(page.locator("[data-source-target].is-selected")).toHaveAttribute(
    "data-anchor-hash",
    anchorHash
  );
}

test.beforeAll(async () => {
  // This repeats the npm pretest cleanup so direct Playwright invocations also
  // cannot leave a stale proof behind when an early browser assertion fails.
  await rm(cleanupEvidencePath(process.env), { force: true });
  evidencePath = resolveEvidencePath(process.env);
  const fixtureAttestation = await readFixtureAttestation();
  runAttestation = resolveRunAttestation(process.env, fixtureAttestation);
});

test("every real golden extraction clicks, deep-links, and resolves its exact source target", async ({
  context,
  page
}) => {
  const blocked = await installNetworkGuard(context);
  const [captureIndex, expectedGoldenPaths] = await Promise.all([provenance(), goldenManifestPaths()]);
  const firstCaptureByManifestPath = new Map();
  for (const capture of captureIndex.captures) {
    if (!firstCaptureByManifestPath.has(capture.manifest_path)) {
      firstCaptureByManifestPath.set(capture.manifest_path, capture);
    }
  }
  expect([...firstCaptureByManifestPath.keys()].sort((left, right) => left.localeCompare(right))).toEqual(
    expectedGoldenPaths
  );

  for (const [manifestPath, capture] of [...firstCaptureByManifestPath].sort(([a], [b]) =>
    a.localeCompare(b)
  )) {
    const blockedBefore = blocked.length;
    const payload = await fixture(capture.payload_file);
    const blocks = payload.result.blocks;
    await openPayload(page, capture.payload_file);
    await expect(page.locator("[data-citation]")).toHaveCount(blocks.length);
    await expect(page.locator("[data-source-target]")).toHaveCount(blocks.length);

    let geometryMatch = true;
    for (const block of blocks) {
      if (["pdf_block", "image_bbox"].includes(block.anchor.kind)) {
        geometryMatch = (await normalizedGeometryMatches(page, block)) && geometryMatch;
      } else {
        geometryMatch = (await structuredPathMatches(page, block)) && geometryMatch;
      }
      await page.locator(`[data-citation="${block.anchor_hash}"]`).click();
      await assertSingleHighlight(page, block.anchor_hash);
      await expect(page.locator("[data-selected-text-fingerprint]")).toHaveText(
        block.anchor.text_fingerprint
      );
    }

    const deepLinkBlock = blocks.at(-1);
    await openPayload(page, capture.payload_file, deepLinkBlock.anchor_hash);
    await assertSingleHighlight(page, deepLinkBlock.anchor_hash);
    await page.reload();
    await expect(page.locator("[data-viewer-status]")).toHaveText("Ready");
    await assertSingleHighlight(page, deepLinkBlock.anchor_hash);
    const selectedCount = await page.locator("[data-source-target].is-selected").count();
    const selectedHash = await page
      .locator("[data-source-target].is-selected")
      .getAttribute("data-anchor-hash");
    const externalRequests = blocked.length - blockedBefore;
    expect(externalRequests).toBe(0);

    evidence.set(manifestPath, {
      selected_count: selectedCount,
      target_anchor_set_hash: payload.result.anchor_set_hash,
      deep_link_match: selectedHash === deepLinkBlock.anchor_hash,
      geometry_match: geometryMatch,
      external_requests: externalRequests
    });

    if (manifestPath === TABLE_PATH) {
      await mkdir(join(ROOT, "evidence"), { recursive: true });
      await page.screenshot({
        path: join(ROOT, "evidence", "hwp-table-deep-link.png"),
        fullPage: true
      });
    }
  }
  expect(blocked).toEqual([]);
});

test("complete real structured table and footnote paths remain visible in citation labels and DOM", async ({
  context,
  page
}) => {
  const blocked = await installNetworkGuard(context);
  const captureIndex = await provenance();
  const checkedManifestPaths = new Set();
  const structuredManifestPaths = new Set();
  for (const capture of captureIndex.captures) {
    if (checkedManifestPaths.has(capture.manifest_path)) continue;
    checkedManifestPaths.add(capture.manifest_path);
    const payload = await fixture(capture.payload_file);
    const structuredBlocks = payload.result.blocks.filter(
      (block) => block.anchor.locator.table || block.anchor.locator.footnote
    );
    if (structuredBlocks.length === 0) continue;
    structuredManifestPaths.add(capture.manifest_path);
    await openPayload(page, capture.payload_file);
    for (const block of structuredBlocks) {
      await structuredPathMatches(page, block);
      const label = page.locator(`[data-citation="${block.anchor_hash}"] .citation-path`);
      const locator = block.anchor.locator;
      await expect(label).toContainText(`section ${locator.section} · paragraph ${locator.paragraph}`);
      if (locator.table) {
        await expect(label).toContainText(
          `table ${locator.table.index} / block ${locator.table.block} / row ${locator.table.row} / cell ${locator.table.cell} / paragraph ${locator.table.paragraph}`
        );
      }
      if (locator.footnote) {
        await expect(label).toContainText(
          `footnote ${locator.footnote.index} / paragraph ${locator.footnote.paragraph}`
        );
      }
    }
  }
  expect(structuredManifestPaths.size).toBeGreaterThan(0);
  expect(blocked).toEqual([]);
});

test("two independent real table/footnote runs resolve the same deterministic DOM target", async ({
  context,
  page
}) => {
  const blocked = await installNetworkGuard(context);
  const [first, second, captureIndex] = await Promise.all([
    fixture("hwp-table-footnote-run-a.json"),
    fixture("hwp-table-footnote-run-b.json"),
    provenance()
  ]);
  const repeats = captureIndex.captures.filter((capture) => capture.manifest_path === TABLE_PATH);
  expect(repeats).toHaveLength(2);
  expect(repeats[0].invocation_id).not.toBe(repeats[1].invocation_id);
  expect(repeats[0].container_name).not.toBe(repeats[1].container_name);
  expect(first).toEqual(second);
  expect(first.result.anchor_set_hash).toBe(second.result.anchor_set_hash);
  const anchorHash = first.result.blocks.find((block) => block.anchor.locator.table).anchor_hash;

  await openPayload(page, basename(repeats[0].payload_file), anchorHash);
  const firstId = await page.locator("[data-source-target].is-selected").getAttribute("id");
  await assertSingleHighlight(page, anchorHash);
  await openPayload(page, basename(repeats[1].payload_file), anchorHash);
  const secondId = await page.locator("[data-source-target].is-selected").getAttribute("id");
  await assertSingleHighlight(page, anchorHash);
  expect(firstId).toBe(`target-${anchorHash}`);
  expect(secondId).toBe(firstId);
  expect(blocked).toEqual([]);
});

test("the zero-external-request guard has an active blocking positive control", async ({
  context,
  page
}) => {
  const blocked = await installNetworkGuard(context);
  await expect(page.goto("https://blocked.example.invalid/probe")).rejects.toThrow();
  expect(blocked).toEqual([
    { method: "GET", url: "https://blocked.example.invalid/probe" }
  ]);
});

test("writes fresh schema-v2 browser evidence only after every browser proof passes", async () => {
  const expectedGoldenPaths = await goldenManifestPaths();
  expect(evidence.size).toBe(expectedGoldenPaths.length);
  expect(evidencePath).toBeTruthy();
  expect(runAttestation).toBeTruthy();
  const fixtures = Object.fromEntries([...evidence].sort(([a], [b]) => a.localeCompare(b)));
  expect(Object.keys(fixtures)).toEqual(expectedGoldenPaths);
  for (const proof of Object.values(fixtures)) {
    expect(proof).toEqual({
      selected_count: 1,
      target_anchor_set_hash: expect.stringMatching(/^[0-9a-f]{64}$/u),
      deep_link_match: true,
      geometry_match: true,
      external_requests: 0
    });
  }
  const renderedEvidence = {
    schema_version: 2,
    fixtures,
    attestation: runAttestation
  };
  await mkdir(dirname(evidencePath), { recursive: true });
  await writeFile(evidencePath, `${JSON.stringify(renderedEvidence, null, 2)}\n`, "utf8");
  await expect.poll(async () => jsonFile(evidencePath)).toEqual(renderedEvidence);
});
