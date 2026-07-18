import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PUBLIC_ROOT = join(ROOT, "public");
const FIXTURE_ROOT = join(ROOT, "fixtures");
const PORT = readPort(process.argv.slice(2));

const STATIC_FILES = new Map([
  ["/", join(PUBLIC_ROOT, "index.html")],
  ["/index.html", join(PUBLIC_ROOT, "index.html")],
  ["/styles.css", join(PUBLIC_ROOT, "styles.css")],
  ["/viewer.mjs", join(PUBLIC_ROOT, "viewer.mjs")]
]);

const CONTENT_TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"]
]);

const SECURITY_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Security-Policy": [
    "default-src 'none'",
    "base-uri 'none'",
    "connect-src 'self'",
    "font-src 'self'",
    "form-action 'none'",
    "frame-ancestors 'none'",
    "img-src 'self' data:",
    "script-src 'self'",
    "style-src 'self'"
  ].join("; "),
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff"
};

function readPort(args) {
  const portIndex = args.indexOf("--port");
  const raw = portIndex === -1 ? "4173" : args[portIndex + 1];
  const port = Number(raw);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new TypeError(`invalid --port value: ${raw ?? "<missing>"}`);
  }
  return port;
}

function send(response, status, body, contentType = "text/plain; charset=utf-8", headOnly = false) {
  const bytes = Buffer.isBuffer(body) ? body : Buffer.from(body, "utf8");
  response.writeHead(status, {
    ...SECURITY_HEADERS,
    "Content-Length": bytes.byteLength,
    "Content-Type": contentType
  });
  response.end(headOnly ? undefined : bytes);
}

function fixturePath(pathname) {
  if (!/^\/fixtures\/[a-z0-9][a-z0-9-]*\.json$/u.test(pathname)) return null;
  const candidate = normalize(join(FIXTURE_ROOT, pathname.slice("/fixtures/".length)));
  return candidate.startsWith(`${FIXTURE_ROOT}${sep}`) ? candidate : null;
}

const server = createServer(async (request, response) => {
  const headOnly = request.method === "HEAD";
  if (request.method !== "GET" && !headOnly) {
    response.setHeader("Allow", "GET, HEAD");
    send(response, 405, "method not allowed\n", undefined, headOnly);
    return;
  }

  let url;
  try {
    url = new URL(request.url ?? "/", "http://127.0.0.1");
  } catch {
    send(response, 400, "bad request\n", undefined, headOnly);
    return;
  }

  if (url.pathname === "/healthz") {
    send(response, 200, '{"status":"ok"}\n', CONTENT_TYPES.get(".json"), headOnly);
    return;
  }

  const target = STATIC_FILES.get(url.pathname) ?? fixturePath(url.pathname);
  if (target === null || target === undefined) {
    send(response, 404, "not found\n", undefined, headOnly);
    return;
  }

  try {
    const body = await readFile(target);
    send(response, 200, body, CONTENT_TYPES.get(extname(target)), headOnly);
  } catch (error) {
    if (error?.code === "ENOENT") {
      send(response, 404, "not found\n", undefined, headOnly);
      return;
    }
    console.error("viewer static server read failure", error);
    send(response, 500, "internal error\n", undefined, headOnly);
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`G0 citation viewer listening on http://127.0.0.1:${PORT}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => server.close(() => process.exit(0)));
}
