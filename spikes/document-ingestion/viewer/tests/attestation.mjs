import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

export const VIEWER_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
export const REPOSITORY_ROOT = resolve(VIEWER_ROOT, "../../..");
export const DEFAULT_EVIDENCE_PATH = join(
  VIEWER_ROOT,
  "evidence",
  "browser-evidence.v2.json"
);

const HASH_PATTERN = /^[0-9a-f]{64}$/u;
const IMAGE_ID_PATTERN = /^sha256:[0-9a-f]{64}$/u;
const ATTESTATION_ENV = "AXIT_G0_BROWSER_ATTESTATION_JSON";
const EVIDENCE_PATH_ENV = "AXIT_G0_BROWSER_EVIDENCE_PATH";

function fail(message) {
  throw new Error(`browser evidence attestation: ${message}`);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requireExactKeys(value, keys, label) {
  if (!isRecord(value)) fail(`${label} must be an object`);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(`${label} has unexpected keys`);
  }
}

function requireHash(value, label) {
  if (typeof value !== "string" || !HASH_PATTERN.test(value)) {
    fail(`${label} must be a lowercase SHA-256 hex digest`);
  }
  return value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function sha256File(path) {
  return sha256(await readFile(path));
}

function repositoryFile(relativePath, label) {
  if (typeof relativePath !== "string" || relativePath.length === 0) {
    fail(`${label} is missing`);
  }
  const path = resolve(REPOSITORY_ROOT, relativePath);
  const pathFromRoot = relative(REPOSITORY_ROOT, path);
  if (
    pathFromRoot === "" ||
    pathFromRoot === ".." ||
    pathFromRoot.startsWith(`..${sep}`) ||
    isAbsolute(pathFromRoot)
  ) {
    fail(`${label} escapes the repository`);
  }
  return path;
}

function hasGateAttestation(environment) {
  return Object.prototype.hasOwnProperty.call(environment, ATTESTATION_ENV) &&
    environment[ATTESTATION_ENV] !== undefined;
}

function validateNonce(value) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value ||
    Buffer.byteLength(value, "utf8") > 512 ||
    /[\u0000-\u001f\u007f]/u.test(value)
  ) {
    fail("attestation.nonce must be a non-empty printable token no longer than 512 bytes");
  }
  return value;
}

export function cleanupEvidencePath(environment = process.env) {
  const configured = environment[EVIDENCE_PATH_ENV];
  if (typeof configured !== "string" || configured.trim() === "") {
    return DEFAULT_EVIDENCE_PATH;
  }
  return resolve(configured);
}

export function resolveEvidencePath(environment = process.env) {
  const configured = environment[EVIDENCE_PATH_ENV];
  const gateMode = hasGateAttestation(environment);
  if (configured === undefined) {
    if (gateMode) fail(`${EVIDENCE_PATH_ENV} is required when ${ATTESTATION_ENV} is set`);
    return DEFAULT_EVIDENCE_PATH;
  }
  if (typeof configured !== "string" || configured.trim() === "") {
    fail(`${EVIDENCE_PATH_ENV} must be a non-empty path`);
  }
  if (gateMode && !isAbsolute(configured)) {
    fail(`${EVIDENCE_PATH_ENV} must be absolute for gate evidence`);
  }
  return resolve(configured);
}

export async function readFixtureAttestation() {
  const provenancePath = join(VIEWER_ROOT, "fixtures", "provenance.v1.json");
  const provenance = JSON.parse(await readFile(provenancePath, "utf8"));
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
    "fixture provenance"
  );
  if (provenance.schema_version !== 1 || !Array.isArray(provenance.captures)) {
    fail("fixture provenance has an unsupported schema");
  }
  if (!isRecord(provenance.image) || Object.keys(provenance.image).sort().join(",") !== "id,reference") {
    fail("fixture provenance image is malformed");
  }
  if (typeof provenance.image.id !== "string" || !IMAGE_ID_PATTERN.test(provenance.image.id)) {
    fail("fixture provenance image id is not content-addressed");
  }

  const manifestPath = repositoryFile(provenance.manifest_path, "fixture provenance manifest_path");
  const policyPath = repositoryFile(provenance.policy_path, "fixture provenance policy_path");
  const [manifestSha256, policySha256, provenanceSha256] = await Promise.all([
    sha256File(manifestPath),
    sha256File(policyPath),
    sha256File(provenancePath)
  ]);
  if (provenance.manifest_sha256 !== manifestSha256) {
    fail("fixture provenance manifest SHA-256 does not match current bytes");
  }
  if (provenance.policy_sha256 !== policySha256) {
    fail("fixture provenance policy SHA-256 does not match current bytes");
  }

  return {
    manifest_sha256: requireHash(manifestSha256, "manifest SHA-256"),
    policy_sha256: requireHash(policySha256, "policy SHA-256"),
    extraction_image_id: provenance.image.id,
    provenance_sha256: requireHash(provenanceSha256, "provenance SHA-256")
  };
}

export function resolveRunAttestation(environment, fixtureAttestation) {
  if (!hasGateAttestation(environment)) {
    return {
      nonce: null,
      ...fixtureAttestation
    };
  }

  const raw = environment[ATTESTATION_ENV];
  if (typeof raw !== "string") fail(`${ATTESTATION_ENV} must be JSON text`);
  let supplied;
  try {
    supplied = JSON.parse(raw);
  } catch {
    fail(`${ATTESTATION_ENV} is not valid JSON`);
  }
  requireExactKeys(
    supplied,
    [
      "nonce",
      "manifest_sha256",
      "policy_sha256",
      "extraction_image_id",
      "provenance_sha256"
    ],
    "gate attestation"
  );
  validateNonce(supplied.nonce);
  requireHash(supplied.manifest_sha256, "gate attestation manifest_sha256");
  requireHash(supplied.policy_sha256, "gate attestation policy_sha256");
  requireHash(supplied.provenance_sha256, "gate attestation provenance_sha256");
  if (
    typeof supplied.extraction_image_id !== "string" ||
    !IMAGE_ID_PATTERN.test(supplied.extraction_image_id)
  ) {
    fail("gate attestation extraction_image_id must be a content-addressed image id");
  }

  for (const field of [
    "manifest_sha256",
    "policy_sha256",
    "extraction_image_id",
    "provenance_sha256"
  ]) {
    if (supplied[field] !== fixtureAttestation[field]) {
      fail(`gate attestation ${field} does not match current fixture provenance`);
    }
  }
  return supplied;
}

export const browserAttestationEnvironment = {
  attestation: ATTESTATION_ENV,
  evidencePath: EVIDENCE_PATH_ENV
};
