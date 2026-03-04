import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { PinnedConcept } from "./types"

export interface StagedPaper {
  paper_id: string
  title: string
  authors: string[]
  abstract: string
  arxiv_id?: string
}

interface VaultStore {
  stagedPapers: StagedPaper[]
  stagePaper(p: StagedPaper): void
  unstagePaper(paper_id: string): void
  pinnedConcepts: PinnedConcept[]
  pinConcept(c: PinnedConcept): void
  unpinConcept(concept_id: string): void
  /** Increment to trigger Linked Concepts / concept graph refetch (e.g. after ingest completes). */
  conceptGraphVersion: number
  invalidateConceptGraph(): void
}

export const useVaultStore = create<VaultStore>()(
  persist(
    (set) => ({
      stagedPapers: [],

      stagePaper: (p) =>
        set((state) => {
          if (state.stagedPapers.some((s) => s.paper_id === p.paper_id)) return state
          return { stagedPapers: [...state.stagedPapers, p] }
        }),

      unstagePaper: (paper_id) =>
        set((state) => ({
          stagedPapers: state.stagedPapers.filter((p) => p.paper_id !== paper_id),
        })),

      pinnedConcepts: [],

      pinConcept: (c) =>
        set((state) => {
          if (state.pinnedConcepts.some((p) => p.concept_id === c.concept_id)) return state
          return { pinnedConcepts: [...state.pinnedConcepts, c] }
        }),

      unpinConcept: (concept_id) =>
        set((state) => ({
          pinnedConcepts: state.pinnedConcepts.filter((p) => p.concept_id !== concept_id),
        })),

      conceptGraphVersion: 0,
      invalidateConceptGraph: () =>
        set((state) => ({ conceptGraphVersion: state.conceptGraphVersion + 1 })),
    }),
    {
      name: "heaven-vault-store",
      partialize: (state) => ({
        stagedPapers: state.stagedPapers,
        pinnedConcepts: state.pinnedConcepts,
      }),
    }
  )
)
