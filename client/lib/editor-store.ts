/**
 * editor-store.ts
 *
 * LaTeX editor integration:
 *  1. Module-level refs for the LaTeX document content and its React setter.
 *  2. Module-level map for embedded images (Python visualization output, etc.).
 *  3. A small Zustand store for UI state (Cmd+K palette, chat context).
 *  4. Helper functions (insertAIBlocks, getEditorContent, transformDocument)
 *     called by other components to read and write the document programmatically.
 */

import { create } from "zustand"
import type { ParsedBlock } from "./parse-reply-to-blocks"
import type { CorrelationItem, FactCheckResponse, FormalizeResult } from "./types"

// ---------------------------------------------------------------------------
// Module-level LaTeX state (not serialised — client-only)
// ---------------------------------------------------------------------------

// Setter provided by LaTeXEditor on mount — calls React's setState
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _latexSetter: ((value: string | ((prev: string) => string)) => void) | null = null

// Mirrors the current textarea value synchronously for getEditorContent()
let _latexContent = ""

/** Called by LaTeXEditor on mount to register its setState wrapper. */
export function setLatexSetter(setter: ((value: string | ((prev: string) => string)) => void) | null) {
  _latexSetter = setter
}

/** Called by LaTeXEditor on every change to keep the cache in sync. */
export function setLatexContent(content: string) {
  _latexContent = content
}

// Backward-compat stubs — cmd-k-toolbar and visuals-view import these
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function setEditorRef(_editor: any) { /* no-op — replaced by setLatexSetter */ }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getEditorRef(): any        { return null }

// ---------------------------------------------------------------------------
// Module-level correlation results (read by renderLatex/renderInline)
// ---------------------------------------------------------------------------

let _activeCorrelations: CorrelationItem[] = []
export function setActiveCorrelations(c: CorrelationItem[]): void { _activeCorrelations = c }
export function getActiveCorrelations(): CorrelationItem[] { return _activeCorrelations }

// ---------------------------------------------------------------------------
// Embedded images — keyed by placeholder ID (e.g. "pyvis-1706123456789")
// ---------------------------------------------------------------------------

const _embeddedImages = new Map<string, string>()

/** Store a data URL so the preview renderer can display it inline. */
export function addEmbeddedImage(id: string, dataUrl: string): void {
  _embeddedImages.set(id, dataUrl)
}

/** Retrieve a stored data URL by ID. Returns undefined if not found. */
export function getEmbeddedImage(id: string): string | undefined {
  return _embeddedImages.get(id)
}

// ---------------------------------------------------------------------------
// Helpers for programmatic document operations
// ---------------------------------------------------------------------------

/**
 * Apply an arbitrary transformation to the current LaTeX document source.
 * The transform function receives the current content and returns the new content.
 * No-op if the editor is not mounted.
 */
export function transformDocument(transform: (prev: string) => string): void {
  if (_latexSetter) _latexSetter(transform)
}

/**
 * Convert ParsedBlock[] (from the AI reply parser) into LaTeX text
 * and append it to the current document.
 * Returns the number of blocks inserted (0 if the editor isn't mounted).
 */
export function insertAIBlocks(parsed: ParsedBlock[]): number {
  if (!_latexSetter || parsed.length === 0) return 0

  let body = ""
  let inItemize = false

  for (const b of parsed) {
    if (b.type === "bullet") {
      if (!inItemize) { body += "\\begin{itemize}\n"; inItemize = true }
      body += `  \\item ${b.content}\n`
    } else {
      if (inItemize) { body += "\\end{itemize}\n\n"; inItemize = false }

      if (b.type === "latex") {
        body += `$$${b.content}$$\n\n`
      } else if (b.type === "heading1") {
        body += `\\section{${b.content}}\n\n`
      } else if (b.type === "heading2") {
        body += `\\subsection{${b.content}}\n\n`
      } else {
        body += `${b.content}\n\n`
      }
    }
  }
  if (inItemize) body += "\\end{itemize}\n\n"

  // Wrap in pending markers so the editor can show Accept / Reject / Verify UI
  const pid = Math.random().toString(36).slice(2, 10)
  const toAppend = `\n\n%HEAVEN_AI_START:${pid}\n${body.trim()}\n%HEAVEN_AI_END:${pid}\n`

  _latexSetter((prev) => prev + toAppend)
  useEditorStore.getState()._setLastInserted()
  return parsed.length
}

/**
 * Append raw LaTeX text at the end of the current document.
 * Used by legacy callers; prefer transformDocument for complex mutations.
 */
export function appendToDocument(latex: string): void {
  if (_latexSetter) _latexSetter((prev) => `${prev}\n\n${latex}\n\n`)
}

/**
 * Return the current LaTeX document as a flat block list for the nudge API.
 * Returns [{type: "latex", content: <full source>}].
 */
export function getEditorContent(): Array<{ type: string; content: string }> {
  if (!_latexContent.trim()) return []
  return [{ type: "latex", content: _latexContent }]
}

// ---------------------------------------------------------------------------
// Line context payload — for "Ask HEAVEN" → RE chip flow
// ---------------------------------------------------------------------------

export interface LineContextPayload {
  lineNum: number
  /** Set when the selection spans multiple lines (e.g. L27–L29). */
  lineEnd?: number
  /** Short display label shown in the RE chip (≤ 60 chars). */
  excerpt: string
  /** Full selected text / current line sent to the AI as context. */
  fullText: string
}

// ---------------------------------------------------------------------------
// Zustand store (UI state only)
// ---------------------------------------------------------------------------

interface EditorStore {
  cmdKBlockId: string | null
  pyVisTargetBlockId: string | null
  lastInsertedAt: number | null
  lastFactCheck: FactCheckResponse | null
  /** Text snippet from the editor that the user wants to add to the chat. */
  pendingChatContext: string | null
  /** Line-context chip set by "Ask HEAVEN" right-click — displayed in RE input. */
  pendingLineContext: LineContextPayload | null
  /** Formalization results keyed by statement.slice(0, 80) */
  formalizationResults: Record<string, FormalizeResult>
  /** Key of the statement currently being formalized (for spinner) */
  formalizingKey: string | null

  openCmdK: (blockId: string) => void
  closeCmdK: () => void
  openPyVis: (blockId: string) => void
  closePyVis: () => void
  _setLastInserted: () => void
  setFactCheck: (result: FactCheckResponse) => void
  clearFactCheck: () => void
  setChatContext: (text: string) => void
  clearChatContext: () => void
  setLineContext: (ctx: LineContextPayload) => void
  clearLineContext: () => void
  setFormalizationResult: (key: string, r: FormalizeResult) => void
  setFormalizingKey: (key: string | null) => void
}

export const useEditorStore = create<EditorStore>()((set) => ({
  cmdKBlockId:           null,
  pyVisTargetBlockId:    null,
  lastInsertedAt:        null,
  lastFactCheck:         null,
  pendingChatContext:    null,
  pendingLineContext:    null,
  formalizationResults:  {},
  formalizingKey:        null,

  openCmdK:                 (blockId) => set({ cmdKBlockId: blockId }),
  closeCmdK:                ()        => set({ cmdKBlockId: null }),
  openPyVis:                (blockId) => set({ pyVisTargetBlockId: blockId }),
  closePyVis:               ()        => set({ pyVisTargetBlockId: null }),
  _setLastInserted:         ()        => set({ lastInsertedAt: Date.now() }),
  setFactCheck:             (result)  => set({ lastFactCheck: result }),
  clearFactCheck:           ()        => set({ lastFactCheck: null }),
  setChatContext:           (text)    => set({ pendingChatContext: text }),
  clearChatContext:         ()        => set({ pendingChatContext: null }),
  setLineContext:           (ctx)     => set({ pendingLineContext: ctx }),
  clearLineContext:         ()        => set({ pendingLineContext: null }),
  setFormalizationResult:   (key, r)  => set(s => ({ formalizationResults: { ...s.formalizationResults, [key]: r } })),
  setFormalizingKey:        (key)     => set({ formalizingKey: key }),
}))
