"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { MousePointer2, Circle, Minus, Trash2, FileInput, Undo2, X } from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tool = "select" | "node" | "edge"

interface GNode { id: string; x: number; y: number; label: string }
interface GEdge { id: string; from: string; to: string; label: string; directed: boolean }

let _nodeSeq = 0
let _edgeSeq = 0
function nid() { return `n${++_nodeSeq}` }
function eid() { return `e${++_edgeSeq}` }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function nodeById(nodes: GNode[], id: string): GNode | undefined {
  return nodes.find((n) => n.id === id)
}

/** Convert SVG canvas coordinates to TikZ (x in cm, y flipped). */
function toTikZ(x: number, y: number, cx: number, cy: number): string {
  const scale = 0.018  // pixels → cm (roughly)
  return `${((x - cx) * scale).toFixed(2)},${(-(y - cy) * scale).toFixed(2)}`
}

/** Generate a TikZ representation of the current graph. */
function buildTikZ(nodes: GNode[], edges: GEdge[], svgW: number, svgH: number): string {
  const cx = svgW / 2
  const cy = svgH / 2

  const nodeLines = nodes
    .map((n) => `  \\node[circle,draw,fill=blue!10,minimum size=22pt,font=\\small] (${n.id}) at (${toTikZ(n.x, n.y, cx, cy)}) {$${escTex(n.label)}$};`)
    .join("\n")

  const edgeLines = edges
    .map((e) => {
      const arr   = e.directed ? "->" : "-"
      const label = e.label ? ` node[midway,above,sloped,font=\\scriptsize] {$${escTex(e.label)}$}` : ""
      return `  \\draw[${arr},thick] (${e.from}) --${label} (${e.to});`
    })
    .join("\n")

  return `\\begin{tikzpicture}[>=latex]\n${nodeLines}\n${edgeLines}\n\\end{tikzpicture}`
}

function escTex(s: string): string {
  return s.replace(/[&%$#_{}~^\\]/g, (c) => `\\${c}`)
}

// ---------------------------------------------------------------------------
// Graph Builder component
// ---------------------------------------------------------------------------

interface GraphBuilderProps {
  onInsert: (tikz: string) => void
  onClose: () => void
}

export function GraphBuilder({ onInsert, onClose }: GraphBuilderProps) {
  const [nodes,     setNodes]     = useState<GNode[]>([])
  const [edges,     setEdges]     = useState<GEdge[]>([])
  const [tool,      setTool]      = useState<Tool>("node")
  const [directed,  setDirected]  = useState(true)
  const [selected,  setSelected]  = useState<string | null>(null)
  const [pending,   setPending]   = useState<string | null>(null)  // edge src
  const [editing,   setEditing]   = useState<{ id: string; label: string } | null>(null)
  const [history,   setHistory]   = useState<{ nodes: GNode[]; edges: GEdge[] }[]>([])

  const svgRef     = useRef<SVGSVGElement>(null)
  const inputRef   = useRef<HTMLInputElement>(null)
  const dragging   = useRef<{ id: string; ox: number; oy: number; mx: number; my: number } | null>(null)

  // ── Keyboard shortcuts ─────────────────────────────────────────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (editing) return
      if (e.key === "Delete" || e.key === "Backspace") {
        if (!selected) return
        snapshot()
        setNodes((ns) => ns.filter((n) => n.id !== selected))
        setEdges((es) => es.filter((e) => e.id !== selected && e.from !== selected && e.to !== selected))
        setSelected(null)
      }
      if (e.key === "Escape") { setPending(null); setSelected(null) }
      if (e.key === "n") setTool("node")
      if (e.key === "e") setTool("edge")
      if (e.key === "s") setTool("select")
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [selected, editing]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Global mouse events for node dragging ─────────────────────────────────
  useEffect(() => {
    function onMove(e: MouseEvent) {
      const d = dragging.current
      if (!d) return
      setNodes((ns) =>
        ns.map((n) =>
          n.id === d.id ? { ...n, x: d.ox + (e.clientX - d.mx), y: d.oy + (e.clientY - d.my) } : n
        )
      )
    }
    function onUp() { dragging.current = null }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup",   onUp)
    return () => {
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup",   onUp)
    }
  }, [])

  // ── Focus label input when editing starts ─────────────────────────────────
  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  // ── History snapshot ──────────────────────────────────────────────────────
  function snapshot() {
    setHistory((h) => [...h.slice(-20), { nodes: [...nodes], edges: [...edges] }])
  }

  function undo() {
    setHistory((h) => {
      if (h.length === 0) return h
      const prev = h[h.length - 1]
      setNodes(prev.nodes)
      setEdges(prev.edges)
      return h.slice(0, -1)
    })
  }

  // ── SVG coordinate helpers ────────────────────────────────────────────────
  function svgPt(e: React.MouseEvent): { x: number; y: number } {
    const r = svgRef.current!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }

  // ── SVG canvas click ──────────────────────────────────────────────────────
  function handleBgClick(e: React.MouseEvent) {
    if (dragging.current) return
    setSelected(null)
    setPending(null)
    if (tool !== "node") return
    snapshot()
    const { x, y } = svgPt(e)
    const id        = nid()
    setNodes((ns) => [...ns, { id, x, y, label: `v${ns.length + 1}` }])
    setSelected(id)
  }

  // ── Node interactions ─────────────────────────────────────────────────────
  function handleNodeDown(e: React.MouseEvent, node: GNode) {
    e.stopPropagation()
    if (tool === "select") {
      setSelected(node.id)
      dragging.current = { id: node.id, ox: node.x, oy: node.y, mx: e.clientX, my: e.clientY }
      return
    }
    if (tool === "edge") {
      if (!pending) {
        setPending(node.id)
        setSelected(node.id)
      } else if (pending !== node.id) {
        snapshot()
        const id = eid()
        setEdges((es) => [...es, { id, from: pending, to: node.id, label: "", directed }])
        setPending(null)
        setSelected(id)
      }
    }
    if (tool === "node") setSelected(node.id)
  }

  function handleNodeDblClick(e: React.MouseEvent, node: GNode) {
    e.stopPropagation()
    setEditing({ id: node.id, label: node.label })
  }

  // ── Edge interactions ─────────────────────────────────────────────────────
  function handleEdgeClick(e: React.MouseEvent, edge: GEdge) {
    e.stopPropagation()
    setSelected(edge.id)
  }

  function handleEdgeDblClick(e: React.MouseEvent, edge: GEdge) {
    e.stopPropagation()
    setEditing({ id: edge.id, label: edge.label })
  }

  // ── Commit label edit ─────────────────────────────────────────────────────
  function commitEdit() {
    if (!editing) return
    const { id, label } = editing
    snapshot()
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, label } : n)))
    setEdges((es) => es.map((e) => (e.id === id ? { ...e, label } : e)))
    setEditing(null)
  }

  // ── Insert TikZ into document ─────────────────────────────────────────────
  function insertToDocument() {
    if (nodes.length === 0) return
    const svg  = svgRef.current
    const tikz = buildTikZ(nodes, edges, svg?.clientWidth ?? 600, svg?.clientHeight ?? 400)
    onInsert(tikz)
  }

  // ── Toolbar ───────────────────────────────────────────────────────────────
  const toolBtnCls = (t: Tool) =>
    `flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-colors ${
      tool === t
        ? "bg-blue-600 text-white shadow-sm"
        : "bg-gray-100 text-gray-600 hover:bg-gray-200"
    }`

  // ── Arrowhead marker ──────────────────────────────────────────────────────
  const ARROW_ID = "gb-arrow"

  // ── Edge midpoint for label & click area ─────────────────────────────────
  function edgeMid(e: GEdge): { x: number; y: number } {
    const a = nodeById(nodes, e.from)
    const b = nodeById(nodes, e.to)
    if (!a || !b) return { x: 0, y: 0 }
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
  }

  // ── Editing overlay position ──────────────────────────────────────────────
  const editNode = editing ? nodes.find((n) => n.id === editing.id) : null
  const editEdge = editing && !editNode ? edges.find((e) => e.id === editing.id) : null
  const editPos  = editNode
    ? { x: editNode.x - 48, y: editNode.y + 26 }
    : editEdge
    ? { x: edgeMid(editEdge).x - 48, y: edgeMid(editEdge).y - 14 }
    : null

  const clearAll = useCallback(() => { snapshot(); setNodes([]); setEdges([]); setSelected(null) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-gray-50">
      {/* ── Toolbar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 bg-white border-b border-gray-200 flex-shrink-0 flex-wrap">
        <button className={toolBtnCls("select")} onClick={() => setTool("select")}>
          <MousePointer2 className="w-3 h-3" /> Select <span className="opacity-50 text-[9px]">S</span>
        </button>
        <button className={toolBtnCls("node")} onClick={() => setTool("node")}>
          <Circle className="w-3 h-3" /> Node <span className="opacity-50 text-[9px]">N</span>
        </button>
        <button className={toolBtnCls("edge")} onClick={() => setTool("edge")}>
          <Minus className="w-3 h-3" /> Edge <span className="opacity-50 text-[9px]">E</span>
        </button>

        <div className="h-4 w-px bg-gray-200 mx-0.5" />

        <label className="flex items-center gap-1.5 text-[11px] text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={directed}
            onChange={(e) => setDirected(e.target.checked)}
            className="w-3 h-3 accent-blue-600"
          />
          Directed
        </label>

        <div className="h-4 w-px bg-gray-200 mx-0.5" />

        <button
          className="flex items-center gap-1 text-[11px] px-2 py-1.5 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
          onClick={undo}
          disabled={history.length === 0}
          title="Undo (Ctrl+Z not supported — use this button)"
        >
          <Undo2 className="w-3 h-3" />
        </button>

        <button
          className="flex items-center gap-1 text-[11px] px-2 py-1.5 rounded-lg bg-gray-100 text-red-500 hover:bg-red-50 transition-colors"
          onClick={clearAll}
        >
          <Trash2 className="w-3 h-3" /> Clear
        </button>

        <div className="flex-1" />

        {pending && (
          <span className="text-[10px] text-blue-600 animate-pulse mr-2">
            Click a target node to complete edge…
          </span>
        )}

        <button
          disabled={nodes.length === 0}
          onClick={insertToDocument}
          className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
        >
          <FileInput className="w-3.5 h-3.5" /> Insert to Doc
        </button>

        <button
          onClick={onClose}
          className="flex items-center gap-1 text-[11px] px-2 py-1.5 rounded-lg bg-gray-100 text-gray-500 hover:bg-gray-200 transition-colors"
          title="Close"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* ── Canvas ──────────────────────────────────────────────────────── */}
      <div className="flex-1 relative overflow-hidden">
        <svg
          ref={svgRef}
          className="w-full h-full"
          style={{ cursor: tool === "node" ? "crosshair" : tool === "edge" ? "cell" : "default" }}
          onClick={handleBgClick}
        >
          <defs>
            <marker id={ARROW_ID} markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill="#6b7280" />
            </marker>
          </defs>

          {/* Grid background */}
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e5e7eb" strokeWidth="0.5" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />

          {/* Edges */}
          {edges.map((edge) => {
            const a = nodeById(nodes, edge.from)
            const b = nodeById(nodes, edge.to)
            if (!a || !b) return null
            const isSelected = selected === edge.id
            const mid = edgeMid(edge)

            // Offset endpoints to node circumference (r=20)
            const dx = b.x - a.x
            const dy = b.y - a.y
            const len = Math.sqrt(dx * dx + dy * dy) || 1
            const r   = 20
            const x1  = a.x + (dx / len) * r
            const y1  = a.y + (dy / len) * r
            const x2  = b.x - (dx / len) * (r + (edge.directed ? 6 : 0))
            const y2  = b.y - (dy / len) * (r + (edge.directed ? 6 : 0))

            return (
              <g key={edge.id}>
                {/* Wide invisible hit area */}
                <line
                  x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke="transparent" strokeWidth={14}
                  style={{ cursor: "pointer" }}
                  onClick={(e) => handleEdgeClick(e, edge)}
                  onDoubleClick={(e) => handleEdgeDblClick(e, edge)}
                />
                {/* Visible line */}
                <line
                  x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke={isSelected ? "#3b82f6" : "#9ca3af"}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  markerEnd={edge.directed ? `url(#${ARROW_ID})` : undefined}
                  style={{ pointerEvents: "none" }}
                />
                {/* Edge label */}
                {edge.label && (
                  <text
                    x={mid.x} y={mid.y - 6}
                    textAnchor="middle"
                    fontSize={11}
                    fill={isSelected ? "#3b82f6" : "#6b7280"}
                    fontFamily="serif"
                    style={{ pointerEvents: "none", userSelect: "none" }}
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            )
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const isSelected = selected === node.id
            const isPending  = pending === node.id
            return (
              <g
                key={node.id}
                style={{ cursor: tool === "select" ? "move" : tool === "edge" ? "pointer" : "default" }}
                onMouseDown={(e) => handleNodeDown(e, node)}
                onClick={(e) => e.stopPropagation()}
                onDoubleClick={(e) => handleNodeDblClick(e, node)}
              >
                <circle
                  cx={node.x} cy={node.y} r={20}
                  fill={isPending ? "#dbeafe" : isSelected ? "#eff6ff" : "#f8fafc"}
                  stroke={isPending ? "#60a5fa" : isSelected ? "#3b82f6" : "#94a3b8"}
                  strokeWidth={isPending || isSelected ? 2.5 : 1.5}
                />
                <text
                  x={node.x} y={node.y}
                  textAnchor="middle" dominantBaseline="central"
                  fontSize={13} fontFamily="serif" fontStyle="italic"
                  fill={isSelected ? "#1d4ed8" : "#374151"}
                  style={{ pointerEvents: "none", userSelect: "none" }}
                >
                  {node.label}
                </text>
              </g>
            )
          })}
        </svg>

        {/* ── Inline label editor (HTML overlay) ─────────────────────── */}
        {editing && editPos && (
          <div
            className="absolute z-20"
            style={{ left: editPos.x, top: editPos.y }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <input
              ref={inputRef}
              value={editing.label}
              onChange={(e) => setEditing({ ...editing, label: e.target.value })}
              onBlur={commitEdit}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitEdit()
                if (e.key === "Escape") setEditing(null)
              }}
              className="w-24 text-center text-xs border border-blue-400 rounded-lg shadow-lg px-2 py-1 outline-none bg-white font-serif"
              placeholder="label…"
            />
          </div>
        )}

        {/* ── Empty state hint ─────────────────────────────────────────── */}
        {nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center text-gray-400">
              <p className="text-sm font-medium">Click the canvas to add nodes</p>
              <p className="text-xs mt-1">Switch to Edge tool to connect them · Double-click to label</p>
            </div>
          </div>
        )}
      </div>

      {/* ── Status bar ──────────────────────────────────────────────────── */}
      <div className="px-3 py-1 bg-white border-t border-gray-100 flex-shrink-0 flex items-center gap-4">
        <span className="text-[10px] text-gray-400">{nodes.length} nodes · {edges.length} edges</span>
        <span className="text-[10px] text-gray-300">
          Del = delete selected · Dbl-click = edit label · Insert TikZ → Document
        </span>
      </div>
    </div>
  )
}
