"use client"

import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ConceptRead, ConceptSearchResult } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Latex } from "@/components/latex"
import { Search } from "lucide-react"

function leanBadgeVariant(status: string): "default" | "destructive" | "secondary" | "outline" {
  return (
    ({
      verified: "default",
      failed: "destructive",
      pending: "secondary",
      not_attempted: "outline",
    } as const)[status] ?? "outline"
  )
}

function ConceptDetail({ id }: { id: string }) {
  const { data: concept, isLoading: cLoading } = useQuery<ConceptRead>({
    queryKey: ["concept", id],
    queryFn: () => api.getConcept(id),
  })

  const { data: impact, isLoading: iLoading } = useQuery({
    queryKey: ["impact", id],
    queryFn: () => api.getConceptImpact(id),
  })

  if (cLoading) return <p className="p-4 text-sm text-muted-foreground">Loading…</p>
  if (!concept) return null

  return (
    <div className="p-5 space-y-4">
      {/* Header */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-base font-semibold">{concept.name}</h2>
          <Badge variant="outline">{concept.concept_type}</Badge>
          <Badge variant={leanBadgeVariant(concept.lean_verification_status)}>
            Lean: {concept.lean_verification_status}
          </Badge>
        </div>
        {concept.msc_codes.length > 0 && (
          <div className="flex gap-1 flex-wrap">
            {concept.msc_codes.map(code => (
              <Badge key={code} variant="secondary" className="text-xs font-mono">
                {code}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* LaTeX statement */}
      <div className="rounded-md border p-3 bg-muted overflow-auto">
        <Latex src={concept.latex_statement} display />
      </div>

      {concept.description && (
        <p className="text-sm text-muted-foreground">{concept.description}</p>
      )}

      {/* Tabs */}
      <Tabs defaultValue="impact">
        <TabsList>
          <TabsTrigger value="impact">Impact</TabsTrigger>
          <TabsTrigger value="lean">Lean Output</TabsTrigger>
        </TabsList>

        <TabsContent value="impact" className="pt-3 space-y-3">
          {iLoading && <p className="text-sm text-muted-foreground">Loading impact…</p>}
          {impact && (() => {
            const hasDeps = impact.dependencies.length > 0
            const hasConflicts = impact.potential_conflicts.length > 0
            const hasAffected = Object.keys(impact.affected_by_relationship).length > 0
            if (!hasDeps && !hasConflicts && !hasAffected) {
              return <p className="text-sm text-muted-foreground">No graph connections found.</p>
            }
            return (
              <>
                {hasDeps && (
                  <div className="text-sm">
                    <p className="font-medium mb-1.5">
                      Dependencies ({impact.dependencies.length})
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {impact.dependencies.map(d => (
                        <Badge key={d} variant="outline" className="text-xs font-mono">
                          {d.slice(0, 8)}…
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                {hasConflicts && (
                  <div className="text-sm">
                    <p className="font-medium text-destructive mb-1.5">
                      Potential Conflicts ({impact.potential_conflicts.length})
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {impact.potential_conflicts.map(c => (
                        <Badge key={c} variant="destructive" className="text-xs font-mono">
                          {c.slice(0, 8)}…
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                {hasAffected && (
                  <div className="text-sm">
                    <p className="font-medium mb-1.5">Affected By</p>
                    <div className="space-y-1">
                      {Object.entries(impact.affected_by_relationship).map(([rel, ids]) => (
                        <div key={rel} className="flex items-start gap-2">
                          <Badge variant="secondary" className="text-xs shrink-0">
                            {rel}
                          </Badge>
                          <span className="text-xs text-muted-foreground font-mono">
                            {(ids as string[]).map(id => id.slice(0, 8)).join(", ")}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )
          })()}
        </TabsContent>

        <TabsContent value="lean" className="pt-3">
          {concept.lean_output ? (
            <pre className="text-xs bg-muted rounded-md p-3 overflow-auto whitespace-pre-wrap">
              {concept.lean_output}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">No Lean output available.</p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default function ConceptsPage() {
  const [query, setQuery] = useState("")
  const [selected, setSelected] = useState<ConceptSearchResult | null>(null)

  const searchMut = useMutation({
    mutationFn: () => api.searchConcepts(query, 15),
  })

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (query.trim()) searchMut.mutate()
  }

  return (
    <div className="flex h-full">
      {/* Left panel — search + results */}
      <div className="w-72 shrink-0 border-r flex flex-col">
        <div className="p-4 border-b">
          <h1 className="text-lg font-semibold mb-3">Concepts</h1>
          <form onSubmit={handleSearch} className="flex gap-2">
            <Input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search…"
              className="flex-1"
            />
            <Button
              type="submit"
              size="icon"
              variant="outline"
              disabled={!query.trim() || searchMut.isPending}
            >
              <Search className="size-4" />
            </Button>
          </form>
        </div>

        <div className="flex-1 overflow-auto divide-y">
          {searchMut.isError && (
            <p className="p-3 text-sm text-destructive">
              {(searchMut.error as Error).message}
            </p>
          )}
          {searchMut.data?.length === 0 && (
            <p className="p-3 text-sm text-muted-foreground">No results.</p>
          )}
          {searchMut.data?.map(c => (
            <button
              key={c.concept_id}
              onClick={() => setSelected(c)}
              className={`w-full px-3 py-2.5 text-left hover:bg-muted transition-colors ${
                selected?.concept_id === c.concept_id ? "bg-muted" : ""
              }`}
            >
              <p className="text-sm font-medium truncate">{c.name}</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <Badge variant="outline" className="text-xs">
                  {c.concept_type}
                </Badge>
                <span className="text-xs text-muted-foreground">{c.distance != null && typeof c.distance === "number" ? c.distance.toFixed(3) : "—"}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Right panel — detail */}
      <div className="flex-1 overflow-auto">
        {selected ? (
          <ConceptDetail id={selected.concept_id} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">Select a concept to view details.</p>
          </div>
        )}
      </div>
    </div>
  )
}
