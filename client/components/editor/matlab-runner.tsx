"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, Play, X, Code2 } from "lucide-react"
import { api } from "@/lib/api"
import { useEditorStore } from "@/lib/editor-store"

const PLACEHOLDER = `# NumPy, SciPy, and Matplotlib are pre-imported.
# Use plt.plot(), plt.show() — the figure is captured automatically.

import numpy as np
import matplotlib.pyplot as plt

x = np.linspace(0, 2 * np.pi, 400)
y = np.sin(x) * np.exp(-0.3 * x)

plt.figure(figsize=(7, 3.5))
plt.plot(x, y, color="#4f46e5", lw=2)
plt.title("Damped sine wave")
plt.xlabel("x")
plt.ylabel("y")
plt.tight_layout()`

interface Props {
  editor: any
}

export function PythonVisualRunner({ editor }: Props) {
  const { pyVisTargetBlockId, closePyVis } = useEditorStore()
  const [code, setCode] = useState(PLACEHOLDER)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const isOpen = pyVisTargetBlockId !== null

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => textareaRef.current?.focus(), 80)
    }
  }, [isOpen])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && isOpen) closePyVis()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [isOpen, closePyVis])

  async function run() {
    if (loading || !code.trim()) return
    setError(null)
    setLoading(true)

    try {
      const result = await api.runPythonVisual(code)
      const targetId = pyVisTargetBlockId
      const outputBlock = {
        type: "matlabOutput" as const,
        props: {
          code,
          imageBase64: result.image_base64 ?? "",
          stdout: result.output ?? "",
          error: result.error ?? "",
        },
      }

      const doc = editor.document as Array<{ id: string }>
      const ref = doc.find((b) => b.id === targetId) ?? doc[doc.length - 1]
      if (ref) {
        editor.insertBlocks([outputBlock], ref, "after")
      }
      closePyVis()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-[680px] max-w-[95vw] max-h-[90vh] bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-gray-900 rounded-t-2xl shrink-0">
          <div className="flex items-center gap-2">
            <Code2 className="w-4 h-4 text-green-400" />
            <span className="text-sm font-semibold text-green-400 font-mono">
              Python Visualization
            </span>
          </div>
          <button
            onClick={closePyVis}
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Info bar */}
        <div className="px-4 py-2 bg-gray-800 text-[10px] text-gray-400 font-mono shrink-0">
          numpy · scipy · matplotlib pre-imported &nbsp;·&nbsp; max 20 s execution &nbsp;·&nbsp;
          <span className="text-blue-400">⌘↵</span> to run
        </div>

        {/* Code editor */}
        <div className="flex-1 min-h-0 overflow-hidden bg-gray-950">
          <textarea
            ref={textareaRef}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault()
                run()
              }
            }}
            spellCheck={false}
            className="w-full h-full min-h-[320px] resize-none bg-transparent text-gray-200 font-mono text-sm px-4 py-3 outline-none leading-relaxed"
          />
        </div>

        {/* Error */}
        {error && (
          <div className="px-4 py-2 bg-red-950 text-red-300 text-xs font-mono shrink-0 border-t border-red-900 whitespace-pre-wrap max-h-28 overflow-y-auto">
            {error}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100 bg-white shrink-0">
          <p className="text-[10px] text-gray-400">
            Results are embedded directly into your document as a block.
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={closePyVis}
              className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={run}
              disabled={loading || !code.trim()}
              className="flex items-center gap-1.5 text-xs font-medium bg-gray-900 text-white px-4 py-1.5 rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
            >
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5 fill-current" />
              )}
              {loading ? "Running…" : "Run"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
