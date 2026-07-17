import type { NextRequest } from "next/server";

import {
  sanitizeProxyRequestHeaders,
  sanitizeProxyResponseHeaders,
} from "@/lib/proxy-headers";
import { validateMultipartEnvelopeHeaders } from "@/lib/multipart-envelope";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BODYLESS_METHODS = new Set(["GET", "HEAD"]);

type NodeStreamingRequestInit = RequestInit & {
  duplex?: "half";
};

function internalApiOrigin(): URL {
  const configured = process.env.INTERNAL_API_URL;
  if (configured === undefined || configured.trim() === "") {
    throw new Error("INTERNAL_API_URL is required");
  }

  const url = new URL(configured);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username !== "" ||
    url.password !== "" ||
    (url.pathname !== "" && url.pathname !== "/") ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw new Error("INTERNAL_API_URL must be an HTTP(S) origin");
  }
  return url;
}

function multipartEnvelopeError(request: NextRequest): Response | null {
  const error = validateMultipartEnvelopeHeaders(request.headers);
  return error === null
    ? null
    : Response.json({ detail: error.detail }, { status: error.status });
}

function upstreamUrl(request: NextRequest): URL {
  const apiOrigin = internalApiOrigin();
  return new URL(
    `${request.nextUrl.pathname}${request.nextUrl.search}`,
    apiOrigin,
  );
}

async function proxyToApi(request: NextRequest): Promise<Response> {
  const envelopeError = multipartEnvelopeError(request);
  if (envelopeError !== null) {
    return envelopeError;
  }

  let target: URL;
  try {
    target = upstreamUrl(request);
  } catch {
    return Response.json(
      { detail: "internal API origin is not configured" },
      { status: 500 },
    );
  }

  const method = request.method.toUpperCase();
  const init: NodeStreamingRequestInit = {
    cache: "no-store",
    headers: sanitizeProxyRequestHeaders(request.headers),
    method,
    redirect: "manual",
    signal: request.signal,
  };

  if (!BODYLESS_METHODS.has(method) && request.body !== null) {
    // Passing the ReadableStream through is the proof-critical behavior.
    // Do not replace this with request.formData(), json(), or arrayBuffer().
    init.body = request.body;
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch {
    return Response.json(
      { detail: "internal API unavailable" },
      { status: 502 },
    );
  }

  return new Response(upstream.body, {
    headers: sanitizeProxyResponseHeaders(upstream.headers),
    status: upstream.status,
    statusText: upstream.statusText,
  });
}

export function DELETE(request: NextRequest): Promise<Response> {
  return proxyToApi(request);
}

export function GET(request: NextRequest): Promise<Response> {
  return proxyToApi(request);
}

export function HEAD(request: NextRequest): Promise<Response> {
  return proxyToApi(request);
}

export function OPTIONS(request: NextRequest): Promise<Response> {
  return proxyToApi(request);
}

export function PATCH(request: NextRequest): Promise<Response> {
  return proxyToApi(request);
}

export function POST(request: NextRequest): Promise<Response> {
  return proxyToApi(request);
}

export function PUT(request: NextRequest): Promise<Response> {
  return proxyToApi(request);
}
