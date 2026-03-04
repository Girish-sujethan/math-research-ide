"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { KnowledgeVault } from "@/components/knowledge-vault/knowledge-vault"
import { MiddlePane } from "@/components/middle-pane/middle-pane"
import { ReasoningEngine } from "@/components/reasoning-engine/reasoning-engine"

// ---------------------------------------------------------------------------
// Draggable pane divider
// ---------------------------------------------------------------------------

function PaneDivider({ onDelta }: { onDelta: (dx: number) => void }) {
  const dragging = useRef(false)
  const lastX    = useRef(0)
  // Stable callback ref so the event listener doesn't go stale
  const cbRef    = useRef(onDelta)
  cbRef.current  = onDelta

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragging.current) return
      cbRef.current(e.clientX - lastX.current)
      lastX.current = e.clientX
    }
    function onUp() { dragging.current = false }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup",   onUp)
    return () => {
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup",   onUp)
    }
  }, [])

  return (
    <div
      className="w-1 flex-shrink-0 bg-gray-200 hover:bg-blue-400 active:bg-blue-500 cursor-col-resize transition-colors z-10"
      onMouseDown={(e) => {
        e.preventDefault()
        dragging.current = true
        lastX.current    = e.clientX
      }}
    />
  )
}

// ---------------------------------------------------------------------------
// Workspace layout
// ---------------------------------------------------------------------------

export default function WorkspacePage() {
  const [leftW,  setLeftW]  = useState(260)
  const [rightW, setRightW] = useState(320)

  const dragLeft  = useCallback((dx: number) => setLeftW( w => Math.max(180, Math.min(420, w + dx))), [])
  const dragRight = useCallback((dx: number) => setRightW(w => Math.max(240, Math.min(520, w - dx))), [])

  return (
    <div className="flex h-screen overflow-hidden bg-white select-none">
      {/* Left pane — Knowledge Vault */}
      <div className="flex-shrink-0 flex flex-col overflow-hidden" style={{ width: leftW }}>
        <KnowledgeVault className="flex-1 min-h-0 border-r border-gray-200 flex flex-col overflow-hidden" />
      </div>

      <PaneDivider onDelta={dragLeft} />

      {/* Middle pane — Document / Graph / Visuals / Papers */}
      <MiddlePane className="flex-1 min-w-0 overflow-hidden" />

      <PaneDivider onDelta={dragRight} />

      {/* Right pane — Reasoning Engine */}
      <div className="flex-shrink-0 flex flex-col overflow-hidden" style={{ width: rightW }}>
        <ReasoningEngine className="flex-1 min-h-0 border-l border-gray-200 flex flex-col overflow-hidden" />
      </div>
    </div>
  )
}
