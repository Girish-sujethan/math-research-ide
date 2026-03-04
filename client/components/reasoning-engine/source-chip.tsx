import type { StagedPaper } from "@/lib/vault-store"

interface Props {
  paperId: string
  stagedPapers: StagedPaper[]
}

export function SourceChip({ paperId, stagedPapers }: Props) {
  const paper = stagedPapers.find((p) => p.paper_id === paperId)
  const title = paper?.title ?? paperId

  return (
    <span className="inline-flex items-center gap-0.5 text-[10px] bg-amber-100 text-amber-700 rounded-full px-2 py-0.5 mr-1">
      📄 <span className="max-w-[120px] truncate">{title}</span>
    </span>
  )
}
