import { validateRequestBodyEnvelopeHeaders } from "./multipart-envelope.mjs";
import {
  sanitizeProxyRequestHeaders,
  sanitizeProxyResponseHeaders,
} from "./proxy-headers.mjs";

const BODYLESS_METHODS = new Set(["GET", "HEAD"]);

function jsonError(detail, status) {
  return Response.json({ detail }, { status });
}

export function parseInternalApiOrigin(configured) {
  if (typeof configured !== "string" || configured.trim() === "") return null;

  try {
    const url = new URL(configured);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username !== "" ||
      url.password !== "" ||
      (url.pathname !== "" && url.pathname !== "/") ||
      url.search !== "" ||
      url.hash !== ""
    ) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

export function createGateway({ internalApiUrl, fetchImpl = fetch } = {}) {
  const internalApiOrigin = parseInternalApiOrigin(internalApiUrl);

  return async function gateway(request) {
    const requestUrl = new URL(request.url);
    if (requestUrl.pathname === "/health") {
      return Response.json({ service: "web", status: "ok" });
    }

    if (
      requestUrl.pathname !== "/api" &&
      !requestUrl.pathname.startsWith("/api/")
    ) {
      return jsonError("not found", 404);
    }

    const method = request.method.toUpperCase();
    if (!BODYLESS_METHODS.has(method) && request.body !== null) {
      const envelopeError = validateRequestBodyEnvelopeHeaders(request.headers);
      if (envelopeError !== null) {
        return jsonError(envelopeError.detail, envelopeError.status);
      }
    }
    if (internalApiOrigin === null) {
      return jsonError("internal API origin is not configured", 500);
    }

    const target = new URL(
      `${requestUrl.pathname}${requestUrl.search}`,
      internalApiOrigin,
    );
    const init = {
      cache: "no-store",
      headers: sanitizeProxyRequestHeaders(request.headers),
      method,
      redirect: "manual",
      signal: request.signal,
    };
    if (!BODYLESS_METHODS.has(method) && request.body !== null) {
      init.body = request.body;
      init.duplex = "half";
    }

    let upstream;
    try {
      upstream = await fetchImpl(target, init);
    } catch {
      return jsonError("internal API unavailable", 502);
    }

    return new Response(upstream.body, {
      headers: sanitizeProxyResponseHeaders(upstream.headers),
      status: upstream.status,
      statusText: upstream.statusText,
    });
  };
}
