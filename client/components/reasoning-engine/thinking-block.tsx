"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"

interface Props {
  thinking: string
}

export function ThinkingBlock({ thinking }: Props) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="mb-1.5">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-gray-700 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
        HEAVEN's reasoning
      </button>
      {expanded && (
        <pre className="mt-1 text-[10px] text-gray-600 bg-gray-50 rounded-lg p-2 whitespace-pre-wrap leading-relaxed">
          {thinking}
        </pre>
      )}
    </div>
  )
}
