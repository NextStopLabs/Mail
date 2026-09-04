"use client"
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { apiFetch } from "@/lib/api"
import { Mail, Lock, ArrowRight, Shield } from "lucide-react"

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(()=>{
    // prime CSRF
    apiFetch("/auth/csrf/", {method:"GET"}).catch(()=>{})
  },[])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      // ensure csrf
      await apiFetch("/auth/csrf/", {method:"GET"})
      const res = await apiFetch("/auth/login/", {
        method: "POST",
        body: JSON.stringify({email, password}),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Login failed")
      router.push("/mail")
    } catch (err:any) {
      setError(err.message || "Login failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left branding */}
      <div className="hidden lg:flex w-[46%] bg-[#0a0a0f] text-white flex-col justify-between p-12 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-violet-600/20 via-transparent to-blue-600/20" />
        <div className="absolute -top-32 -right-32 w-96 h-96 bg-violet-600/25 rounded-full blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-2 text-sm font-medium tracking-widest uppercase opacity-70">
            <div className="w-8 h-8 rounded-lg bg-white text-black flex items-center justify-center font-bold">N</div>
            Next Stop Labs
          </div>
        </div>
        <div className="relative space-y-6 max-w-md">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">Mail that feels<br/>like a modern app.</h1>
          <p className="text-white/60 leading-relaxed">Secure webmail powered by your existing mailbox. No migrations, no new passwords — just a polished, fast interface.</p>
          <div className="flex items-center gap-2 text-xs text-white/50 pt-4">
            <Shield className="w-4 h-4" /> IMAP + SMTP · Dovecot · Postfix · Encrypted sessions
          </div>
        </div>
        <div className="relative text-xs text-white/40">© {new Date().getFullYear()} Next Stop Labs · webmail.nextstoplabs.org</div>
      </div>

      {/* Right form */}
      <div className="flex-1 flex items-center justify-center p-6 bg-background">
        <div className="w-full max-w-sm space-y-8">
          <div className="space-y-2">
            <div className="lg:hidden flex items-center gap-2 text-sm font-semibold">
              <div className="w-7 h-7 rounded-md bg-foreground text-background flex items-center justify-center text-xs">N</div>
              NextStop
            </div>
            <h2 className="text-2xl font-semibold tracking-tight">Welcome back</h2>
            <p className="text-sm text-muted-foreground">Sign in with your existing email credentials.</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium">Email address</label>
              <div className="relative">
                <Mail className="absolute left-3 top-3 w-4 h-4 text-muted-foreground" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={e=>setEmail(e.target.value)}
                  placeholder="you@nextstoplabs.org"
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border bg-card text-sm focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 w-4 h-4 text-muted-foreground" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={e=>setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border bg-card text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <p className="text-[11px] text-muted-foreground">Uses your existing mailbox password. Never stored in plain text.</p>
            </div>

            {error && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-lg px-3 py-2.5">{error}</div>}

            <button
              type="submit"
              disabled={loading}
              className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-foreground text-background py-2.5 text-sm font-medium hover:bg-foreground/90 transition disabled:opacity-50"
            >
              {loading ? "Signing in…" : "Sign in"} {!loading && <ArrowRight className="w-4 h-4" />}
            </button>
          </form>

          <div className="text-xs text-muted-foreground leading-relaxed border-t pt-6">
            Protected by secure HTTP-only cookies, CSRF, and rate limiting. Sessions expire after 14 days.
          </div>
        </div>
      </div>
    </div>
  )
}
