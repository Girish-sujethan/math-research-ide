"use client"

import {
  HTMLContainer,
  Rectangle2d,
  RecordProps,
  ShapeUtil,
  T,
  TLBaseShape,
} from "@tldraw/tldraw"

export type AnnotationShape = TLBaseShape<
  "annotation",
  {
    w: number
    h: number
    text: string
    color: string
  }
>

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export class AnnotationShapeUtil extends ShapeUtil<any> {
  static override type = "annotation" as const

  static override props: RecordProps<AnnotationShape> = {
    w: T.number,
    h: T.number,
    text: T.string,
    color: T.string,
  }

  getDefaultProps(): AnnotationShape["props"] {
    return {
      w: 200,
      h: 120,
      text: "",
      color: "#fef9c3",
    }
  }

  getGeometry(shape: AnnotationShape) {
    return new Rectangle2d({ width: shape.props.w, height: shape.props.h, isFilled: true })
  }

  component(shape: AnnotationShape) {
    const { text, color } = shape.props

    return (
      <HTMLContainer
        id={shape.id}
        style={{ width: shape.props.w, height: shape.props.h }}
      >
        <div
          className="w-full h-full rounded-md shadow-sm p-3 text-xs text-gray-800 font-sans overflow-hidden"
          style={{ backgroundColor: color }}
        >
          <p className="whitespace-pre-wrap break-words">
            {text || <span className="text-gray-400 italic">Note…</span>}
          </p>
        </div>
      </HTMLContainer>
    )
  }

  indicator(shape: AnnotationShape) {
    return <rect width={shape.props.w} height={shape.props.h} rx={6} />
  }
}
