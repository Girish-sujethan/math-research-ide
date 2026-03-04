"use client"

import React from "react"
import katex from "katex"
import "katex/dist/katex.min.css"

interface LatexProps {
  src: string
  display?: boolean
  className?: string
}

export function Latex({ src, display = false, className }: LatexProps) {
  let html: string
  try {
    html = katex.renderToString(src, { displayMode: display, throwOnError: false })
  } catch {
    html = src
  }
  return (
    <span
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

// ---------------------------------------------------------------------------
// MathText — renders a plain string that may contain inline $...$ and
// display $$...$$ LaTeX. Line breaks are preserved. Safe for user-facing text
// from papers, AI chat messages, agent reports, etc.
// ---------------------------------------------------------------------------

function renderMathSegment(text: string, baseKey: number): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  let s = text
  let k = baseKey

  while (s.length > 0) {
    // Display math $$...$$
    if (s.startsWith("$$")) {
      const close = s.indexOf("$$", 2)
      if (close >= 0) {
        const math = s.slice(2, close)
        try {
          const html = katex.renderToString(math, { displayMode: true, throwOnError: false })
          parts.push(
            <span key={k++} className="block text-center my-2" dangerouslySetInnerHTML={{ __html: html }} />
          )
        } catch {
          parts.push(<span key={k++}>$${math}$$</span>)
        }
        s = s.slice(close + 2)
        continue
      }
    }

    // Inline math $...$
    if (s.startsWith("$")) {
      const close = s.indexOf("$", 1)
      if (close >= 0) {
        const math = s.slice(1, close)
        try {
          const html = katex.renderToString(math, { throwOnError: false })
          parts.push(<span key={k++} dangerouslySetInnerHTML={{ __html: html }} />)
        } catch {
          parts.push(<span key={k++}>${math}$</span>)
        }
        s = s.slice(close + 1)
        continue
      }
    }

    // Plain text up to the next $
    const nextDollar = s.indexOf("$")
    if (nextDollar < 0) {
      parts.push(<span key={k++}>{s}</span>)
      break
    }
    parts.push(<span key={k++}>{s.slice(0, nextDollar)}</span>)
    s = s.slice(nextDollar)
  }

  return parts
}

interface MathTextProps {
  /** Raw text that may contain inline $...$ or display $$...$$ LaTeX. */
  text: string
  className?: string
}

/**
 * Renders a mixed text + LaTeX string.
 * - Inline `$math$` → rendered with KaTeX in inline mode
 * - Display `$$math$$` → rendered with KaTeX in display mode (block, centred)
 * - Newlines → `<br />`
 * - Plain text → rendered as-is
 */
export function MathText({ text, className }: MathTextProps) {
  const lines = text.split("\n")
  const nodes: React.ReactNode[] = []
  let k = 0

  lines.forEach((line, i) => {
    nodes.push(...renderMathSegment(line, k))
    k += 10000
    if (i < lines.length - 1) nodes.push(<br key={`br-${i}`} />)
  })

  return <span className={className}>{nodes}</span>
}
