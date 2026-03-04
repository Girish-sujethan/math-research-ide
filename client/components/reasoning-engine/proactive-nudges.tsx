import { X } from "lucide-react"
import type { NudgeItem } from "@/lib/types"
import { SourceChip } from "./source-chip"
import type { StagedPaper } from "@/lib/vault-store"

interface Props {
  nudges: NudgeItem[]
  stagedPapers: StagedPaper[]
  onDismiss: (i: number) => void
}

export function ProactiveNudges({ nudges, stagedPapers, onDismiss }: Props) {
  if (nudges.length === 0) return null

  const headerLabel = nudges.some(n => n.distance != null && typeof n.distance === "number" && n.distance < 0.15)
    ? "References"
    : "Nudges"

  return (
    <div className="px-3 pt-2 pb-1 border-b border-amber-100 bg-amber-50/60">
      <p className="text-[9px] font-semibold text-amber-600 uppercase tracking-wide mb-1.5">
        {headerLabel}
      </p>
      <div className="space-y-1.5">
        {nudges.map((nudge, i) => (
          <div key={i} className="flex items-start gap-1.5 group">
            <span className="flex-shrink-0 text-xs mt-0.5">
              {nudge.type === "warning" ? "⚠" : nudge.type === "connection" ? "🔗" : "💡"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1 flex-wrap">
                <p className="text-[10px] text-gray-700 leading-tight">{nudge.message}</p>
                {nudge.distance != null && typeof nudge.distance === "number" && (
                  <span className={`text-[8px] font-mono px-1 rounded ${
                    nudge.distance < 0.12 ? "bg-green-100 text-green-700"
                    : nudge.distance < 0.18 ? "bg-blue-100 text-blue-700"
                    : "bg-gray-100 text-gray-500"
                  }`}>{Number(nudge.distance).toFixed(2)}</span>
                )}
              </div>
              {nudge.source_paper_id && (
                <div className="mt-0.5">
                  <SourceChip paperId={nudge.source_paper_id} stagedPapers={stagedPapers} />
                </div>
              )}
            </div>
            <button
              onClick={() => onDismiss(i)}
              className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-gray-600"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
