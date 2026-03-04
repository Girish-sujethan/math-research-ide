"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { useVaultStore } from "@/lib/vault-store"
import type { ConceptGraphResponse, ConceptNode, ConceptEdge } from "@/lib/types"

interface StagedPaperRef {
  paper_id: string
  title: string
}

interface Props {
  stagedPaperIds: string[]
  stagedPapers?: StagedPaperRef[]
}

function conceptTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    theorem: "Theorem", proposition: "Proposition", definition: "Definition",
    lemma: "Lemma", corollary: "Corollary", axiom: "Axiom", conjecture: "Conjecture",
    remark: "Remark", note: "Note", example: "Example", claim: "Claim", proof: "Proof",
  }
  return labels[type] ?? (type.charAt(0).toUpperCase() + type.slice(1))
}

function relationshipTypeLabel(type: string): string {
  if (type === "same_as") return "same as"
  if (type === "related_to") return "related to"
  return type.replace(/_/g, " ")
}

interface DirectedEdge {
  edge: ConceptEdge
  direction: "outgoing" | "incoming"
}

export function CitationMapPanel({ stagedPaperIds, stagedPapers = [] }: Props) {
  const conceptGraphVersion = useVaultStore((s) => s.conceptGraphVersion)
  const [graph, setGraph] = useState<ConceptGraphResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!stagedPaperIds.length) return
    setLoading(true)
    setError(null)
    api.getConceptGraph(stagedPaperIds)
      .then((graphData) => setGraph(graphData))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false))
  }, [stagedPaperIds.join(","), conceptGraphVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!stagedPaperIds.length)
    return (
      <p className="text-[10px] text-gray-400 p-3">Stage papers first.</p>
    )
  if (loading)
    return (
      <p className="text-[10px] text-gray-400 p-3 animate-pulse">Loading links…</p>
    )
  if (error)
    return (
      <p className="text-[10px] text-red-400 p-3">{error}</p>
    )
  if (!graph) {
    return (
      <div className="p-4 text-center text-[11px] text-gray-500">
        <p className="font-medium text-gray-600">No linked concepts yet</p>
        <p className="mt-1 text-[10px]">
          Concepts with relationships (e.g. proves, depends on) will appear here once extraction has run for your staged papers.
        </p>
      </div>
    )
  }

  const paperTitleById = new Map(stagedPapers.map((p) => [p.paper_id, p.title]))
  const nodeById = new Map<string, ConceptNode>(graph.nodes.map((n) => [n.id, n]))
  const stagedPaperIdSet = new Set(stagedPaperIds)

  // Use all nodes from the graph endpoint (already filtered by paper_ids server-side)
  const linkedNodes = graph.nodes.filter((n) => stagedPaperIdSet.has(n.paper_id ?? ""))

  // Build edges for each node — both outgoing AND incoming
  const edgesFor = new Map<string, DirectedEdge[]>()
  for (const e of graph.edges) {
    if (!edgesFor.has(e.source)) edgesFor.set(e.source, [])
    edgesFor.get(e.source)!.push({ edge: e, direction: "outgoing" })

    if (!edgesFor.has(e.target)) edgesFor.set(e.target, [])
    edgesFor.get(e.target)!.push({ edge: e, direction: "incoming" })
  }

  // Group by paper
  const byPaper = new Map<string, ConceptNode[]>()
  for (const pid of stagedPaperIds) {
    byPaper.set(pid, linkedNodes.filter((n) => (n.paper_id ?? "") === pid))
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-wide">
        {linkedNodes.length} concept{linkedNodes.length !== 1 ? "s" : ""} · {graph.edges.length} relationship{graph.edges.length !== 1 ? "s" : ""}
      </p>
      {graph.edges.length === 0 && linkedNodes.length > 0 && (
        <p className="text-[10px] text-amber-600 bg-amber-50 border border-amber-200 rounded px-2 py-1">
          No relationships extracted yet. Run ingestion on staged papers to extract &quot;proves&quot;, &quot;depends on&quot;, etc.
        </p>
      )}

      {Array.from(byPaper.entries()).map(([paperId, nodes]) => {
        const paperTitle = paperTitleById.get(paperId) ?? (paperId ? "Unknown paper" : "Other")
        return (
          <div key={paperId || "no-paper"} className="space-y-2">
            <p className="text-[10px] font-medium text-gray-500 truncate" title={paperTitle}>
              From: {paperTitle}
            </p>
            <ul className="space-y-2">
              {nodes.map((node) => {
                const directedEdges = edgesFor.get(node.id) ?? []
                return (
                  <li key={node.id} className="border border-gray-100 rounded-lg p-2.5 bg-gray-50/50">
                    <div className="flex items-baseline gap-1.5 flex-wrap">
                      <span className="font-semibold text-gray-800 text-[11px]">{node.name}</span>
                      <span className="text-[9px] text-gray-400">{conceptTypeLabel(node.concept_type)}</span>
                      {directedEdges.length > 0 && (
                        <span className="text-[8px] text-gray-300 ml-auto">{directedEdges.length} link{directedEdges.length !== 1 ? "s" : ""}</span>
                      )}
                    </div>
                    {directedEdges.length > 0 && (
                      <ul className="mt-1.5 pl-2 space-y-0.5 border-l border-gray-200">
                        {directedEdges.map((de, i) => {
                          const otherNodeId = de.direction === "outgoing" ? de.edge.target : de.edge.source
                          const otherNode = nodeById.get(otherNodeId)
                          const otherPaperTitle = otherNode?.paper_id ? paperTitleById.get(otherNode.paper_id) : null
                          const relLabel = relationshipTypeLabel(de.edge.relationship_type)
                          return (
                            <li key={i} className="text-[10px] text-gray-600">
                              {de.direction === "outgoing" ? (
                                <>
                                  <span className="text-indigo-600 font-medium">{relLabel}</span>
                                  {" → "}
                                  {otherNode?.name ?? otherNodeId}
                                </>
                              ) : (
                                <>
                                  <span className="text-gray-400">← </span>
                                  {otherNode?.name ?? otherNodeId}
                                  <span className="text-indigo-600 font-medium"> {relLabel}</span>
                                  <span className="text-gray-400"> this</span>
                                </>
                              )}
                              {otherPaperTitle && otherNode?.paper_id !== paperId && (
                                <span className="text-[9px] text-gray-400"> (from {otherPaperTitle})</span>
                              )}
                            </li>
                          )
                        })}
                      </ul>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </div>
  )
}
