import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const fixtureDir = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(fixtureDir, "../../../..");
const manifestPath = join(
  repositoryRoot,
  "tests",
  "fixtures",
  "document-ingestion",
  "manifest.v1.json"
);
const sourceRoot = dirname(manifestPath);
const provenancePath = join(fixtureDir, "provenance.v1.json");
const HASH_PATTERN = /^[0-9a-f]{64}$/u;
const IMAGE_ID_PATTERN = /^sha256:[0-9a-f]{64}$/u;

const CAPTURE_INVENTORY = new Map([
  ["hwp/simple.hwp", ["hwp-simple.json"]],
  [
    "hwp/table-footnote.hwp",
    ["hwp-table-footnote-run-a.json", "hwp-table-footnote-run-b.json"]
  ],
  ["hwpx/simple.hwpx", ["hwpx-simple.json"]],
  ["hwpx/table-footnote.hwpx", ["hwpx-table-footnote.json"]],
  ["images/korean-clean.jpg", ["image-korean-clean-jpeg.json"]],
  ["images/korean-clean.png", ["image-korean-clean-png.json"]],
  ["images/rotated-low-confidence.jpg", ["image-rotated-low-confidence.json"]],
  ["pdf/scanned-korean.pdf", ["pdf-scanned-korean.json"]],
  ["pdf/text-korean.pdf", ["pdf-text-korean.json"]]
]);

const APPROVED_PARSERS = new Map([
  ["application/pdf", ["pypdfium2", "5.12.1"]],
  ["image/png", ["pillow+tesseract-cli", "12.3.0+5.3.0"]],
  ["image/jpeg", ["pillow+tesseract-cli", "12.3.0+5.3.0"]],
  ["application/x-hwp", ["pyhwp", "0.1b15"]],
  ["application/x-hwpx", ["hwpxlib", "1.0.9"]],
  [
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ["libreoffice+pypdfium2+tesseract-cli", "1.0.0"]
  ],
  [
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ["stdlib-xlsx", "1.0.0"]
  ]
]);

function fail(message) {
  throw new Error(`real viewer fixture check failed: ${message}`);
}

function requireObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function requireExactKeys(value, keys, label) {
  const actual = Object.keys(requireObject(value, label)).sort();
  const expected = [...keys].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(`${label} fields do not match the committed contract`);
  }
}

function normalizeText(value) {
  return value.replaceAll("\r\n", "\n").replaceAll("\r", "\n").normalize("NFC");
}

function normalizeJson(value) {
  if (Array.isArray(value)) return value.map(normalizeJson);
  if (value !== null && typeof value === "object") {
    const normalized = {};
    for (const rawKey of Object.keys(value)) {
      const key = normalizeText(rawKey);
      if (Object.hasOwn(normalized, key)) fail("canonical JSON has colliding normalized keys");
      normalized[key] = normalizeJson(value[rawKey]);
    }
    return Object.fromEntries(
      Object.keys(normalized)
        .sort()
        .map((key) => [key, normalized[key]])
    );
  }
  if (typeof value === "string") return normalizeText(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("canonical JSON numbers must be finite");
    const rounded = Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
    return Object.is(rounded, -0) ? 0 : rounded;
  }
  if (["boolean", "undefined"].includes(typeof value) && value === undefined) {
    fail("canonical JSON cannot contain undefined");
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(normalizeJson(value));
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function sha256File(path) {
  return sha256(await readFile(path));
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function validateHwpLocator(locator, label) {
  const allowed = new Set(["parser", "parser_version", "section", "paragraph", "table", "footnote"]);
  for (const key of Object.keys(locator)) if (!allowed.has(key)) fail(`${label} has an unknown field`);
  for (const key of ["parser", "parser_version", "section", "paragraph"]) {
    if (!Object.hasOwn(locator, key)) fail(`${label} is missing ${key}`);
  }
  if (locator.table !== undefined && locator.footnote !== undefined) {
    fail(`${label} cannot be both a table cell and a footnote`);
  }
  if (locator.table !== undefined) {
    requireExactKeys(locator.table, ["index", "block", "row", "cell", "paragraph"], `${label}.table`);
  }
  if (locator.footnote !== undefined) {
    requireExactKeys(locator.footnote, ["index", "paragraph"], `${label}.footnote`);
  }
}

function validatePayload(payload, manifestEntry, label) {
  requireExactKeys(payload, ["schema_version", "ok", "result"], label);
  if (payload.schema_version !== 1 || payload.ok !== true) fail(`${label} is not a successful v1 envelope`);
  const result = requireObject(payload.result, `${label}.result`);
  requireExactKeys(
    result,
    [
      "source_sha256",
      "media_type",
      "parser",
      "normalization_profile",
      "config_profile_hash",
      "anchor_set_hash",
      "blocks",
      "warnings"
    ],
    `${label}.result`
  );
  if (result.source_sha256 !== manifestEntry.sha256) fail(`${label} source hash differs from the manifest`);
  if (result.media_type !== manifestEntry.media_type) fail(`${label} media type differs from the manifest`);
  if (result.normalization_profile !== "nfc-lf-v1") fail(`${label} normalization profile is not approved`);
  if (!HASH_PATTERN.test(result.config_profile_hash)) fail(`${label} config profile hash is invalid`);
  const approved = APPROVED_PARSERS.get(result.media_type);
  if (
    approved === undefined ||
    result.parser?.name !== approved[0] ||
    result.parser?.version !== approved[1]
  ) {
    fail(`${label} parser identity is not the approved pinned implementation`);
  }
  if (!Array.isArray(result.blocks) || result.blocks.length === 0) fail(`${label} has no blocks`);

  const expectedKind = new Map([
    ["application/pdf", "pdf_block"],
    ["image/png", "image_bbox"],
    ["image/jpeg", "image_bbox"],
    ["application/x-hwp", "hwp_paragraph"],
    ["application/x-hwpx", "hwp_paragraph"],
    [
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      "pdf_block"
    ],
    [
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "xlsx_cell"
    ]
  ]).get(result.media_type);
  const anchorHashes = [];
  for (const [ordinal, block] of result.blocks.entries()) {
    requireExactKeys(
      block,
      ["ordinal", "text", "block_type", "confidence", "anchor", "anchor_hash"],
      `${label}.blocks[${ordinal}]`
    );
    if (block.ordinal !== ordinal) fail(`${label} block ordinals are not contiguous`);
    if (typeof block.text !== "string" || !block.text || normalizeText(block.text) !== block.text) {
      fail(`${label} block ${ordinal} text is not normalized`);
    }
    const anchor = requireObject(block.anchor, `${label}.blocks[${ordinal}].anchor`);
    requireExactKeys(
      anchor,
      [
        "schema_version",
        "kind",
        "source_sha256",
        "extraction_profile_hash",
        "locator",
        "text_fingerprint"
      ],
      `${label}.blocks[${ordinal}].anchor`
    );
    if (anchor.kind !== expectedKind) fail(`${label} block ${ordinal} has an incompatible anchor kind`);
    if (anchor.source_sha256 !== manifestEntry.sha256) fail(`${label} block ${ordinal} is source-unbound`);
    if (anchor.extraction_profile_hash !== result.config_profile_hash) {
      fail(`${label} block ${ordinal} is profile-unbound`);
    }
    if (anchor.text_fingerprint !== sha256(Buffer.from(normalizeText(block.text), "utf8"))) {
      fail(`${label} block ${ordinal} text fingerprint is invalid`);
    }
    if (expectedKind === "hwp_paragraph") {
      validateHwpLocator(anchor.locator, `${label}.blocks[${ordinal}].anchor.locator`);
      if (
        anchor.locator.parser !== result.parser.name ||
        anchor.locator.parser_version !== result.parser.version
      ) {
        fail(`${label} block ${ordinal} locator parser is inconsistent`);
      }
    }
    const expectedAnchorHash = sha256(Buffer.from(canonicalJson(anchor), "utf8"));
    if (block.anchor_hash !== expectedAnchorHash) fail(`${label} block ${ordinal} canonical hash is invalid`);
    anchorHashes.push(expectedAnchorHash);
  }
  if (new Set(anchorHashes).size !== anchorHashes.length) fail(`${label} contains duplicate anchors`);
  const expectedSetHash = sha256(
    Buffer.from(canonicalJson({ schema_version: 1, anchor_hashes: anchorHashes }), "utf8")
  );
  if (result.anchor_set_hash !== expectedSetHash) {
    fail(`${label} ordered anchor-set hash is invalid`);
  }
}

async function check() {
  const [manifest, provenance] = await Promise.all([
    readJson(manifestPath),
    readJson(provenancePath)
  ]);
  if (manifest.schema_version !== 1 || !Array.isArray(manifest.fixtures)) {
    fail("canonical manifest is malformed");
  }
  const manifestEntries = new Map(manifest.fixtures.map((entry) => [entry.path, entry]));
  const golden = manifest.fixtures.filter((entry) => entry.classification === "golden");
  if (
    golden.length !== CAPTURE_INVENTORY.size ||
    golden.some((entry) => !CAPTURE_INVENTORY.has(entry.path))
  ) {
    fail("capture inventory does not cover every and only golden manifest fixture");
  }

  requireExactKeys(
    provenance,
    [
      "capture_method",
      "captures",
      "image",
      "manifest_path",
      "manifest_sha256",
      "policy_path",
      "policy_sha256",
      "schema_version"
    ],
    "provenance"
  );
  if (provenance.schema_version !== 1 || provenance.capture_method !== "sandbox_runner.execute_sandbox") {
    fail("provenance does not name the real host sandbox boundary");
  }
  if (!IMAGE_ID_PATTERN.test(provenance.image?.id)) fail("provenance image ID is not content addressed");
  if (provenance.manifest_path !== "tests/fixtures/document-ingestion/manifest.v1.json") {
    fail("provenance is not bound to the canonical manifest path");
  }
  if (provenance.manifest_sha256 !== (await sha256File(manifestPath))) {
    fail("provenance manifest hash is stale");
  }
  const policyPath = join(repositoryRoot, ...provenance.policy_path.split("/"));
  if (provenance.policy_sha256 !== (await sha256File(policyPath))) fail("provenance policy hash is stale");
  const expectedCaptureCount = [...CAPTURE_INVENTORY.values()].flat().length;
  if (!Array.isArray(provenance.captures) || provenance.captures.length !== expectedCaptureCount) {
    fail("provenance must contain every golden capture plus the independent table/footnote repeat");
  }

  const capturesByFile = new Map(provenance.captures.map((capture) => [capture.payload_file, capture]));
  const expectedFiles = [...CAPTURE_INVENTORY.values()].flat();
  const payloads = new Map();
  for (const [manifestRelativePath, files] of CAPTURE_INVENTORY) {
    const manifestEntry = manifestEntries.get(manifestRelativePath);
    if (manifestEntry === undefined) fail(`${manifestRelativePath} is absent from the manifest`);
    const actualSourceHash = await sha256File(
      join(sourceRoot, ...manifestRelativePath.split("/"))
    );
    if (actualSourceHash !== manifestEntry.sha256) fail(`${manifestRelativePath} source bytes drifted`);
    for (const payloadFile of files) {
      const capture = capturesByFile.get(payloadFile);
      if (capture === undefined) fail(`${payloadFile} has no real-capture provenance`);
      if (
        capture.manifest_path !== manifestRelativePath ||
        capture.manifest_sha256 !== manifestEntry.sha256 ||
        capture.media_type !== manifestEntry.media_type
      ) {
        fail(`${payloadFile} provenance is not bound to its manifest entry`);
      }
      if (
        capture.execution?.ok !== true ||
        capture.execution?.exit_code !== 0 ||
        capture.execution?.stderr_bytes !== 0 ||
        capture.execution?.killed !== false
      ) {
        fail(`${payloadFile} provenance is not a clean successful sandbox execution`);
      }
      const payload = await readJson(join(fixtureDir, payloadFile));
      validatePayload(payload, manifestEntry, payloadFile);
      if (capture.payload_sha256 !== sha256(Buffer.from(canonicalJson(payload), "utf8"))) {
        fail(`${payloadFile} payload hash differs from capture provenance`);
      }
      if (capture.anchor_set_hash !== payload.result.anchor_set_hash) {
        fail(`${payloadFile} anchor set differs from capture provenance`);
      }
      payloads.set(payloadFile, payload);
    }
  }
  if (capturesByFile.size !== expectedFiles.length) fail("provenance contains an unexpected payload");

  const repeatAName = "hwp-table-footnote-run-a.json";
  const repeatBName = "hwp-table-footnote-run-b.json";
  if (canonicalJson(payloads.get(repeatAName)) !== canonicalJson(payloads.get(repeatBName))) {
    fail("the two independent table/footnote sandbox runs are not identical");
  }
  if (
    capturesByFile.get(repeatAName).invocation_id === capturesByFile.get(repeatBName).invocation_id ||
    capturesByFile.get(repeatAName).container_name === capturesByFile.get(repeatBName).container_name
  ) {
    fail("table/footnote repeats were not recorded as independent invocations");
  }

  const committedJson = (await readdir(fixtureDir))
    .filter((name) => name.endsWith(".json"))
    .sort();
  const expectedJson = [...expectedFiles, "provenance.v1.json"].sort();
  if (JSON.stringify(committedJson) !== JSON.stringify(expectedJson)) {
    fail("legacy or unexpected JSON fixtures are present");
  }
  process.stdout.write(
    `Validated ${CAPTURE_INVENTORY.size} real golden payloads (${expectedFiles.length} sandbox runs) from ${provenance.image.id}.\n`
  );
}

const argumentsSet = new Set(process.argv.slice(2));
if ([...argumentsSet].some((argument) => argument !== "--check")) {
  fail("use capture_real_payloads.py to recapture; this command only validates committed payloads");
}
await check();
