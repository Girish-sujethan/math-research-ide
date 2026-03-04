"use client"

import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ConceptSearchResult, DiscoveryJobResult } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Latex } from "@/components/latex"
import { Search, RefreshCw } from "lucide-react"

type DiscoveryJob = {
  job_id: string
  name: string
}

function subStatusVariant(s: string): "default" | "destructive" | "secondary" | "outline" {
  return (
    ({ passed: "default", failed: "destructive", pending: "secondary", skipped: "outline" } as const)[s] ??
    "outline"
  )
}

function DiscoveryJobCard({ job }: { job: DiscoveryJob }) {
  const { data, refetch } = useQuery<DiscoveryJobResult>({
    queryKey: ["discovery", job.job_id],
    queryFn: () => api.getDiscoveryStatus(job.job_id),
    refetchInterval: q =>
      q.state.data?.status === "running" || q.state.data?.status === "pending" ? 2000 : false,
  })

  const resumeMut = useMutation({
    mutationFn: () => api.resumeDiscovery(job.job_id),
    onSuccess: () => refetch(),
  })

  const topBadge =
    data?.status === "done"
      ? "default"
      : data?.status === "failed"
        ? "destructive"
        : "secondary"

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium">{job.name}</CardTitle>
          <div className="flex items-center gap-2">
            {data && (
              <Badge variant={topBadge as "default" | "destructive" | "secondary"}>{data.status}</Badge>
            )}
            {data?.status === "failed" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => resumeMut.mutate()}
                disabled={resumeMut.isPending}
              >
                <RefreshCw className="size-3 mr-1" />
                Resume
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      {data && (
        <CardContent className="pt-0 pb-3 flex flex-wrap items-center gap-3 text-xs">
          {data.sympy_status && (
            <span className="flex items-center gap-1">
              SymPy <Badge variant={subStatusVariant(data.sympy_status)}>{data.sympy_status}</Badge>
            </span>
          )}
          {data.lean_status && (
            <span className="flex items-center gap-1">
              Lean <Badge variant={subStatusVariant(data.lean_status)}>{data.lean_status}</Badge>
            </span>
          )}
          {data.impacts_count !== undefined && (
            <span className="text-muted-foreground">
              {data.impacts_count} impact{data.impacts_count !== 1 ? "s" : ""}
            </span>
          )}
          {!!data.conflict_count && (
            <span className="text-destructive">
              {data.conflict_count} conflict{data.conflict_count !== 1 ? "s" : ""}
            </span>
          )}
          {data.error && <span className="text-destructive">{data.error}</span>}
        </CardContent>
      )}
    </Card>
  )
}

export default function DiscoveriesPage() {
  const [conceptQuery, setConceptQuery] = useState("")
  const [selectedConcept, setSelectedConcept] = useState<ConceptSearchResult | null>(null)
  const [name, setName] = useState("")
  const [latex, setLatex] = useState("")
  const [description, setDescription] = useState("")
  const [jobs, setJobs] = useState<DiscoveryJob[]>([])

  const conceptSearchMut = useMutation({
    mutationFn: () => api.searchConcepts(conceptQuery, 8),
  })

  const createMut = useMutation({
    mutationFn: () =>
      api.createDiscovery({
        name,
        base_concept_id: selectedConcept?.concept_id,
        modified_latex_statement: latex,
        modification_description: description,
      }),
    onSuccess: res => {
      setJobs(prev => [{ job_id: res.job_id, name }, ...prev])
      setName("")
      setLatex("")
      setDescription("")
      setSelectedConcept(null)
      setConceptQuery("")
      conceptSearchMut.reset()
    },
  })

  const canSubmit =
    name.trim() !== "" && latex.trim() !== "" && description.trim() !== "" && !createMut.isPending

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <h1 className="text-xl font-semibold">Discoveries</h1>

      {/* Base concept picker */}
      <div className="space-y-2">
        <p className="text-sm font-medium">Base Concept (optional)</p>
        <div className="flex gap-2">
          <Input
            value={conceptQuery}
            onChange={e => setConceptQuery(e.target.value)}
            placeholder="Search concepts…"
            onKeyDown={e => {
              if (e.key === "Enter" && conceptQuery.trim()) conceptSearchMut.mutate()
            }}
          />
          <Button
            variant="outline"
            onClick={() => conceptSearchMut.mutate()}
            disabled={!conceptQuery.trim() || conceptSearchMut.isPending}
          >
            <Search className="size-4" />
          </Button>
        </div>
        {conceptSearchMut.data && conceptSearchMut.data.length > 0 && (
          <div className="rounded-md border divide-y max-h-48 overflow-auto">
            {conceptSearchMut.data.map(c => (
              <button
                key={c.concept_id}
                className={`w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors ${
                  selectedConcept?.concept_id === c.concept_id ? "bg-muted font-medium" : ""
                }`}
                onClick={() => setSelectedConcept(c)}
              >
                {c.name}
                <Badge variant="outline" className="ml-2 text-xs">
                  {c.concept_type}
                </Badge>
              </button>
            ))}
          </div>
        )}
        {selectedConcept && (
          <p className="text-xs text-muted-foreground">
            Selected:{" "}
            <span className="font-medium text-foreground">{selectedConcept.name}</span>{" "}
            <button
              className="underline"
              onClick={() => {
                setSelectedConcept(null)
                conceptSearchMut.reset()
                setConceptQuery("")
              }}
            >
              clear
            </button>
          </p>
        )}
      </div>

      {/* Discovery form */}
      <div className="space-y-3">
        <Input value={name} onChange={e => setName(e.target.value)} placeholder="Discovery name" />

        <div className="space-y-1">
          <Textarea
            value={latex}
            onChange={e => setLatex(e.target.value)}
            placeholder="Modified LaTeX statement…"
            rows={3}
            className="font-mono text-sm"
          />
          {latex.trim() && (
            <div className="rounded-md border px-3 py-2 bg-muted text-sm overflow-auto">
              <Latex src={latex} display />
            </div>
          )}
        </div>

        <Textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe the modification…"
          rows={2}
        />

        <Button onClick={() => createMut.mutate()} disabled={!canSubmit}>
          Submit Discovery
        </Button>
        {createMut.isError && (
          <p className="text-sm text-destructive">{(createMut.error as Error).message}</p>
        )}
      </div>

      {/* Jobs */}
      {jobs.length > 0 && (
        <>
          <Separator />
          <div className="space-y-3">
            <h2 className="text-sm font-semibold">Discovery Jobs</h2>
            {jobs.map(job => (
              <DiscoveryJobCard key={job.job_id} job={job} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
