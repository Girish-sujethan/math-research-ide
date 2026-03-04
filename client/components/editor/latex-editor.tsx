"use client"

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react"
import katex from "katex"
import "katex/dist/katex.min.css"
import { Download, FileText, Network, Terminal, X, Loader2, ChevronDown, Sparkles, Check, FlaskConical } from "lucide-react"
import CodeMirror from "@uiw/react-codemirror"
import { EditorView, Decoration, lineNumbers, highlightActiveLine, highlightActiveLineGutter, keymap } from "@codemirror/view"
import { RangeSetBuilder } from "@codemirror/state"
import {
  setLatexContent,
  setLatexSetter,
  getEmbeddedImage,
  addEmbeddedImage,
  transformDocument,
  useEditorStore,
  setActiveCorrelations,
  getActiveCorrelations,
} from "@/lib/editor-store"
import { api } from "@/lib/api"
import { GraphBuilder } from "@/components/middle-pane/graph-builder"
import { useVaultStore } from "@/lib/vault-store"
import type { FactCheckResponse, LiveCheckItem } from "@/lib/types"
import type { LineContextPayload } from "@/lib/editor-store"

// ---------------------------------------------------------------------------
// Module-level toggle state (read by renderLatex, renderEnv, renderInline, CM extension)
// Updated from the component render body on every render.
// ---------------------------------------------------------------------------

let _showFormal = true
let _showCorrelations = true
let _liveCheckResults: LiveCheckItem[] = []

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

const STORAGE_KEY = "heaven-latex-v1"

const DEFAULT_CONTENT = `\\documentclass{article}
\\title{Untitled Document}
\\author{}
\\date{\\today}

\\begin{document}
\\maketitle

\\begin{abstract}
Write a brief summary of your work here.
\\end{abstract}

\\section{Introduction}

Write your mathematical document here. Inline math works: $x \\in \\mathbb{R}$.

Display math:
$$\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}$$

\\begin{theorem}
Every continuous function on a compact set attains its maximum and minimum.
\\end{theorem}

\\begin{proof}
By the extreme value theorem, since $f$ is continuous on a compact domain $K$,
the image $f(K)$ is compact, hence closed and bounded.
\\end{proof}

\\begin{definition}
A topological space $X$ is \\emph{compact} if every open cover of $X$
has a finite subcover.
\\end{definition}

\\section{Main Result}

\\begin{align}
  \\zeta(s) &= \\sum_{n=1}^{\\infty} \\frac{1}{n^s} \\\\
            &= \\prod_{p \\text{ prime}} \\frac{1}{1 - p^{-s}}
\\end{align}

\\begin{remark}
The identity above holds for $\\text{Re}(s) > 1$.
\\end{remark}

\\section{Conclusion}

Further work remains. See \\texttt{arxiv:2301.00001} for details.

\\end{document}
`

function loadFromStorage(): string {
  if (typeof window === "undefined") return DEFAULT_CONTENT
  try {
    return localStorage.getItem(STORAGE_KEY) ?? DEFAULT_CONTENT
  } catch {
    return DEFAULT_CONTENT
  }
}

// ---------------------------------------------------------------------------
// Document mutation helpers
// ---------------------------------------------------------------------------

function ensurePackage(doc: string, pkg: string): string {
  if (doc.includes(`\\usepackage{${pkg}}`)) return doc
  const m = doc.match(/\\documentclass(?:\[[^\]]*\])?\{[^}]*\}/)
  if (m && m.index !== undefined) {
    const pos = m.index + m[0].length
    return doc.slice(0, pos) + `\n\\usepackage{${pkg}}` + doc.slice(pos)
  }
  return doc
}

/**
 * Find a good insertion point near `fromPos`: the end of the current
 * paragraph (next double-newline), or just after `fromPos` if none found.
 */
function findInsertPoint(doc: string, fromPos: number): number {
  // Snap to end of the nearest paragraph (next \n\n)
  const idx = doc.indexOf("\n\n", fromPos)
  if (idx >= 0) return idx
  // Fall back: just before \end{document}
  const endDoc = doc.lastIndexOf("\\end{document}")
  return endDoc >= 0 ? endDoc : doc.length
}

/**
 * Insert `block` into `doc` at or just after `atPos`, snapping to the
 * next paragraph boundary. Prepends preamble packages first.
 * If `pendingId` is provided the block is wrapped with AI-pending markers
 * so the preview shows Accept / Reject / Verify controls.
 */
function insertNearCursor(
  rawDoc: string,
  block: string,
  atPos: number,
  packages: string[] = [],
  pendingId?: string,
): string {
  let doc = rawDoc
  const origLen = doc.length
  for (const pkg of packages) doc = ensurePackage(doc, pkg)
  const preambleAdded = doc.length - origLen
  const adjustedPos   = Math.min(atPos + preambleAdded, doc.length)
  const insertAt      = findInsertPoint(doc, adjustedPos)
  const content       = pendingId ? wrapAsPending(block, pendingId) : block
  return doc.slice(0, insertAt) + "\n\n" + content + "\n" + doc.slice(insertAt)
}

// ---------------------------------------------------------------------------
// Pending AI insertion helpers
// ---------------------------------------------------------------------------

type DocSegment =
  | { type: "normal"; content: string; startOffset: number }
  | { type: "pending"; id: string; content: string; startOffset: number }

function generatePendingId(): string {
  return Math.random().toString(36).slice(2, 10)
}

function wrapAsPending(content: string, id: string): string {
  return `%HEAVEN_AI_START:${id}\n${content.trim()}\n%HEAVEN_AI_END:${id}\n`
}

/** Split a LaTeX source string into normal and pending segments; each segment has startOffset in the full document. */
function extractPendingSections(source: string): DocSegment[] {
  const result: DocSegment[] = []
  const re = /%HEAVEN_AI_START:([a-z0-9]+)\n([\s\S]*?)%HEAVEN_AI_END:\1\n/g
  let lastIdx = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(source)) !== null) {
    if (m.index > lastIdx) result.push({ type: "normal", content: source.slice(lastIdx, m.index), startOffset: lastIdx })
    result.push({ type: "pending", id: m[1], content: m[2], startOffset: m.index })
    lastIdx = m.index + m[0].length
  }
  if (lastIdx < source.length) result.push({ type: "normal", content: source.slice(lastIdx), startOffset: lastIdx })
  return result
}

function countPendingSections(source: string): number {
  return (source.match(/%HEAVEN_AI_START:[a-z0-9]+\n/g) ?? []).length
}

function acceptPending(doc: string, id: string): string {
  return doc.replace(
    new RegExp(`%HEAVEN_AI_START:${id}\\n([\\s\\S]*?)%HEAVEN_AI_END:${id}\\n`),
    "$1\n",
  )
}

function rejectPending(doc: string, id: string): string {
  return doc.replace(
    new RegExp(`\\n*%HEAVEN_AI_START:${id}\\n[\\s\\S]*?%HEAVEN_AI_END:${id}\\n`),
    "",
  )
}

function acceptAllPending(doc: string): string {
  return doc
    .replace(/%HEAVEN_AI_START:[a-z0-9]+\n/g, "")
    .replace(/%HEAVEN_AI_END:[a-z0-9]+\n/g, "")
}

function rejectAllPending(doc: string): string {
  return doc.replace(/\n*%HEAVEN_AI_START:[a-z0-9]+\n[\s\S]*?%HEAVEN_AI_END:[a-z0-9]+\n/g, "")
}

// ---------------------------------------------------------------------------
// CodeMirror extensions (module-level — stable, created once)
// ---------------------------------------------------------------------------

/** Theme: matches the rest of the UI's monospace styling. */
const CM_THEME = EditorView.theme({
  "&":                                  { height: "100%" },
  ".cm-scroller":                       { overflow: "auto", lineHeight: "1.625", fontFamily: '"Menlo","Consolas","Monaco",monospace', fontSize: "13px" },
  ".cm-content":                        { padding: "1rem 1rem 1rem 0" },
  ".cm-gutters":                        { backgroundColor: "#f9fafb", borderRight: "1px solid #f3f4f6", userSelect: "none" },
  ".cm-lineNumbers .cm-gutterElement":  { color: "#d1d5db", paddingRight: "8px", minWidth: "2.5rem", textAlign: "right" },
  ".cm-activeLineGutter":               { backgroundColor: "#eff6ff", color: "#3b82f6", fontWeight: "600" },
  ".cm-activeLine":                     { backgroundColor: "rgba(59,130,246,0.04)" },
  ".cm-pending-ai":                     { backgroundColor: "rgba(16,185,129,0.12)" },
  ".cm-selectionBackground, .cm-focused .cm-selectionBackground": { backgroundColor: "#bfdbfe !important" },
})

/** Decoration: highlights every line inside a pending AI section with an emerald tint. */
const CM_PENDING_DECORATION = EditorView.decorations.compute(["doc"], (state) => {
  const src = state.doc.toString()
  const re  = /%HEAVEN_AI_START:([a-z0-9]+)\n[\s\S]*?%HEAVEN_AI_END:\1\n/g
  const builder = new RangeSetBuilder<Decoration>()
  const mark    = Decoration.line({ class: "cm-pending-ai" })
  let m: RegExpExecArray | null
  while ((m = re.exec(src)) !== null) {
    const sLine = state.doc.lineAt(m.index)
    const eLine = state.doc.lineAt(m.index + m[0].length - 1)
    for (let ln = sLine.number; ln <= eLine.number; ln++) {
      const l = state.doc.line(ln)
      builder.add(l.from, l.from, mark)
    }
  }
  return builder.finish()
})

// ---------------------------------------------------------------------------
// TikZ → SVG preview renderer
// ---------------------------------------------------------------------------

interface TikZNode { id: string; x: number; y: number; label: string }
interface TikZEdge { from: string; to: string; directed: boolean; label: string }

function parseTikZToSVG(body: string): React.ReactNode {
  const nodes: TikZNode[] = []
  const edges: TikZEdge[] = []

  const nodeRe = /\\node\[[^\]]*\]\s*\((\w+)\)\s*at\s*\(([^,]+),([^)]+)\)\s*\{([^}]*)\}/g
  let m: RegExpExecArray | null
  while ((m = nodeRe.exec(body)) !== null) {
    nodes.push({
      id: m[1],
      x: parseFloat(m[2]),
      y: parseFloat(m[3]),
      label: m[4].replace(/\$([^$]*)\$/g, "$1").trim(),
    })
  }

  const edgeRe = /\\draw\[([^\]]*)\]\s*\((\w+)\)\s*--(?:\s*node\[[^\]]*\]\s*\{([^}]*)\})?\s*\((\w+)\)/g
  while ((m = edgeRe.exec(body)) !== null) {
    edges.push({
      from: m[2],
      to:   m[4],
      directed: m[1].includes("->"),
      label: m[3] ? m[3].replace(/\$([^$]*)\$/g, "$1").trim() : "",
    })
  }

  if (nodes.length === 0) return null

  const scale = 50
  const xs = nodes.map(n => n.x)
  const ys = nodes.map(n => n.y)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const pad  = 1.2

  const W = Math.max(200, (maxX - minX + pad * 2) * scale)
  const H = Math.max(120, (maxY - minY + pad * 2) * scale)

  function toSvg(x: number, y: number) {
    return { sx: (x - minX + pad) * scale, sy: H - (y - minY + pad) * scale }
  }

  const nodeMap: Record<string, { sx: number; sy: number }> = {}
  nodes.forEach(n => { nodeMap[n.id] = toSvg(n.x, n.y) })
  const R = 22
  const arrowId = `tikz-${Math.random().toString(36).slice(2, 7)}`

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
      className="block mx-auto my-2 border border-gray-100 rounded-lg bg-gray-50">
      <defs>
        <marker id={arrowId} markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="#4b5563" />
        </marker>
      </defs>
      {edges.map((e, i) => {
        const a = nodeMap[e.from], b = nodeMap[e.to]
        if (!a || !b) return null
        const dx = b.sx - a.sx, dy = b.sy - a.sy
        const len = Math.sqrt(dx * dx + dy * dy) || 1
        const x1  = a.sx + (dx / len) * R
        const y1  = a.sy + (dy / len) * R
        const x2  = b.sx - (dx / len) * (R + (e.directed ? 7 : 0))
        const y2  = b.sy - (dy / len) * (R + (e.directed ? 7 : 0))
        return (
          <g key={i}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#4b5563" strokeWidth={1.5}
              markerEnd={e.directed ? `url(#${arrowId})` : undefined} />
            {e.label && (
              <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6}
                textAnchor="middle" fontSize={11} fill="#6b7280" fontFamily="serif" fontStyle="italic">
                {e.label}
              </text>
            )}
          </g>
        )
      })}
      {nodes.map(n => {
        const { sx, sy } = toSvg(n.x, n.y)
        return (
          <g key={n.id}>
            <circle cx={sx} cy={sy} r={R} fill="#dbeafe" stroke="#3b82f6" strokeWidth={1.5} />
            <text x={sx} y={sy} textAnchor="middle" dominantBaseline="central"
              fontSize={13} fontFamily="serif" fontStyle="italic" fill="#1e3a8a">{n.label}</text>
          </g>
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Inline renderer
// ---------------------------------------------------------------------------

function renderInline(text: string, baseKey = 0): React.ReactNode {
  // Correlation highlights are applied by paragraph in the preview (see LaTeXPreview normal-section rendering)
  const parts: React.ReactNode[] = []
  let s = text
  let k = baseKey * 10000

  while (s.length > 0) {
    let m: RegExpMatchArray | null
    if (s.startsWith("\\(")) {
      const end = s.indexOf("\\)", 2)
      if (end > 2) {
        const inner = s.slice(2, end)
        try {
          const html = katex.renderToString(inner, { throwOnError: false, output: "html" })
          parts.push(<span key={k++} dangerouslySetInnerHTML={{ __html: html }} />)
        } catch {
          parts.push(<span key={k++} className="text-red-500">{s.slice(0, end + 2)}</span>)
        }
        s = s.slice(end + 2); continue
      }
    }
    if ((m = s.match(/^\$((?:[^$\\]|\\[\s\S])*)\$/))) {
      try {
        const html = katex.renderToString(m[1], { throwOnError: false, output: "html" })
        parts.push(<span key={k++} dangerouslySetInnerHTML={{ __html: html }} />)
      } catch {
        parts.push(<span key={k++} className="text-red-500">{m[0]}</span>)
      }
      s = s.slice(m[0].length); continue
    }
    if (s.startsWith("\\\\")) { parts.push(<br key={k++} />); s = s.slice(2); continue }
    if ((m = s.match(/^\\textbf\{((?:[^{}]|\{[^{}]*\})*)\}/))) {
      parts.push(<strong key={k++}>{m[1]}</strong>); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\(?:textit|emph)\{((?:[^{}]|\{[^{}]*\})*)\}/))) {
      parts.push(<em key={k++}>{m[1]}</em>); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\texttt\{((?:[^{}]|\{[^{}]*\})*)\}/))) {
      parts.push(<code key={k++} className="font-mono text-[0.875em] bg-gray-100 px-0.5 rounded">{m[1]}</code>)
      s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\underline\{((?:[^{}]|\{[^{}]*\})*)\}/))) {
      parts.push(<span key={k++} className="underline">{m[1]}</span>); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\textsc\{((?:[^{}]|\{[^{}]*\})*)\}/))) {
      parts.push(<span key={k++} style={{ fontVariant: "small-caps" }}>{m[1]}</span>)
      s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\(?:ldots|dots|cdots)\b/))) {
      parts.push(<span key={k++}>…</span>); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\(?:qed|square|blacksquare)\b/))) {
      parts.push(<span key={k++} className="float-right">□</span>); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\([%${}&#_])/))) {
      parts.push(<span key={k++}>{m[1]}</span>); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\(?:cite|label|ref|eqref|pageref|footnote|index)\{[^}]*\}/))) {
      s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\[a-zA-Z]+\{(?:[^{}]|\{[^{}]*\})*\}/))) { s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\[a-zA-Z]+\b/)))                          { s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\./)))                                      { s = s.slice(m[0].length); continue }
    const nextIdx = s.search(/\$|\\/)
    if (nextIdx < 0)       { parts.push(<span key={k++}>{s}</span>); s = "" }
    else if (nextIdx === 0){ parts.push(<span key={k++}>{s[0]}</span>); s = s.slice(1) }
    else                   { parts.push(<span key={k++}>{s.slice(0, nextIdx)}</span>); s = s.slice(nextIdx) }
  }

  if (parts.length === 0) return null
  return parts.length === 1 ? parts[0] : <>{parts}</>
}

// ---------------------------------------------------------------------------
// Environment renderer
// ---------------------------------------------------------------------------

const MATH_ENVS = new Set([
  "equation", "equation*", "align", "align*", "gather", "gather*",
  "multline", "multline*", "split", "cases",
  "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "matrix",
  "flalign", "flalign*", "alignat", "alignat*",
])

interface EnvStyle { label: string; border: string; bg: string; text: string }
const THEOREM_STYLES: Record<string, EnvStyle> = {
  theorem:     { label: "Theorem",     border: "border-blue-400",   bg: "bg-blue-50",   text: "text-blue-900" },
  lemma:       { label: "Lemma",       border: "border-blue-400",   bg: "bg-blue-50",   text: "text-blue-900" },
  corollary:   { label: "Corollary",   border: "border-blue-300",   bg: "bg-blue-50",   text: "text-blue-900" },
  proposition: { label: "Proposition", border: "border-blue-400",   bg: "bg-blue-50",   text: "text-blue-900" },
  definition:  { label: "Definition",  border: "border-green-400",  bg: "bg-green-50",  text: "text-green-900" },
  remark:      { label: "Remark",      border: "border-amber-400",  bg: "bg-amber-50",  text: "text-amber-900" },
  note:        { label: "Note",        border: "border-amber-400",  bg: "bg-amber-50",  text: "text-amber-900" },
  example:     { label: "Example",     border: "border-orange-400", bg: "bg-orange-50", text: "text-orange-900" },
  claim:       { label: "Claim",       border: "border-purple-400", bg: "bg-purple-50", text: "text-purple-900" },
  conjecture:  { label: "Conjecture",  border: "border-purple-400", bg: "bg-purple-50", text: "text-purple-900" },
  proof:       { label: "Proof",       border: "border-gray-300",   bg: "bg-gray-50",   text: "text-gray-800" },
  observation: { label: "Observation", border: "border-amber-400",  bg: "bg-amber-50",  text: "text-amber-900" },
  axiom:       { label: "Axiom",       border: "border-red-400",    bg: "bg-red-50",    text: "text-red-900"   },
}

function renderEnv(
  name: string, body: string, key: number,
  srcText?: string, onJump?: (q: string) => void,
): React.ReactNode {
  const jp = onJump && srcText ? { onClick: () => onJump(srcText), className: "cursor-pointer" } : {}

  if (MATH_ENVS.has(name)) {
    const src = `\\begin{${name}}${body}\\end{${name}}`
    try {
      const html = katex.renderToString(src, { displayMode: true, throwOnError: false, output: "html" })
      return <div key={key} {...jp} className={`my-5 overflow-x-auto text-center ${jp.className ?? ""}`} dangerouslySetInnerHTML={{ __html: html }} />
    } catch {
      return <pre key={key} className="text-red-500 text-sm font-mono my-2 whitespace-pre-wrap">{src}</pre>
    }
  }

  // TikZ graph → SVG
  if (name === "tikzpicture") {
    const svg = parseTikZToSVG(body)
    if (svg) return <div key={key} className={`my-6 text-center ${jp.className ?? ""}`} {...(onJump && srcText ? { onClick: () => onJump(srcText) } : {})}>{svg}</div>
    return <pre key={key} className="text-xs font-mono text-gray-400 bg-gray-50 p-3 rounded my-4 overflow-x-auto">{body}</pre>
  }

  // Figure environment — look inside for tikzpicture or embedded image
  if (name === "figure" || name === "figure*") {
    const captionM = body.match(/\\caption\{([^}]*)\}/)
    const caption  = captionM ? captionM[1] : null
    const jumpAttrs = onJump && srcText ? { onClick: () => onJump(srcText) } : {}

    const tikzM = body.match(/\\begin\{tikzpicture\}([\s\S]*?)\\end\{tikzpicture\}/)
    if (tikzM) {
      return (
        <figure key={key} className={`my-8 text-center ${jp.className ?? ""}`} {...jumpAttrs}>
          {parseTikZToSVG(tikzM[1])}
          {caption && <figcaption className="text-sm text-gray-500 mt-2 italic">{caption}</figcaption>}
        </figure>
      )
    }

    const imgM = body.match(/\\includegraphics(?:\[[^\]]*\])?\{(pyvis-\d+)\}/)
    if (imgM) {
      const dataUrl = getEmbeddedImage(imgM[1])
      if (dataUrl) {
        return (
          <figure key={key} className={`my-8 text-center ${jp.className ?? ""}`} {...jumpAttrs}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={dataUrl} alt="Python visualization output" className="max-w-full mx-auto border border-gray-100 rounded-lg" />
            {caption && <figcaption className="text-sm text-gray-500 mt-2 italic">{caption}</figcaption>}
          </figure>
        )
      }
    }

    return (
      <figure key={key} className={`my-6 text-center italic text-gray-600 text-sm ${jp.className ?? ""}`} {...jumpAttrs}>
        {renderInline(body.trim())}
        {caption && <figcaption className="mt-1">{caption}</figcaption>}
      </figure>
    )
  }

  if (name === "enumerate" || name === "itemize") {
    const Tag = name === "enumerate" ? "ol" : "ul"
    const cls = name === "enumerate" ? "list-decimal list-outside ml-6 my-3 space-y-1" : "list-disc list-outside ml-6 my-3 space-y-1"
    const items = body.split(/\\item\b/).filter(s => s.trim())
    return (
      <Tag key={key} className={cls}>
        {items.map((item, i) => <li key={i} className="leading-relaxed text-gray-800">{renderInline(item.trim(), i + 1)}</li>)}
      </Tag>
    )
  }

  if (name === "abstract") {
    return (
      <div key={key} className="mx-10 my-6 text-sm text-gray-700 border border-gray-200 rounded-lg p-4">
        <p className="font-bold text-center mb-2">Abstract</p>
        <p className="italic leading-relaxed">{renderInline(body.trim())}</p>
      </div>
    )
  }

  if (name === "verbatim" || name === "lstlisting") {
    return <pre key={key} className="font-mono text-sm bg-gray-100 rounded-lg p-4 my-4 overflow-x-auto leading-normal">{body}</pre>
  }

  const style = THEOREM_STYLES[name.replace(/\*$/, "")]
  if (style) {
    const isProof = name === "proof"
    const fKey = body.trim().slice(0, 80)
    const fResult = _showFormal ? useEditorStore.getState().formalizationResults[fKey] : undefined
    const fBusy   = _showFormal ? useEditorStore.getState().formalizingKey === fKey : false
    const liveHit = _showFormal ? _liveCheckResults.find(r =>
      r.expression && body.trim().slice(0, 80).includes(r.expression.slice(0, 30))
    ) : undefined
    const badge = _showFormal
      ? fBusy
        ? <span className="text-[9px] text-gray-400 animate-pulse">Formalizing…</span>
        : fResult?.success
          ? <span className="inline-flex items-center gap-0.5 text-[9px] text-green-600 font-semibold bg-green-50 border border-green-200 rounded-full px-1.5 py-0.5">✓ Verified</span>
          : fResult
            ? <span className="text-[9px] text-red-500">Formalization failed</span>
            : liveHit?.status === "verified"
              ? <span className="inline-flex items-center gap-0.5 text-[9px] text-green-600 font-semibold bg-green-50 border border-green-200 rounded-full px-1.5 py-0.5" title={`Verified (${liveHit.tier})`}>✓ Verified</span>
              : liveHit?.status === "failed"
                ? <span className="inline-flex items-center gap-0.5 text-[9px] text-red-500 font-semibold bg-red-50 border border-red-200 rounded-full px-1.5 py-0.5" title={`Failed (${liveHit.tier}): ${liveHit.output.slice(0, 80)}`}>✗ Error</span>
                : liveHit?.status === "skipped"
                  ? <span className="inline-flex items-center gap-0.5 text-[9px] text-gray-400 font-medium bg-gray-50 border border-gray-200 rounded-full px-1.5 py-0.5" title={liveHit.output}>Skipped</span>
                    : null
      : null
    return (
      <div key={key}
        className={`my-4 border-l-4 ${style.border} ${style.bg} pl-4 pr-3 py-3 rounded-r-xl ${onJump && srcText ? "cursor-pointer hover:brightness-95 transition-[filter]" : ""}`}
        {...(onJump && srcText ? { onClick: () => onJump(srcText) } : {})}
      >
        <div className="flex justify-between items-start mb-0.5">
          <span className={`font-bold text-sm ${style.text} mr-1.5`}>{style.label}.</span>
          {badge}
        </div>
        <span className={`leading-relaxed ${style.text} ${isProof ? "" : "italic"}`}>{renderInline(body.trim())}</span>
        {isProof && <span className="float-right text-gray-500 mt-1 select-none">□</span>}
      </div>
    )
  }

  return <div key={key} className="my-3 pl-5 border-l-2 border-gray-200 text-gray-700 text-sm italic leading-relaxed">{renderInline(body.trim())}</div>
}

// ---------------------------------------------------------------------------
// Block pattern scanner
// ---------------------------------------------------------------------------

const BLOCK_PATTERNS: RegExp[] = [
  /\$\$/, /\\\[/, /\\begin\{/, /\\(?:section|subsection|subsubsection)\*?\{/,
  /\\(?:title|author|date)\{/, /\\maketitle\b/, /\\(?:newpage|clearpage|pagebreak)\b/,
  /\\vspace\{/, /\\hspace\{/, /\\(?:medskip|bigskip|smallskip|vfill)\b/,
  /\\(?:noindent|centering|raggedright|raggedleft|par|hfill)\b/,
  /\\(?:label|ref|cite|eqref)\{/, /^%/m,
  /\\(?:documentclass|usepackage|geometry|pagestyle|setlength|setcounter)\{/,
  /\\(?:begin|end)\{document\}/,
  /\\(?:newcommand|renewcommand|DeclareMathOperator|theoremstyle|newtheorem)\{/,
  /\\appendix\b/, /\\tableofcontents\b/,
]

function findNextBlock(s: string): number {
  let min = s.length
  for (const p of BLOCK_PATTERNS) {
    const idx = s.search(p)
    if (idx > 0 && idx < min) min = idx
  }
  return min
}

// ---------------------------------------------------------------------------
// Main LaTeX → React renderer
// ---------------------------------------------------------------------------

function renderLatex(source: string, onJump?: (q: string) => void): React.ReactNode {
  const nodes: React.ReactNode[] = []
  let s = source

  const bodyStart = s.indexOf("\\begin{document}")
  if (bodyStart >= 0) s = s.slice(bodyStart + "\\begin{document}".length)
  const bodyEnd = s.indexOf("\\end{document}")
  if (bodyEnd >= 0) s = s.slice(0, bodyEnd)

  let k = 0
  let storedTitle = "", storedAuthor = "", storedDate = ""

  if (bodyStart < 0) {
    const tM = source.match(/\\title\{([\s\S]*?)\}/)
    const aM = source.match(/\\author\{([\s\S]*?)\}/)
    const dM = source.match(/\\date\{([\s\S]*?)\}/)
    if (tM) storedTitle  = tM[1]
    if (aM) storedAuthor = aM[1]
    if (dM) storedDate   = dM[1] === "\\today"
      ? new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })
      : dM[1]
  }

  const jProps = (q: string) => onJump
    ? { onClick: () => onJump(q), className: "cursor-pointer hover:bg-blue-50/60 rounded transition-colors -mx-1 px-1" }
    : {}

  while (s.length > 0) {
    let m: RegExpMatchArray | null

    if ((m = s.match(/^\\\[([\s\S]*?)\\\]/))) {
      try {
        const html = katex.renderToString(m[1].trim(), { displayMode: true, throwOnError: false, output: "html" })
        nodes.push(<div key={k++} className="my-5 overflow-x-auto text-center" dangerouslySetInnerHTML={{ __html: html }} />)
      } catch { nodes.push(<pre key={k++} className="text-red-500 text-sm font-mono">{m[0]}</pre>) }
      s = s.slice(m[0].length); continue
    }

    if ((m = s.match(/^\$\$([\s\S]*?)\$\$/))) {
      try {
        const mathContent = m[1].trim()
        const html = katex.renderToString(mathContent, { displayMode: true, throwOnError: false, output: "html" })
        const katexAttrs = onJump
          ? { onClick: () => onJump(m![0]), className: "my-5 overflow-x-auto text-center cursor-pointer hover:bg-blue-50/40 rounded transition-colors" }
          : { className: "my-5 overflow-x-auto text-center" }
        const liveHit = _showFormal ? _liveCheckResults.find(r =>
          r.expression && mathContent.includes(r.expression.slice(0, 20))
        ) : undefined
        const badge = liveHit ? (
          liveHit.status === "verified"
            ? <span className="absolute -right-1 -top-1 bg-emerald-500 text-white rounded-full w-4 h-4 flex items-center justify-center text-[8px] shadow-sm" title={`Verified (${liveHit.tier}): ${liveHit.output.slice(0, 80)}`}>✓</span>
            : liveHit.status === "failed"
            ? <span className="absolute -right-1 -top-1 bg-red-500 text-white rounded-full w-4 h-4 flex items-center justify-center text-[8px] shadow-sm" title={`Failed (${liveHit.tier}): ${liveHit.output.slice(0, 80)}`}>✗</span>
            : null
        ) : null
        nodes.push(
          <div key={k++} className="relative" style={{ display: "flow-root" }}>
            <div {...katexAttrs} dangerouslySetInnerHTML={{ __html: html }} />
            {badge}
          </div>
        )
      } catch { nodes.push(<pre key={k++} className="text-red-500 text-sm font-mono">{m[0]}</pre>) }
      s = s.slice(m[0].length); continue
    }

    if ((m = s.match(/^\\begin\{(\w+\*?)\}([\s\S]*?)\\end\{\1\}/))) {
      nodes.push(renderEnv(m[1], m[2], k++, m[0], onJump))
      s = s.slice(m[0].length); continue
    }

    if ((m = s.match(/^\\section\*?\{([\s\S]*?)\}/))) {
      nodes.push(<h2 key={k++} {...jProps(m[0])} className={`text-[1.3rem] font-bold mt-8 mb-3 text-gray-900 border-b border-gray-200 pb-1 ${onJump ? "cursor-pointer hover:bg-blue-50/60 rounded transition-colors -mx-1 px-1" : ""}`}>{renderInline(m[1])}</h2>)
      s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\subsection\*?\{([\s\S]*?)\}/))) {
      nodes.push(<h3 key={k++} {...jProps(m[0])} className={`text-base font-bold mt-5 mb-2 text-gray-800 ${onJump ? "cursor-pointer hover:bg-blue-50/60 rounded transition-colors -mx-1 px-1" : ""}`}>{renderInline(m[1])}</h3>)
      s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\subsubsection\*?\{([\s\S]*?)\}/))) {
      nodes.push(<h4 key={k++} {...jProps(m[0])} className={`text-sm font-bold mt-4 mb-1.5 text-gray-700 ${onJump ? "cursor-pointer hover:bg-blue-50/60 rounded transition-colors -mx-1 px-1" : ""}`}>{renderInline(m[1])}</h4>)
      s = s.slice(m[0].length); continue
    }

    if ((m = s.match(/^\\title\{([\s\S]*?)\}/)))  { storedTitle  = m[1]; s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\author\{([\s\S]*?)\}/))) { storedAuthor = m[1]; s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\date\{([\s\S]*?)\}/)))   {
      storedDate = m[1] === "\\today"
        ? new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })
        : m[1]
      s = s.slice(m[0].length); continue
    }

    if ((m = s.match(/^\\maketitle\b/))) {
      if (storedTitle) {
        nodes.push(
          <div key={k++} className="text-center my-8">
            <h1 className="text-[1.9rem] font-bold text-gray-900 leading-tight mb-1">{renderInline(storedTitle)}</h1>
            {storedAuthor && <p className="text-gray-600 mt-1">{storedAuthor}</p>}
            {storedDate   && <p className="text-gray-500 text-sm mt-0.5">{storedDate}</p>}
          </div>
        )
      }
      s = s.slice(m[0].length); continue
    }

    if ((m = s.match(/^\\(?:newpage|clearpage|pagebreak)\b/))) {
      nodes.push(<hr key={k++} className="my-8 border-gray-300" />); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\(?:medskip|bigskip|smallskip|vfill)\b/))) {
      nodes.push(<div key={k++} className="my-3" />); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\vspace\{[^}]*\}/))) {
      nodes.push(<div key={k++} className="my-4" />); s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\appendix\b/))) {
      nodes.push(<hr key={k++} className="my-8 border-dashed border-gray-400" />); s = s.slice(m[0].length); continue
    }

    if ((m = s.match(/^%[^\n]*\n?/))) { s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\(?:noindent|centering|raggedright|raggedleft|par|hfill)\b/))) { s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\hspace\{[^}]*\}/))) { s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\(?:label|ref|cite|eqref)\{[^}]*\}/))) { s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\(?:tableofcontents|listoffigures|listoftables)\b/))) { s = s.slice(m[0].length); continue }
    if ((m = s.match(/^\\(?:documentclass|usepackage|geometry|pagestyle|setlength|setcounter)(?:\*?)(?:\[[^\]]*\])?\{[^}]*\}(?:\{[^}]*\})?/))) {
      s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\(?:newcommand|renewcommand|DeclareMathOperator|theoremstyle|newtheorem)\{[^}]*\}(?:\[[^\]]*\])?(?:\{[^}]*\})?(?:\{[^}]*\})?/))) {
      s = s.slice(m[0].length); continue
    }
    if ((m = s.match(/^\\(?:begin|end)\{document\}/))) { s = s.slice(m[0].length); continue }

    const nextBlock = findNextBlock(s)
    if (nextBlock === 0) { s = s.slice(1); continue }
    const textChunk = s.slice(0, nextBlock)
    s = s.slice(nextBlock)
    for (const para of textChunk.split(/\n{2,}/)) {
      const trimmed = para.trim()
      if (!trimmed) continue
      const srcQuery = trimmed.slice(0, 80)
      const crossrefHit = _showFormal ? _liveCheckResults.find(r =>
        r.tier === "crossref" && r.expression && trimmed.length > 30 &&
        trimmed.slice(0, 40).replace(/\\[a-zA-Z]+/g, '').trim().includes(
          r.expression.slice(0, 15).replace(/\\[a-zA-Z]+/g, '').trim()
        )
      ) : undefined
      nodes.push(
        <div key={k++} className="relative mb-3">
          <p
            className={`text-gray-800 leading-relaxed ${onJump ? "cursor-text hover:bg-blue-50/30 rounded transition-colors -mx-1 px-1" : ""}`}
            onClick={onJump ? () => onJump(srcQuery) : undefined}
          >
            {renderInline(trimmed)}
          </p>
          {crossrefHit && crossrefHit.paper_title && (
            <span
              className="inline-flex items-center gap-1 text-[8px] text-indigo-600 bg-indigo-50 border border-indigo-200 rounded-full px-1.5 py-0.5 mt-0.5"
              title={crossrefHit.output}
            >
              📄 Supported by: {crossrefHit.paper_title.slice(0, 50)}{crossrefHit.paper_title.length > 50 ? "…" : ""}
            </span>
          )}
        </div>
      )
    }
  }

  return <>{nodes}</>
}

// ---------------------------------------------------------------------------
// State interfaces
// ---------------------------------------------------------------------------

interface CtxMenuState {
  x: number
  y: number
  /** Selected text at right-click time (empty string if cursor, not selection). */
  selection: string
  /** CodeMirror character offset of selection start (used for insertion). */
  insertPos: number
  selectionEnd: number
  /** 1-based line numbers captured at right-click (for correct line refs). */
  fromLine: number
  toLine: number
  /** Full text of the line under the cursor at right-click time. */
  lineText: string
}

interface PyVisModalState {
  code: string
  running: boolean
  result: string | null
  error: string | null
  /** Textarea cursor position to insert near. */
  insertPos: number
}

// Paragraph ranges: same logic as correlation effect so para_index aligns with backend.
function getParagraphRanges(content: string): { start_char: number; end_char: number; para_index: number }[] {
  const out: { start_char: number; end_char: number; para_index: number }[] = []
  let pos = 0
  for (const chunk of content.split(/\n\n+/)) {
    const stripped = chunk.replace(/\\[a-zA-Z]+(?:\{[^}]*\})?/g, " ").trim()
    if (stripped.length >= 30) {
      out.push({ start_char: pos, end_char: pos + chunk.length, para_index: out.length })
    }
    pos += chunk.length + 2
  }
  return out
}

// ---------------------------------------------------------------------------
// Preview component
// ---------------------------------------------------------------------------

interface PreviewProps {
  content: string
  onJump?: (q: string) => void
  onContextMenu?: (e: React.MouseEvent) => void
  contentRef?: React.RefObject<HTMLDivElement | null>
  onAccept?: (id: string) => void
  onReject?: (id: string) => void
  onVerify?: (id: string, content: string) => void
  verifyingIds?: Set<string>
  verifyResults?: Map<string, FactCheckResponse>
  /** Version counter — increment to force re-render when module-level results change */
  correlationVersion?: number
  /** Version counter — increment to force re-render when live-check results change */
  liveCheckVersion?: number
}

function LaTeXPreview({
  content, onJump, onContextMenu, contentRef,
  onAccept, onReject, onVerify, verifyingIds, verifyResults,
  correlationVersion, liveCheckVersion,
}: PreviewProps) {
  const sections = useMemo(
    () => extractPendingSections(content),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [content, correlationVersion, liveCheckVersion],
  )
  const paraRanges = useMemo(() => getParagraphRanges(content), [content])
  const correlations = getActiveCorrelations()

  return (
    <div className="h-full overflow-y-auto bg-white select-text" onContextMenu={onContextMenu}>
      <div ref={contentRef} className="max-w-2xl mx-auto px-10 py-8 font-serif text-[15px] text-gray-900 leading-relaxed">
        {sections.map((sec, i) => {
          if (sec.type === "normal") {
            // Render by paragraph so we can highlight using para_index from the correlate API
            let sectionPos = 0
            const nodes: React.ReactNode[] = []
            const chunks = sec.content.split(/\n\n+/)
            for (let j = 0; j < chunks.length; j++) {
              const chunk = chunks[j]
              const stripped = chunk.replace(/\\[a-zA-Z]+(?:\{[^}]*\})?/g, " ").trim()
              const globalStart = sec.startOffset + sectionPos
              sectionPos += chunk.length + 2
              const para = paraRanges.find(p => globalStart >= p.start_char && globalStart < p.end_char)
              const paraHits = para !== undefined ? correlations.filter(c => c.para_index === para.para_index) : []
              const best = paraHits.length > 0 ? paraHits.sort((a, b) => (a.distance ?? 1) - (b.distance ?? 1))[0] : null
              const body = renderLatex(chunk, onJump)
              const bestDist = best?.distance != null && typeof best.distance === "number" ? best.distance : null
              if (best && _showCorrelations && bestDist !== null) {
                const strength = bestDist < 0.2 ? "strong" : bestDist < 0.35 ? "moderate" : "weak"
                const bgCls = strength === "strong"
                  ? "bg-violet-100/70 border-violet-300"
                  : strength === "moderate"
                  ? "bg-blue-50/70 border-blue-200"
                  : "bg-sky-50/50 border-sky-200"
                const dotCls = strength === "strong" ? "bg-violet-500" : strength === "moderate" ? "bg-blue-400" : "bg-sky-400"
                const shortTitle = best.paper_title
                  ? (best.paper_title.length > 40 ? best.paper_title.slice(0, 37) + "…" : best.paper_title)
                  : ""
                const matchPct = Math.round((1 - bestDist) * 100)
                nodes.push(
                  <div
                    key={`${i}-${j}`}
                    className={`relative rounded-md border-l-[3px] ${bgCls} px-3 py-1.5 my-1 cursor-pointer group transition-colors hover:bg-violet-100/90`}
                    onClick={() => {
                      useEditorStore.getState().setLineContext({
                        lineNum: 0,
                        excerpt: `~ ${best.concept_name}`,
                        fullText: `Correlated concept: ${best.concept_name} (${best.concept_type}) from "${best.paper_title}", similarity ${matchPct}%`,
                      })
                    }}
                  >
                    {body}
                    <div className="flex items-center gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <span className={`w-1.5 h-1.5 rounded-full ${dotCls} shrink-0`} />
                      <span className="text-[9px] font-medium text-gray-600">
                        {best.concept_name}
                      </span>
                      <span className="text-[8px] text-gray-400">·</span>
                      <span className="text-[8px] text-gray-500 italic truncate max-w-[200px]">
                        {shortTitle || best.concept_type}
                      </span>
                      <span className="text-[8px] text-gray-400 ml-auto shrink-0">
                        {matchPct}% match
                      </span>
                    </div>
                  </div>
                )
              } else {
                nodes.push(<React.Fragment key={`${i}-${j}`}>{body}</React.Fragment>)
              }
            }
            return <React.Fragment key={`n-${i}`}>{nodes}</React.Fragment>
          }

          // ── Pending AI-inserted section ───────────────────────────────────
          const { id, content: pendingContent } = sec
          const isVerifying  = verifyingIds?.has(id) ?? false
          const verifyResult = verifyResults?.get(id)
          const verdictCls   = !verifyResult ? "" :
            verifyResult.verdict === "supported"    ? "bg-emerald-100 border-emerald-200 text-emerald-800" :
            verifyResult.verdict === "contradicted" ? "bg-red-100 border-red-200 text-red-800" :
                                                      "bg-amber-100 border-amber-200 text-amber-800"

          return (
            <div key={`p-${id}`} className="my-6 rounded-xl border border-emerald-300 bg-emerald-50/40 overflow-hidden shadow-sm">

              {/* Action header */}
              <div className="flex items-center gap-1.5 px-3 py-2 bg-emerald-100/80 border-b border-emerald-200">
                <Sparkles className="w-3 h-3 text-emerald-600 shrink-0" />
                <span className="text-[10px] font-semibold text-emerald-700 flex-1">AI Generated</span>

                <button
                  onClick={() => onVerify?.(id, pendingContent)}
                  disabled={isVerifying}
                  title="Mathematically verify this insertion"
                  className="flex items-center gap-0.5 text-[9px] px-2 py-0.5 rounded-md bg-white border border-blue-200 text-blue-700 hover:bg-blue-50 transition-colors disabled:opacity-50"
                >
                  {isVerifying
                    ? <Loader2 className="w-2.5 h-2.5 animate-spin" />
                    : <FlaskConical className="w-2.5 h-2.5" />}
                  Verify
                </button>

                <button
                  onClick={() => onReject?.(id)}
                  title="Reject this AI insertion"
                  className="flex items-center gap-0.5 text-[9px] px-2 py-0.5 rounded-md bg-white border border-red-200 text-red-700 hover:bg-red-50 transition-colors"
                >
                  <X className="w-2.5 h-2.5" /> Reject
                </button>

                <button
                  onClick={() => onAccept?.(id)}
                  title="Accept this AI insertion"
                  className="flex items-center gap-0.5 text-[9px] px-2.5 py-0.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 transition-colors font-medium"
                >
                  <Check className="w-2.5 h-2.5" /> Accept
                </button>
              </div>

              {/* Verify result ribbon */}
              {verifyResult && (
                <div className={`px-4 py-1.5 text-[10px] leading-relaxed border-b ${verdictCls}`}>
                  <span className="font-semibold capitalize">{verifyResult.verdict}</span>
                  {" · "}
                  <span className="opacity-80">{Math.round(verifyResult.confidence * 100)}% confidence</span>
                  {" — "}
                  {verifyResult.explanation}
                </div>
              )}

              {/* Rendered content */}
              <div className="px-2 py-1 bg-white/60">
                {renderLatex(pendingContent, onJump)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main LaTeX Editor component
// ---------------------------------------------------------------------------

const DEFAULT_PYVIS = `# Write any Python/NumPy/Matplotlib code here
x = np.linspace(0, 2 * np.pi, 400)
y = np.sin(x)

plt.figure(figsize=(7, 3.5))
plt.plot(x, y, 'b-', linewidth=1.5)
plt.title('Sine Wave')
plt.xlabel('x')
plt.ylabel('sin(x)')
plt.grid(True)`

interface Props {
  className?: string
}

export function LaTeXEditor({ className }: Props) {
  const { setLineContext } = useEditorStore()
  const { stagedPapers } = useVaultStore()
  const [content, setContent] = useState<string>(loadFromStorage)

  // ── Intelligence toggle state ─────────────────────────────────────────────
  const [showFormal, setShowFormal]             = useState(true)
  const [showCorrelations, setShowCorrelations] = useState(true)

  // Live verification state
  const [liveCheckResults, setLiveCheckResults] = useState<LiveCheckItem[]>([])
  const [liveCheckVersion, setLiveCheckVersion] = useState(0)
  const [liveCheckRunning, setLiveCheckRunning] = useState(false)

  // Update module-level toggle vars on every render so renderLatex/renderEnv read them
  _showFormal       = showFormal
  _showCorrelations = showCorrelations
  _liveCheckResults = liveCheckResults

  // Subscribe to Zustand formalization state to trigger re-renders of the preview
  useEditorStore(s => s.formalizingKey)
  useEditorStore(s => s.formalizationResults)

  // Version counter to force preview re-render when module-level results change
  const [correlationVersion, setCorrelationVersion] = useState(0)

  // Debounced preview
  const [previewContent, setPreviewContent] = useState<string>(content)
  useEffect(() => {
    const t = setTimeout(() => setPreviewContent(content), 200)
    return () => clearTimeout(t)
  }, [content])

  // Pending AI insertion review
  const [verifyingIds, setVerifyingIds] = useState<Set<string>>(new Set())
  const [verifyResults, setVerifyResults] = useState<Map<string, FactCheckResponse>>(new Map())
  const pendingCount = useMemo(() => countPendingSections(previewContent), [previewContent])

  // CodeMirror editor view — set via onCreateEditor
  const cmViewRef = useRef<EditorView | null>(null)
  // Stable ref to setCtxMenu so the CM extension (created once) always calls the current setter
  const setCtxMenuRef = useRef<React.Dispatch<React.SetStateAction<CtxMenuState | null>>>(null!)

  // Drag-to-resize split
  const [split, setSplit]      = useState(50)
  const splitContainerRef      = useRef<HTMLDivElement>(null)
  const outerRef               = useRef<HTMLDivElement>(null)
  const splitDragging          = useRef(false)

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!splitDragging.current || !splitContainerRef.current) return
      const rect = splitContainerRef.current.getBoundingClientRect()
      setSplit(Math.max(25, Math.min(75, ((e.clientX - rect.left) / rect.width) * 100)))
    }
    function onUp() { splitDragging.current = false }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup",   onUp)
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp) }
  }, [])

  const previewContentRef = useRef<HTMLDivElement>(null)

  // Cache last preview text selection (for preview-side context menu)
  const lastPreviewSel = useRef("")

  useEffect(() => {
    function onSelChange() {
      const sel = window.getSelection()?.toString().trim() ?? ""
      if (sel) lastPreviewSel.current = sel
    }
    document.addEventListener("selectionchange", onSelChange)
    return () => document.removeEventListener("selectionchange", onSelChange)
  }, [])

  // Jump from preview click → CodeMirror editor position
  const onJump = useCallback((sourceQuery: string) => {
    const view = cmViewRef.current
    if (!view) return
    const pos = view.state.doc.toString().indexOf(sourceQuery)
    if (pos < 0) return
    view.dispatch({
      selection: { anchor: pos, head: pos + Math.min(sourceQuery.length, 100) },
      effects:   EditorView.scrollIntoView(pos, { y: "center" }),
    })
    view.focus()
  }, [])

  // Register with editor-store
  useEffect(() => {
    const setter = (value: string | ((prev: string) => string)) => {
      setContent((prev) => {
        const next = typeof value === "function" ? value(prev) : value
        setLatexContent(next)
        try { localStorage.setItem(STORAGE_KEY, next) } catch { /* quota */ }
        return next
      })
    }
    setLatexSetter(setter)
    setLatexContent(content)
    return () => setLatexSetter(null)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // CodeMirror onChange — receives a plain string (not a ChangeEvent)
  const handleChange = useCallback((val: string) => {
    setContent(val)
    setLatexContent(val)
    try { localStorage.setItem(STORAGE_KEY, val) } catch { /* quota */ }
  }, [])

  // ── Pending AI review: accept / reject / verify ───────────────────────────

  function handleAcceptPending(id: string) {
    transformDocument(prev => acceptPending(prev, id))
    setVerifyResults(m => { const n = new Map(m); n.delete(id); return n })
  }

  function handleRejectPending(id: string) {
    transformDocument(prev => rejectPending(prev, id))
    setVerifyResults(m => { const n = new Map(m); n.delete(id); return n })
  }

  async function handleVerifyPending(id: string, pendingContent: string) {
    // Strip LaTeX markup to get plain prose for the fact-check API
    const plain = pendingContent
      .replace(/%[^\n]*/g, "")
      .replace(/\\begin\{[^}]+\}|\\end\{[^}]+\}/g, "")
      .replace(/\$\$([\s\S]*?)\$\$/g, "$1")
      .replace(/\$([^$]+)\$/g, "$1")
      .replace(/\\(?:section|subsection|subsubsection|textbf|textit|emph)\{([^}]*)\}/g, "$1")
      .replace(/\\[a-zA-Z]+/g, "")
      .replace(/[{}]/g, "")
      .trim()
      .slice(0, 1000)

    setVerifyingIds(s => new Set(s).add(id))
    try {
      const stagedIds = stagedPapers.map(p => p.paper_id)
      const result = await api.factCheck(plain, stagedIds)
      setVerifyResults(m => new Map(m).set(id, result))
    } catch {
      // silently ignore — the Verify button will just become un-disabled
    } finally {
      setVerifyingIds(s => { const n = new Set(s); n.delete(id); return n })
    }
  }

  // ── Toggle effects: trigger CM update when correlations toggle ────
  useEffect(() => { cmViewRef.current?.dispatch({}) }, [showCorrelations])

  // ── Correlation debounce effect ───────────────────────────────────────────
  const correlationTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stagedPaperIds = stagedPapers.map(p => p.paper_id)
  useEffect(() => {
    if (correlationTimer.current) clearTimeout(correlationTimer.current)
    correlationTimer.current = setTimeout(async () => {
      if (!showCorrelations || !stagedPaperIds.length) {
        setActiveCorrelations([])
        setCorrelationVersion(v => v + 1)
        return
      }
      const paragraphs: { text: string; start_char: number; end_char: number }[] = []
      let pos = 0
      for (const chunk of content.split(/\n\n+/)) {
        const stripped = chunk.replace(/\\[a-zA-Z]+(?:\{[^}]*\})?/g, " ").trim()
        if (stripped.length >= 30)
          paragraphs.push({ text: stripped, start_char: pos, end_char: pos + chunk.length })
        pos += chunk.length + 2
      }
      if (!paragraphs.length) return
      try {
        const res = await api.getCorrelations(paragraphs, stagedPaperIds)
        setActiveCorrelations(res.correlations)
        setCorrelationVersion(v => v + 1)
      } catch { /* silent */ }
    }, 3000)
    return () => { if (correlationTimer.current) clearTimeout(correlationTimer.current) }
  }, [content, stagedPaperIds.join(","), showCorrelations]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Live verification debounce effect ──────────────────────────────────────
  const liveCheckTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (liveCheckTimer.current) clearTimeout(liveCheckTimer.current)
    if (!showFormal) {
      setLiveCheckResults([])
      _liveCheckResults = []
      setLiveCheckVersion(v => v + 1)
      setLiveCheckRunning(false)
      return
    }
    liveCheckTimer.current = setTimeout(async () => {
      if (!content.trim() || content.length < 20) return
      setLiveCheckRunning(true)
      try {
        const res = await api.liveCheck(content, stagedPaperIds)
        setLiveCheckResults(res.results)
        _liveCheckResults = res.results
        setLiveCheckVersion(v => v + 1)
      } catch { /* silent */ }
      setLiveCheckRunning(false)
    }, 2000)
    return () => {
      if (liveCheckTimer.current) clearTimeout(liveCheckTimer.current)
    }
  }, [content, showFormal, stagedPaperIds.join(",")]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Formalize handler ─────────────────────────────────────────────────────
  async function handleFormalize() {
    const insertPos = ctxMenu?.insertPos ?? 0
    setCtxMenu(null)
    const src = content
    const envRe = /\\begin\{(theorem|lemma|definition|proposition|corollary)\}([\s\S]*?)\\end\{\1\}/gi
    let match: RegExpExecArray | null
    while ((match = envRe.exec(src)) !== null) {
      if (match.index <= insertPos && insertPos <= match.index + match[0].length) {
        const statement = match[2].trim()
        const key = statement.slice(0, 80)
        useEditorStore.getState().setFormalizingKey(key)
        try {
          const res = await api.formalizeStatement(statement, match[1])
          useEditorStore.getState().setFormalizationResult(key, res)
        } finally {
          useEditorStore.getState().setFormalizingKey(null)
        }
        break
      }
    }
  }

  // ── Download .tex ─────────────────────────────────────────────────────────
  function handleDownloadTex() {
    const blob = new Blob([content], { type: "text/plain" })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement("a")
    a.href = url; a.download = "document.tex"; a.click()
    URL.revokeObjectURL(url)
  }

  // ── Export PDF via browser print ──────────────────────────────────────────
  function handleExportPDF() {
    const el = previewContentRef.current
    if (!el) return

    const html = `<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><title>Document</title>
<script src="https://cdn.tailwindcss.com"><\/script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<style>
  body { font-family: Georgia,'Times New Roman',serif; max-width:700px; margin:2cm auto; font-size:12pt; line-height:1.7; color:#111; }
  @media print { body { margin:0; max-width:100%; } @page { margin:2cm; } }
  svg { display:block; margin:auto; }
  img { max-width:100%; }
</style>
</head><body>${el.innerHTML}</body></html>`

    const blob = new Blob([html], { type: "text/html" })
    const url  = URL.createObjectURL(blob)
    const w    = window.open(url, "_blank")
    if (w) {
      w.addEventListener("load", () => setTimeout(() => w.print(), 300))
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }

  // Download dropdown state
  const [showDlMenu, setShowDlMenu] = useState(false)
  const dlMenuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!showDlMenu) return
    function onDown(e: MouseEvent) {
      if (dlMenuRef.current?.contains(e.target as Node)) return
      setShowDlMenu(false)
    }
    window.addEventListener("mousedown", onDown)
    return () => window.removeEventListener("mousedown", onDown)
  }, [showDlMenu])

  // ── Cursor-aware TikZ insertion ───────────────────────────────────────────
  const [graphInsertPos, setGraphInsertPos] = useState(0)

  function handleInsertTikZ(rawTikZ: string) {
    const pid = generatePendingId()
    transformDocument((prev) =>
      insertNearCursor(
        prev,
        `\\begin{figure}[H]\n\\centering\n${rawTikZ}\n\\caption{Graph}\n\\end{figure}`,
        graphInsertPos,
        ["tikz", "float"],
        pid,
      )
    )
  }

  // ── GraphBuilder popup ────────────────────────────────────────────────────
  const [showGraphBuilder, setShowGraphBuilder] = useState(false)

  // ── Python Visualization modal ─────────────────────────────────────────────
  const [pyVisModal, setPyVisModal] = useState<PyVisModalState | null>(null)

  /** Fire "Ask HEAVEN": package the selected text/line + line range as a chip for the RE.
   *  All info comes from values captured at right-click time by the CM context menu handler. */
  function handleAskHeaven(sel: string, lineText: string, fromLine: number, toLine: number) {
    const fullText = sel.trim() || lineText.trim()
    const lineNum  = fromLine
    const lineEnd  = toLine !== fromLine ? toLine : undefined
    const excerpt  = fullText.replace(/\s+/g, " ").trim().slice(0, 60) + (fullText.length > 60 ? "…" : "")
    setLineContext({ lineNum, lineEnd, excerpt, fullText } satisfies LineContextPayload)
  }

  // ── CodeMirror extensions ─────────────────────────────────────────────────
  //
  // Created once; the contextmenu handler reads from setCtxMenuRef so it's
  // always current without re-creating the extension on every render.
  const cmExtensions = useMemo(() => [
    lineNumbers(),
    highlightActiveLine(),
    highlightActiveLineGutter(),
    CM_PENDING_DECORATION,
    CM_THEME,
    EditorView.lineWrapping,
    // Tab = 2 spaces
    keymap.of([{
      key: "Tab",
      run: (view) => { view.dispatch(view.state.replaceSelection("  ")); return true },
    }]),
    // Right-click context menu — CodeMirror preserves selection on right-click,
    // so view.state.selection gives the correct from/to even when clicking elsewhere.
    EditorView.domEventHandlers({
      contextmenu: (e, view) => {
        e.preventDefault()
        const { state } = view
        const { from, to } = state.selection.main
        const sel      = from === to ? "" : state.doc.sliceString(from, to).trim()
        const fromLine = state.doc.lineAt(from).number
        const toLine   = from === to ? fromLine : state.doc.lineAt(to).number
        const lineText = state.doc.lineAt(from).text
        setCtxMenuRef.current({
          x: e.clientX, y: e.clientY,
          selection: sel, insertPos: from, selectionEnd: to,
          fromLine, toLine, lineText,
        })
        return true
      },
    }),
  ], []) // eslint-disable-line react-hooks/exhaustive-deps

  async function runPyVis() {
    if (!pyVisModal || pyVisModal.running) return
    setPyVisModal(m => m && { ...m, running: true, error: null })
    try {
      const res = await api.runPythonVisual(pyVisModal.code)
      if (res.error) throw new Error(res.error)
      if (!res.image_base64) throw new Error("No image was returned. Make sure your code generates a figure.")

      const dataUrl = `data:image/png;base64,${res.image_base64}`
      const id      = `pyvis-${Date.now()}`
      addEmbeddedImage(id, dataUrl)

      // Show preview in the modal
      setPyVisModal(m => m && { ...m, running: false, result: dataUrl })

      // Insert at original cursor position (pending — user must accept/reject)
      const pos = pyVisModal.insertPos
      const pid = generatePendingId()
      transformDocument((prev) =>
        insertNearCursor(
          prev,
          `\\begin{figure}[H]\n\\centering\n\\includegraphics[width=0.8\\linewidth]{${id}}\n\\caption{Python Visualization Output}\n\\end{figure}`,
          pos,
          ["float"],
          pid,
        )
      )
    } catch (err) {
      setPyVisModal(m => m && { ...m, running: false, error: err instanceof Error ? err.message : "Unknown error" })
    }
  }

  // ── Context menu ──────────────────────────────────────────────────────────
  const [ctxMenu, setCtxMenu]   = useState<CtxMenuState | null>(null)
  const ctxMenuRef              = useRef<HTMLDivElement>(null)

  // Keep setCtxMenuRef current so the CM extension (created once) always has
  // the latest setter without needing to be recreated on every render.
  setCtxMenuRef.current = setCtxMenu

  useEffect(() => {
    if (!ctxMenu) return
    function onDown(e: MouseEvent) {
      if (ctxMenuRef.current?.contains(e.target as Node)) return
      setCtxMenu(null)
    }
    window.addEventListener("mousedown", onDown)
    return () => window.removeEventListener("mousedown", onDown)
  }, [ctxMenu])

  // Source-side context menu is handled entirely by the CM domEventHandlers extension.
  // Preview-side context menu falls back to DOM selection + CM cursor position for insertPos.
  function handlePreviewContextMenu(e: React.MouseEvent) {
    e.preventDefault()
    const sel      = window.getSelection()?.toString().trim() || lastPreviewSel.current
    const view     = cmViewRef.current
    const insertPos = view ? view.state.selection.main.from : content.length
    const fromLine  = view ? view.state.doc.lineAt(insertPos).number : 1
    setCtxMenu({
      x: e.clientX, y: e.clientY,
      selection: sel, insertPos, selectionEnd: insertPos,
      fromLine, toLine: fromLine, lineText: "",
    })
  }

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div ref={outerRef} className={`flex flex-col h-full overflow-hidden relative ${className ?? ""}`}>

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-gray-100 bg-gray-50 flex-shrink-0">
        <span className="text-[10px] text-gray-400 font-medium uppercase tracking-wide flex-1">LaTeX Editor</span>

        {/* Download dropdown */}
        <div ref={dlMenuRef} className="relative">
          <button
            onClick={() => setShowDlMenu(v => !v)}
            className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md bg-white border border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50 transition-colors shadow-sm"
          >
            <Download className="w-3 h-3" /> Export <ChevronDown className="w-2.5 h-2.5 opacity-60" />
          </button>
          {showDlMenu && (
            <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-xl shadow-xl py-1 w-40 z-50">
              <button
                className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12px] text-gray-700 hover:bg-gray-50 transition-colors"
                onClick={() => { handleDownloadTex(); setShowDlMenu(false) }}
              >
                <FileText className="w-3.5 h-3.5 text-blue-500" /> Download .tex
              </button>
              <button
                className="w-full flex items-center gap-2 px-3 py-2 text-left text-[12px] text-gray-700 hover:bg-gray-50 transition-colors"
                onClick={() => { handleExportPDF(); setShowDlMenu(false) }}
              >
                <FileText className="w-3.5 h-3.5 text-red-500" /> Export PDF
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Split pane ───────────────────────────────────────────────────── */}
      <div ref={splitContainerRef} className="flex-1 flex overflow-hidden select-none">

        {/* Left: LaTeX source */}
        <div className="flex flex-col overflow-hidden" style={{ width: `${split}%` }}>
          <div className="px-3 py-1 border-b border-gray-100 bg-gray-50 flex-shrink-0 flex items-center justify-between">
            <span className="text-[10px] text-gray-400 font-medium uppercase tracking-wide">LaTeX Source</span>
            <span className="text-[9px] text-gray-300">Tab = 2 sp · Right-click for options</span>
          </div>

          {/* Pending insertions banner */}
          {pendingCount > 0 && (
            <div className="px-3 py-1.5 bg-emerald-50 border-b border-emerald-200 flex-shrink-0 flex items-center gap-1.5">
              <Sparkles className="w-3 h-3 text-emerald-600 shrink-0" />
              <span className="text-[10px] text-emerald-700 flex-1">
                {pendingCount} pending AI edit{pendingCount > 1 ? "s" : ""} — review in preview
              </span>
              <button
                onClick={() => { transformDocument(acceptAllPending); setVerifyResults(new Map()) }}
                className="text-[9px] px-2 py-0.5 rounded-md bg-emerald-500 text-white hover:bg-emerald-600 transition-colors font-medium"
              >
                Accept All
              </button>
              <button
                onClick={() => { transformDocument(rejectAllPending); setVerifyResults(new Map()) }}
                className="text-[9px] px-2 py-0.5 rounded-md bg-white border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
              >
                Reject All
              </button>
            </div>
          )}

          {/* Source body: CodeMirror editor (handles line numbers, active-line gutter,
               pending-section highlighting, and context menu natively) */}
          <div className="flex-1 min-h-0 overflow-hidden">
            <CodeMirror
              value={content}
              onChange={handleChange}
              onCreateEditor={(view) => { cmViewRef.current = view }}
              extensions={cmExtensions}
              basicSetup={{
                lineNumbers:              false, // provided by our own lineNumbers() extension
                highlightActiveLine:      false, // provided by our own highlightActiveLine() extension
                highlightActiveLineGutter:false, // provided by our own highlightActiveLineGutter()
                foldGutter:               false,
                autocompletion:           false,
                bracketMatching:          false,
                closeBrackets:            false,
                closeBracketsKeymap:      false,
                searchKeymap:             false,
                foldKeymap:               false,
                completionKeymap:         false,
                lintKeymap:               false,
              }}
              height="100%"
              style={{ height: "100%" }}
              placeholder="Start writing LaTeX…"
            />
          </div>
        </div>

        {/* Drag handle */}
        <div
          className="w-1 flex-shrink-0 bg-gray-200 hover:bg-blue-400 active:bg-blue-500 cursor-col-resize transition-colors z-10"
          onMouseDown={(e) => { e.preventDefault(); splitDragging.current = true }}
        />

        {/* Right: preview */}
        <div className="flex flex-col overflow-hidden" style={{ width: `${100 - split}%` }}>
          <div className="px-3 py-1 border-b border-gray-100 bg-gray-50 flex-shrink-0 flex items-center gap-1.5">
            <span className="text-[10px] text-gray-400 font-medium uppercase tracking-wide flex-1">Preview</span>
            {liveCheckRunning && showFormal && (
              <span className="text-[9px] text-blue-500 animate-pulse flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                Verifying...
              </span>
            )}
            {showFormal && !liveCheckRunning && liveCheckResults.length > 0 && (
              <span className="text-[9px] text-gray-400">
                {liveCheckResults.filter(r => r.status === "verified").length} verified
                {liveCheckResults.some(r => r.status === "failed") && ` · ${liveCheckResults.filter(r => r.status === "failed").length} failed`}
              </span>
            )}
            {[
              { k: "formal", label: "Verified",     s: showFormal,       set: setShowFormal, title: "Live verification: equations checked with SymPy/Wolfram, theorems verified with LLM, prose cross-referenced with staged papers." },
              { k: "corr",   label: "Correlations", s: showCorrelations, set: setShowCorrelations, title: "Highlight paragraphs that correlate with concepts in your staged papers. Hover to see the matched concept and source paper." },
            ].map(({ k, label, s, set, title }) => (
              <button key={k} onClick={() => set(v => !v)} title={title}
                className={`text-[9px] px-1.5 py-0.5 rounded transition-colors ${
                  s ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-400"
                }`}
              >{label}</button>
            ))}
          </div>
          <LaTeXPreview
            content={previewContent}
            onJump={onJump}
            onContextMenu={handlePreviewContextMenu}
            contentRef={previewContentRef}
            onAccept={handleAcceptPending}
            onReject={handleRejectPending}
            onVerify={handleVerifyPending}
            verifyingIds={verifyingIds}
            verifyResults={verifyResults}
            correlationVersion={correlationVersion}
            liveCheckVersion={liveCheckVersion}
          />
        </div>
      </div>

      {/* ── Context menu ─────────────────────────────────────────────────── */}
      {ctxMenu && (
        <div
          ref={ctxMenuRef}
          className="fixed z-[9999] bg-white border border-gray-200 shadow-xl rounded-xl py-1.5 w-60 text-[12px]"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
        >
          {/* ── Ask HEAVEN → sends line context to RE ─────────────────── */}
          <button
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left text-gray-800 hover:bg-violet-50 transition-colors"
            onClick={() => {
              handleAskHeaven(ctxMenu.selection, ctxMenu.lineText, ctxMenu.fromLine, ctxMenu.toLine)
              setCtxMenu(null)
            }}
          >
            <Sparkles className="w-3.5 h-3.5 text-violet-500 shrink-0" />
            <div>
              <p className="font-medium leading-tight">Ask HEAVEN</p>
              <p className="text-[10px] text-gray-400 leading-tight mt-0.5">
                {ctxMenu.selection
                  ? `Send selection (${ctxMenu.fromLine === ctxMenu.toLine ? `L${ctxMenu.fromLine}` : `L${ctxMenu.fromLine}–${ctxMenu.toLine}`}) to chat`
                  : `Send line L${ctxMenu.fromLine} to chat`}
              </p>
            </div>
          </button>

          <div className="mx-3 my-1 border-t border-gray-100" />

          {/* ── Insert options ────────────────────────────────────────────── */}
          <button
            className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-gray-700 hover:bg-gray-50 transition-colors"
            onClick={() => {
              setPyVisModal({ code: DEFAULT_PYVIS, running: false, result: null, error: null, insertPos: ctxMenu.insertPos })
              setCtxMenu(null)
            }}
          >
            <Terminal className="w-3.5 h-3.5 text-orange-500 shrink-0" />
            Run Python Visualization
          </button>
          <button
            className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-gray-700 hover:bg-gray-50 transition-colors"
            onClick={() => {
              setGraphInsertPos(ctxMenu.insertPos)
              setShowGraphBuilder(true)
              setCtxMenu(null)
            }}
          >
            <Network className="w-3.5 h-3.5 text-blue-500 shrink-0" />
            Add Graph (Builder)
          </button>

          {/\\begin\{(theorem|lemma|definition|proposition|corollary)\}/i.test(ctxMenu.lineText) && (
            <>
              <div className="border-t border-gray-100 my-0.5" />
              <button
                className="w-full flex items-center gap-2.5 px-3 py-2 text-left text-gray-700 hover:bg-indigo-50 transition-colors"
                onClick={handleFormalize}
              >
                <span className="w-3.5 h-3.5 text-indigo-500 shrink-0 text-center text-[12px] font-bold">∀</span>
                Formalize ↗
              </button>
            </>
          )}

        </div>
      )}

      {/* ── Graph Builder popup ───────────────────────────────────────────── */}
      {showGraphBuilder && (
        <div className="absolute inset-0 z-40 bg-black/30 flex flex-col">
          <div className="flex-1 m-4 bg-white rounded-xl overflow-hidden flex flex-col shadow-2xl">
            <GraphBuilder
              onInsert={(tikz) => { handleInsertTikZ(tikz); setShowGraphBuilder(false) }}
              onClose={() => setShowGraphBuilder(false)}
            />
          </div>
        </div>
      )}

      {/* ── Python Visualization modal ──────────────────────────────────── */}
      {pyVisModal && (
        <div className="absolute inset-0 z-50 bg-black/30 flex items-center justify-center p-6">
          <div className="bg-white rounded-xl shadow-2xl flex flex-col w-full max-w-[720px] max-h-[90vh]">

            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <Terminal className="w-4 h-4 text-orange-500" />
                <div>
                  <p className="font-semibold text-sm text-gray-800">Run Python Visualization</p>
                  <p className="text-[11px] text-gray-400 mt-0.5">Generate plots, graphs, visualizations, and computations — the output image will be embedded inline.</p>
                </div>
              </div>
              <button onClick={() => setPyVisModal(null)} className="text-gray-400 hover:text-gray-600 transition-colors ml-4 flex-shrink-0">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4 min-h-0">
              <textarea
                value={pyVisModal.code}
                onChange={(e) => setPyVisModal(m => m && { ...m, code: e.target.value })}
                className="w-full font-mono text-[12.5px] border border-gray-200 rounded-xl p-4 outline-none focus:border-orange-300 focus:ring-1 focus:ring-orange-100 resize-none select-text leading-relaxed"
                style={{ minHeight: "260px" }}
                spellCheck={false}
                placeholder="Write Python code…"
              />

              {/* Output preview */}
              {pyVisModal.result && (
                <div className="border border-gray-100 rounded-xl overflow-hidden bg-gray-50 p-3">
                  <p className="text-[10px] text-gray-400 mb-2 uppercase tracking-wide font-medium">Output Preview</p>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={pyVisModal.result} alt="Python visualization output" className="max-h-64 mx-auto rounded-lg" />
                </div>
              )}

              {/* Error */}
              {pyVisModal.error && (
                <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3">
                  <p className="text-[11px] text-red-600 font-medium mb-1">Error</p>
                  <p className="text-[11px] text-red-500 font-mono whitespace-pre-wrap">{pyVisModal.error}</p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-5 py-4 border-t border-gray-100 flex items-center justify-between flex-shrink-0">
              <p className="text-[10px] text-gray-400">
                Inserts after the paragraph at your cursor position.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPyVisModal(null)}
                  className="text-[12px] px-4 py-2 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={runPyVis}
                  disabled={pyVisModal.running}
                  className="flex items-center gap-1.5 text-[12px] px-5 py-2 rounded-lg bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-60 disabled:cursor-not-allowed transition-colors font-medium"
                >
                  {pyVisModal.running
                    ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running…</>
                    : "Run & Insert"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
