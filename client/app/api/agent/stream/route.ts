/**
 * Proxy to FastAPI POST /agent/stream (lightweight Agent synthesis, no external search).
 */

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export async function POST(req: Request) {
  const body = await req.json();
  const { query, staged_paper_ids = [], canvas_summary = "" } = body as {
    query: string;
    staged_paper_ids?: string[];
    canvas_summary?: string;
  };

  const res = await fetch(`${BACKEND}/agent/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      staged_paper_ids: staged_paper_ids ?? [],
      canvas_summary: canvas_summary ?? "",
    }),
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
