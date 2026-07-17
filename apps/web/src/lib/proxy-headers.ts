const ORIGINAL_HOST_HEADER = "x-axit-original-host";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const PHASE0_REQUEST_HEADER_ALLOWLIST = new Set([
  "accept",
  "accept-encoding",
  "accept-language",
  "cache-control",
  "content-length",
  "content-type",
  "cookie",
  "if-match",
  "if-none-match",
  "origin",
  "pragma",
  "range",
  "user-agent",
  "x-csrf-token",
]);

function connectionHeaderTokens(headers: Headers): Set<string> {
  const connection = headers.get("connection");
  if (connection === null) {
    return new Set();
  }

  return new Set(
    connection
      .split(",")
      .map((token) => token.trim().toLowerCase())
      .filter(Boolean),
  );
}

/**
 * Build the only request-header set that may cross the web/API trust boundary.
 *
 * The browser-facing Host is carried in a dedicated header because fetch must
 * generate the actual Host for INTERNAL_API_URL. Any client-supplied copy of
 * that dedicated header, identity, authorization-context, or forwarding
 * metadata is discarded before the authoritative value is installed.
 */
export function sanitizeProxyRequestHeaders(incoming: Headers): Headers {
  const sanitized = new Headers();
  const originalHost = incoming.get("host");

  for (const [rawName, value] of incoming.entries()) {
    const name = rawName.toLowerCase();
    if (!PHASE0_REQUEST_HEADER_ALLOWLIST.has(name)) {
      continue;
    }
    sanitized.append(rawName, value);
  }

  if (originalHost !== null && originalHost.trim() !== "") {
    sanitized.set(ORIGINAL_HOST_HEADER, originalHost.trim());
  }

  return sanitized;
}

function responseConnectionHeaderTokens(headers: Headers): Set<string> {
  return connectionHeaderTokens(headers);
}

/**
 * Preserve end-to-end upstream response headers, including every Set-Cookie,
 * while removing hop-by-hop transport metadata that Next must regenerate.
 */
export function sanitizeProxyResponseHeaders(upstream: Headers): Headers {
  const sanitized = new Headers();
  const connectionTokens = responseConnectionHeaderTokens(upstream);

  for (const [rawName, value] of upstream.entries()) {
    const name = rawName.toLowerCase();
    if (
      name === "set-cookie" ||
      HOP_BY_HOP_HEADERS.has(name) ||
      connectionTokens.has(name)
    ) {
      continue;
    }
    sanitized.append(rawName, value);
  }

  const headersWithCookies = upstream as Headers & {
    getSetCookie?: () => string[];
  };
  const setCookies =
    headersWithCookies.getSetCookie?.() ??
    (upstream.get("set-cookie") === null
      ? []
      : [upstream.get("set-cookie") as string]);
  for (const cookie of setCookies) {
    sanitized.append("set-cookie", cookie);
  }

  return sanitized;
}
