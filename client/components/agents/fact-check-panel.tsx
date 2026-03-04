"use client"

import { useState } from "react"
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  Loader2,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Lightbulb,
} from "lucide-react"
import { api } from "@/lib/api"
import { useVaultStore } from "@/lib/vault-store"
import type { FactCheckResponse } from "@/lib/types"

// ---------------------------------------------------------------------------
// Confidence bar
// ---------------------------------------------------------------------------

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color =
    value >= 0.75
      ? "bg-emerald-500"
      : value >= 0.45
      ? "bg-amber-400"
      : "bg-red-400"

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] font-mono text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Verdict icon + label
// ---------------------------------------------------------------------------

function VerdictBadge({ verdict }: { verdict: FactCheckResponse["verdict"] }) {
  if (verdict === "supported") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">
        <CheckCircle2 className="w-3 h-3" /> Supported
      </span>
    )
  }
  if (verdict === "contradicted") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-red-700 bg-red-50 border border-red-200 rounded-full px-2 py-0.5">
        <XCircle className="w-3 h-3" /> Contradicted
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">
      <HelpCircle className="w-3 h-3" /> Uncertain
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function FactCheckPanel() {
  const { stagedPapers } = useVaultStore()

  const [statement, setStatement] = useState("")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<FactCheckResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showEvidence, setShowEvidence] = useState(false)

  async function check() {
    const text = statement.trim()
    if (!text || loading) return
    setError(null)
    setResult(null)
    setLoading(true)
    try {
      const stagedIds = stagedPapers.map((p) => p.paper_id)
      const res = await api.factCheck(text, stagedIds)
      setResult(res)
      setShowEvidence(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  // Auto-fill from browser selection
  function fillFromSelection() {
    const sel = window.getSelection()?.toString().trim()
    if (sel) setStatement(sel)
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-3 pt-3 pb-1 flex-shrink-0">
        <ShieldCheck className="w-3.5 h-3.5 text-violet-500" />
        <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
          Fact-Checker
        </h3>
      </div>

      <div className="px-3 flex flex-col gap-2">
        {/* Input */}
        <textarea
          value={statement}
          onChange={(e) => setStatement(e.target.value)}
          onFocus={fillFromSelection}
          placeholder="Paste or type a mathematical statement to verify…"
          rows={3}
          className="w-full resize-none text-xs border border-gray-200 rounded-xl px-3 py-2 outline-none focus:border-violet-400 focus:ring-1 focus:ring-violet-100 text-gray-800 placeholder:text-gray-300"
        />

        {stagedPapers.length > 0 && (
          <p className="text-[9px] text-gray-400">
            Checking against {stagedPapers.length} staged paper{stagedPapers.length !== 1 ? "s" : ""} + knowledge base
          </p>
        )}

        <button
          onClick={check}
          disabled={loading || !statement.trim()}
          className="flex items-center justify-center gap-1.5 text-xs font-medium bg-violet-600 text-white rounded-xl py-1.5 hover:bg-violet-700 disabled:opacity-50 transition-colors"
        >
          {loading ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin" />
              Checking…
            </>
          ) : (
            <>
              <ShieldCheck className="w-3 h-3" />
              Check Statement
            </>
          )}
        </button>

        {error && (
          <p className="text-[10px] text-red-500 leading-relaxed">{error}</p>
        )}

        {/* Results */}
        {result && (
          <div className="rounded-xl border border-gray-200 overflow-hidden">
            {/* Verdict + confidence */}
            <div className="px-3 py-2.5 bg-gray-50 flex items-center justify-between gap-2 border-b border-gray-100">
              <VerdictBadge verdict={result.verdict} />
              <div className="flex-1">
                <ConfidenceBar value={result.confidence} />
              </div>
            </div>

            {/* Explanation */}
            <div className="px-3 py-2">
              <p className="text-[11px] text-gray-700 leading-relaxed">{result.explanation}</p>
            </div>

            {/* Issues */}
            {result.issues.length > 0 && (
              <div className="px-3 pb-2">
                {result.issues.map((issue, i) => (
                  <p key={i} className="text-[10px] text-red-600 leading-relaxed">
                    ⚠ {issue}
                  </p>
                ))}
              </div>
            )}

            {/* Suggestion */}
            {result.suggestion && (
              <div className="mx-3 mb-2 px-2 py-1.5 bg-violet-50 border border-violet-100 rounded-lg flex gap-1.5">
                <Lightbulb className="w-3 h-3 text-violet-400 shrink-0 mt-0.5" />
                <p className="text-[10px] text-violet-700 leading-relaxed">{result.suggestion}</p>
              </div>
            )}

            {/* Collapsible evidence */}
            {result.supporting_evidence.length > 0 && (
              <>
                <button
                  onClick={() => setShowEvidence((v) => !v)}
                  className="w-full flex items-center justify-between px-3 py-1.5 text-[10px] text-gray-400 hover:text-gray-600 border-t border-gray-100 transition-colors"
                >
                  <span>Supporting evidence ({result.supporting_evidence.length})</span>
                  {showEvidence ? (
                    <ChevronUp className="w-3 h-3" />
                  ) : (
                    <ChevronDown className="w-3 h-3" />
                  )}
                </button>
                {showEvidence && (
                  <ul className="px-3 pb-2 space-y-1">
                    {result.supporting_evidence.map((ev, i) => (
                      <li key={i} className="text-[10px] text-gray-600 leading-relaxed">
                        • {ev}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
