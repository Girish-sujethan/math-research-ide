"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { MessageSquare, FileText, Lightbulb, BookOpen } from "lucide-react"
import { cn } from "@/lib/utils"

const links = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/papers", label: "Papers", icon: FileText },
  { href: "/discoveries", label: "Discoveries", icon: Lightbulb },
  { href: "/concepts", label: "Concepts", icon: BookOpen },
]

export function Nav() {
  const pathname = usePathname()
  return (
    <nav className="flex h-screen w-52 shrink-0 flex-col gap-1 border-r p-3">
      <div className="mb-4 px-2 pt-2">
        <span className="text-lg font-semibold tracking-tight">HEAVEN</span>
      </div>
      {links.map(({ href, label, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          className={cn(
            "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
            pathname.startsWith(href)
              ? "bg-muted font-medium text-foreground"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          <Icon className="size-4" />
          {label}
        </Link>
      ))}
    </nav>
  )
}
