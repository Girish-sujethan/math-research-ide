"use client"

import { usePathname } from "next/navigation"
import { Nav } from "./nav"

export function NavWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const showNav = pathname.startsWith("/library") || pathname.startsWith("/chat") ||
    pathname.startsWith("/papers") || pathname.startsWith("/discoveries") ||
    pathname.startsWith("/concepts")

  if (showNav) {
    return (
      <div className="flex h-screen overflow-hidden">
        <Nav />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    )
  }

  return <>{children}</>
}
