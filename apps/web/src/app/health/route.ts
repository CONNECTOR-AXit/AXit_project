export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json(
    {
      service: "web",
      status: "ok",
    },
    {
      headers: {
        "cache-control": "no-store",
      },
    },
  );
}
