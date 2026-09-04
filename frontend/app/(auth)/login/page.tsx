"use client"
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { apiFetch } from "@/lib/api"
import { Mail, Lock, ArrowRight } from "lucide-react"

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
    <div className="min-h-screen flex items-center justify-center p-6 bg-background">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2 text-center">
          <div className="mx-auto w-10 h-10 rounded-xl bg-foreground text-background flex items-center justify-center text-sm font-bold">N</div>
          <h1 className="text-2xl font-semibold tracking-tight">Next Stop Mail</h1>
          <p className="text-sm text-muted-foreground">Sign in with your email credentials.</p>
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
      </div>
    </div>
  )
}
