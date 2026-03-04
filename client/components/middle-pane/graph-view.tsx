"use client"

import dynamic from "next/dynamic"
import { useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import { useVaultStore } from "@/lib/vault-store"
import type { ConceptGraphResponse } from "@/lib/types"
import { GraphBuilder } from "./graph-builder"

// Load react-force-graph-2d client-only (uses canvas + window)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ForceGraph2D = dynamic(() => import("react-force-graph-2d").then((m) => m.default), { ssr: false }) as any

const TYPE_COLORS: Record<string, string> = {
  theorem:    "#3b82f6",
  definition: "#22c55e",
  lemma:      "#f59e0b",
  axiom:      "#a855f7",
  conjecture: "#ef4444",
  corollary:  "#06b6d4",
}

function nodeColor(type: string): string {
  return TYPE_COLORS[type] ?? "#6b7280"
}

// ---------------------------------------------------------------------------
// Knowledge Graph pane
// ---------------------------------------------------------------------------

function KnowledgeGraphPane() {
  const { stagedPapers } = useVaultStore()
  const [graphData, setGraphData] = useState<ConceptGraphResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 600, height: 500 })

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        setDimensions({ width, height })
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const ids = stagedPapers.map((p) => p.paper_id)
    setLoading(true)
    api.getConceptGraph(ids.length ? ids : undefined)
      .then(setGraphData)
      .catch(() => setGraphData(null))
      .finally(() => setLoading(false))
  }, [stagedPapers])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
        Loading graph…
      </div>
    )
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
        No concepts found. Stage and ingest papers to build the knowledge graph.
      </div>
    )
  }

  const nodes = graphData.nodes.map((n) => ({
    id: n.id, name: n.name, concept_type: n.concept_type, color: nodeColor(n.concept_type),
  }))
  const links = graphData.edges.map((e) => ({
    source: e.source, target: e.target, label: e.relationship_type,
  }))

  return (
    <div ref={containerRef} className="flex-1 relative overflow-hidden bg-gray-50">
      <div className="absolute top-3 left-3 z-10 flex flex-wrap gap-1.5 max-w-xs">
        {Object.entries(TYPE_COLORS).map(([type, color]) => (
          <span key={type}
            className="inline-flex items-center gap-1 text-[9px] bg-white border border-gray-200 rounded-full px-2 py-0.5 shadow-sm"
          >
            <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
      </div>
      <ForceGraph2D
        width={dimensions.width}
        height={dimensions.height}
        graphData={{ nodes, links }}
        nodeColor={(n: { color: string }) => n.color}
        nodeLabel={(n: { name: string; concept_type: string }) => `${n.name} (${n.concept_type})`}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkColor={() => "#d1d5db"}
        linkWidth={1}
        nodeRelSize={5}
        backgroundColor="#f9fafb"
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// GraphView — toggle between Knowledge Graph and Builder
// ---------------------------------------------------------------------------

type GraphTab = "knowledge" | "builder"

export function GraphView() {
  const [tab, setTab] = useState<GraphTab>("knowledge")

  const tabCls = (t: GraphTab) =>
    `text-[11px] px-3 py-1 rounded-md font-medium transition-colors ${
      tab === t
        ? "bg-blue-600 text-white shadow-sm"
        : "text-gray-500 hover:bg-gray-100"
    }`

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Tab switcher */}
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-gray-100 bg-white flex-shrink-0">
        <button className={tabCls("knowledge")} onClick={() => setTab("knowledge")}>
          Knowledge Graph
        </button>
        <button className={tabCls("builder")} onClick={() => setTab("builder")}>
          Graph Builder
        </button>
      </div>

      {/* Panels — both mounted, shown/hidden via CSS */}
      <div className={`flex-1 flex flex-col overflow-hidden ${tab === "knowledge" ? "" : "hidden"}`}>
        <KnowledgeGraphPane />
      </div>

      <div className={`flex-1 flex flex-col overflow-hidden ${tab === "builder" ? "" : "hidden"}`}>
        <GraphBuilder onInsert={() => {}} onClose={() => setTab("knowledge")} />
      </div>
    </div>
  )
}
