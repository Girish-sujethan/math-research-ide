"use client"

import {
  HTMLContainer,
  Rectangle2d,
  RecordProps,
  ShapeUtil,
  T,
  TLBaseShape,
} from "@tldraw/tldraw"

export type PaperCardShape = TLBaseShape<
  "paper-card",
  {
    w: number
    h: number
    paperId: string
    title: string
    authors: string[]
    abstract: string
    arxivId: string
    isLoading: boolean
  }
>

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export class PaperCardShapeUtil extends ShapeUtil<any> {
  static override type = "paper-card" as const

  static override props: RecordProps<PaperCardShape> = {
    w: T.number,
    h: T.number,
    paperId: T.string,
    title: T.string,
    authors: T.arrayOf(T.string),
    abstract: T.string,
    arxivId: T.string,
    isLoading: T.boolean,
  }

  getDefaultProps(): PaperCardShape["props"] {
    return {
      w: 280,
      h: 160,
      paperId: "",
      title: "Paper",
      authors: [],
      abstract: "",
      arxivId: "",
      isLoading: false,
    }
  }

  getGeometry(shape: PaperCardShape) {
    return new Rectangle2d({ width: shape.props.w, height: shape.props.h, isFilled: true })
  }

  component(shape: PaperCardShape) {
    const { title, authors, abstract, arxivId, isLoading } = shape.props
    const authorsDisplay =
      authors.length > 2
        ? `${authors[0]}, ${authors[1]} et al.`
        : authors.join(", ")

    return (
      <HTMLContainer
        id={shape.id}
        style={{ width: shape.props.w, height: shape.props.h, overflow: "hidden" }}
      >
        <div className="flex flex-col h-full bg-white border border-gray-200 rounded-lg shadow-sm text-xs font-sans overflow-hidden">
          {/* Header */}
          <div className="flex items-start gap-1.5 px-3 py-2 border-b border-gray-100 bg-gray-50">
            <span className="font-semibold text-gray-900 flex-1 line-clamp-2 leading-tight">
              {title}
            </span>
            {arxivId && (
              <span className="shrink-0 px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 text-[10px]">
                arXiv
              </span>
            )}
          </div>

          {/* Body */}
          <div className="flex-1 px-3 py-2 overflow-hidden">
            {isLoading ? (
              <div className="flex items-center justify-center h-full">
                <div className="w-4 h-4 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : (
              <div className="space-y-1">
                {authorsDisplay && (
                  <p className="text-gray-500 truncate">{authorsDisplay}</p>
                )}
                {abstract && (
                  <p className="text-gray-700 leading-relaxed line-clamp-3">{abstract}</p>
                )}
              </div>
            )}
          </div>
        </div>
      </HTMLContainer>
    )
  }

  indicator(shape: PaperCardShape) {
    return <rect width={shape.props.w} height={shape.props.h} rx={8} />
  }
}
