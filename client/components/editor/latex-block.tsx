"use client"

import { useEffect, useRef, useState } from "react"
import { Check, AlertCircle, Loader2, Pencil } from "lucide-react"
import { createReactBlockSpec } from "@blocknote/react"

// ---------------------------------------------------------------------------
// Renderer (used by the block spec)
// ---------------------------------------------------------------------------

function LatexRenderer({ block, editor }: { block: any; editor: any }) {
  const renderRef = useRef<HTMLDivElement>(null)
  const [editing, setEditing] = useState(!block.props.content)
  const [editValue, setEditValue] = useState<string>(block.props.content ?? "")
  const [katexStatus, setKatexStatus] = useState<"idle" | "ok" | "error">("idle")
  const [katexError, setKatexError] = useState("")

  // Sync editValue when props change externally (e.g. Cmd+K replacement)
  useEffect(() => {
    if (!editing) setEditValue(block.props.content ?? "")
  }, [block.props.content]) // eslint-disable-line

  // Render KaTeX in view mode
  useEffect(() => {
    if (editing || !renderRef.current) return
    const latex = (block.props.content ?? "").trim()
    if (!latex) { setKatexStatus("idle"); return }

    setKatexStatus("idle")
    import("katex").then((k) => {
      try {
        k.default.render(latex, renderRef.current!, {
          throwOnError: true,
          displayMode: true,
          trust: false,
        })
        setKatexStatus("ok")
      } catch (e) {
        setKatexStatus("error")
        setKatexError(e instanceof Error ? e.message : "LaTeX error")
        if (renderRef.current) renderRef.current.textContent = latex
      }
    })
  }, [block.props.content, editing])

  function commitEdit() {
    editor.updateBlock(block, { props: { ...block.props, content: editValue } })
    setEditing(false)
  }

  // ── Edit mode ──────────────────────────────────────────────────────────────
  if (editing) {
    return (
      <div className="w-full rounded-lg border border-blue-200 bg-blue-50/20 p-3 my-1">
        <textarea
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); commitEdit() }
            if (e.key === "Escape") { setEditValue(block.props.content ?? ""); setEditing(false) }
          }}
          autoFocus
          rows={3}
          placeholder="Enter LaTeX expression… e.g. \sum_{n=1}^{\infty} \frac{1}{n^2}"
          className="w-full resize-none bg-transparent font-mono text-sm text-gray-800 outline-none placeholder:text-gray-300"
        />
        {/* Live preview */}
        <div className="mt-3 border-t border-blue-100 pt-2">
          <span className="text-[9px] uppercase tracking-widest text-blue-400 font-medium">Preview</span>
          <div className="mt-1 overflow-x-auto min-h-[2.5rem] flex items-center">
            <InlinePreview latex={editValue} />
          </div>
        </div>
        <p className="mt-1 text-[9px] text-gray-400">⌘↵ to save · Esc to cancel · click outside to save</p>
      </div>
    )
  }

  // ── View mode ──────────────────────────────────────────────────────────────
  return (
    <div
      className="w-full group/latex cursor-pointer rounded px-1 py-2 hover:bg-gray-50/70 transition-colors my-0.5"
      onClick={() => setEditing(true)}
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 overflow-x-auto">
          {(block.props.content ?? "").trim() ? (
            <div ref={renderRef} />
          ) : (
            <span className="text-sm text-gray-300 italic">Empty LaTeX block — click to edit</span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover/latex:opacity-100 transition-opacity">
          {katexStatus === "ok" && <Check className="w-3 h-3 text-emerald-500" />}
          {katexStatus === "error" && (
            <span title={katexError}>
              <AlertCircle className="w-3 h-3 text-red-400 cursor-help" />
            </span>
          )}
          {katexStatus === "idle" && (block.props.content ?? "").trim() && (
            <Loader2 className="w-3 h-3 animate-spin text-gray-300" />
          )}
          <Pencil className="w-3 h-3 text-gray-300" />
        </div>
      </div>
    </div>
  )
}

// Inline KaTeX preview used in edit mode
function InlinePreview({ latex }: { latex: string }) {
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const l = latex.trim()
    if (!l) { ref.current.textContent = ""; return }
    import("katex").then((k) => {
      try {
        k.default.render(l, ref.current!, { throwOnError: false, displayMode: true })
      } catch {
        if (ref.current) ref.current.textContent = l
      }
    })
  }, [latex])

  if (!latex.trim()) {
    return <span className="text-xs text-gray-300 italic">Start typing to preview…</span>
  }
  return <span ref={ref} />
}

// ---------------------------------------------------------------------------
// BlockNote block spec export
// ---------------------------------------------------------------------------

export const LatexBlockSpec = createReactBlockSpec(
  {
    type: "latex" as const,
    propSchema: {
      content: { default: "" as string },
    },
    content: "none" as const,
  },
  { render: LatexRenderer }
)
