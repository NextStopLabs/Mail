const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "/api").replace(/\/$/, "")

export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`
  return `${API_BASE}${p}`
}

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  const v = document.cookie.split("; ").find(row => row.startsWith(name+"="))
  return v ? decodeURIComponent(v.split("=")[1]) : null
}

export async function apiFetch(path: string, opts: RequestInit = {}) {
  const headers: Record<string,string> = { ...(opts.headers as any) }
  if (!(opts.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json"
  }
  const csrf = getCookie("csrftoken")
  if (csrf) headers["X-CSRFToken"] = csrf
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers,
    credentials: "include",
  })
  if (res.status === 401) {
    if (typeof window !== "undefined" && !path.startsWith("/auth")) {
      // Avoid redirect loop on login page
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login"
      }
    }
  }
  return res
}

export async function apiJson<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, opts)
  if (!res.ok) {
    const text = await res.text()
    let detail = text
    try { detail = JSON.parse(text).detail || text } catch {}
    throw new Error(detail || `Request failed ${res.status}`)
  }
  return res.json()
}
