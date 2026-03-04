// ── Job status ────────────────────────────────────────────────────────────────

export type JobStatus = "pending" | "running" | "done" | "failed";

// ── Papers ────────────────────────────────────────────────────────────────────

export interface PaperSearchResult {
  arxiv_id?: string;
  title: string;
  authors: string[];
  abstract?: string;
  url: string;
  source: string;
}

export interface IngestJobResponse {
  job_id: string;
  paper_id: string;
  status: JobStatus;
}

export interface IngestJobResult {
  job_id: string;
  paper_id: string;
  status: JobStatus;
  concepts_created?: number;
  concept_ids?: string[];
  relationships_created?: number;
  error?: string;
}

// ── Concepts ──────────────────────────────────────────────────────────────────

export interface ConceptRead {
  id: string;
  name: string;
  concept_type: string;
  latex_statement: string;
  description?: string;
  msc_codes: string[];
  lean_verification_status: string;
  lean_output?: string;
  source_paper_id?: string;
}

export interface ConceptSearchResult {
  concept_id: string;
  name: string;
  concept_type: string;
  distance: number;
}

export interface ImpactAnalysisResult {
  concept_id: string;
  affected_by_relationship: Record<string, string[]>;
  potential_conflicts: string[];
  dependencies: string[];
}

// ── Discoveries ───────────────────────────────────────────────────────────────

export interface DiscoveryCreate {
  name: string;
  base_concept_id?: string;
  modified_latex_statement: string;
  modification_description: string;
}

export interface DiscoveryJobResponse {
  job_id: string;
  status: JobStatus;
}

export interface DiscoveryJobResult {
  job_id: string;
  status: JobStatus;
  discovery_id?: string;
  sympy_status?: string;
  lean_status?: string;
  impacts_count?: number;
  conflict_count?: number;
  error?: string;
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export interface CanvasItem {
  type: "concept" | "paper" | "research-job";
  id: string;
  name: string;
}

// ── Research ──────────────────────────────────────────────────────────────────

export interface ResearchJobResult {
  job_id: string;
  status: JobStatus;
  report?: string;       // Content for document insertion
  heaven_note?: string;   // HEAVEN-relevant message for chat pane
  concept_ids?: string[];
  concept_names?: string[];
  paper_ids?: string[];
  paper_names?: string[];
  error?: string;
}

export interface SuggestedAction {
  type: string;
  payload: Record<string, unknown>;
}

export interface ChatResponse {
  reply: string;
  session_id: string;
  canvas_items: CanvasItem[];
  thinking?: string;
  sources?: string[];
}

// ── Editor ────────────────────────────────────────────────────────────────────

export type BlockType = "text" | "latex" | "heading1" | "heading2" | "bullet"

export interface Block {
  id: string
  type: BlockType
  content: string
  diffState?: { original: string; proposed: string }
}

// ── Nudges ────────────────────────────────────────────────────────────────────

export interface NudgeItem {
  type: string
  message: string
  source_paper_id?: string
  source_paper_title?: string
  block_index?: number
  distance?: number
}

// ── Editor intelligence ────────────────────────────────────────────────────

export interface ParityCheckItem {
  start_char: number
  end_char: number
  expression: string
  lhs?: string
  rhs?: string
  status: "verified" | "failed" | "invalid" | "skip"
  output: string
  simplified_form?: string
}

export interface ParityResult { results: ParityCheckItem[] }

export interface FormalizeResult {
  success: boolean
  lean_source?: string
  attempts: number
  error?: string
}

export interface CorrelationItem {
  para_index: number
  start_char: number
  end_char: number
  concept_id: string
  concept_name: string
  concept_type: string
  distance: number
  paper_id: string
  paper_title: string
}

export interface CorrelateResult { correlations: CorrelationItem[] }

// ── Concept graph ─────────────────────────────────────────────────────────────

export interface ConceptNode {
  id: string
  name: string
  concept_type: string
  paper_id?: string
}

export interface ConceptEdge {
  source: string
  target: string
  relationship_type: string
}

export interface ConceptGraphResponse {
  nodes: ConceptNode[]
  edges: ConceptEdge[]
}

// ── Pinned concepts ───────────────────────────────────────────────────────────

export interface PinnedConcept {
  concept_id: string
  name: string
  concept_type: string
  latex_statement: string
  paper_id: string
  paper_title: string
}

// ── Paper Discovery ───────────────────────────────────────────────────────────

export interface DiscoveredPaper {
  arxiv_id?: string
  title: string
  authors: string[]
  abstract?: string
  url: string
  source: string
  relevance_score: number
  relevance_explanation: string
}

export interface PaperDiscoveryJobResult {
  job_id: string
  status: JobStatus
  stage?: string         // "searching_sources" | "ranking_papers" | "done"
  papers: DiscoveredPaper[]
  error?: string
}

// ── Agents ────────────────────────────────────────────────────────────────────

export interface PythonVisualResponse {
  output: string
  image_base64?: string
  error?: string
}

export interface FactCheckResponse {
  verdict: "supported" | "contradicted" | "uncertain"
  confidence: number           // 0.0 – 1.0
  explanation: string
  supporting_evidence: string[]
  issues: string[]
  suggestion?: string
}

// ── Live verification ─────────────────────────────────────────────────────────

export interface LiveCheckItem {
  start_char: number
  end_char: number
  expression: string
  status: "verified" | "failed" | "skipped" | "error"
  tier: "sympy" | "wolfram" | "llm" | "crossref"
  output: string
  simplified_form?: string
  paper_title?: string
}
