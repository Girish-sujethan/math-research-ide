import { create } from "zustand"
import { persist } from "zustand/middleware"

export type CanvasMode = "card" | "graph"

interface CanvasStore {
  mode: CanvasMode
  selectedConceptIds: string[]
  selectedPaperIds: string[]
  editingConceptId: string | null
  // Pre-graph positions keyed by shape id: { x, y }
  savedCardPositions: Record<string, { x: number; y: number }>

  setMode: (m: CanvasMode) => void
  setSelected: (conceptIds: string[], paperIds: string[]) => void
  setEditing: (id: string | null) => void
  saveCardPositions: (positions: Record<string, { x: number; y: number }>) => void
}

export const useCanvasStore = create<CanvasStore>()(
  persist(
    (set) => ({
      mode: "card",
      selectedConceptIds: [],
      selectedPaperIds: [],
      editingConceptId: null,
      savedCardPositions: {},

      setMode: (m) => set({ mode: m }),
      setSelected: (conceptIds, paperIds) =>
        set({ selectedConceptIds: conceptIds, selectedPaperIds: paperIds }),
      setEditing: (id) => set({ editingConceptId: id }),
      saveCardPositions: (positions) => set({ savedCardPositions: positions }),
    }),
    {
      name: "heaven-canvas-store",
      partialize: (state) => ({
        mode: state.mode,
        savedCardPositions: state.savedCardPositions,
      }),
    }
  )
)
