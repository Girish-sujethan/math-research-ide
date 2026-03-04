import type { Metadata } from "next"
import { Geist, Geist_Mono, Gloock } from "next/font/google"
import "./globals.css"
import "katex/dist/katex.min.css"
import { Providers } from "@/components/providers"
import { NavWrapper } from "@/components/nav-wrapper"

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] })
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })
const gloock = Gloock({ weight: "400", subsets: ["latin"], variable: "--font-gloock" })

export const metadata: Metadata = {
  title: "HEAVEN",
  description: "AI-native research assistant for mathematicians",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} ${gloock.variable} antialiased`}>
        <Providers>
          <NavWrapper>{children}</NavWrapper>
        </Providers>
      </body>
    </html>
  )
}
