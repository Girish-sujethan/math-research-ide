type BlockType = "text" | "latex" | "heading1" | "heading2" | "bullet"

export interface ParsedBlock {
  type: BlockType
  content: string
}

/**
 * Converts an AI reply string into typed editor blocks.
 *
 * Rules (in priority order):
 *   $$...$$  (possibly multi-line) → latex block
 *   # text   → heading1
 *   ## text / ### text → heading2
 *   - text / * text   → bullet
 *   1. text / 2. text → bullet (numbered lists flattened)
 *   --- / *** / ___   → skipped (horizontal rules)
 *   ```...```         → skipped (code fences — not useful in a math editor)
 *   everything else   → text
 *
 * Inline $math$ within text lines is left in-place; the text block renderer
 * already shows it literally. The user can change a block to latex type for
 * full KaTeX display mode rendering.
 */
export function parseReplyToBlocks(reply: string): ParsedBlock[] {
  const blocks: ParsedBlock[] = []

  // ── Step 1: Split on display math ($$...$$) ──────────────────────────────
  type Seg = { kind: "math"; content: string } | { kind: "text"; content: string }
  const segments: Seg[] = []
  const displayMathRe = /\$\$([\s\S]+?)\$\$/g
  let lastIdx = 0
  let m: RegExpExecArray | null

  while ((m = displayMathRe.exec(reply)) !== null) {
    if (m.index > lastIdx) {
      segments.push({ kind: "text", content: reply.slice(lastIdx, m.index) })
    }
    const latex = m[1].trim()
    if (latex) segments.push({ kind: "math", content: latex })
    lastIdx = m.index + m[0].length
  }
  if (lastIdx < reply.length) {
    segments.push({ kind: "text", content: reply.slice(lastIdx) })
  }

  // ── Step 2: Process each segment ─────────────────────────────────────────
  let insideCodeFence = false

  for (const seg of segments) {
    if (seg.kind === "math") {
      blocks.push({ type: "latex", content: seg.content })
      continue
    }

    for (const rawLine of seg.content.split("\n")) {
      const line = rawLine.trim()

      // Toggle code fences; skip content inside them
      if (/^```/.test(line)) {
        insideCodeFence = !insideCodeFence
        continue
      }
      if (insideCodeFence) continue

      // Skip blank lines and horizontal rules
      if (!line || line === "---" || line === "***" || line === "___") continue

      if (line.startsWith("### ")) {
        blocks.push({ type: "heading2", content: line.slice(4) })
      } else if (line.startsWith("## ")) {
        blocks.push({ type: "heading2", content: line.slice(3) })
      } else if (line.startsWith("# ")) {
        blocks.push({ type: "heading1", content: line.slice(2) })
      } else if (/^[-*] /.test(line)) {
        blocks.push({ type: "bullet", content: line.slice(2) })
      } else if (/^\d+\. /.test(line)) {
        // Numbered list → bullet (ordering is implicit in document position)
        blocks.push({ type: "bullet", content: line.replace(/^\d+\. /, "") })
      } else if (line.startsWith("> ")) {
        // Blockquote → plain text
        blocks.push({ type: "text", content: line.slice(2) })
      } else {
        blocks.push({ type: "text", content: line })
      }
    }
  }

  return blocks.filter((b) => b.content.trim().length > 0)
}
