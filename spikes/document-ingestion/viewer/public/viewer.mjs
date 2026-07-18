const HASH_PATTERN = /^[0-9a-f]{64}$/u;
const PAYLOAD_PATTERN = /^\/fixtures\/[a-z0-9][a-z0-9-]*\.json$/u;
const statusNode = document.querySelector("[data-viewer-status]");
const titleNode = document.querySelector("[data-document-title]");
const metaNode = document.querySelector("[data-proof-meta]");
const listNode = document.querySelector("[data-citation-list]");
const stageNode = document.querySelector("[data-source-stage]");
const selectedHashNode = document.querySelector("[data-selected-anchor-hash]");
const selectedFingerprintNode = document.querySelector("[data-selected-text-fingerprint]");

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function requireObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value;
}

function validatePayload(payload) {
  requireObject(payload, "payload");
  const result = requireObject(payload.result, "payload.result");
  if (payload.ok !== true || !Array.isArray(result.blocks) || result.blocks.length === 0) {
    throw new TypeError("payload must contain a successful non-empty extraction result");
  }
  for (const [index, block] of result.blocks.entries()) {
    requireObject(block, `block ${index}`);
    requireObject(block.anchor, `block ${index} anchor`);
    requireObject(block.anchor.locator, `block ${index} locator`);
    if (!HASH_PATTERN.test(block.anchor_hash) || !HASH_PATTERN.test(block.anchor.text_fingerprint)) {
      throw new TypeError(`block ${index} has an invalid deterministic identity`);
    }
    if (typeof block.text !== "string") throw new TypeError(`block ${index} text must be a string`);
  }
  return result;
}

function locatorLabel(block) {
  const locator = block.anchor.locator;
  if (block.anchor.kind === "pdf_block") {
    return `page ${locator.page} · ${locator.block_id}`;
  }
  if (block.anchor.kind === "image_bbox") {
    return `${locator.image_id} · bbox ${locator.bbox.join(", ")}`;
  }
  const base = `section ${locator.section} · paragraph ${locator.paragraph}`;
  if (locator.table) {
    return `${base} · table ${locator.table.index} / block ${locator.table.block} / row ${locator.table.row} / cell ${locator.table.cell} / paragraph ${locator.table.paragraph}`;
  }
  if (locator.footnote) {
    return `${base} · footnote ${locator.footnote.index} / paragraph ${locator.footnote.paragraph}`;
  }
  return base;
}

function attachIdentity(target, block) {
  target.id = `target-${block.anchor_hash}`;
  target.dataset.sourceTarget = "";
  target.dataset.anchorHash = block.anchor_hash;
  target.dataset.textFingerprint = block.anchor.text_fingerprint;
  target.dataset.anchorKind = block.anchor.kind;
  target.setAttribute("tabindex", "-1");
  return target;
}

function renderMeta(result, payloadPath) {
  titleNode.textContent = payloadPath.slice("/fixtures/".length);
  const entries = [
    ["media type", result.media_type],
    ["parser", `${result.parser.name} ${result.parser.version}`],
    ["anchors", String(result.blocks.length)]
  ];
  for (const [term, description] of entries) {
    const wrapper = element("div");
    wrapper.append(element("dt", null, term), element("dd", null, description));
    metaNode.append(wrapper);
  }
}

function renderCitations(blocks) {
  for (const block of blocks) {
    const item = element("li");
    const button = element("button", "citation-button");
    button.type = "button";
    button.dataset.citation = block.anchor_hash;
    const content = element("span");
    content.append(
      element("span", "citation-text", block.text),
      element("span", "citation-path", locatorLabel(block))
    );
    button.append(content);
    button.addEventListener("click", () => selectAnchor(block.anchor_hash, true));
    item.append(button);
    listNode.append(item);
  }
}

function normalizedTarget(block) {
  const target = attachIdentity(element("div", "normalized-target", block.text), block);
  const [left, top, right, bottom] = block.anchor.locator.bbox;
  for (const value of [left, top, right, bottom]) {
    if (typeof value !== "number" || value < 0 || value > 1) {
      throw new TypeError("normalized bbox values must be within [0, 1]");
    }
  }
  if (right <= left || bottom <= top) throw new TypeError("normalized bbox must have positive area");
  target.style.left = `${left * 100}%`;
  target.style.top = `${top * 100}%`;
  target.style.width = `${(right - left) * 100}%`;
  target.style.height = `${(bottom - top) * 100}%`;
  return target;
}

function renderNormalizedSources(blocks, kind) {
  const groupKey = kind === "pdf_block" ? "page" : "image_id";
  const grouped = Map.groupBy(blocks, (block) => block.anchor.locator[groupKey]);
  for (const [group, groupBlocks] of grouped) {
    const surface = element(
      "div",
      `normalized-surface ${kind === "pdf_block" ? "pdf-surface" : "image-surface"}`
    );
    surface.dataset.normalizedSurface = String(group);
    surface.append(element("span", "surface-label", `${groupKey.replace("_", " ")} ${group}`));
    for (const block of groupBlocks) surface.append(normalizedTarget(block));
    stageNode.append(surface);
  }
}

function hwpTarget(block) {
  const target = attachIdentity(element("span", null, block.text), block);
  const locator = block.anchor.locator;
  target.dataset.parser = locator.parser;
  target.dataset.parserVersion = locator.parser_version;
  target.dataset.section = String(locator.section);
  target.dataset.paragraph = String(locator.paragraph);
  if (locator.table) {
    target.dataset.tableIndex = String(locator.table.index);
    target.dataset.tableBlock = String(locator.table.block);
    target.dataset.tableRow = String(locator.table.row);
    target.dataset.tableCell = String(locator.table.cell);
    target.dataset.tableParagraph = String(locator.table.paragraph);
  }
  if (locator.footnote) {
    target.dataset.footnoteIndex = String(locator.footnote.index);
    target.dataset.footnoteParagraph = String(locator.footnote.paragraph);
  }
  return target;
}

function renderStructuredSource(blocks, parser) {
  const documentSurface = element("article", "document-surface");
  documentSurface.dataset.structuredDocument = parser.name;
  const header = element("header");
  header.append(
    element("p", "section-label", `${parser.name} ${parser.version}`),
    element("h2", null, "회의 사전 브리핑 원문")
  );
  documentSurface.append(header);

  for (const block of blocks) {
    const locator = block.anchor.locator;
    const target = hwpTarget(block);
    if (locator.table) {
      const table = element("table");
      table.dataset.tableIndex = String(locator.table.index);
      table.dataset.tableBlock = String(locator.table.block);
      const row = element("tr");
      row.dataset.row = String(locator.table.row);
      const cell = element("td");
      cell.dataset.cell = String(locator.table.cell);
      cell.dataset.cellParagraph = String(locator.table.paragraph);
      cell.append(target);
      row.append(cell);
      table.append(row);
      documentSurface.append(table);
      continue;
    }
    if (locator.footnote) {
      const note = element("aside");
      note.dataset.footnoteIndex = String(locator.footnote.index);
      note.dataset.footnoteParagraph = String(locator.footnote.paragraph);
      note.append(element("strong", null, `각주 ${locator.footnote.index + 1}. `), target);
      documentSurface.append(note);
      continue;
    }
    const paragraph = element("p");
    paragraph.append(target);
    documentSurface.append(paragraph);
  }
  stageNode.append(documentSurface);
}

function selectAnchor(anchorHash, updateLocation) {
  if (!HASH_PATTERN.test(anchorHash)) return false;
  const target = document.getElementById(`target-${anchorHash}`);
  if (!target) return false;

  for (const selected of document.querySelectorAll("[data-source-target].is-selected")) {
    selected.classList.remove("is-selected");
  }
  for (const citation of document.querySelectorAll("[data-citation]")) {
    citation.setAttribute("aria-current", String(citation.dataset.citation === anchorHash));
  }
  target.classList.add("is-selected");
  selectedHashNode.textContent = anchorHash;
  selectedFingerprintNode.textContent = target.dataset.textFingerprint;
  if (updateLocation) {
    window.history.replaceState(null, "", `${location.pathname}${location.search}#anchor=${anchorHash}`);
  }
  target.scrollIntoView({ block: "center", behavior: "instant" });
  return true;
}

function requestedAnchor() {
  if (!location.hash.startsWith("#anchor=")) return null;
  const hash = location.hash.slice("#anchor=".length);
  return HASH_PATTERN.test(hash) ? hash : null;
}

async function start() {
  const payloadPath = new URL(location.href).searchParams.get("payload");
  if (payloadPath === null || !PAYLOAD_PATTERN.test(payloadPath)) {
    throw new TypeError("payload must be a same-origin /fixtures/*.json path");
  }
  const payloadUrl = new URL(payloadPath, location.origin);
  if (payloadUrl.origin !== location.origin) throw new TypeError("cross-origin payloads are forbidden");

  const response = await fetch(payloadUrl, {
    cache: "no-store",
    credentials: "omit",
    redirect: "error"
  });
  if (!response.ok) throw new Error(`payload request failed with HTTP ${response.status}`);
  const result = validatePayload(await response.json());
  renderMeta(result, payloadPath);
  renderCitations(result.blocks);

  const normalized = result.blocks.filter((block) =>
    ["pdf_block", "image_bbox"].includes(block.anchor.kind)
  );
  const structured = result.blocks.filter((block) => block.anchor.kind === "hwp_paragraph");
  if (normalized.length > 0) {
    const kinds = new Set(normalized.map((block) => block.anchor.kind));
    if (kinds.size !== 1) throw new TypeError("a normalized fixture must use one anchor kind");
    renderNormalizedSources(normalized, normalized[0].anchor.kind);
  }
  if (structured.length > 0) renderStructuredSource(structured, result.parser);
  if (normalized.length + structured.length !== result.blocks.length) {
    throw new TypeError("fixture contains an unsupported anchor kind");
  }

  const deepLinked = requestedAnchor();
  if (deepLinked !== null && !selectAnchor(deepLinked, false)) {
    throw new TypeError("deep-linked anchor does not exist in this payload");
  }
  statusNode.textContent = "Ready";
}

window.addEventListener("hashchange", () => {
  const anchorHash = requestedAnchor();
  if (anchorHash !== null) selectAnchor(anchorHash, false);
});

start().catch((error) => {
  statusNode.textContent = "Error";
  stageNode.replaceChildren(element("p", "error-card", error.message));
  console.error("G0 citation viewer failed", error);
});
