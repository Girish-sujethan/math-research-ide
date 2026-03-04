"use client"

import { Editor, createShapeId } from "@tldraw/tldraw"
import { GitGraph, StickyNote, Upload, Link } from "lucide-react"
import { useRef, useState } from "react"
import { useCanvasStore } from "@/lib/canvas-store"
import { api } from "@/lib/api"

interface Props {
  editor: Editor
}

export function CanvasToolbar({ editor }: Props) {
  const mode = useCanvasStore((s) => s.mode)
  const setMode = useCanvasStore((s) => s.setMode)
  const [doiInput, setDoiInput] = useState("")
  const [showDoiPopover, setShowDoiPopover] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  function handleGraphToggle() {
    setMode(mode === "graph" ? "card" : "graph")
  }

  function handleAddNote() {
    const vp = editor.getViewportPageBounds()
    const id = createShapeId()
    ;(editor as any).createShape({
      id,
      type: "annotation",
      x: vp.center.x - 100,
      y: vp.center.y - 60,
      props: { text: "", color: "#fef9c3", w: 200, h: 120 },
    })
    editor.select(id)
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await api.uploadPaper(file)
    } catch (err) {
      console.error("Upload failed:", err)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  async function handleDoiSubmit() {
    if (!doiInput.trim()) return
    setShowDoiPopover(false)
    try {
      await api.ingestByDoi(doiInput.trim())
    } catch (err) {
      console.error("DOI ingest failed:", err)
    }
    setDoiInput("")
  }

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 bg-white border border-gray-200 rounded-full shadow-lg px-4 py-2">
      {/* Graph mode toggle */}
      <button
        onClick={handleGraphToggle}
        title={mode === "graph" ? "Switch to card mode" : "Switch to graph mode"}
        className={`p-2 rounded-full transition-colors ${
          mode === "graph" ? "bg-blue-600 text-white" : "text-gray-600 hover:bg-gray-100"
        }`}
      >
        <GitGraph className="w-4 h-4" />
      </button>

      {/* Add note */}
      <button
        onClick={handleAddNote}
        title="Add sticky note"
        className="p-2 rounded-full text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <StickyNote className="w-4 h-4" />
      </button>

      {/* Upload PDF */}
      <button
        onClick={() => fileRef.current?.click()}
        disabled={uploading}
        title="Upload PDF"
        className="p-2 rounded-full text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-50"
      >
        <Upload className="w-4 h-4" />
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Add by DOI */}
      <div className="relative">
        <button
          onClick={() => setShowDoiPopover((v) => !v)}
          title="Add paper by DOI"
          className={`p-2 rounded-full transition-colors ${
            showDoiPopover ? "bg-gray-100" : "text-gray-600 hover:bg-gray-100"
          }`}
        >
          <Link className="w-4 h-4" />
        </button>
        {showDoiPopover && (
          <div className="absolute bottom-10 left-1/2 -translate-x-1/2 bg-white border border-gray-200 rounded-lg shadow-xl p-3 w-64 z-50">
            <p className="text-xs text-gray-500 mb-2">Enter DOI</p>
            <div className="flex gap-2">
              <input
                autoFocus
                type="text"
                value={doiInput}
                onChange={(e) => setDoiInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleDoiSubmit()}
                placeholder="10.1234/example"
                className="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5 outline-none focus:border-blue-500"
              />
              <button
                onClick={handleDoiSubmit}
                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700"
              >
                Add
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
