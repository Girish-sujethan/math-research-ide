"use client"

import { useEffect } from "react"
import {
  SuggestionMenuController,
  getDefaultReactSlashMenuItems,
  useCreateBlockNote,
} from "@blocknote/react"
import { BlockNoteView } from "@blocknote/mantine"
import { BlockNoteSchema, defaultBlockSpecs } from "@blocknote/core"
import { Pi, Code2 } from "lucide-react"
import "@blocknote/mantine/style.css"
import renderMathInElement from "katex/contrib/auto-render"
import "katex/dist/katex.min.css"

import { LatexBlockSpec } from "./latex-block"
import { PythonVisualOutputBlockSpec } from "./matlab-output-block"
import { PythonVisualRunner } from "./matlab-runner"
import { CmdKToolbar } from "./cmd-k-toolbar"
import { setEditorRef, useEditorStore } from "@/lib/editor-store"
import "./blocknote-latex.css"

// ---------------------------------------------------------------------------
// Schema with custom blocks
// ---------------------------------------------------------------------------

const schema = BlockNoteSchema.create({
  blockSpecs: {
    ...defaultBlockSpecs,
    latex: LatexBlockSpec(),
    matlabOutput: PythonVisualOutputBlockSpec(),
  },
})

// ---------------------------------------------------------------------------
// Storage helpers
// ---------------------------------------------------------------------------

const STORAGE_KEY = "heaven-blocknote-v1"

function loadFromStorage(): unknown[] | undefined {
  if (typeof window === "undefined") return undefined
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return undefined
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) && parsed.length > 0 ? parsed : undefined
  } catch {
    return undefined
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  className?: string
}

export function BlockNoteEditor({ className }: Props) {
  const { cmdKBlockId, openCmdK, openPyVis } = useEditorStore()

  const editor = useCreateBlockNote({
    schema,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    initialContent: loadFromStorage() as any,
  })

  // Register editor ref so reasoning engine + cmd-k can access it
  useEffect(() => {
    setEditorRef(editor)
    return () => setEditorRef(null)
  }, [editor])

  // Auto-save to localStorage on every change
  useEffect(() => {
    return editor.onChange(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(editor.document))
      } catch {
        // Ignore storage quota errors
      }
    })
  }, [editor])

  // KaTeX auto-render for inline $...$ and display $$...$$ in paragraph text
  useEffect(() => {
    const container = document.querySelector(".bn-editor")
    if (!container) return
    const render = () =>
      renderMathInElement(container as HTMLElement, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
        ],
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
        throwOnError: false,
      })
    render()
    return editor.onChange(render)
  }, [editor])

  // Global Cmd+K — open the AI edit palette for the current block
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        try {
          const pos = editor.getTextCursorPosition()
          if (pos?.block?.id) openCmdK(pos.block.id)
        } catch {
          // Editor not yet focused
        }
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [editor, openCmdK])

  // Custom slash menu items
  async function getSlashItems(query: string) {
    const allItems = [
      ...getDefaultReactSlashMenuItems(editor),
      {
        title: "LaTeX Math",
        subtext: "Display-mode LaTeX equation with live preview",
        aliases: ["latex", "math", "equation", "formula", "katex"],
        group: "Math & Science",
        icon: <Pi className="w-4 h-4" />,
        onItemClick: () => {
          const pos = editor.getTextCursorPosition()
          editor.insertBlocks(
            [{ type: "latex", props: { content: "" } }],
            pos.block,
            "after"
          )
        },
      },
      {
        title: "Python Visualization",
        subtext: "Run NumPy / SciPy / Matplotlib and embed the result",
        aliases: ["python", "visualization", "numpy", "scipy", "plot", "compute", "figure"],
        group: "Math & Science",
        icon: <Code2 className="w-4 h-4" />,
        onItemClick: () => {
          const pos = editor.getTextCursorPosition()
          openPyVis(pos.block.id)
        },
      },
    ]
    if (!query) return allItems
    const q = query.toLowerCase()
    return allItems.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        (item as { group?: string }).group?.toLowerCase().includes(q) ||
        (item as { aliases?: string[] }).aliases?.some((a) => a.toLowerCase().includes(q))
    )
  }

  return (
    <div className={`relative ${className ?? ""}`}>
      <BlockNoteView
        editor={editor}
        theme="light"
        slashMenu={false}
        style={{ minHeight: "100%" }}
      >
        <SuggestionMenuController
          triggerCharacter="/"
          getItems={getSlashItems}
        />
      </BlockNoteView>

      {/* Cmd+K AI toolbar */}
      {cmdKBlockId && <CmdKToolbar />}

      {/* Python Visualization runner modal */}
      <PythonVisualRunner editor={editor} />
    </div>
  )
}
