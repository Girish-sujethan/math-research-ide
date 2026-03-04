"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, CheckCircle2, ExternalLink } from "lucide-react"
import { api } from "@/lib/api"
import { useVaultStore } from "@/lib/vault-store"
import type { DiscoveredPaper, PaperDiscoveryJobResult } from "@/lib/types"

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  arxiv: { label: "arXiv", cls: "bg-orange-100 text-orange-600" },
  exa:   { label: "Exa",   cls: "bg-teal-100 text-teal-600" },
}

function stageLabel(stage?: string): string {
  if (!stage || stage === "running") return "Planning queries…"
  if (stage === "searching_sources") return "Searching arXiv and Exa…"
  if (stage === "ranking_papers") return "Ranking by relevance…"
  return "Processing…"
}

// searchKey: parent passes {query, t} when user submits. Changing t with the same
// query re-triggers the search (e.g. user presses Find twice for the same topic).
export interface FindSearchKey {
  query: string
  t: number
}

interface Props {
  searchKey: FindSearchKey | null
  className?: string
}

export function PaperDiscoveryPanel({ searchKey, className }: Props) {
  const { stagePaper, stagedPapers } = useVaultStore()

  const [jobId, setJobId] = useState<string | null>(null)
  const [stage, setStage] = useState<string | undefined>()
  const [papers, setPapers] = useState<DiscoveredPaper[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [currentQuery, setCurrentQuery] = useState<string | null>(null)
  const [stagingIds, setStagingIds] = useState<Set<string>>(new Set())

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timeoutRef  = useRef<ReturnType<typeof setTimeout>  | null>(null)

  function clearPolling() {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    if (timeoutRef.current)  { clearTimeout(timeoutRef.current);   timeoutRef.current  = null }
  }

  // Trigger a new search whenever searchKey changes
  useEffect(() => {
    if (!searchKey?.query) return
    let cancelled = false

    clearPolling()
    setPapers([])
    setStage(undefined)
    setError(null)
    setJobId(null)
    setLoading(true)
    setCurrentQuery(searchKey.query)

    api.discoverPapers(searchKey.query)
      .then(res => {
        if (!cancelled) setJobId(res.job_id)
      })
      .catch(err => {
        if (!cancelled) {
          setError(`Failed to start: ${err instanceof Error ? err.message : "unknown"}`)
          setLoading(false)
        }
      })

    return () => { cancelled = true }
  }, [searchKey])

  // Poll the job once we have a jobId
  useEffect(() => {
    if (!jobId) return
    clearPolling()

    intervalRef.current = setInterval(async () => {
      try {
        const result: PaperDiscoveryJobResult = await api.getPaperDiscoveryStatus(jobId)
        setStage(result.stage)
        if (result.status === "done") {
          setPapers(result.papers)
          setLoading(false)
          clearPolling()
        } else if (result.status === "failed") {
          setError(result.error ?? "Discovery failed")
          setLoading(false)
          clearPolling()
        }
      } catch (err) {
        setError(`Polling error: ${err instanceof Error ? err.message : "unknown"}`)
        setLoading(false)
        clearPolling()
      }
    }, 1500)

    timeoutRef.current = setTimeout(() => {
      setError("Discovery timed out after 90 s")
      setLoading(false)
      clearPolling()
    }, 90000)

    return clearPolling
  }, [jobId])

  async function handleStage(paper: DiscoveredPaper) {
    const key = paper.arxiv_id ?? paper.title
    setStagingIds(s => new Set(s).add(key))
    try {
      let job
      if (paper.arxiv_id) {
        job = await api.ingestPaper(paper.arxiv_id)
      } else if (paper.url.includes("doi.org")) {
        const doi = paper.url.replace(/https?:\/\/doi\.org\//, "")
        job = await api.ingestByDoi(doi)
      } else {
        setError(`Cannot stage "${paper.title}": no arXiv ID or DOI`)
        return
      }
      stagePaper({
        paper_id: job.paper_id,
        title: paper.title,
        authors: paper.authors,
        abstract: paper.abstract ?? "",
        arxiv_id: paper.arxiv_id,
      })
    } catch (err) {
      setError(`Stage failed: ${err instanceof Error ? err.message : "unknown"}`)
    } finally {
      setStagingIds(s => { const n = new Set(s); n.delete(key); return n })
    }
  }

  // ── render ─────────────────────────────────────────────────────────────────

  if (!searchKey) {
    return (
      <div className={`flex items-center justify-center ${className ?? ""}`}>
        <p className="text-[10px] text-gray-400 text-center px-4 leading-relaxed">
          Type a research topic below and press <span className="font-semibold">Find</span> — HEAVEN
          will search arXiv and Exa, then rank results by relevance.
        </p>
      </div>
    )
  }

  return (
    <div className={`flex flex-col ${className ?? ""}`}>
      {/* Progress indicator */}
      {loading && (
        <div className="px-3 py-3 flex items-center gap-2 flex-shrink-0 border-b border-gray-50">
          <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin shrink-0" />
          <span className="text-xs text-blue-600">{stageLabel(stage)}</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="px-3 py-2 flex-shrink-0">
          <p className="text-[10px] text-red-500 leading-tight">{error}</p>
        </div>
      )}

      {/* Results */}
      {papers.length > 0 && (
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2.5">
          <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide">
            {papers.length} papers · "{currentQuery}"
          </p>

          {papers.map((p, i) => {
            const key = p.arxiv_id ?? p.title
            const isStaging = stagingIds.has(key)
            // Derive from vault so removing a paper in Knowledge Vault resets the Stage button here
            const isStaged = p.arxiv_id
              ? stagedPapers.some((s) => s.arxiv_id === p.arxiv_id)
              : stagedPapers.some((s) => s.title === p.title)
            const canStage  = !!(p.arxiv_id || p.url.includes("doi.org"))
            const badge     = SOURCE_BADGE[p.source] ?? { label: p.source, cls: "bg-gray-100 text-gray-500" }
            const score     = Math.round(p.relevance_score * 10) / 10

            return (
              <div key={i} className="border border-gray-100 rounded-xl p-2.5 space-y-1.5">
                <p className="text-[10px] font-semibold text-gray-800 leading-snug line-clamp-2">
                  {p.title}
                </p>

                <div className="flex items-center gap-1.5 flex-wrap">
                  {p.authors.length > 0 && (
                    <span className="text-[9px] text-gray-400 truncate max-w-[110px]">
                      {p.authors.slice(0, 2).join(", ")}
                    </span>
                  )}
                  <span className={`text-[8px] px-1.5 rounded font-medium ${badge.cls}`}>
                    {badge.label}
                  </span>
                  <span className="ml-auto text-[9px] font-medium text-blue-600 shrink-0">
                    {score} ★
                  </span>
                </div>

                {p.relevance_explanation && p.relevance_explanation !== "Unranked" && (
                  <p className="text-[9px] text-blue-700 italic leading-snug line-clamp-1">
                    {p.relevance_explanation}
                  </p>
                )}

                {p.abstract && (
                  <p className="text-[9px] text-gray-500 leading-snug line-clamp-4">
                    {p.abstract}
                  </p>
                )}

                <div className="flex items-center justify-between pt-0.5">
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[9px] text-gray-400 hover:text-blue-500 flex items-center gap-0.5 transition-colors"
                  >
                    <ExternalLink className="w-2.5 h-2.5" />
                    View
                  </a>

                  {isStaged ? (
                    <span className="text-[9px] px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded-lg flex items-center gap-0.5">
                      <CheckCircle2 className="w-2.5 h-2.5" />
                      Staged
                    </span>
                  ) : canStage ? (
                    <button
                      onClick={() => handleStage(p)}
                      disabled={isStaging}
                      className="text-[9px] px-2 py-0.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center gap-0.5"
                    >
                      {isStaging ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : "Stage"}
                    </button>
                  ) : (
                    <span className="text-[9px] text-gray-300" title="No arXiv ID or DOI">—</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Loading placeholder when no results yet */}
      {loading && papers.length === 0 && !error && (
        <div className="flex-1" />
      )}
    </div>
  )
}
