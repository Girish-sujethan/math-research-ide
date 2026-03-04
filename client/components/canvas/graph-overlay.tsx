"use client"

import { Editor, createShapeId } from "@tldraw/tldraw"
import dagre from "@dagrejs/dagre"
import { useEffect } from "react"
import { useCanvasStore } from "@/lib/canvas-store"
import type { ConceptCardShape } from "./shapes/concept-card-shape"

interface Relationship {
  source_concept_id: string
  target_concept_id: string
  relationship_type: string
  id: string
}

async function fetchRelationships(conceptIds: string[]): Promise<Relationship[]> {
  if (conceptIds.length === 0) return []
  const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"
  const params = new URLSearchParams()
  conceptIds.forEach((id) => params.append("concept_ids", id))
  try {
    const res = await fetch(`${BASE}/relationships?${params.toString()}`)
    if (!res.ok) return []
    return res.json()
  } catch {
    return []
  }
}

export function useGraphLayout(editor: Editor | null) {
  const mode = useCanvasStore((s) => s.mode)
  const saveCardPositions = useCanvasStore((s) => s.saveCardPositions)
  const savedPositions = useCanvasStore((s) => s.savedCardPositions)

  useEffect(() => {
    if (!editor) return

    if (mode === "graph") {
      applyGraphLayout(editor, saveCardPositions)
    } else {
      restoreCardPositions(editor, savedPositions)
    }
  }, [mode, editor]) // eslint-disable-line react-hooks/exhaustive-deps
}

async function applyGraphLayout(
  editor: Editor,
  saveCardPositions: (p: Record<string, { x: number; y: number }>) => void
) {
  const shapes = editor.getCurrentPageShapes()
  const conceptShapes = (shapes as any[]).filter((s) => s.type === "concept-card") as ConceptCardShape[]
  if (conceptShapes.length === 0) return

  // Save current positions before re-layouting
  const currentPositions: Record<string, { x: number; y: number }> = {}
  for (const s of conceptShapes) {
    currentPositions[s.id] = { x: s.x, y: s.y }
  }
  saveCardPositions(currentPositions)

  // Fetch relationships for these concept shapes
  const conceptIds = conceptShapes.map((s) => s.props.conceptId)
  const relationships = await fetchRelationships(conceptIds)

  // Build dagre graph
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 120 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const s of conceptShapes) {
    g.setNode(s.props.conceptId, { width: s.props.w, height: s.props.h, shapeId: s.id })
  }

  const conceptIdToShapeId = new Map(conceptShapes.map((s) => [s.props.conceptId, s.id]))

  for (const rel of relationships) {
    if (g.hasNode(rel.source_concept_id) && g.hasNode(rel.target_concept_id)) {
      g.setEdge(rel.source_concept_id, rel.target_concept_id, {
        label: rel.relationship_type,
        relId: rel.id,
      })
    }
  }

  dagre.layout(g)

  // Move shapes to dagre positions
  const updates = conceptShapes.map((s) => {
    const node = g.node(s.props.conceptId)
    return {
      id: s.id,
      type: s.type,
      x: node.x - node.width / 2,
      y: node.y - node.height / 2,
    }
  })
  ;(editor as any).updateShapes(updates)

  // Create arrows for edges
  for (const edge of g.edges()) {
    const sourceShapeId = conceptIdToShapeId.get(edge.v)
    const targetShapeId = conceptIdToShapeId.get(edge.w)
    const edgeMeta = g.edge(edge)
    if (!sourceShapeId || !targetShapeId) continue

    // Remove existing arrow between same concepts to avoid duplicates
    const existing = shapes.find(
      (s) =>
        s.type === "arrow" &&
        (s as any).props?.start?.boundShapeId === sourceShapeId &&
        (s as any).props?.end?.boundShapeId === targetShapeId
    )
    if (existing) continue

    const arrowId = createShapeId()
    ;(editor as any).createShape({
      id: arrowId,
      type: "arrow",
      props: {
        start: { type: "binding", boundShapeId: sourceShapeId, normalizedAnchor: { x: 0.5, y: 0.5 } },
        end: { type: "binding", boundShapeId: targetShapeId, normalizedAnchor: { x: 0.5, y: 0.5 } },
        text: edgeMeta?.label ?? "",
      },
    })
  }
}

function restoreCardPositions(
  editor: Editor,
  savedPositions: Record<string, { x: number; y: number }>
) {
  const shapes = editor.getCurrentPageShapes() as any[]
  const updates = shapes
    .filter((s) => s.type === "concept-card" && savedPositions[s.id])
    .map((s) => ({
      id: s.id,
      type: s.type,
      x: savedPositions[s.id].x,
      y: savedPositions[s.id].y,
    }))
  if (updates.length > 0) {
    ;(editor as any).updateShapes(updates)
  }
}
