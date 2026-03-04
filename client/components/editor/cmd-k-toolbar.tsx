"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, X } from "lucide-react"
import { api } from "@/lib/api"
import { useEditorStore, getEditorRef } from "@/lib/editor-store"
import { useVaultStore } from "@/lib/vault-store"

export function CmdKToolbar() {
  const { cmdKBlockId, closeCmdK, setFactCheck } = useEditorStore()
  const { stagedPapers } = useVaultStore()
  const [instruction, setInstruction] = useState("")
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | undefined>()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    setInstruction("")
  }, [cmdKBlockId])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") closeCmdK()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [closeCmdK])

  async function submit() {
    if (!instruction.trim() || !cmdKBlockId || loading) return

    const editor = getEditorRef()
    if (!editor) return

    // Read current block content from BlockNote
    const doc = editor.document as Array<{ id: string; type: string; content: unknown; props?: Record<string, unknown> }>
    const block = doc.find((b) => b.id === cmdKBlockId)
    if (!block) return

    // Extract text content from the block
    let blockContent = ""
    if (block.type === "latex") {
      blockContent = String(block.props?.content ?? "")
    } else if (Array.isArray(block.content)) {
      blockContent = block.content
        .map((c: unknown) => {
          const node = c as { text?: string }
          return node.text ?? ""
        })
        .join("")
    }

    setLoading(true)
    try {
      const stagedIds = stagedPapers.map((p) => p.paper_id)
      const res = await api.chat(instruction, sessionId, {
        transform_mode: true,
        transform_content: blockContent,
        staged_paper_ids: stagedIds,
      })
      setSessionId(res.session_id)

      // Apply the suggestion: replace block content with AI reply
      const proposed = res.reply.trim()
      if (block.type === "latex") {
        editor.updateBlock(block, { props: { ...block.props, content: proposed } })
      } else if (block.type === "heading" || block.type === "paragraph" || block.type === "bulletListItem") {
        editor.updateBlock(block, { content: proposed })
      } else {
        // For any other type insert a new paragraph after
        editor.insertBlocks(
          [{ type: "paragraph" as const, content: proposed }],
          block,
          "after"
        )
      }
      closeCmdK()

      // Fire-and-forget fact-check on the new content (non-blocking)
      if (proposed.trim().length >= 20) {
        const stagedIds = stagedPapers.map((p) => p.paper_id)
        api.factCheck(proposed, stagedIds)
          .then((fc) => setFactCheck(fc))
          .catch(() => { /* silent — fact-check is best-effort */ })
      }
    } catch {
      // Keep toolbar open so user can retry
    } finally {
      setLoading(false)
    }
  }

  if (!cmdKBlockId) return null

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 bg-black/20 backdrop-blur-[2px]">
      <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 p-4 w-[520px] max-w-[92vw]">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-gray-700">Edit with AI</p>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-400 bg-gray-100 rounded px-1.5 py-0.5 font-mono">⌘K</span>
            <button onClick={closeCmdK} className="text-gray-400 hover:text-gray-600 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        <input
          ref={inputRef}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit() }
            if (e.key === "Escape") closeCmdK()
          }}
          placeholder="Describe how to transform this block…"
          className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2.5 outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-100 text-gray-800 placeholder:text-gray-300"
        />
        <div className="flex justify-end mt-3 gap-2">
          <button
            onClick={closeCmdK}
            className="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={loading || !instruction.trim()}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading && <Loader2 className="w-3 h-3 animate-spin" />}
            {loading ? "Generating…" : "Apply"}
          </button>
        </div>
      </div>
    </div>
  )
}
