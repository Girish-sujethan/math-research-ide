"use client"

import { Editor, createShapeId } from "@tldraw/tldraw"
import { Send, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import { useCanvasStore } from "@/lib/canvas-store"
import type { CanvasItem } from "@/lib/types"

interface Message {
  role: "user" | "assistant"
  content: string
}

interface Props {
  editor: Editor | null
}

function placeCardOnCanvas(item: CanvasItem, editor: Editor) {
  if (item.type === "research-job") return  // handled by research polling

  const vp = editor.getViewportPageBounds()
  const existingCount = editor.getCurrentPageShapes().filter(
    (s) => s.type === `${item.type}-card`
  ).length

  const id = createShapeId()
  const baseProps =
    item.type === "concept"
      ? {
          conceptId: item.id,
          name: item.name,
          conceptType: "theorem",
          latexStatement: "",
          leanStatus: "unverified",
          isLoading: true,
        }
      : {
          paperId: item.id,
          title: item.name,
          authors: [],
          abstract: "",
          arxivId: "",
          isLoading: false,
        }

  ;(editor as any).createShape({
    id,
    type: `${item.type}-card`,
    x: vp.center.x - 140,
    y: vp.center.y + existingCount * 210,
    props: { w: 280, h: item.type === "concept" ? 180 : 160, ...baseProps },
  })

  // Hydrate concept cards with full data after placement
  if (item.type === "concept") {
    api.getConcept(item.id)
      .then((concept) => {
        ;(editor as any).updateShape({
          id,
          type: "concept-card",
          props: {
            latexStatement: concept.latex_statement,
            conceptType: concept.concept_type,
            leanStatus: concept.lean_verification_status,
            isLoading: false,
          },
        })
      })
      .catch(() => {
        ;(editor as any).updateShape({ id, type: "concept-card", props: { isLoading: false } })
      })
  }
}

export function ChatPanel({ editor }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | undefined>()
  const [activeResearchJobs, setActiveResearchJobs] = useState<string[]>([])
  const endRef = useRef<HTMLDivElement>(null)

  const selectedConceptIds = useCanvasStore((s) => s.selectedConceptIds)
  const selectedPaperIds = useCanvasStore((s) => s.selectedPaperIds)
  const setSelected = useCanvasStore((s) => s.setSelected)

  // Poll active research jobs every 2 seconds
  useEffect(() => {
    if (activeResearchJobs.length === 0) return

    const interval = setInterval(async () => {
      const completed: string[] = []

      for (const jobId of activeResearchJobs) {
        try {
          const result = await api.getResearchStatus(jobId)

          if (result.status === "done") {
            completed.push(jobId)

            // Append HEAVEN-relevant note to chat (not the document content)
            const chatText = result.heaven_note ?? "Content added to document."
            setMessages((m) => [...m, { role: "assistant", content: chatText }])

            // Place discovered concepts on the canvas
            if (editor && result.concept_ids && result.concept_names) {
              for (let i = 0; i < result.concept_ids.length; i++) {
                placeCardOnCanvas(
                  { type: "concept", id: result.concept_ids[i], name: result.concept_names[i] ?? "" },
                  editor
                )
              }
            }

            // Place new papers on the canvas
            if (editor && result.paper_ids && result.paper_names) {
              for (let i = 0; i < result.paper_ids.length; i++) {
                placeCardOnCanvas(
                  { type: "paper", id: result.paper_ids[i], name: result.paper_names[i] ?? "" },
                  editor
                )
              }
            }

            setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50)

          } else if (result.status === "failed") {
            completed.push(jobId)
            const errMsg = result.error ?? "Unknown error"
            setMessages((m) => [
              ...m,
              { role: "assistant", content: `Research failed: ${errMsg}` },
            ])
          }
        } catch {
          // Transient polling error — will retry on next tick
        }
      }

      if (completed.length > 0) {
        setActiveResearchJobs((jobs) => jobs.filter((j) => !completed.includes(j)))
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [activeResearchJobs, editor])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput("")
    setMessages((m) => [...m, { role: "user", content: text }])
    setLoading(true)

    try {
      const context: Record<string, unknown> = {}
      if (selectedConceptIds.length > 0) context.concept_ids = selectedConceptIds
      if (selectedPaperIds.length > 0) context.paper_ids = selectedPaperIds

      const res = await api.chat(text, sessionId, Object.keys(context).length > 0 ? context : undefined)
      setSessionId(res.session_id)
      setMessages((m) => [...m, { role: "assistant", content: res.reply }])

      // Handle canvas items from response
      if (res.canvas_items?.length > 0) {
        const researchJobs: string[] = []
        for (const item of res.canvas_items) {
          if (item.type === "research-job") {
            researchJobs.push(item.id)
          } else if (editor) {
            placeCardOnCanvas(item, editor)
          }
        }
        if (researchJobs.length > 0) {
          setActiveResearchJobs((jobs) => [...jobs, ...researchJobs])
        }
      }
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `Error: ${err instanceof Error ? err.message : "Unknown error"}` },
      ])
    } finally {
      setLoading(false)
      setTimeout(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Context chips */}
      {(selectedConceptIds.length > 0 || selectedPaperIds.length > 0) && (
        <div className="flex flex-wrap gap-1.5 px-3 pt-2 pb-1 border-b border-gray-100">
          <span className="text-[10px] text-gray-400 w-full mb-0.5">Context:</span>
          {selectedConceptIds.map((id) => (
            <span
              key={id}
              className="flex items-center gap-1 text-[10px] bg-blue-100 text-blue-700 rounded-full px-2 py-0.5"
            >
              concept
              <button
                onClick={() =>
                  setSelected(
                    selectedConceptIds.filter((c) => c !== id),
                    selectedPaperIds
                  )
                }
              >
                <X className="w-2.5 h-2.5" />
              </button>
            </span>
          ))}
          {selectedPaperIds.map((id) => (
            <span
              key={id}
              className="flex items-center gap-1 text-[10px] bg-orange-100 text-orange-700 rounded-full px-2 py-0.5"
            >
              paper
              <button
                onClick={() =>
                  setSelected(
                    selectedConceptIds,
                    selectedPaperIds.filter((p) => p !== id)
                  )
                }
              >
                <X className="w-2.5 h-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Research in-progress banner */}
      {activeResearchJobs.length > 0 && (
        <div className="px-3 py-1.5 border-b border-purple-100 bg-purple-50 flex items-center gap-2">
          <div className="flex gap-0.5">
            <div className="w-1 h-1 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
            <div className="w-1 h-1 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
            <div className="w-1 h-1 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
          <span className="text-[10px] text-purple-600">
            Researching… ({activeResearchJobs.length} job{activeResearchJobs.length > 1 ? "s" : ""} running)
          </span>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 text-sm">
        {messages.length === 0 && (
          <p className="text-gray-400 text-xs text-center pt-8">
            Ask about any mathematical concept or paper.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[90%] rounded-2xl px-3 py-2 text-xs leading-relaxed ${
                m.role === "user"
                  ? "bg-blue-600 text-white rounded-br-sm"
                  : "bg-gray-100 text-gray-800 rounded-bl-sm"
              }`}
            >
              <pre className="whitespace-pre-wrap font-sans">{m.content}</pre>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl rounded-bl-sm px-3 py-2">
              <div className="flex gap-1">
                <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="px-3 pb-3 pt-2 border-t border-gray-100">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
            placeholder="Ask HEAVEN…"
            rows={2}
            className="flex-1 resize-none text-xs border border-gray-200 rounded-xl px-3 py-2 outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-200"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="p-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
