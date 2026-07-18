import { rm } from "node:fs/promises";
import { cleanupEvidencePath } from "./attestation.mjs";

// npm invokes this before fixture validation or Playwright starts. It makes a
// stale gate output unusable even if a later preflight step fails.
await rm(cleanupEvidencePath(process.env), { force: true });
