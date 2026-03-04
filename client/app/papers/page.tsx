"use client"

import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { PaperSearchResult, IngestJobResult } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Search, Download, RefreshCw } from "lucide-react"

type IngestJob = {
  job_id: string
  arxiv_id: string
  title: string
}

function statusVariant(status: string): "secondary" | "outline" | "default" | "destructive" {
  return (
    ({ pending: "secondary", running: "outline", done: "default", failed: "destructive" } as const)[
      status
    ] ?? "outline"
  )
}

function IngestJobCard({ job }: { job: IngestJob }) {
  const { data, refetch } = useQuery<IngestJobResult>({
    queryKey: ["ingest", job.job_id],
    queryFn: () => api.getIngestStatus(job.job_id),
    refetchInterval: q =>
      q.state.data?.status === "running" || q.state.data?.status === "pending" ? 2000 : false,
  })

  const resumeMut = useMutation({
    mutationFn: () => api.resumeIngest(job.job_id),
    onSuccess: () => refetch(),
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-medium truncate">{job.title}</CardTitle>
          <div className="flex items-center gap-2 shrink-0">
            {data && <Badge variant={statusVariant(data.status)}>{data.status}</Badge>}
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
        <p className="text-xs text-muted-foreground font-mono">{job.arxiv_id}</p>
      </CardHeader>
      {data?.concepts_created !== undefined && (
        <CardContent className="pt-0 pb-3">
          <p className="text-xs text-muted-foreground">
            {data.concepts_created} concept{data.concepts_created !== 1 ? "s" : ""} extracted
            {data.relationships_created !== undefined &&
              `, ${data.relationships_created} relationship${data.relationships_created !== 1 ? "s" : ""}`}
          </p>
        </CardContent>
      )}
    </Card>
  )
}

export default function PapersPage() {
  const [query, setQuery] = useState("")
  const [source, setSource] = useState("arxiv")
  const [jobs, setJobs] = useState<IngestJob[]>([])

  const searchMut = useMutation({
    mutationFn: () => api.searchPapers(query, source, 10),
  })

  const ingestMut = useMutation({
    mutationFn: (paper: PaperSearchResult) => api.ingestPaper(paper.arxiv_id!),
    onSuccess: (res, paper) => {
      setJobs(prev => [{ job_id: res.job_id, arxiv_id: paper.arxiv_id!, title: paper.title }, ...prev])
    },
  })

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (query.trim()) searchMut.mutate()
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <h1 className="text-xl font-semibold">Papers</h1>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <select
          value={source}
          onChange={e => setSource(e.target.value)}
          className="rounded-md border bg-background px-2 text-sm"
        >
          <option value="arxiv">arXiv</option>
          <option value="exa">Exa</option>
        </select>
        <Input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search papers…"
          className="flex-1"
        />
        <Button type="submit" disabled={searchMut.isPending || !query.trim()}>
          <Search className="size-4 mr-1" />
          Search
        </Button>
      </form>

      {/* Search results */}
      {searchMut.isError && (
        <p className="text-sm text-destructive">{(searchMut.error as Error).message}</p>
      )}
      {searchMut.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">No results found.</p>
      )}
      {searchMut.data && searchMut.data.length > 0 && (
        <div className="space-y-3">
          {searchMut.data.map((paper, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <CardTitle className="text-sm font-medium leading-snug">{paper.title}</CardTitle>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {paper.authors.slice(0, 3).join(", ")}
                      {paper.authors.length > 3 && " et al."}
                    </p>
                    {paper.arxiv_id && (
                      <p className="text-xs font-mono text-muted-foreground">{paper.arxiv_id}</p>
                    )}
                  </div>
                  {paper.arxiv_id && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => ingestMut.mutate(paper)}
                      disabled={ingestMut.isPending}
                    >
                      <Download className="size-3 mr-1" />
                      Ingest
                    </Button>
                  )}
                </div>
              </CardHeader>
              {paper.abstract && (
                <CardContent className="pt-0 pb-3">
                  <p className="text-xs text-muted-foreground line-clamp-3">{paper.abstract}</p>
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      )}

      {/* Ingest jobs */}
      {jobs.length > 0 && (
        <>
          <Separator />
          <div className="space-y-3">
            <h2 className="text-sm font-semibold">Ingest Jobs</h2>
            {jobs.map(job => (
              <IngestJobCard key={job.job_id} job={job} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
