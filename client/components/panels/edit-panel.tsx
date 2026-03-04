"use client"

import { useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { EditorView, basicSetup } from "codemirror"
import { StreamLanguage } from "@codemirror/language"
import { stex } from "@codemirror/legacy-modes/mode/stex"
import { EditorState } from "@codemirror/state"
import { X, Save, Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import { useCanvasStore } from "@/lib/canvas-store"
import type { DiscoveryJobResult } from "@/lib/types"

interface Props {
  conceptId: string
}

export function EditPanel({ conceptId }: Props) {
  const setEditing = useCanvasStore((s) => s.setEditing)
  const editorRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const [latex, setLatex] = useState("")
  const [saving, setSaving] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)

  const { data: concept, isLoading: conceptLoading } = useQuery({
    queryKey: ["concept", conceptId],
    queryFn: () => api.getConcept(conceptId),
  })

  // Poll job status when a job is running
  const { data: jobResult } = useQuery<DiscoveryJobResult>({
    queryKey: ["discovery-job", jobId],
    queryFn: () => api.getDiscoveryStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data || data.status === "running" || data.status === "pending") return 2000
      return false
    },
  })

  // Initialise CodeMirror
  useEffect(() => {
    if (!editorRef.current || viewRef.current) return

    const view = new EditorView({
      state: EditorState.create({
        doc: concept?.latex_statement ?? "",
        extensions: [
          basicSetup,
          StreamLanguage.define(stex),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              setLatex(update.state.doc.toString())
            }
          }),
        ],
      }),
      parent: editorRef.current,
    })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
  }, [editorRef.current]) // eslint-disable-line react-hooks/exhaustive-deps

  // Seed editor once concept loads
  useEffect(() => {
    if (!concept || !viewRef.current) return
    const view = viewRef.current
    const currentContent = view.state.doc.toString()
    if (currentContent === "" && concept.latex_statement) {
      view.dispatch({
        changes: {
          from: 0,
          to: currentContent.length,
          insert: concept.latex_statement,
        },
      })
      setLatex(concept.latex_statement)
    }
  }, [concept])

  async function handleSave() {
    if (!concept || !latex.trim()) return
    setSaving(true)
    try {
      const res = await api.createDiscovery({
        name: `Modified ${concept.name}`,
        base_concept_id: conceptId,
        modified_latex_statement: latex,
        modification_description: `User edit via canvas workspace`,
      })
      setJobId(res.job_id)
    } catch (err) {
      console.error("Discovery creation failed:", err)
    } finally {
      setSaving(false)
    }
  }

  const jobDone = jobResult?.status === "done" || jobResult?.status === "failed"

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <span className="font-medium text-gray-800 truncate flex-1">
          {conceptLoading ? "Loading…" : concept?.name ?? "Concept"}
        </span>
        <button
          onClick={() => setEditing(null)}
          className="p-1 text-gray-400 hover:text-gray-700 rounded"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Live KaTeX preview */}
      <div className="px-3 py-2 border-b border-gray-100 min-h-[64px] bg-gray-50">
        <p className="text-[10px] text-gray-400 mb-1">Preview</p>
        <LatexPreview latex={latex || concept?.latex_statement || ""} />
      </div>

      {/* CodeMirror editor */}
      <div className="flex-1 overflow-hidden border-b border-gray-100">
        <p className="text-[10px] text-gray-400 px-3 pt-2 pb-1">LaTeX editor</p>
        <div
          ref={editorRef}
          className="h-[calc(100%-24px)] overflow-auto text-xs [&_.cm-editor]:h-full [&_.cm-scroller]:font-mono"
        />
      </div>

      {/* Job results */}
      {jobResult && (
        <div className="px-3 py-2 border-b border-gray-100 space-y-1">
          {jobResult.sympy_status && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-gray-500">SymPy:</span>
              <StatusBadge status={jobResult.sympy_status} />
            </div>
          )}
          {jobResult.lean_status && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-gray-500">Lean 4:</span>
              <StatusBadge status={jobResult.lean_status} />
            </div>
          )}
          {jobResult.impacts_count !== undefined && (
            <p className="text-xs text-gray-500">
              {jobResult.impacts_count} impact(s) · {jobResult.conflict_count ?? 0} conflict(s)
            </p>
          )}
          {jobResult.status === "failed" && jobResult.error && (
            <p className="text-xs text-red-600">{jobResult.error}</p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="px-3 py-2 flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={saving || !!jobId && !jobDone}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {saving || (jobId && !jobDone) ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Save className="w-3 h-3" />
          )}
          {jobId && !jobDone ? "Analyzing…" : "Save & Verify"}
        </button>
        <button
          onClick={() => setEditing(null)}
          className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-100 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function LatexPreview({ latex }: { latex: string }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current || !latex) return
    import("katex").then(({ default: katex }) => {
      try {
        katex.render(latex, ref.current!, {
          throwOnError: false,
          displayMode: false,
          output: "html",
        })
      } catch {
        if (ref.current) ref.current.textContent = latex
      }
    })
  }, [latex])

  if (!latex) return <span className="text-gray-400 text-xs italic">No LaTeX</span>
  return <div ref={ref} className="text-sm overflow-auto" />
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    passed: "bg-green-100 text-green-700",
    verified: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    pending: "bg-yellow-100 text-yellow-700",
    running: "bg-blue-100 text-blue-700",
    skipped: "bg-gray-100 text-gray-600",
  }
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] capitalize ${colors[status] ?? "bg-gray-100 text-gray-600"}`}>
      {status}
    </span>
  )
}
