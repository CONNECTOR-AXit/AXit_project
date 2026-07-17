import type { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

describe("Phase 0 streaming proxy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("passes the original multipart ReadableStream to upstream fetch", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://api:8000");
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("phase0-stream-probe"));
        controller.close();
      },
    });
    const request = {
      body,
      headers: new Headers({
        "content-length": "128",
        "content-type": "multipart/form-data; boundary=phase0",
        host: "localhost:3000",
        origin: "http://localhost:3000",
      }),
      method: "POST",
      nextUrl: new URL(
        "http://localhost:3000/api/__phase0/upload?stream=identity",
      ),
      signal: new AbortController().signal,
    } as unknown as NextRequest;
    let forwardedInit: RequestInit | undefined;
    const fetchMock = vi.fn(
      async (target: string | URL | Request, init?: RequestInit) => {
        expect(String(target)).toBe(
          "http://api:8000/api/__phase0/upload?stream=identity",
        );
        forwardedInit = init;
        return Response.json(
          { bytes_received: 20 * 1024 * 1024, sha256: "fixture" },
          { headers: { "x-phase0-upstream": "api" } },
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(request);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(forwardedInit?.body).toBe(body);
    expect(
      (forwardedInit as RequestInit & { duplex?: string }).duplex,
    ).toBe("half");
    expect(response.headers.get("x-phase0-upstream")).toBe("api");
  });
});
