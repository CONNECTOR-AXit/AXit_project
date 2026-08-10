import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  sanitizeProxyRequestHeaders,
  sanitizeProxyResponseHeaders,
} from "./proxy-headers.mjs";

describe("sanitizeProxyRequestHeaders", () => {
  it("forwards only browser headers from the request allowlist", () => {
    const sanitized = sanitizeProxyRequestHeaders(
      new Headers({
        accept: "application/json",
        "content-type": "application/json",
        cookie: "phase0_session=opaque",
        origin: "http://localhost:3000",
        "x-arbitrary-identity-claim": "admin",
        "x-csrf-token": "session-bound-token",
        "x-forwarded-host": "attacker.invalid",
        "x-user-id": "attacker",
      }),
    );

    assert.deepEqual(Object.fromEntries(sanitized), {
      accept: "application/json",
      "content-type": "application/json",
      cookie: "phase0_session=opaque",
      origin: "http://localhost:3000",
      "x-csrf-token": "session-bound-token",
    });
  });

  it("replaces a spoofed original-host header with the received host", () => {
    const sanitized = sanitizeProxyRequestHeaders(
      new Headers({
        host: "localhost:3000",
        "x-axit-original-host": "attacker.invalid",
      }),
    );

    assert.equal(sanitized.get("x-axit-original-host"), "localhost:3000");
    assert.equal(sanitized.has("host"), false);
  });

  it("does not invent an original host when the request has no host", () => {
    const sanitized = sanitizeProxyRequestHeaders(
      new Headers({ cookie: "phase0_session=opaque" }),
    );

    assert.equal(sanitized.get("x-axit-original-host"), null);
  });
});

describe("sanitizeProxyResponseHeaders", () => {
  it("removes standard and connection-nominated hop-by-hop headers", () => {
    const sanitized = sanitizeProxyResponseHeaders(
      new Headers({
        connection: "keep-alive, x-upstream-private",
        "content-type": "application/json",
        "keep-alive": "timeout=5",
        "transfer-encoding": "chunked",
        "x-upstream-private": "remove-me",
      }),
    );

    assert.deepEqual(Object.fromEntries(sanitized), {
      "content-type": "application/json",
    });
  });

  it("preserves every Set-Cookie value from the upstream response", () => {
    const upstream = new Headers();
    upstream.append("set-cookie", "phase0_session=one; Path=/; HttpOnly");
    upstream.append("set-cookie", "csrf=two; Path=/; SameSite=Strict");

    const sanitized = sanitizeProxyResponseHeaders(upstream);

    assert.deepEqual(sanitized.getSetCookie(), [
      "phase0_session=one; Path=/; HttpOnly",
      "csrf=two; Path=/; SameSite=Strict",
    ]);
  });
});
