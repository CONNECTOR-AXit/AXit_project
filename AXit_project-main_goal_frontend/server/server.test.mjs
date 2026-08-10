import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, it } from "node:test";
import { createServer, get } from "node:http";

import { createProductionServer } from "./server.mjs";

describe("production static server", () => {
  let baseUrl;
  let distDir;
  let server;

  before(async () => {
    distDir = await mkdtemp(join(tmpdir(), "axit-static-test-"));
    await writeFile(join(distDir, "index.html"), "<h1>AXit</h1>");
    await mkdir(join(distDir, "assets"));
    await writeFile(
      join(distDir, "assets", "Rooms-NEW12345.js"),
      "export default 'current rooms';",
    );
    server = createProductionServer({ distDir });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    baseUrl = `http://127.0.0.1:${server.address().port}`;
  });

  after(async () => {
    await new Promise((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
    await rm(distDir, { force: true, recursive: true });
  });

  it("sets anti-framing and content-sniffing headers on SPA responses", async () => {
    const response = await fetch(`${baseUrl}/rooms/example`);

    assert.equal(response.status, 200);
    assert.equal(
      response.headers.get("content-security-policy"),
      "frame-ancestors 'none'",
    );
    assert.equal(response.headers.get("x-content-type-options"), "nosniff");
    assert.equal(response.headers.get("referrer-policy"), "no-referrer");
    assert.equal(response.headers.get("x-frame-options"), "DENY");
    assert.equal(response.headers.get("cache-control"), "no-store");
  });

  it("does not attach static security headers to API responses", async () => {
    const response = await fetch(`${baseUrl}/api/meetings`);

    assert.equal(response.status, 500);
    assert.equal(response.headers.get("content-security-policy"), null);
    assert.equal(response.headers.get("x-frame-options"), null);
  });

  it("pins absolute-form API requests to the configured internal origin", async () => {
    let receivedPath;
    const upstream = createServer((request, response) => {
      receivedPath = request.url;
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true }));
    });
    await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    const proxy = createProductionServer({
      distDir,
      internalApiUrl: `http://127.0.0.1:${upstream.address().port}`,
    });
    await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));

    try {
      const response = await new Promise((resolve, reject) => {
        const request = get(
          {
            host: "127.0.0.1",
            port: proxy.address().port,
            path: "http://attacker.example/api/secret?probe=1",
          },
          (response) => {
            response.resume();
            response.once("end", () => resolve(response));
          },
        );
        request.on("error", reject);
      });
      assert.equal(response.statusCode, 200);
      assert.equal(receivedPath, "/api/secret?probe=1");
    } finally {
      await new Promise((resolve, reject) =>
        proxy.close((error) => (error ? reject(error) : resolve())),
      );
      await new Promise((resolve, reject) =>
        upstream.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });

  it("returns 404 for a stale hashed route chunk instead of serving different bytes", async () => {
    const response = await fetch(`${baseUrl}/assets/Rooms-OLD12345.js`);

    assert.equal(response.status, 404);
    assert.equal(response.headers.get("x-axit-asset-recovery"), null);
  });

  it("serves an exact known hashed asset with immutable caching", async () => {
    const response = await fetch(`${baseUrl}/assets/Rooms-NEW12345.js`);

    assert.equal(response.status, 200);
    assert.equal(await response.text(), "export default 'current rooms';");
    assert.equal(
      response.headers.get("cache-control"),
      "public, max-age=31536000, immutable",
    );
    assert.equal(response.headers.get("x-axit-asset-recovery"), null);
  });

  it("keeps unrelated missing assets as 404 responses", async () => {
    const response = await fetch(`${baseUrl}/assets/Unknown-OLD12345.js`);

    assert.equal(response.status, 404);
  });

  it("keeps serving after a client aborts a static asset response", async () => {
    const largeAsset = Buffer.alloc(8 * 1024 * 1024, 0x5a);
    await writeFile(join(distDir, "assets", "large.js"), largeAsset);

    await new Promise((resolve, reject) => {
      const request = get(`${baseUrl}/assets/large.js`, (response) => {
        response.once("data", () => {
          response.destroy();
          resolve();
        });
      });
      request.on("error", (error) => {
        if (error.code === "ECONNRESET") resolve();
        else reject(error);
      });
    });

    const response = await fetch(`${baseUrl}/login`);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "<h1>AXit</h1>");
  });

  it("streams a large API request to the upstream server byte-exact", async () => {
    const payload = Buffer.alloc(24 * 1024 * 1024, 0x5a);
    let received = 0;
    const upstream = createServer((request, response) => {
      request.on("data", (chunk) => {
        received += chunk.length;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ received }));
      });
    });
    await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    const proxy = createProductionServer({
      distDir,
      internalApiUrl: `http://127.0.0.1:${upstream.address().port}`,
    });
    await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));

    try {
      const response = await fetch(
        `http://127.0.0.1:${proxy.address().port}/api/upload`,
        {
          body: payload,
          headers: { "content-length": String(payload.length) },
          method: "POST",
        },
      );

      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { received: payload.length });
    } finally {
      await new Promise((resolve, reject) =>
        proxy.close((error) => (error ? reject(error) : resolve())),
      );
      await new Promise((resolve, reject) =>
        upstream.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });

  it("times out a never-ending upstream request and keeps serving", async () => {
    const upstream = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.flushHeaders();
      // Deliberately never send a response body or finish the request.
    });
    await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    const proxy = createProductionServer({
      distDir,
      internalApiUrl: `http://127.0.0.1:${upstream.address().port}`,
      proxyTimeoutMs: 50,
    });
    await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));

    try {
      const response = await fetch(
        `http://127.0.0.1:${proxy.address().port}/api/never`,
      );
      assert.equal(response.status, 504);
      assert.deepEqual(await response.json(), {
        detail: "internal API request timed out",
      });

      const health = await fetch(
        `http://127.0.0.1:${proxy.address().port}/login`,
      );
      assert.equal(health.status, 200);
      assert.equal(await health.text(), "<h1>AXit</h1>");
    } finally {
      await new Promise((resolve, reject) =>
        proxy.close((error) => (error ? reject(error) : resolve())),
      );
      await new Promise((resolve, reject) =>
        upstream.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });

  it("allows an active upstream response to exceed the inactivity timeout", async () => {
    const upstream = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "text/plain" });
      let chunksWritten = 0;
      const interval = setInterval(() => {
        response.write("chunk");
        chunksWritten += 1;
        if (chunksWritten === 6) {
          clearInterval(interval);
          response.end();
        }
      }, 20);
    });
    await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    const proxy = createProductionServer({
      distDir,
      internalApiUrl: `http://127.0.0.1:${upstream.address().port}`,
      proxyTimeoutMs: 50,
    });
    await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));

    try {
      const response = await fetch(
        `http://127.0.0.1:${proxy.address().port}/api/slow-stream`,
      );
      assert.equal(response.status, 200);
      assert.equal(await response.text(), "chunk".repeat(6));
    } finally {
      await new Promise((resolve, reject) =>
        proxy.close((error) => (error ? reject(error) : resolve())),
      );
      await new Promise((resolve, reject) =>
        upstream.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });

  it("keeps serving after a client aborts a proxied API response", async () => {
    const payload = Buffer.alloc(8 * 1024 * 1024, 0x5a);
    const upstream = createServer((_request, response) => {
      response.writeHead(200, {
        "content-length": String(payload.length),
        "content-type": "application/octet-stream",
      });
      response.write(payload.subarray(0, 1024));
      setTimeout(() => response.end(payload.subarray(1024)), 25);
    });
    await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
    const proxy = createProductionServer({
      distDir,
      internalApiUrl: `http://127.0.0.1:${upstream.address().port}`,
    });
    await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));

    try {
      await new Promise((resolve, reject) => {
        const request = get(
          `http://127.0.0.1:${proxy.address().port}/api/stream`,
          (response) => {
            response.once("data", () => {
              response.destroy();
              resolve();
            });
          },
        );
        request.on("error", (error) => {
          if (error.code === "ECONNRESET") resolve();
          else reject(error);
        });
      });

      const response = await fetch(
        `http://127.0.0.1:${proxy.address().port}/api/stream`,
      );
      assert.equal(response.status, 200);
      assert.equal((await response.arrayBuffer()).byteLength, payload.length);
    } finally {
      await new Promise((resolve, reject) =>
        proxy.close((error) => (error ? reject(error) : resolve())),
      );
      await new Promise((resolve, reject) =>
        upstream.close((error) => (error ? reject(error) : resolve())),
      );
    }
  });
});
