"use client"

import {
  HTMLContainer,
  Rectangle2d,
  RecordProps,
  ShapeUtil,
  T,
  TLBaseShape,
} from "@tldraw/tldraw"
import { useCanvasStore } from "@/lib/canvas-store"

export type ConceptCardShape = TLBaseShape<
  "concept-card",
  {
    w: number
    h: number
    conceptId: string
    name: string
    conceptType: string
    latexStatement: string
    leanStatus: string
    isLoading: boolean
  }
>

const STATUS_COLORS: Record<string, string> = {
  verified: "bg-green-100 text-green-800",
  unverified: "bg-yellow-100 text-yellow-800",
  failed: "bg-red-100 text-red-800",
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export class ConceptCardShapeUtil extends ShapeUtil<any> {
  static override type = "concept-card" as const

  static override props: RecordProps<ConceptCardShape> = {
    w: T.number,
    h: T.number,
    conceptId: T.string,
    name: T.string,
    conceptType: T.string,
    latexStatement: T.string,
    leanStatus: T.string,
    isLoading: T.boolean,
  }

  getDefaultProps(): ConceptCardShape["props"] {
    return {
      w: 280,
      h: 180,
      conceptId: "",
      name: "Concept",
      conceptType: "theorem",
      latexStatement: "",
      leanStatus: "unverified",
      isLoading: false,
    }
  }

  getGeometry(shape: ConceptCardShape) {
    return new Rectangle2d({ width: shape.props.w, height: shape.props.h, isFilled: true })
  }

  component(shape: ConceptCardShape) {
    const { conceptId, name, conceptType, latexStatement, leanStatus, isLoading } = shape.props
    const setEditing = useCanvasStore((s) => s.setEditing)
    const statusClass = STATUS_COLORS[leanStatus] ?? STATUS_COLORS["unverified"]

    return (
      <HTMLContainer
        id={shape.id}
        style={{ width: shape.props.w, height: shape.props.h, overflow: "hidden" }}
      >
        <div className="flex flex-col h-full bg-white border border-gray-200 rounded-lg shadow-sm text-xs font-sans overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-1.5 px-3 py-2 border-b border-gray-100 bg-gray-50">
            <span className="font-semibold text-gray-900 truncate flex-1">{name}</span>
            <span className="shrink-0 px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 capitalize">
              {conceptType}
            </span>
            <span className={`shrink-0 px-1.5 py-0.5 rounded capitalize ${statusClass}`}>
              {leanStatus}
            </span>
          </div>

          {/* Body */}
          <div className="flex-1 px-3 py-2 overflow-hidden">
            {isLoading ? (
              <div className="flex items-center justify-center h-full">
                <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : latexStatement ? (
              <span className="text-gray-700 text-[11px] leading-relaxed font-mono break-words line-clamp-4">
                {latexStatement}
              </span>
            ) : (
              <span className="text-gray-400 italic">No statement</span>
            )}
          </div>

          {/* Footer */}
          <div className="px-3 py-1.5 border-t border-gray-100 flex justify-end">
            <button
              className="text-[11px] px-2 py-0.5 rounded bg-blue-600 text-white hover:bg-blue-700"
              onPointerDown={(e) => {
                e.stopPropagation()
                setEditing(conceptId)
              }}
            >
              Edit
            </button>
          </div>
        </div>
      </HTMLContainer>
    )
  }

  indicator(shape: ConceptCardShape) {
    return <rect width={shape.props.w} height={shape.props.h} rx={8} />
  }
}
