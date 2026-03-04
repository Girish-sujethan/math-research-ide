"use client"

import { useEffect, useRef, useState } from "react"
import { Upload, Link2, X, Loader2, ChevronRight, ChevronDown, Pin, PinOff } from "lucide-react"
import { api } from "@/lib/api"
import { useVaultStore } from "@/lib/vault-store"
import type { ConceptRead } from "@/lib/types"

/** Max concepts to fetch for the vault dropdown (avoids memory blowup from 200+ KaTeX renders). */
const VAULT_CONCEPT_LIMIT = 50
/** Number of concepts to show initially; "Show more" reveals the rest in chunks. */
const INITIAL_CONCEPTS_VISIBLE = 25
const SHOW_MORE_STEP = 25

/** Truncate LaTeX for list display without rendering (avoids KaTeX per row). */
function truncateStatement(latex: string, maxLen: number = 70): string {
  let stripped = latex.replace(/\$\$[^$]*\$\$/g, "…").replace(/\$[^$]*\$/g, "…")
  stripped = stripped.replace(/\s+/g, " ").trim()
  return stripped.length <= maxLen ? stripped : stripped.slice(0, maxLen) + "…"
}

const INGEST_POLL_INTERVAL_MS = 2000

interface Props {
  className?: string
}

function conceptTypeLabel(concept_type: string): string {
  const labels: Record<string, string> = {
    theorem: "Theorem",
    proposition: "Proposition",
    definition: "Definition",
    lemma: "Lemma",
    corollary: "Corollary",
    axiom: "Axiom",
    conjecture: "Conjecture",
    remark: "Remark",
    note: "Note",
    example: "Example",
    claim: "Claim",
    proof: "Proof",
  }
  return labels[concept_type] ?? (concept_type.charAt(0).toUpperCase() + concept_type.slice(1))
}

export function KnowledgeVault({ className }: Props) {
  const { stagedPapers, stagePaper, unstagePaper, pinnedConcepts, pinConcept, unpinConcept, invalidateConceptGraph } = useVaultStore()
  const [doiInput, setDoiInput] = useState("")
  const [error, setError] = useState<string | null>(null)

  // Concept browser state
  const [expandedPaperIds, setExpandedPaperIds] = useState<Set<string>>(new Set())
  const [paperConcepts, setPaperConcepts] = useState<Record<string, ConceptRead[]>>({})
  const [loadingConcepts, setLoadingConcepts] = useState<Set<string>>(new Set())
  /** Per-paper: how many concepts to show (starts at INITIAL_CONCEPTS_VISIBLE, "Show more" increases). */
  const [visibleCountByPaper, setVisibleCountByPaper] = useState<Record<string, number>>({})

  // Track ingest jobs so we can poll and refetch concepts when done (upload/DOI)
  const [pendingIngestJobs, setPendingIngestJobs] = useState<Record<string, string>>({}) // paper_id -> job_id
  const pendingIngestRef = useRef<Record<string, string>>({})
  const expandedPaperIdsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    pendingIngestRef.current = pendingIngestJobs
  }, [pendingIngestJobs])
  useEffect(() => {
    expandedPaperIdsRef.current = expandedPaperIds
  }, [expandedPaperIds])

  // Poll pending ingest jobs; when done, clear concepts cache and refetch if paper is expanded
  useEffect(() => {
    const entries = Object.entries(pendingIngestJobs)
    if (entries.length === 0) return

    const interval = setInterval(async () => {
      const current = { ...pendingIngestRef.current }
      for (const [paper_id, job_id] of Object.entries(current)) {
        try {
          const result = await api.getIngestStatus(job_id)
          if (result.status === "done" || result.status === "failed") {
            delete current[paper_id]
            setPendingIngestJobs((prev) => {
              const next = { ...prev }
              delete next[paper_id]
              return next
            })
              if (result.status === "done") {
              invalidateConceptGraph()
              setPaperConcepts((prev) => {
                const next = { ...prev }
                delete next[paper_id]
                return next
              })
              setVisibleCountByPaper((prev) => {
                const next = { ...prev }
                delete next[paper_id]
                return next
              })
              if (expandedPaperIdsRef.current.has(paper_id)) {
                setLoadingConcepts((s) => new Set(s).add(paper_id))
                try {
                  const concepts = await api.getPaperConcepts(paper_id, VAULT_CONCEPT_LIMIT)
                  setPaperConcepts((prev) => ({ ...prev, [paper_id]: concepts }))
                  setVisibleCountByPaper((prev) => ({ ...prev, [paper_id]: INITIAL_CONCEPTS_VISIBLE }))
                } catch {
                  // ignore
                } finally {
                  setLoadingConcepts((s) => {
                    const n = new Set(s)
                    n.delete(paper_id)
                    return n
                  })
                }
              }
            }
          }
        } catch {
          // keep polling
        }
      }
    }, INGEST_POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [pendingIngestJobs, expandedPaperIds])

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    try {
      const job = await api.uploadPaper(file)
      stagePaper({
        paper_id: job.paper_id,
        title: file.name.replace(/\.pdf$/i, ""),
        authors: [],
        abstract: "",
      })
      setPendingIngestJobs((prev) => ({ ...prev, [job.paper_id]: job.job_id }))
    } catch (err) {
      setError(`Upload failed: ${err instanceof Error ? err.message : "unknown error"}`)
    }
    e.target.value = ""
  }

  async function handleDoi() {
    const doi = doiInput.trim()
    if (!doi) return
    setError(null)
    try {
      const job = await api.ingestByDoi(doi)
      stagePaper({
        paper_id: job.paper_id,
        title: doi,
        authors: [],
        abstract: "",
      })
      setPendingIngestJobs((prev) => ({ ...prev, [job.paper_id]: job.job_id }))
    } catch (err) {
      setError(`DOI import failed: ${err instanceof Error ? err.message : "unknown error"}`)
    }
    setDoiInput("")
  }

  async function toggleConceptList(paper_id: string) {
    setExpandedPaperIds((prev) => {
      const next = new Set(prev)
      if (next.has(paper_id)) {
        next.delete(paper_id)
        return next
      }
      next.add(paper_id)
      return next
    })
    if (!paperConcepts[paper_id]) {
      setLoadingConcepts((s) => new Set(s).add(paper_id))
      try {
        const concepts = await api.getPaperConcepts(paper_id, VAULT_CONCEPT_LIMIT)
        setPaperConcepts((prev) => ({ ...prev, [paper_id]: concepts }))
        setVisibleCountByPaper((prev) => ({ ...prev, [paper_id]: INITIAL_CONCEPTS_VISIBLE }))
      } catch {
        // silently ignore — concepts are optional UI enhancement
      } finally {
        setLoadingConcepts((s) => { const n = new Set(s); n.delete(paper_id); return n })
      }
    }
  }

  function showMoreConcepts(paper_id: string) {
    setVisibleCountByPaper((prev) => {
      const current = prev[paper_id] ?? INITIAL_CONCEPTS_VISIBLE
      const total = paperConcepts[paper_id]?.length ?? 0
      return { ...prev, [paper_id]: Math.min(current + SHOW_MORE_STEP, total) }
    })
  }

  return (
    <div className={`flex flex-col bg-white ${className ?? ""}`}>
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-gray-100">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Knowledge Vault
        </h2>

        {/* Upload + DOI row */}
        <div className="flex gap-1.5">
          <label className="flex-1 flex items-center justify-center gap-1 text-[10px] text-gray-500 border border-dashed border-gray-200 rounded-lg py-1.5 cursor-pointer hover:border-blue-300 hover:text-blue-500 transition-colors">
            <Upload className="w-3 h-3" />
            PDF
            <input type="file" accept=".pdf" className="hidden" onChange={handleUpload} />
          </label>
          <div className="flex-1 flex">
            <input
              value={doiInput}
              onChange={(e) => setDoiInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleDoi()}
              placeholder="DOI…"
              className="flex-1 min-w-0 text-[10px] border border-gray-200 rounded-l-lg px-2 py-1.5 outline-none focus:border-blue-400"
            />
            <button
              onClick={handleDoi}
              className="px-2 py-1.5 bg-gray-100 border border-l-0 border-gray-200 rounded-r-lg hover:bg-gray-200 transition-colors"
            >
              <Link2 className="w-3 h-3 text-gray-500" />
            </button>
          </div>
        </div>

        {error && <p className="mt-1.5 text-[10px] text-red-500 leading-tight">{error}</p>}
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Staged papers with concept browser */}
        {stagedPapers.length > 0 && (
          <div className="px-3 pt-2 pb-1 border-b border-gray-100">
            <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
              Staged ({stagedPapers.length})
            </p>
            <div className="space-y-1">
              {stagedPapers.map((p) => {
                const isExpanded = expandedPaperIds.has(p.paper_id)
                const isLoadingC = loadingConcepts.has(p.paper_id)
                const isExtracting = Boolean(pendingIngestJobs[p.paper_id])
                const concepts = paperConcepts[p.paper_id] ?? []
                const showExtracting = isExpanded && isExtracting && concepts.length === 0
                const showSpinner = isLoadingC || showExtracting
                return (
                  <div key={p.paper_id}>
                    <div className="flex items-start gap-1.5 group">
                      {/* Expand toggle */}
                      <button
                        onClick={() => toggleConceptList(p.paper_id)}
                        className="mt-0.5 flex-shrink-0 text-gray-300 hover:text-gray-500 transition-colors"
                      >
                        {showSpinner
                          ? <Loader2 className="w-3 h-3 animate-spin text-gray-400" />
                          : isExpanded
                          ? <ChevronDown className="w-3 h-3" />
                          : <ChevronRight className="w-3 h-3" />
                        }
                      </button>
                      <div className="flex-1 min-w-0">
                        <p className="text-[10px] text-gray-700 leading-tight line-clamp-2">{p.title}</p>
                        {p.authors.length > 0 && (
                          <p className="text-[9px] text-gray-400 truncate mt-0.5">
                            {p.authors.slice(0, 2).join(", ")}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() => unstagePaper(p.paper_id)}
                        className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 hover:text-red-500"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>

                    {/* Concept list: only render visible slice to avoid 100+ KaTeX nodes and freeze */}
                    {isExpanded && concepts.length > 0 && (() => {
                      const visible = visibleCountByPaper[p.paper_id] ?? INITIAL_CONCEPTS_VISIBLE
                      const toShow = concepts.slice(0, visible)
                      const remaining = concepts.length - visible
                      return (
                        <div className="ml-4 mt-1 space-y-0.5">
                          {toShow.map((c) => {
                            const isPinned = pinnedConcepts.some((pc) => pc.concept_id === c.id)
                            return (
                              <div key={c.id} className="flex items-start gap-1 py-0.5 group/concept">
                                <span className={`mt-0.5 flex-shrink-0 text-[8px] px-1 rounded font-medium ${
                                  c.concept_type === "theorem"     ? "bg-blue-100 text-blue-700" :
                                  c.concept_type === "definition"  ? "bg-green-100 text-green-700" :
                                  c.concept_type === "lemma"       ? "bg-amber-100 text-amber-700" :
                                  c.concept_type === "axiom"       ? "bg-purple-100 text-purple-700" :
                                  c.concept_type === "conjecture"  ? "bg-red-100 text-red-700" :
                                  c.concept_type === "corollary"   ? "bg-cyan-100 text-cyan-700" :
                                  "bg-gray-100 text-gray-600"
                                }`}>
                                  {conceptTypeLabel(c.concept_type)}
                                </span>
                                <div className="flex-1 min-w-0 min-h-0">
                                  <p className="text-[9px] text-gray-700 font-medium leading-tight truncate">{c.name}</p>
                                  {c.latex_statement && (
                                    <p className="text-[8px] text-gray-500 truncate font-mono" title={c.latex_statement}>
                                      {truncateStatement(c.latex_statement)}
                                    </p>
                                  )}
                                </div>
                                <button
                                  onClick={() => isPinned
                                    ? unpinConcept(c.id)
                                    : pinConcept({
                                        concept_id: c.id,
                                        name: c.name,
                                        concept_type: c.concept_type,
                                        latex_statement: c.latex_statement,
                                        paper_id: p.paper_id,
                                        paper_title: p.title,
                                      })
                                  }
                                  className={`flex-shrink-0 opacity-0 group-hover/concept:opacity-100 transition-opacity p-0.5 ${
                                    isPinned ? "text-amber-500" : "text-gray-400 hover:text-amber-500"
                                  }`}
                                  title={isPinned ? "Unpin concept" : "Pin to chat context"}
                                >
                                  {isPinned ? <PinOff className="w-3 h-3" /> : <Pin className="w-3 h-3" />}
                                </button>
                              </div>
                            )
                          })}
                          {remaining > 0 && (
                            <button
                              type="button"
                              onClick={() => showMoreConcepts(p.paper_id)}
                              className="text-[9px] text-blue-600 hover:text-blue-800 mt-0.5"
                            >
                              Show more ({remaining} more)
                            </button>
                          )}
                        </div>
                      )
                    })()}
                    {isExpanded && concepts.length === 0 && (
                      <div className="ml-4 mt-1 flex items-center gap-1.5 text-[9px] text-gray-500">
                        {showExtracting ? (
                          <>
                            <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />
                            <span>Extracting concepts…</span>
                          </>
                        ) : isLoadingC ? (
                          <>
                            <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />
                            <span>Loading…</span>
                          </>
                        ) : (
                          <span className="italic text-gray-400">No concepts extracted yet.</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Pinned concepts summary */}
            {pinnedConcepts.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-100">
                <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
                  <span className="text-amber-500">📌</span> Pinned ({pinnedConcepts.length})
                </p>
                <div className="space-y-0.5">
                  {pinnedConcepts.map((pc) => (
                    <div key={pc.concept_id} className="flex items-center gap-1 group/pin">
                      <span className="flex-1 min-w-0 text-[9px] text-gray-700 truncate">{pc.name}</span>
                      <button
                        onClick={() => unpinConcept(pc.concept_id)}
                        className="flex-shrink-0 opacity-0 group-hover/pin:opacity-100 transition-opacity p-0.5 hover:text-red-400"
                      >
                        <X className="w-2.5 h-2.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}
