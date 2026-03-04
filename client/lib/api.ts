import type {
  ChatResponse,
  ConceptGraphResponse,
  ConceptRead,
  ConceptSearchResult,
  CorrelateResult,
  DiscoveryCreate,
  DiscoveryJobResponse,
  DiscoveryJobResult,
  FactCheckResponse,
  FormalizeResult,
  ImpactAnalysisResult,
  IngestJobResponse,
  IngestJobResult,
  LiveCheckItem,
  PythonVisualResponse,
  NudgeItem,
  PaperDiscoveryJobResult,
  ParityResult,
  PaperSearchResult,
  ResearchJobResult,
} from "./types";

export type { IngestJobResponse };

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function get<T>(path: string) {
  return req<T>(path);
}

function post<T>(path: string, body?: unknown) {
  return req<T>(path, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export const api = {
  // ── Papers ─────────────────────────────────────────────────────────────────
  searchPapers: (query: string, source: string, limit = 10) =>
    post<PaperSearchResult[]>("/papers/search", { query, source, limit }),

  ingestPaper: (arxiv_id: string) =>
    post<IngestJobResponse>("/papers/ingest", { arxiv_id }),

  getIngestStatus: (job_id: string) =>
    get<IngestJobResult>(`/papers/ingest/${job_id}`),

  resumeIngest: (job_id: string) =>
    post<IngestJobResponse>(`/papers/ingest/${job_id}/resume`),

  // ── Discoveries ────────────────────────────────────────────────────────────
  createDiscovery: (payload: DiscoveryCreate) =>
    post<DiscoveryJobResponse>("/discoveries", payload),

  getDiscoveryStatus: (job_id: string) =>
    get<DiscoveryJobResult>(`/discoveries/jobs/${job_id}`),

  resumeDiscovery: (job_id: string) =>
    post<DiscoveryJobResponse>(`/discoveries/jobs/${job_id}/resume`),

  // ── Concepts ───────────────────────────────────────────────────────────────
  searchConcepts: (query: string, n_results = 10) =>
    post<ConceptSearchResult[]>("/concepts/search", { query, n_results }),

  getConcept: (id: string) => get<ConceptRead>(`/concepts/${id}`),

  getConceptImpact: (id: string) =>
    get<ImpactAnalysisResult>(`/concepts/${id}/impact`),

  getPaperConcepts: (paper_id: string, limit = 200) =>
    get<ConceptRead[]>(`/concepts?source_paper_id=${paper_id}&limit=${limit}`),

  getConceptGraph: (paper_ids?: string[]) => {
    const q = paper_ids?.length ? `?paper_ids=${paper_ids.join(",")}` : ""
    return get<ConceptGraphResponse>(`/concepts/graph${q}`)
  },

  // ── Chat ───────────────────────────────────────────────────────────────────
  chat: (
    message: string,
    session_id?: string,
    context?: Record<string, unknown>
  ) => post<ChatResponse>("/chat", { message, session_id, context }),

  // ── Upload ─────────────────────────────────────────────────────────────────
  uploadPaper: async (file: File): Promise<IngestJobResponse> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/papers/upload`, { method: "POST", body: form });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json() as Promise<IngestJobResponse>;
  },

  // ── DOI ingest ─────────────────────────────────────────────────────────────
  ingestByDoi: (doi: string) =>
    post<IngestJobResponse>("/papers/ingest", { doi }),

  // ── Research ───────────────────────────────────────────────────────────────
  startResearch: (query: string) =>
    post<{ job_id: string; status: string }>("/research/start", { query }),

  getResearchStatus: (job_id: string) =>
    get<ResearchJobResult>(`/research/jobs/${job_id}`),

  // ── Verify / Nudges ────────────────────────────────────────────────────────
  getNudges: (
    blocks: { type: string; content: string }[],
    staged_paper_ids: string[]
  ) =>
    post<{ nudges: NudgeItem[] }>("/verify/nudge", { blocks, staged_paper_ids }),

  checkParity: (source: string) =>
    post<ParityResult>("/verify/parity", { source }),

  formalizeStatement: (statement: string, concept_name: string) =>
    post<FormalizeResult>("/verify/formalize", { statement, concept_name }),

  getCorrelations: (
    paragraphs: { text: string; start_char: number; end_char: number }[],
    staged_paper_ids: string[]
  ) => post<CorrelateResult>("/verify/correlate", { paragraphs, staged_paper_ids }),

  liveCheck: (source: string, staged_paper_ids: string[] = []) =>
    post<{ results: LiveCheckItem[] }>("/verify/live-check", { source, staged_paper_ids }),

  // ── Paper Discovery ────────────────────────────────────────────────────────
  discoverPapers: (query: string) =>
    post<{ job_id: string; status: string }>("/papers/discover", { query }),

  getPaperDiscoveryStatus: (job_id: string) =>
    get<PaperDiscoveryJobResult>(`/papers/discover/${job_id}`),

  // ── Agents ─────────────────────────────────────────────────────────────────
  runPythonVisual: (code: string, title?: string) =>
    post<PythonVisualResponse>("/agents/python-visual", { code, title }),

  factCheck: (statement: string, staged_paper_ids: string[]) =>
    post<FactCheckResponse>("/agents/fact-check", { statement, staged_paper_ids }),
};
