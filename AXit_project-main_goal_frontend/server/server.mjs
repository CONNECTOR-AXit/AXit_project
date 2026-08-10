import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { extname, relative, resolve, sep } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createGateway, parseInternalApiOrigin } from "./gateway.mjs";
import { validateRequestBodyEnvelopeHeaders } from "./multipart-envelope.mjs";
import {
  sanitizeProxyRequestHeaders,
  sanitizeProxyResponseHeaders,
} from "./proxy-headers.mjs";

const BODYLESS_METHODS = new Set(["GET", "HEAD"]);
const CONTENT_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".txt", "text/plain; charset=utf-8"],
  [".webp", "image/webp"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);

const DEFAULT_DIST_DIR = fileURLToPath(new URL("../dist/", import.meta.url));
const DEFAULT_PROXY_INACTIVITY_TIMEOUT_MS = 30_000;
const MAX_TIMER_DELAY_MS = 2_147_483_647;
const STATIC_SECURITY_HEADERS = {
  "content-security-policy": "frame-ancestors 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
};

function incomingHeaders(request) {
  const headers = new Headers();
  for (let index = 0; index < request.rawHeaders.length; index += 2) {
    headers.append(request.rawHeaders[index], request.rawHeaders[index + 1]);
  }
  return headers;
}

function toWebRequest(request) {
  const host = request.headers.host ?? "localhost";
  const method = (request.method ?? "GET").toUpperCase();
  const init = {
    headers: incomingHeaders(request),
    method,
  };
  if (!BODYLESS_METHODS.has(method)) {
    init.body = Readable.toWeb(request);
    init.duplex = "half";
  }
  return new Request(`http://${host}${request.url ?? "/"}`, init);
}

async function writeWebResponse(response, outgoing, method = "GET") {
  outgoing.statusCode = response.status;
  outgoing.statusMessage = response.statusText;

  for (const [name, value] of response.headers) {
    if (name.toLowerCase() !== "set-cookie") outgoing.setHeader(name, value);
  }
  const setCookies = response.headers.getSetCookie();
  if (setCookies.length > 0) outgoing.setHeader("set-cookie", setCookies);

  if (method === "HEAD" || response.body === null) {
    outgoing.end();
    return;
  }
  await pipeline(Readable.fromWeb(response.body), outgoing);
}

function headersFromIncoming(message) {
  const headers = new Headers();
  for (const [name, values] of Object.entries(message.headersDistinct)) {
    for (const value of values) headers.append(name, value);
  }
  return headers;
}

function writeJsonError(response, status, detail) {
  const body = JSON.stringify({ detail });
  response.writeHead(status, {
    "content-length": Buffer.byteLength(body),
    "content-type": "application/json",
  });
  response.end(body);
}

function normalizeProxyTimeoutMs(value) {
  if (value === undefined || value === null || value === "") {
    return DEFAULT_PROXY_INACTIVITY_TIMEOUT_MS;
  }
  const timeout = Number(value);
  if (!Number.isSafeInteger(timeout) || timeout <= 0) {
    return DEFAULT_PROXY_INACTIVITY_TIMEOUT_MS;
  }
  return Math.min(timeout, MAX_TIMER_DELAY_MS);
}

async function proxyApiRequest(
  request,
  response,
  internalApiOrigin,
  proxyTimeoutMs,
) {
  const method = (request.method ?? "GET").toUpperCase();
  const incoming = incomingHeaders(request);
  if (!BODYLESS_METHODS.has(method)) {
    const envelopeError = validateRequestBodyEnvelopeHeaders(incoming);
    if (envelopeError !== null) {
      writeJsonError(response, envelopeError.status, envelopeError.detail);
      return;
    }
  }
  if (internalApiOrigin === null) {
    writeJsonError(response, 500, "internal API origin is not configured");
    return;
  }

  // Only forward the request path and query. `request.url` may use the
  // HTTP absolute-form when a client talks directly to this server; passing
  // it as-is to `new URL()` would let the client replace the trusted API host
  // and turn this gateway into an SSRF proxy.
  const incomingUrl = new URL(request.url ?? "/", "http://localhost");
  const target = new URL(
    `${incomingUrl.pathname}${incomingUrl.search}`,
    internalApiOrigin,
  );
  const requestImpl = target.protocol === "https:" ? httpsRequest : httpRequest;
  const headers = Object.fromEntries(
    sanitizeProxyRequestHeaders(incoming).entries(),
  );

  await new Promise((resolvePromise) => {
    let settled = false;
    let timedOut = false;
    let timeout;
    let activeUpstreamResponse;
    const resetTimeout = () => {
      if (settled) return;
      clearTimeout(timeout);
      timeout = setTimeout(onTimeout, proxyTimeoutMs);
      timeout.unref();
    };
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      request.off("aborted", abortUpstream);
      request.off("data", resetTimeout);
      response.off("close", closeUpstream);
      upstream.off("finish", resetTimeout);
      activeUpstreamResponse?.off("data", resetTimeout);
      resolvePromise();
    };
    const abortUpstream = () => {
      upstream.destroy();
      finish();
    };
    const closeUpstream = () => {
      if (!response.writableEnded) abortUpstream();
    };
    const onTimeout = () => {
      if (settled) return;
      timedOut = true;
      request.unpipe(upstream);
      if (!request.readableEnded && !request.destroyed) request.resume();
      if (!response.destroyed) {
        if (!response.headersSent) {
          for (const name of response.getHeaderNames()) response.removeHeader(name);
          response.statusMessage = "Gateway Timeout";
          writeJsonError(response, 504, "internal API request timed out");
        } else if (!response.writableEnded) {
          response.destroy();
        }
      }
      upstream.destroy(new Error("internal API request timed out"));
      finish();
    };
    const upstream = requestImpl(
      target,
      { headers, method },
      async (upstreamResponse) => {
        if (settled) {
          upstreamResponse.destroy();
          return;
        }
        activeUpstreamResponse = upstreamResponse;
        upstreamResponse.on("data", resetTimeout);
        resetTimeout();
        response.statusCode = upstreamResponse.statusCode ?? 502;
        response.statusMessage = upstreamResponse.statusMessage ?? "";
        const sanitized = sanitizeProxyResponseHeaders(
          headersFromIncoming(upstreamResponse),
        );
        for (const [name, value] of sanitized) {
          if (name.toLowerCase() !== "set-cookie") response.setHeader(name, value);
        }
        const setCookies = sanitized.getSetCookie();
        if (setCookies.length > 0) response.setHeader("set-cookie", setCookies);
        try {
          await pipeline(upstreamResponse, response);
        } catch {
          if (timedOut) return;
          // A browser may cancel an API response during navigation or refresh.
          // This callback is not awaited by http.request, so consume the
          // pipeline rejection instead of allowing an unhandled rejection to
          // terminate the server.
          const clientAborted = request.aborted || response.destroyed;
          if (!clientAborted) {
            if (!response.headersSent) {
              writeJsonError(response, 502, "internal API response failed");
            } else {
              response.destroy();
            }
          }
        } finally {
          finish();
        }
      },
    );
    upstream.on("error", () => {
      if (settled) return;
      if (response.destroyed) {
        finish();
        return;
      }
      if (!response.headersSent) {
        writeJsonError(response, 502, "internal API unavailable");
      } else if (!response.writableEnded) {
        response.destroy();
      }
      finish();
    });
    request.once("aborted", abortUpstream);
    request.on("data", resetTimeout);
    response.once("close", closeUpstream);
    upstream.on("finish", resetTimeout);
    resetTimeout();
    if (BODYLESS_METHODS.has(method)) upstream.end();
    else request.pipe(upstream);
  });
}

export function resolveStaticPath(pathname, distDir = DEFAULT_DIST_DIR) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  if (
    decoded.includes("\0") ||
    decoded.includes("\\") ||
    decoded.split("/").includes("..")
  ) {
    return null;
  }

  const root = resolve(distDir);
  const candidate = resolve(root, `.${decoded}`);
  const fromRoot = relative(root, candidate);
  if (fromRoot === ".." || fromRoot.startsWith(`..${sep}`)) return null;
  return candidate;
}

async function regularFile(pathname) {
  try {
    const metadata = await stat(pathname);
    return metadata.isFile() ? metadata : null;
  } catch {
    return null;
  }
}

async function serveStatic(request, response, distDir) {
  for (const [name, value] of Object.entries(STATIC_SECURITY_HEADERS)) {
    response.setHeader(name, value);
  }
  const method = (request.method ?? "GET").toUpperCase();
  if (!BODYLESS_METHODS.has(method)) {
    response.writeHead(405, { allow: "GET, HEAD" }).end();
    return;
  }

  let url;
  try {
    url = new URL(request.url ?? "/", "http://localhost");
  } catch {
    response.writeHead(400).end();
    return;
  }

  const requestedPath = resolveStaticPath(url.pathname, distDir);
  if (requestedPath === null) {
    response.writeHead(400).end();
    return;
  }

  let filePath = requestedPath;
  let metadata = await regularFile(filePath);
  if (metadata === null) {
    if (extname(url.pathname) !== "") {
      response.writeHead(404).end();
      return;
    } else {
      filePath = resolve(distDir, "index.html");
      metadata = await regularFile(filePath);
    }
  }
  if (metadata === null) {
    response.writeHead(404).end();
    return;
  }

  response.statusCode = 200;
  response.setHeader("content-length", metadata.size);
  response.setHeader(
    "content-type",
    CONTENT_TYPES.get(extname(filePath).toLowerCase()) ??
      "application/octet-stream",
  );
  response.setHeader(
    "cache-control",
    filePath.endsWith(`${sep}index.html`)
      ? "no-store"
      : "public, max-age=31536000, immutable",
  );
  if (method === "HEAD") {
    response.end();
    return;
  }
  try {
    await pipeline(createReadStream(filePath), response);
  } catch (error) {
    // A browser can cancel an asset request during navigation, refresh, or a
    // deployment update. The response is already unusable in that case, but
    // the cancellation must not escape the request boundary and kill Node.
    if (request.aborted || response.destroyed) {
      return;
    }
    throw error;
  }
}

export function createProductionServer({
  distDir = DEFAULT_DIST_DIR,
  fetchImpl = fetch,
  internalApiUrl = process.env.INTERNAL_API_URL,
  proxyTimeoutMs = process.env.INTERNAL_API_TIMEOUT_MS,
} = {}) {
  const gateway = createGateway({ fetchImpl, internalApiUrl });
  const internalApiOrigin = parseInternalApiOrigin(internalApiUrl);
  const normalizedProxyTimeoutMs = normalizeProxyTimeoutMs(proxyTimeoutMs);

  return createServer(async (request, response) => {
    try {
      const pathname = new URL(
        request.url ?? "/",
        "http://localhost",
      ).pathname;
      if (
        pathname === "/health"
      ) {
        const webRequest = toWebRequest(request);
        await writeWebResponse(await gateway(webRequest), response, webRequest.method);
        return;
      }
      if (
        pathname === "/api" ||
        pathname.startsWith("/api/")
      ) {
        await proxyApiRequest(
          request,
          response,
          internalApiOrigin,
          normalizedProxyTimeoutMs,
        );
        return;
      }
      await serveStatic(request, response, distDir);
    } catch {
      if (request.aborted || response.destroyed) return;
      if (!response.headersSent) {
        response.writeHead(500, { "content-type": "application/json" });
      }
      if (!response.writableEnded) {
        response.end(JSON.stringify({ detail: "internal server error" }));
      }
    }
  });
}

export function startProductionServer({
  host = "0.0.0.0",
  port = Number(process.env.PORT ?? 3000),
  ...options
} = {}) {
  const server = createProductionServer(options);
  server.listen(port, host, () => {
    console.log(`AXit frontend listening on http://${host}:${port}`);
  });
  return server;
}

if (
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  startProductionServer();
}
