import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createGateway } from "./gateway.mjs";
import { MULTIPART_ENVELOPE_LIMIT_BYTES } from "./multipart-envelope.mjs";

describe("createGateway", () => {
  it("returns a healthy response without calling the upstream API", async () => {
    let upstreamCalls = 0;
    const gateway = createGateway({
      internalApiUrl: "http://api:8000",
      fetchImpl: async () => {
        upstreamCalls += 1;
        return new Response();
      },
    });

    const response = await gateway(new Request("http://localhost:3000/health"));

    assert.equal(response.status, 200);
    assert.match(await response.text(), /ok/i);
    assert.equal(upstreamCalls, 0);
  });

  it("passes the original request stream and Node duplex mode upstream", async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("phase0-stream-probe"));
        controller.close();
      },
    });
    let forwardedTarget;
    let forwardedInit;
    const gateway = createGateway({
      internalApiUrl: "http://api:8000",
      fetchImpl: async (target, init) => {
        forwardedTarget = target;
        forwardedInit = init;
        return Response.json({ accepted: true });
      },
    });
    const request = new Request(
      "http://localhost:3000/api/__phase0/upload?stream=identity",
      {
        body,
        duplex: "half",
        headers: {
          "content-length": "128",
          "content-type": "multipart/form-data; boundary=phase0",
          host: "localhost:3000",
        },
        method: "POST",
      },
    );

    const response = await gateway(request);

    assert.equal(
      String(forwardedTarget),
      "http://api:8000/api/__phase0/upload?stream=identity",
    );
    assert.equal(forwardedInit.body, body);
    assert.equal(forwardedInit.duplex, "half");
    assert.equal(response.status, 200);
  });

  it("returns a safe 500 response for an invalid internal API origin", async () => {
    const gateway = createGateway({
      internalApiUrl: "file:///etc/passwd",
      fetchImpl: async () => {
        throw new Error("fetch must not be called");
      },
    });

    const response = await gateway(
      new Request("http://localhost:3000/api/meetings"),
    );

    assert.equal(response.status, 500);
    assert.deepEqual(await response.json(), {
      detail: "internal API origin is not configured",
    });
  });

  it("returns a safe 502 response when the upstream API is unavailable", async () => {
    const gateway = createGateway({
      internalApiUrl: "http://api:8000",
      fetchImpl: async () => {
        throw new Error("connect ECONNREFUSED api:8000");
      },
    });

    const response = await gateway(
      new Request("http://localhost:3000/api/meetings"),
    );

    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), {
      detail: "internal API unavailable",
    });
  });

  it("requires a declared length for every streamed request body", async () => {
    let upstreamCalls = 0;
    const gateway = createGateway({
      internalApiUrl: "http://api:8000",
      fetchImpl: async () => {
        upstreamCalls += 1;
        return new Response();
      },
    });
    const response = await gateway(
      new Request("http://localhost:3000/api/meetings", {
        body: "{}",
        method: "POST",
      }),
    );

    assert.equal(response.status, 411);
    assert.deepEqual(await response.json(), {
      detail: "content-length is required",
    });
    assert.equal(upstreamCalls, 0);
  });

  it("rejects malformed and oversized declared request bodies", async () => {
    const gateway = createGateway({ internalApiUrl: "http://api:8000" });
    const malformed = await gateway(
      new Request("http://localhost:3000/api/meetings", {
        body: "{}",
        headers: { "content-length": "unknown" },
        method: "POST",
      }),
    );
    const oversized = await gateway(
      new Request("http://localhost:3000/api/meetings", {
        body: "{}",
        headers: {
          "content-length": String(MULTIPART_ENVELOPE_LIMIT_BYTES + 1),
        },
        method: "POST",
      }),
    );

    assert.equal(malformed.status, 400);
    assert.deepEqual(await malformed.json(), {
      detail: "invalid content-length",
    });
    assert.equal(oversized.status, 413);
    assert.deepEqual(await oversized.json(), {
      detail: "request body exceeds proxy limit",
    });
  });
});
