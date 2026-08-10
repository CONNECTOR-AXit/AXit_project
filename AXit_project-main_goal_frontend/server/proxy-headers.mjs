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

const REQUEST_HEADER_ALLOWLIST = new Set([
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

function connectionHeaderTokens(headers) {
  const connection = headers.get("connection");
  if (connection === null) return new Set();

  return new Set(
    connection
      .split(",")
      .map((token) => token.trim().toLowerCase())
      .filter(Boolean),
  );
}

export function sanitizeProxyRequestHeaders(incoming) {
  const sanitized = new Headers();
  const originalHost = incoming.get("host");

  for (const [name, value] of incoming) {
    if (REQUEST_HEADER_ALLOWLIST.has(name.toLowerCase())) {
      sanitized.append(name, value);
    }
  }

  if (originalHost !== null && originalHost.trim() !== "") {
    sanitized.set(ORIGINAL_HOST_HEADER, originalHost.trim());
  }
  return sanitized;
}

export function sanitizeProxyResponseHeaders(upstream) {
  const sanitized = new Headers();
  const connectionTokens = connectionHeaderTokens(upstream);

  for (const [name, value] of upstream) {
    const normalizedName = name.toLowerCase();
    if (
      normalizedName === "set-cookie" ||
      HOP_BY_HOP_HEADERS.has(normalizedName) ||
      connectionTokens.has(normalizedName)
    ) {
      continue;
    }
    sanitized.append(name, value);
  }

  const setCookies =
    typeof upstream.getSetCookie === "function"
      ? upstream.getSetCookie()
      : upstream.get("set-cookie") === null
        ? []
        : [upstream.get("set-cookie")];
  for (const cookie of setCookies) sanitized.append("set-cookie", cookie);

  return sanitized;
}
