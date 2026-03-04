/**
 * Proxy to FastAPI POST /chat/stream.
 * Converts useChat body (messages + session_id, context) to HEAVEN stream API format.
 */

const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

function getContentFromMessage(m: { content?: string; parts?: Array<{ type: string; text?: string }> }): string {
  if (typeof m.content === "string") return m.content;
  if (Array.isArray(m.parts)) {
    return m.parts
      .filter((p): p is { type: string; text: string } => p.type === "text" && typeof p.text === "string")
      .map((p) => p.text)
      .join("");
  }
  return "";
}

export async function POST(req: Request) {
  const body = await req.json();
  const { messages = [], session_id, context } = body as {
    messages?: Array<{ role: string; content?: string; parts?: Array<{ type: string; text?: string }> }>;
    session_id?: string;
    context?: Record<string, unknown>;
  };

  const heavenMessages = messages.map((m) => ({
    role: m.role,
    content: getContentFromMessage(m),
  }));

  const res = await fetch(`${BACKEND}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: heavenMessages,
      session_id: session_id ?? undefined,
      context: context ?? undefined,
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
      "x-vercel-ai-ui-message-stream": res.headers.get("x-vercel-ai-ui-message-stream") ?? "v1",
    },
  });
}
