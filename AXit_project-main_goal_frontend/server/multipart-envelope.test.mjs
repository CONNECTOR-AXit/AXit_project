import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MULTIPART_ENVELOPE_LIMIT_BYTES,
  validateMultipartEnvelopeHeaders,
} from "./multipart-envelope.mjs";

function multipartHeaders(contentLength) {
  const headers = new Headers({
    "content-type": "multipart/form-data; boundary=phase0",
  });
  if (contentLength !== undefined) {
    headers.set("content-length", contentLength);
  }
  return headers;
}

describe("validateMultipartEnvelopeHeaders", () => {
  it("reserves a one MiB envelope above the 200 MiB file boundary", () => {
    assert.equal(MULTIPART_ENVELOPE_LIMIT_BYTES, 201 * 1024 * 1024);
  });

  it("requires multipart requests to declare their envelope length", () => {
    assert.deepEqual(validateMultipartEnvelopeHeaders(multipartHeaders()), {
      detail: "multipart content-length is required",
      status: 411,
    });
  });

  it("rejects a malformed multipart envelope length", () => {
    assert.deepEqual(
      validateMultipartEnvelopeHeaders(multipartHeaders("not-a-number")),
      { detail: "invalid content-length", status: 400 },
    );
  });

  it("rejects a multipart envelope above the configured limit", () => {
    assert.deepEqual(
      validateMultipartEnvelopeHeaders(
        multipartHeaders(String(MULTIPART_ENVELOPE_LIMIT_BYTES + 1)),
      ),
      { detail: "multipart envelope exceeds proxy limit", status: 413 },
    );
  });

  it("allows a multipart envelope exactly at the configured limit", () => {
    assert.equal(
      validateMultipartEnvelopeHeaders(
        multipartHeaders(String(MULTIPART_ENVELOPE_LIMIT_BYTES)),
      ),
      null,
    );
  });

  it("leaves non-multipart request bodies alone", () => {
    assert.equal(
      validateMultipartEnvelopeHeaders(
        new Headers({ "content-type": "application/json" }),
      ),
      null,
    );
  });
});
