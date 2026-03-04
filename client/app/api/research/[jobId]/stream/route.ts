/**
 * Proxy streaming research synthesis from FastAPI:
 *   GET /research/jobs/{jobId}/stream
 * Preserves Vercel AI UI message stream headers.
 */

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export async function GET(
  _req: Request,
  { params }: { params: { jobId: string } }
) {
  const { jobId } = params;

  const res = await fetch(`${BACKEND}/research/jobs/${jobId}/stream`, {
    method: "GET",
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    return new Response(text, { status: res.status });
  }

  return new Response(res.body, {
    headers: {
      "Content-Type": res.headers.get("Content-Type") ?? "text/event-stream",
      "Cache-Control": res.headers.get("Cache-Control") ?? "no-cache",
      "Connection": res.headers.get("Connection") ?? "keep-alive",
      "x-vercel-ai-ui-message-stream":
        res.headers.get("x-vercel-ai-ui-message-stream") ?? "v1",
    },
  });
}

