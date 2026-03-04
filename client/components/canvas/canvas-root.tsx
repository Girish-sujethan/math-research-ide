"use client"

import { Tldraw, Editor } from "@tldraw/tldraw"
import "@tldraw/tldraw/tldraw.css"
import { useCallback } from "react"
import { ConceptCardShapeUtil } from "./shapes/concept-card-shape"
import { PaperCardShapeUtil } from "./shapes/paper-card-shape"
import { AnnotationShapeUtil } from "./shapes/annotation-shape"
import { CanvasToolbar } from "./canvas-toolbar"
import { useGraphLayout } from "./graph-overlay"
import { useCanvasStore } from "@/lib/canvas-store"
import { useWorkspaceEditor } from "./workspace-context"

const CUSTOM_SHAPE_UTILS = [ConceptCardShapeUtil, PaperCardShapeUtil, AnnotationShapeUtil]

export function CanvasRoot() {
  const { editor, setEditor } = useWorkspaceEditor()
  const setSelected = useCanvasStore((s) => s.setSelected)

  useGraphLayout(editor)

  const handleMount = useCallback((e: Editor) => {
    setEditor(e)

    // Track selection changes to update zustand store
    e.on("change", () => {
      const selectedShapes = e.getSelectedShapes()
      const conceptIds: string[] = []
      const paperIds: string[] = []
      for (const shape of selectedShapes) {
        const s = shape as any
        if (s.type === "concept-card") {
          conceptIds.push(s.props.conceptId)
        } else if (s.type === "paper-card") {
          paperIds.push(s.props.paperId)
        }
      }
      setSelected(conceptIds, paperIds)
    })
  }, [setEditor, setSelected])

  return (
    <div className="w-full h-full relative">
      <Tldraw
        shapeUtils={CUSTOM_SHAPE_UTILS}
        onMount={handleMount}
        hideUi={false}
        persistenceKey="heaven-canvas"
      />
      {editor && <CanvasToolbar editor={editor} />}
    </div>
  )
}
