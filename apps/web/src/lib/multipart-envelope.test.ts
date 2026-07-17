import { describe, expect, it } from "vitest";

import {
  MULTIPART_ENVELOPE_LIMIT_BYTES,
  validateMultipartEnvelopeHeaders,
} from "./multipart-envelope";

function multipartHeaders(contentLength?: string): Headers {
  const headers = new Headers({
    "content-type": "multipart/form-data; boundary=phase0",
  });
  if (contentLength !== undefined) {
    headers.set("content-length", contentLength);
  }
  return headers;
}

describe("validateMultipartEnvelopeHeaders", () => {
  it("requires multipart callers to declare the envelope length", () => {
    expect(validateMultipartEnvelopeHeaders(multipartHeaders())).toEqual({
      detail: "multipart content-length is required",
      status: 411,
    });
  });

  it("rejects malformed and over-limit envelope lengths", () => {
    expect(
      validateMultipartEnvelopeHeaders(multipartHeaders("not-a-number")),
    ).toEqual({
      detail: "invalid content-length",
      status: 400,
    });
    expect(
      validateMultipartEnvelopeHeaders(
        multipartHeaders(String(MULTIPART_ENVELOPE_LIMIT_BYTES + 1)),
      ),
    ).toEqual({
      detail: "multipart envelope exceeds proxy limit",
      status: 413,
    });
  });

  it("allows the configured envelope and leaves non-multipart bodies alone", () => {
    expect(
      validateMultipartEnvelopeHeaders(
        multipartHeaders(String(MULTIPART_ENVELOPE_LIMIT_BYTES)),
      ),
    ).toBeNull();
    expect(
      validateMultipartEnvelopeHeaders(
        new Headers({ "content-type": "application/json" }),
      ),
    ).toBeNull();
  });
});
