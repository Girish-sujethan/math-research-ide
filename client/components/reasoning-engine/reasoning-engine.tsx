"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport } from "ai"
import { Send, CheckCircle2, XCircle, HelpCircle, X, BookOpen, Microscope, Search } from "lucide-react"
import { api } from "@/lib/api"
import { useEditorStore, appendToDocument, getEditorContent, addEmbeddedImage } from "@/lib/editor-store"
import { useVaultStore } from "@/lib/vault-store"
import type { NudgeItem, FactCheckResponse, CanvasItem } from "@/lib/types"
import { ThinkingBlock } from "./thinking-block"
import { SourceChip } from "./source-chip"
import { ProactiveNudges } from "./proactive-nudges"
import { PaperDiscoveryPanel, type FindSearchKey } from "./paper-discovery-panel"
import { MathText } from "@/components/latex"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Mode = "ask" | "agent" | "find"

/** HEAVEN metadata streamed at end of reply (data-heaven part). */
interface HeavenMetadata {
  session_id: string
  sources: string[]
  canvas_items: CanvasItem[]
}

interface AgentCorrelation {
  concept_name: string
  concept_type: string
  paper_title: string
  paper_id: string
  distance: number
}

interface AgentRun {
  query: string
  jobId: string
  status: "running" | "done" | "failed"
  reasoning?: string
  report?: string
  heavenNote?: string
  conceptNames?: string[]
  error?: string
  verifyError?: string
  agentNudges?: NudgeItem[]
  correlations?: AgentCorrelation[]
}

// ---------------------------------------------------------------------------
// FactCheckCard (inline, appears after Cmd+K edits)
// ---------------------------------------------------------------------------

function FactCheckCard({ result, onDismiss }: { result: FactCheckResponse; onDismiss: () => void }) {
  const colorCls =
    result.verdict === "supported"    ? "bg-emerald-50 border-emerald-200 text-emerald-800"
    : result.verdict === "contradicted" ? "bg-red-50 border-red-200 text-red-800"
    : "bg-amber-50 border-amber-200 text-amber-800"

  const Icon =
    result.verdict === "supported"    ? CheckCircle2
    : result.verdict === "contradicted" ? XCircle
    : HelpCircle

  const label =
    result.verdict === "supported"    ? "Supported"
    : result.verdict === "contradicted" ? "Contradicted"
    : "Uncertain"

  return (
    <div className={`flex items-start gap-2 px-2.5 py-2 rounded-xl border text-[10px] leading-relaxed ${colorCls}`}>
      <Icon className="w-3.5 h-3.5 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <span className="font-semibold">{label}</span>
        {" · "}
        <span className="opacity-70">{Math.round(result.confidence * 100)}%</span>
        {" — "}
        <span>{result.explanation}</span>
      </div>
      <button onClick={onDismiss} className="shrink-0 opacity-40 hover:opacity-80 transition-opacity mt-0.5">
        <X className="w-3 h-3" />
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode config
// ---------------------------------------------------------------------------

/** Strip raw model headers (DOCUMENT_CONTENT: / HEAVEN_NOTE:) from streaming preview text. */
function stripModelHeaders(text: string): string {
  return text
    .replace(/^(?:#{1,3}\s*)?\*?\*?DOCUMENT[_ ]?CONTENT\*?\*?:?\s*/im, "")
    .replace(/\n(?:#{1,3}\s*)?\*?\*?HEAVEN[_ ]?NOTE\*?\*?:?\s*[\s\S]*$/im, "")
    .trim()
}

/**
 * Convert common markdown idioms to LaTeX equivalents so that agent output using
 * markdown (headings, bold) is rendered correctly even when the model slips.
 * Only converts patterns that are unambiguously markdown and safe to transform.
 */
function normalizeMarkdownToLatex(report: string): string {
  return report
    // Headings: ### → \subsubsection, ## → \subsection, # → \section
    .replace(/^###\s+(.+)$/gm, "\\subsubsection{$1}")
    .replace(/^##\s+(.+)$/gm, "\\subsection{$1}")
    .replace(/^#\s+(.+)$/gm, "\\section{$1}")
    // Bold: **text** → \textbf{text} (must not be inside math — skip if preceded by \ or $)
    .replace(/\*\*([^*\n]+)\*\*/g, "\\textbf{$1}")
}

const HEAVEN_PYTHON_BLOCK_RE = /\s*\\begin\{heaven_python\}\s*([\s\S]*?)\s*\\end\{heaven_python\}\s*/

/**
 * Replace each \begin{heaven_python}...\end{heaven_python} block in the report with the
 * result of running the code (figure with embedded image) or an error comment.
 * Ensures "Python visualization" requests produce an executed plot in the document, not raw code.
 */
async function processPythonBlocksInReport(report: string): Promise<string> {
  let result = report
  while (HEAVEN_PYTHON_BLOCK_RE.test(result)) {
    const match = result.match(HEAVEN_PYTHON_BLOCK_RE)
    if (!match) break
    const code = match[1].trim()
    const fullMatch = match[0]
    let replacement: string
    try {
      const res = await api.runPythonVisual(code)
      if (res.error || !res.image_base64) {
        const msg = (res.error || "No image produced").replace(/\n/g, " ").slice(0, 120)
        replacement = `% HEAVEN Python visualization failed: ${msg}\n`
      } else {
        const id = `pyvis-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        addEmbeddedImage(id, `data:image/png;base64,${res.image_base64}`)
        replacement = `\\begin{figure}[H]\n\\centering\n\\includegraphics[width=0.8\\linewidth]{${id}}\n\\caption{Python Visualization Output}\n\\end{figure}`
      }
    } catch (e) {
      const msg = (e instanceof Error ? e.message : "Execution failed").replace(/\n/g, " ").slice(0, 120)
      replacement = `% HEAVEN Python visualization error: ${msg}\n`
    }
    result = result.replace(fullMatch, replacement)
  }
  return result
}

const MODES: { key: Mode; label: string; icon: React.ReactNode; placeholder: string }[] = [
  {
    key: "agent",
    label: "Agent",
    icon: <Microscope className="w-3 h-3" />,
    placeholder: "Research a topic with HEAVEN…",
  },
  {
    key: "ask",
    label: "Ask",
    icon: <BookOpen className="w-3 h-3" />,
    placeholder: "Ask HEAVEN…",
  },
  {
    key: "find",
    label: "Find",
    icon: <Search className="w-3 h-3" />,
    placeholder: "Find papers about…",
  },
]

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  className?: string
}

export function ReasoningEngine({ className }: Props) {
  const { lastFactCheck, clearFactCheck, pendingChatContext, clearChatContext, pendingLineContext, clearLineContext } = useEditorStore()
  const { stagedPapers, pinnedConcepts } = useVaultStore()

  // When the user clicks "Add To Chat" in the editor, pre-fill the input
  useEffect(() => {
    if (!pendingChatContext) return
    setInput(`> ${pendingChatContext.trim()}\n\n`)
    setMode("ask")
    clearChatContext()
  }, [pendingChatContext]) // eslint-disable-line react-hooks/exhaustive-deps

  // When "Ask HEAVEN" is right-clicked in the editor, switch to Agent mode
  useEffect(() => {
    if (!pendingLineContext) return
    setMode("agent")
  }, [pendingLineContext]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Shared ─────────────────────────────────────────────────────────────────
  const [mode, setMode] = useState<Mode>("agent")
  const [input, setInput] = useState("")
  const [nudges, setNudges] = useState<NudgeItem[]>([])
  const nudgeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // ── Ask mode (Vercel AI SDK streaming) ───────────────────────────────────────
  const sessionIdRef = useRef<string | undefined>(undefined)
  const [lastHeavenMetadata, setLastHeavenMetadata] = useState<HeavenMetadata | null>(null)

  const {
    messages: chatMessages,
    sendMessage,
    status: chatStatus,
  } = useChat({
    transport: useMemo(() => new DefaultChatTransport({ api: "/api/chat" }), []),
    onData: useCallback((part: { type?: string; data?: unknown }) => {
      if (part.type === "data-heaven" && part.data && typeof part.data === "object" && "session_id" in part.data) {
        const d = part.data as HeavenMetadata
        sessionIdRef.current = d.session_id
        setLastHeavenMetadata(d)
      }
    }, []),
  })

  // ── Agent mode ─────────────────────────────────────────────────────────────
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([])
  // Map of jobId → {interval, timeout} for independent per-job polling
  const agentPolls = useRef<Map<string, { interval: ReturnType<typeof setInterval>; timeout: ReturnType<typeof setTimeout> }>>(new Map())

  // Auto-expand input when text wraps
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = "auto"
    const capped = Math.min(el.scrollHeight, 192) // ~max 8 lines
    el.style.height = `${capped}px`
  }, [input])

  // ── Find mode ──────────────────────────────────────────────────────────────
  const [findSearchKey, setFindSearchKey] = useState<FindSearchKey | null>(null)

  // ── Cleanup on unmount ─────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      agentPolls.current.forEach(({ interval, timeout }) => {
        clearInterval(interval)
        clearTimeout(timeout)
      })
    }
  }, [])

  // ── Nudges ─────────────────────────────────────────────────────────────────
  const fetchNudges = useCallback(async () => {
    if (stagedPapers.length === 0) { setNudges([]); return }
    const blocksPayload = getEditorContent()
    const stagedIds = stagedPapers.map(p => p.paper_id)
    try {
      const res = await api.getNudges(blocksPayload, stagedIds)
      setNudges(res.nudges)
    } catch {
      // silently ignore
    }
  }, [stagedPapers])

  useEffect(() => {
    if (nudgeTimerRef.current) clearTimeout(nudgeTimerRef.current)
    nudgeTimerRef.current = setTimeout(fetchNudges, 1200)
    return () => { if (nudgeTimerRef.current) clearTimeout(nudgeTimerRef.current) }
  }, [fetchNudges])

  // Refetch nudges when chat stream finishes
  const prevChatStatusRef = useRef(chatStatus)
  useEffect(() => {
    if (prevChatStatusRef.current !== "ready" && chatStatus === "ready") {
      fetchNudges()
    }
    prevChatStatusRef.current = chatStatus
  }, [chatStatus, fetchNudges])

  // ── Ask: send chat message (streaming via useChat) ──────────────────────────
  async function sendChat(text: string) {
    const lineCtx = pendingLineContext
    const lineRef = lineCtx
      ? (lineCtx.lineEnd ? `L${lineCtx.lineNum}–${lineCtx.lineEnd}` : `L${lineCtx.lineNum}`)
      : null
    const fullText = lineCtx
      ? `[Doc context — ${lineRef}]\n${lineCtx.fullText}\n\n${text}`
      : text
    if (lineCtx) clearLineContext()

    const stagedIds = stagedPapers.map(p => p.paper_id)
    let canvasSummary = getEditorContent()
      .map(b => `[${b.type}] ${b.content}`)
      .join("\n")
      .slice(0, 1800)
    if (pinnedConcepts.length > 0) {
      const pinSection = pinnedConcepts
        .map(c => `[PINNED ${c.concept_type.toUpperCase()} — "${c.paper_title}"]\n${c.name}: ${c.latex_statement}`)
        .join("\n\n")
      canvasSummary += `\n\n── PINNED CONCEPTS ──\n${pinSection}`
    }

    setLastHeavenMetadata(null)
    await sendMessage(
      { text: fullText },
      {
        body: {
          session_id: sessionIdRef.current,
          context: {
            staged_paper_ids: stagedIds,
            canvas_summary: canvasSummary,
          },
        },
      }
    )
    setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
  }

  // ── Agent: streaming synthesis (staged papers + model only, no external search) ──
  async function startAgent(query: string) {
    const jobId = `agent-${Date.now()}`
    setAgentRuns(prev => [...prev, { query, jobId, status: "running" }])

    const stagedIds = stagedPapers.map(p => p.paper_id)
    let canvasSummary = getEditorContent()
      .map(b => `[${b.type}] ${b.content}`)
      .join("\n")
      .slice(0, 1800)
    if (pinnedConcepts.length > 0) {
      const pinSection = pinnedConcepts
        .map(c => `[PINNED ${c.concept_type.toUpperCase()} — "${c.paper_title}"]\n${c.name}: ${c.latex_statement}`)
        .join("\n\n")
      canvasSummary += `\n\n── PINNED CONCEPTS ──\n${pinSection}`
    }

    // Buffer text-deltas and flush to state every 150ms
    // to avoid thousands of React state updates (one per token → OOM).
    let pendingText = ""
    let flushTimer: ReturnType<typeof setInterval> | null = null

    try {
      const res = await fetch("/api/agent/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          staged_paper_ids: stagedIds,
          canvas_summary: canvasSummary,
        }),
      })
      if (!res.ok) throw new Error(await res.text().catch(() => res.statusText))
      if (!res.body) throw new Error("No stream body")

      const reader = res.body.getReader()
      const decoder = new TextDecoder("utf-8")
      let buffer = ""

      let pendingReasoning = ""

      const flushPending = () => {
        const hasText = !!pendingText
        const hasReasoning = !!pendingReasoning
        if (!hasText && !hasReasoning) return
        const text = pendingText
        const reasoning = pendingReasoning
        pendingText = ""
        pendingReasoning = ""
        setAgentRuns(prev =>
          prev.map(r => {
            if (r.jobId !== jobId) return r
            const updates: Partial<AgentRun> = {}
            if (hasText) updates.report = (r.report ?? "") + text
            if (hasReasoning) updates.reasoning = (r.reasoning ?? "") + reasoning
            return { ...r, ...updates }
          }),
        )
      }
      flushTimer = setInterval(flushPending, 150)

      const updateRun = (updates: Partial<AgentRun>) => {
        setAgentRuns(prev =>
          prev.map(r => (r.jobId === jobId ? { ...r, ...updates } : r)),
        )
      }

      const processSSEPayload = (payload: string) => {
        if (payload === "[DONE]") return
        const obj = JSON.parse(payload)
        if (obj.type === "reasoning-delta" && typeof obj.delta === "string") {
          pendingReasoning += obj.delta
        } else if (obj.type === "text-delta" && typeof obj.delta === "string") {
          pendingText += obj.delta
        } else if (obj.type === "data-heaven-research" && obj.data) {
          const d = obj.data
          updateRun({
            heavenNote: d.heaven_note,
            conceptNames: d.concept_names,
          })
          if (d.report?.trim()) {
            processPythonBlocksInReport(normalizeMarkdownToLatex(d.report.trim())).then(processed => appendToDocument(processed))
          }
        } else if (obj.type === "data-heaven-verification" && obj.data) {
          updateRun({
            verifyError: obj.data.error,
          })
        } else if (obj.type === "data-heaven-nudges" && obj.data) {
          updateRun({ agentNudges: obj.data.nudges })
        } else if (obj.type === "data-heaven-correlation" && obj.data) {
          const items: AgentCorrelation[] = (obj.data.correlations ?? []).map((c: Record<string, unknown>) => ({
            concept_name: c.concept_name as string,
            concept_type: c.concept_type as string,
            paper_title: c.paper_title as string || "",
            paper_id: c.paper_id as string || "",
            distance: c.distance as number,
          }))
          updateRun({ correlations: items })
        } else if (obj.type === "error" && obj.errorText) {
          throw new Error(obj.errorText)
        }
      }

      while (true) {
        const { value, done } = await reader.read()
        if (value) buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n\n")
        buffer = lines.pop() ?? ""

        for (const block of lines) {
          const line = block.trim()
          if (!line.startsWith("data:")) continue
          const payload = line.slice(5).trim()
          try { processSSEPayload(payload) } catch (e) {
            if (e instanceof Error && e.message !== "Unexpected end of JSON input") throw e
          }
        }
        if (done) break
      }
      // Process remaining buffer
      if (buffer.trim()) {
        for (const line of buffer.trim().split("\n\n")) {
          const trimmed = line.trim()
          if (!trimmed.startsWith("data:")) continue
          const payload = trimmed.slice(5).trim()
          try { processSSEPayload(payload) } catch (e) {
            if (e instanceof Error && e.message !== "Unexpected end of JSON input") throw e
          }
        }
      }

      // Stop the flush timer and push any remaining buffered text
      if (flushTimer) clearInterval(flushTimer)
      flushPending()

      setAgentRuns(prev =>
        prev.map(r => (r.jobId === jobId ? { ...r, status: "done" } : r)),
      )
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
    } catch (err) {
      if (flushTimer) clearInterval(flushTimer)
      const message =
        err instanceof Error
          ? (err.message || "").toLowerCase().includes("failed to fetch") || (err.message || "").toLowerCase().includes("network")
            ? "Cannot reach the backend. Is the API server running on port 8000?"
            : err.message
          : "Streaming failed"
      setAgentRuns(prev =>
        prev.map(r =>
          r.jobId === jobId ? { ...r, status: "failed", error: message } : r,
        ),
      )
    }
  }

  // ── Unified submit ─────────────────────────────────────────────────────────
  async function handleSubmit() {
    const text = input.trim()
    if (!text) return
    setInput("")

    if (mode === "ask")   await sendChat(text)
    else if (mode === "agent") await startAgent(text)
    else if (mode === "find")  setFindSearchKey({ query: text, t: Date.now() })
  }

  function dismissNudge(i: number) {
    setNudges(n => n.filter((_, idx) => idx !== i))
  }

  const chatLoading = chatStatus === "streaming" || chatStatus === "submitted"
  const isSubmitDisabled = !input.trim() || (mode === "ask" && chatLoading)
  const activeModeConfig = MODES.find(m => m.key === mode)!

  // ── render (Cursor-like chat pane) ─────────────────────────────────────────
  const ThinkingDots = () => (
    <div className="flex items-center gap-1.5 text-[11px] text-gray-500">
      <span className="animate-pulse">Thinking</span>
      <span className="flex gap-0.5">
        <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
        <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
        <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
      </span>
    </div>
  )

  return (
    <div className={`flex flex-col bg-[#fafafa] ${className ?? ""}`}>

      <div className="border-b border-gray-200/80 flex-shrink-0" />

      {stagedPapers.length === 0 && (
        <div className="mx-3 mt-2 px-2 py-1.5 bg-amber-50/80 border border-amber-200/80 rounded-lg flex-shrink-0">
          <p className="text-[10px] text-amber-700">Stage a source in the Knowledge Vault to ground responses.</p>
        </div>
      )}

      {lastFactCheck && (
        <div className="px-3 mt-2 flex-shrink-0">
          <FactCheckCard result={lastFactCheck} onDismiss={clearFactCheck} />
        </div>
      )}

      {nudges.length > 0 && (
        <div className="flex-shrink-0">
          <ProactiveNudges nudges={nudges} stagedPapers={stagedPapers} onDismiss={dismissNudge} />
        </div>
      )}

      {/* Message area */}
      <div className="flex-1 overflow-hidden relative min-h-0">

        {/* Ask: chat (streaming via useChat) */}
        <div className={`absolute inset-0 overflow-y-auto px-4 py-4 space-y-4 ${mode !== "ask" ? "hidden" : ""}`}>
          {chatMessages.length === 0 && (
            <div className="text-center pt-12 px-4 space-y-1">
              <p className="text-gray-400 text-xs">Ask anything. Right-click in the doc and choose Ask HEAVEN to send context.</p>
            </div>
          )}

          {chatMessages.map((m, i) => {
            const isLastAssistant = m.role === "assistant" && i === chatMessages.length - 1
            const sources = isLastAssistant && lastHeavenMetadata ? lastHeavenMetadata.sources : []
            let thinking: string | undefined
            let text = ""
            if ("parts" in m && Array.isArray(m.parts)) {
              for (const p of m.parts as Array<{ type?: string; text?: string }>) {
                if (p.type === "reasoning" && typeof p.text === "string") thinking = (thinking ?? "") + p.text
                if (p.type === "text" && typeof p.text === "string") text += p.text
              }
            }
            if (!text && typeof (m as unknown as { content?: string }).content === "string") text = (m as unknown as { content: string }).content

            return (
              <div key={m.id ?? i} className={m.role === "user" ? "flex justify-end" : "flex flex-col items-start gap-1"}>
                {m.role === "assistant" ? (
                  <>
                    {thinking && <ThinkingBlock thinking={thinking} />}
                    <div className="max-w-[85%] bg-[#f4f4f5] text-gray-800 rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-[13px] leading-relaxed">
                      <MathText text={text} className="whitespace-pre-wrap font-sans" />
                    </div>
                    {sources.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1 mt-1">
                        {sources.map(pid => (
                          <SourceChip key={pid} paperId={pid} stagedPapers={stagedPapers} />
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm px-3.5 py-2.5 text-[13px] leading-relaxed bg-[#2d3748] text-white">
                    <pre className="whitespace-pre-wrap font-sans">{text || (m as unknown as { content?: string }).content}</pre>
                  </div>
                )}
              </div>
            )
          })}

          {chatLoading && (
            <div className="flex justify-start">
              <div className="bg-[#f4f4f5] rounded-2xl rounded-tl-sm px-3.5 py-2.5">
                <ThinkingDots />
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {/* Agent */}
        <div className={`absolute inset-0 overflow-y-auto px-4 py-4 space-y-4 ${mode !== "agent" ? "hidden" : ""}`}>
          {agentRuns.length === 0 && (
            <div className="text-center pt-12 px-4">
              <p className="text-gray-400 text-xs">Agent edits your document automatically. Type a request and press Enter.</p>
            </div>
          )}

          {agentRuns.map((run, i) => (
            <div key={i} className="space-y-2">
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm px-3.5 py-2.5 text-[13px] leading-relaxed bg-[#2d3748] text-white">
                  <pre className="whitespace-pre-wrap font-sans">{run.query}</pre>
                </div>
              </div>

              {run.status === "running" && (
                <div className="flex justify-start flex-col gap-2 max-w-[90%]">
                  {/* Reasoning phase */}
                  {run.reasoning ? (
                    <div className="bg-blue-50/80 border border-blue-100 rounded-2xl rounded-tl-sm px-3.5 py-2.5">
                      <p className="text-[10px] font-medium text-blue-600 mb-1 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
                        Reasoning
                      </p>
                      <p className="text-[11px] text-blue-900/80 leading-relaxed whitespace-pre-wrap">
                        {run.reasoning}
                      </p>
                    </div>
                  ) : (
                    <div className="bg-[#f4f4f5] rounded-2xl rounded-tl-sm px-3.5 py-2.5">
                      <ThinkingDots />
                    </div>
                  )}
                  {/* Writing phase indicator */}
                  {run.report && (
                    <div className="bg-emerald-50/80 border border-emerald-100 rounded-2xl rounded-tl-sm px-3.5 py-2.5">
                      <p className="text-[10px] font-medium text-emerald-600 flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
                        Writing LaTeX to document...
                      </p>
                      <p className="text-[10px] text-emerald-700/60 mt-0.5">
                        {run.report.length} chars generated
                      </p>
                    </div>
                  )}
                </div>
              )}

              {run.status === "done" && (
                <div className="bg-[#f4f4f5] text-gray-800 rounded-2xl rounded-tl-sm px-3 py-2.5 text-xs leading-relaxed max-w-[90%]">
                  {/* Reasoning summary (collapsed) */}
                  {run.reasoning && (
                    <details className="mb-2">
                      <summary className="text-[10px] text-blue-600 cursor-pointer hover:text-blue-700 font-medium">
                        View reasoning
                      </summary>
                      <p className="mt-1 text-[10px] text-gray-600 leading-relaxed whitespace-pre-wrap border-l-2 border-blue-200 pl-2">
                        {run.reasoning}
                      </p>
                    </details>
                  )}
                  <p className="whitespace-pre-wrap font-sans">
                    {run.heavenNote ?? "Content added to document."}
                  </p>
                  {run.report && (
                    <p className="mt-1 text-[9px] text-emerald-600">
                      {run.report.length} chars of LaTeX inserted into document
                    </p>
                  )}
                  {run.conceptNames && run.conceptNames.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-gray-200/80 flex flex-wrap gap-1">
                      {run.conceptNames.slice(0, 6).map((name, j) => (
                        <span key={j} className="text-[8px] bg-white/80 text-gray-600 px-1.5 py-0.5 rounded">
                          {name}
                        </span>
                      ))}
                    </div>
                  )}
                  {(run.verifyError || (run.correlations && run.correlations.length > 0) || (run.agentNudges && run.agentNudges.length > 0)) && (
                    <div className="mt-2 pt-2 border-t border-gray-200/80 space-y-2">
                      {run.verifyError && (
                        <p className="text-[9px] text-amber-600">Verify: {run.verifyError}</p>
                      )}
                      {run.correlations && run.correlations.length > 0 && (() => {
                        const byPaper = new Map<string, AgentCorrelation[]>()
                        for (const c of run.correlations) {
                          const key = c.paper_title || c.paper_id || "Unknown paper"
                          if (!byPaper.has(key)) byPaper.set(key, [])
                          byPaper.get(key)!.push(c)
                        }
                        return (
                          <div className="space-y-1.5">
                            <p className="text-[9px] font-medium text-violet-700">
                              {run.correlations.length} correlation{run.correlations.length !== 1 ? "s" : ""} found
                            </p>
                            {Array.from(byPaper.entries()).map(([paperTitle, concepts], pidx) => (
                              <div key={pidx} className="bg-violet-50/80 border border-violet-200/60 rounded-lg px-2 py-1.5">
                                <p className="text-[9px] font-medium text-violet-800 truncate" title={paperTitle}>
                                  {paperTitle}
                                </p>
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {concepts.slice(0, 5).map((c, cidx) => {
                                    const dist = c.distance != null && typeof c.distance === "number" ? c.distance : 0
                                    const pct = Math.round((1 - dist) * 100)
                                    return (
                                      <span
                                        key={cidx}
                                        className="inline-flex items-center gap-0.5 text-[8px] bg-white/80 text-violet-700 border border-violet-200/60 px-1.5 py-0.5 rounded-full"
                                        title={`${c.concept_name} (${c.concept_type}) — ${pct}% match`}
                                      >
                                        <span className="w-1 h-1 rounded-full bg-violet-400 shrink-0" />
                                        {c.concept_name}
                                        <span className="text-violet-400 ml-0.5">{pct}%</span>
                                      </span>
                                    )
                                  })}
                                  {concepts.length > 5 && (
                                    <span className="text-[8px] text-violet-400 px-1 py-0.5">
                                      +{concepts.length - 5} more
                                    </span>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )
                      })()}
                      {run.agentNudges && run.agentNudges.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {run.agentNudges.slice(0, 3).map((n, j) => (
                            <span key={j} className="text-[8px] bg-amber-100/80 text-amber-800 px-1.5 py-0.5 rounded">
                              {n.message}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  <p className="mt-1.5 text-[9px] text-gray-400 italic">
                    {run.report?.trim() ? "Added to document." : "No document content was generated to insert."}
                  </p>
                </div>
              )}

              {run.status === "failed" && (
                <div className="bg-red-50 border border-red-200 rounded-xl rounded-tl-sm px-3 py-2.5 max-w-[85%]">
                  <p className="text-[11px] font-medium text-red-700">Something went wrong</p>
                  <p className="text-[10px] text-red-600 mt-0.5">{run.error ?? "Research failed"}</p>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Find: paper discovery panel (no input — driven by findSearchKey) */}
        <PaperDiscoveryPanel
          searchKey={findSearchKey}
          className={`absolute inset-0 flex flex-col overflow-hidden ${mode !== "find" ? "hidden" : ""}`}
        />
      </div>

      {pinnedConcepts.length > 0 && (
        <div className="px-3 pt-1.5 pb-1 border-t border-gray-200/80 flex-shrink-0">
          <p className="text-[9px] text-gray-400 mb-1">Pinned:</p>
          <div className="flex flex-wrap gap-1">
            {pinnedConcepts.map(pc => (
              <span key={pc.concept_id} className="text-[9px] bg-gray-200/80 text-gray-600 rounded px-2 py-0.5">
                {pc.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Input: Cursor-style single row */}
      <div className="px-3 py-2 border-t border-gray-200/80 flex-shrink-0 bg-[#fafafa]">
        {pendingLineContext && (
          <div className="flex items-center gap-1.5 mb-1.5 px-2 py-1 bg-[#f4f4f5] border border-gray-200/80 rounded-lg">
            <span className="text-[10px] font-mono text-gray-600 shrink-0">
              @doc · {pendingLineContext.lineEnd ? `L${pendingLineContext.lineNum}–${pendingLineContext.lineEnd}` : `L${pendingLineContext.lineNum}`}
            </span>
            <span className="text-[10px] text-gray-500 truncate flex-1 min-w-0 italic">{pendingLineContext.excerpt}</span>
            <button onClick={clearLineContext} className="shrink-0 text-gray-400 hover:text-gray-600" title="Remove context">
              <X className="w-3 h-3" />
            </button>
          </div>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-gray-200/80 bg-white focus-within:border-gray-300 focus-within:ring-1 focus-within:ring-gray-200">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                handleSubmit()
              }
            }}
            placeholder={activeModeConfig.placeholder}
            rows={1}
            className="flex-1 min-h-[36px] max-h-[192px] resize-none overflow-y-auto text-[13px] px-3 py-2 rounded-xl border-0 bg-transparent outline-none placeholder:text-gray-400"
          />
          <button
            onClick={handleSubmit}
            disabled={isSubmitDisabled}
            className="shrink-0 p-2 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors mb-0.5 mr-0.5"
            title="Send"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <div className="flex items-center gap-1 mt-2">
          {MODES.map(({ key, label, icon }) => (
            <button
              key={key}
              onClick={() => setMode(key)}
              className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-md font-medium transition-colors ${
                mode === key ? "bg-blue-100 text-blue-700" : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </div>
      </div>

    </div>
  )
}
