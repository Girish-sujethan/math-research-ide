"use client"

import dynamic from "next/dynamic"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PapersView } from "./papers-view"

// LaTeXEditor reads localStorage at init — must be client-only
const LaTeXEditor = dynamic(
  () => import("@/components/editor/latex-editor").then((m) => m.LaTeXEditor),
  { ssr: false }
)

interface Props {
  className?: string
}

export function MiddlePane({ className }: Props) {
  return (
    <Tabs defaultValue="document" className={`flex flex-col ${className ?? ""}`}>
      <div className="border-b border-gray-200 flex-shrink-0 py-1.5 flex justify-center">
        <span className="text-sm font-semibold text-gray-700" style={{ fontFamily: "var(--font-gloock), serif" }}>
          HEAVEN
        </span>
      </div>
      <div className="border-b border-gray-200 flex-shrink-0">
        <TabsList className="h-9 bg-transparent px-3 gap-0 rounded-none border-0">
          <TabsTrigger
            value="document"
            className="rounded-none border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:text-blue-600 text-xs px-3 h-9 bg-transparent shadow-none"
          >
            Document
          </TabsTrigger>
          <TabsTrigger
            value="papers"
            className="rounded-none border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:text-blue-600 text-xs px-3 h-9 bg-transparent shadow-none"
          >
            Linked Concepts
          </TabsTrigger>
        </TabsList>
      </div>

      <TabsContent forceMount value="document" className="flex-1 overflow-hidden mt-0 data-[state=inactive]:hidden">
        <LaTeXEditor className="h-full" />
      </TabsContent>

      <TabsContent value="papers" className="flex-1 overflow-hidden mt-0 flex flex-col data-[state=inactive]:hidden">
        <PapersView />
      </TabsContent>
    </Tabs>
  )
}
