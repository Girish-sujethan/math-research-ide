"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, Terminal } from "lucide-react"
import { createReactBlockSpec } from "@blocknote/react"

function PythonVisualOutputRenderer({ block }: { block: any }) {
  const [showCode, setShowCode] = useState(false)
  const { code = "", imageBase64 = "", stdout = "", error = "" } = block.props

  return (
    <div className="w-full my-2 rounded-xl border border-gray-200 overflow-hidden shadow-sm">
      {/* Header bar */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-900">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-green-400" />
          <span className="text-[11px] font-mono font-semibold text-green-400 tracking-wide">
            Python Visualization
          </span>
        </div>
        {code && (
          <button
            onClick={() => setShowCode((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-200 transition-colors"
          >
            {showCode ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {showCode ? "hide code" : "show code"}
          </button>
        )}
      </div>

      {/* Source code (collapsible) */}
      {showCode && (
        <pre className="px-4 py-3 bg-gray-800 text-gray-200 text-xs font-mono overflow-x-auto leading-relaxed">
          {code}
        </pre>
      )}

      {/* Plot */}
      {imageBase64 && (
        <div className="bg-white p-4 flex justify-center border-t border-gray-100">
          <img
            src={`data:image/png;base64,${imageBase64}`}
            alt="Python visualization output"
            className="max-w-full rounded-lg shadow-sm"
          />
        </div>
      )}

      {/* stdout */}
      {stdout && (
        <pre className="px-4 py-3 bg-gray-50 text-gray-700 text-xs font-mono border-t border-gray-100 overflow-x-auto whitespace-pre-wrap leading-relaxed">
          {stdout}
        </pre>
      )}

      {/* Error */}
      {error && (
        <pre className="px-4 py-3 bg-red-50 text-red-700 text-xs font-mono border-t border-red-100 overflow-x-auto whitespace-pre-wrap leading-relaxed">
          {error}
        </pre>
      )}
    </div>
  )
}

export const PythonVisualOutputBlockSpec = createReactBlockSpec(
  {
    type: "matlabOutput" as const,
    propSchema: {
      code:        { default: "" as string },
      imageBase64: { default: "" as string },
      stdout:      { default: "" as string },
      error:       { default: "" as string },
    },
    content: "none" as const,
  },
  { render: PythonVisualOutputRenderer }
)
