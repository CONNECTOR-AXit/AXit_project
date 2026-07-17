export const MULTIPART_ENVELOPE_LIMIT_BYTES = 21 * 1024 * 1024;

export interface MultipartEnvelopeError {
  detail: string;
  status: 400 | 411 | 413;
}

/**
 * Validate only the outer transport envelope without reading the body.
 *
 * The extra MiB leaves room for multipart framing around an exact 20 MiB file.
 * FastAPI remains authoritative for the exact file-byte limit. Requiring a
 * declared length keeps the thin proxy bounded without buffering the stream.
 */
export function validateMultipartEnvelopeHeaders(
  headers: Headers,
): MultipartEnvelopeError | null {
  const contentType = headers.get("content-type")?.toLowerCase();
  if (!contentType?.startsWith("multipart/form-data")) {
    return null;
  }

  const rawContentLength = headers.get("content-length");
  if (rawContentLength === null) {
    return {
      detail: "multipart content-length is required",
      status: 411,
    };
  }
  if (!/^[0-9]+$/.test(rawContentLength)) {
    return {
      detail: "invalid content-length",
      status: 400,
    };
  }

  const contentLength = Number(rawContentLength);
  if (
    !Number.isSafeInteger(contentLength) ||
    contentLength > MULTIPART_ENVELOPE_LIMIT_BYTES
  ) {
    return {
      detail: "multipart envelope exceeds proxy limit",
      status: 413,
    };
  }
  return null;
}
