"use client"

import { Editor } from "@tldraw/tldraw"
import { createContext, useContext, useState } from "react"

interface WorkspaceContextValue {
  editor: Editor | null
  setEditor: (e: Editor | null) => void
}

const WorkspaceContext = createContext<WorkspaceContextValue>({
  editor: null,
  setEditor: () => {},
})

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [editor, setEditor] = useState<Editor | null>(null)
  return (
    <WorkspaceContext.Provider value={{ editor, setEditor }}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspaceEditor() {
  return useContext(WorkspaceContext)
}
