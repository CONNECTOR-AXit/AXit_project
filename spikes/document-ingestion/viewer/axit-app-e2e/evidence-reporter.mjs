import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../../../..");
export const evidenceDirectory = path.join(root, ".omx/state/notification-audit-settings/browser");
export const traceTarget = path.join(evidenceDirectory, "trace.zip");

export default class EvidenceReporter {
  sawTestResult = false;
  copiedTrace = false;

  onTestEnd(_test, result) {
    this.sawTestResult = true;
    if (result.status !== "passed") return;
    const trace = result.attachments.find((item) => item.name === "trace" && item.path);
    if (!trace?.path) return;
    fs.mkdirSync(evidenceDirectory, { recursive: true });
    fs.copyFileSync(trace.path, traceTarget);
    this.copiedTrace = true;
  }

  onEnd(result) {
    if (this.sawTestResult && result.status === "passed" && !this.copiedTrace) {
      throw new Error(`successful run did not produce ${traceTarget}`);
    }
  }
}
