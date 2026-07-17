import { describe, expect, it } from "vitest";

import { sanitizeProxyRequestHeaders } from "./proxy-headers";

describe("sanitizeProxyRequestHeaders", () => {
  it("preserves browser data but replaces trust-boundary metadata", () => {
    const incoming = new Headers({
      connection: "keep-alive, x-connection-private",
      "content-type": "application/json",
      cookie: "phase0_session=opaque",
      forwarded: "for=203.0.113.1;host=attacker.invalid",
      host: "localhost:3000",
      origin: "http://localhost:3000",
      "x-arbitrary-identity-claim": "admin",
      "x-axit-internal-secret": "leak",
      "x-axit-original-host": "attacker.invalid",
      "x-axit-room-id": "other-room",
      "x-authenticated-user": "admin",
      "x-connection-private": "remove-me",
      "x-csrf-token": "session-bound-token",
      "x-forwarded-host": "attacker.invalid",
      "x-internal-user-id": "admin",
      "x-principal": "admin",
      "x-role": "admin",
      "x-tenant-id": "other-tenant",
      "x-user-id": "attacker",
    });

    const sanitized = sanitizeProxyRequestHeaders(incoming);

    expect(sanitized.get("content-type")).toBe("application/json");
    expect(sanitized.get("cookie")).toBe("phase0_session=opaque");
    expect(sanitized.get("origin")).toBe("http://localhost:3000");
    expect(sanitized.get("x-csrf-token")).toBe("session-bound-token");
    expect(sanitized.get("x-axit-original-host")).toBe("localhost:3000");

    for (const removed of [
      "connection",
      "forwarded",
      "host",
      "x-arbitrary-identity-claim",
      "x-axit-internal-secret",
      "x-axit-room-id",
      "x-authenticated-user",
      "x-connection-private",
      "x-forwarded-host",
      "x-internal-user-id",
      "x-principal",
      "x-role",
      "x-tenant-id",
      "x-user-id",
    ]) {
      expect(sanitized.has(removed)).toBe(false);
    }
  });

  it("does not invent an original host when none was received", () => {
    const sanitized = sanitizeProxyRequestHeaders(
      new Headers({ cookie: "phase0_session=opaque" }),
    );

    expect(sanitized.get("x-axit-original-host")).toBeNull();
  });
});
