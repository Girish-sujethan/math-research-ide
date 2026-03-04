"use client"

import { useVaultStore } from "@/lib/vault-store"
import { CitationMapPanel } from "@/components/reasoning-engine/citation-map-panel"

export function PapersView() {
  const { stagedPapers } = useVaultStore()
  const stagedPaperIds = stagedPapers.map((p) => p.paper_id)

  if (stagedPapers.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-sm text-gray-400 px-6 text-center">
        <p className="mb-1">No papers staged.</p>
        <p className="text-xs text-gray-300">
          Stage papers in the Knowledge Vault to see linked concepts and relationships here.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      <div className="flex-shrink-0 px-4 py-2 border-b border-gray-100">
        <p className="text-[10px] text-gray-500">
          Linked concepts from <strong>{stagedPapers.length}</strong> staged paper{stagedPapers.length !== 1 ? "s" : ""}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto min-h-0">
        <CitationMapPanel stagedPaperIds={stagedPaperIds} stagedPapers={stagedPapers} />
      </div>
    </div>
  )
}
