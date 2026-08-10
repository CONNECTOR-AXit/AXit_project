export const MULTIPART_ENVELOPE_LIMIT_BYTES = 201 * 1024 * 1024;

export function validateMultipartEnvelopeHeaders(headers) {
  const contentType = headers.get("content-type")?.toLowerCase();
  if (!contentType?.startsWith("multipart/form-data")) return null;

  return validateDeclaredLength(headers, {
    tooLargeDetail: "multipart envelope exceeds proxy limit",
    requiredDetail: "multipart content-length is required",
  });
}

export function validateRequestBodyEnvelopeHeaders(headers) {
  const multipartError = validateMultipartEnvelopeHeaders(headers);
  if (multipartError !== null) return multipartError;

  return validateDeclaredLength(headers, {
    tooLargeDetail: "request body exceeds proxy limit",
    requiredDetail: "content-length is required",
  });
}

function validateDeclaredLength(headers, { requiredDetail, tooLargeDetail }) {
  const rawContentLength = headers.get("content-length");
  if (rawContentLength === null) {
    return { detail: requiredDetail, status: 411 };
  }
  if (!/^[0-9]+$/.test(rawContentLength)) {
    return { detail: "invalid content-length", status: 400 };
  }

  const contentLength = Number(rawContentLength);
  if (
    !Number.isSafeInteger(contentLength) ||
    contentLength > MULTIPART_ENVELOPE_LIMIT_BYTES
  ) {
    return {
      detail: tooLargeDetail,
      status: 413,
    };
  }
  return null;
}
