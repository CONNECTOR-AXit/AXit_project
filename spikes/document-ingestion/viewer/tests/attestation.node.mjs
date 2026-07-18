import assert from "node:assert/strict";
import test from "node:test";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  DEFAULT_EVIDENCE_PATH,
  browserAttestationEnvironment,
  readFixtureAttestation,
  resolveEvidencePath,
  resolveRunAttestation
} from "./attestation.mjs";

const { attestation: ATTESTATION_ENV, evidencePath: EVIDENCE_PATH_ENV } =
  browserAttestationEnvironment;

test("fixture attestation is content-bound to the committed provenance", async () => {
  const attestation = await readFixtureAttestation();
  assert.match(attestation.manifest_sha256, /^[0-9a-f]{64}$/u);
  assert.match(attestation.policy_sha256, /^[0-9a-f]{64}$/u);
  assert.match(attestation.provenance_sha256, /^[0-9a-f]{64}$/u);
  assert.match(attestation.extraction_image_id, /^sha256:[0-9a-f]{64}$/u);
});

test("local evidence is explicitly unattested rather than using a fabricated nonce", async () => {
  const expected = await readFixtureAttestation();
  assert.deepEqual(resolveRunAttestation({}, expected), { nonce: null, ...expected });
  assert.equal(resolveEvidencePath({}), DEFAULT_EVIDENCE_PATH);
});

test("gate evidence rejects an attestation that is not bound to current provenance", async () => {
  const expected = await readFixtureAttestation();
  const path = join(tmpdir(), "fresh-browser-evidence.v2.json");
  const environment = {
    [EVIDENCE_PATH_ENV]: path,
    [ATTESTATION_ENV]: JSON.stringify({ nonce: "g0-test-nonce", ...expected })
  };
  assert.deepEqual(resolveRunAttestation(environment, expected), {
    nonce: "g0-test-nonce",
    ...expected
  });
  assert.match(resolveEvidencePath(environment), /fresh-browser-evidence\.v2\.json$/u);

  const mismatched = {
    ...environment,
    [ATTESTATION_ENV]: JSON.stringify({
      nonce: "g0-test-nonce",
      ...expected,
      policy_sha256: "0".repeat(64)
    })
  };
  assert.throws(
    () => resolveRunAttestation(mismatched, expected),
    /does not match current fixture provenance/u
  );
  assert.throws(
    () => resolveEvidencePath({ [ATTESTATION_ENV]: environment[ATTESTATION_ENV] }),
    new RegExp(EVIDENCE_PATH_ENV, "u")
  );
});
