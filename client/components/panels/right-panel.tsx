"use client"

import { useCanvasStore } from "@/lib/canvas-store"
import { useWorkspaceEditor } from "@/components/canvas/workspace-context"
import { ChatPanel } from "./chat-panel"
import { EditPanel } from "./edit-panel"

interface Props {
  className?: string
}

export function RightPanel({ className }: Props) {
  const editingConceptId = useCanvasStore((s) => s.editingConceptId)
  const { editor } = useWorkspaceEditor()

  return (
    <div className={`flex flex-col bg-white h-full overflow-hidden ${className ?? ""}`}>
      {editingConceptId ? (
        <EditPanel conceptId={editingConceptId} />
      ) : (
        <ChatPanel editor={editor} />
      )}
    </div>
  )
}
