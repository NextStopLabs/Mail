import "./globals.css"
import type { Metadata } from "next"
import { ThemeProvider } from "@/components/theme-provider"

export const metadata: Metadata = {
  title: "NextStop Webmail",
  description: "Modern webmail for nextstoplabs.org",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  )
}
