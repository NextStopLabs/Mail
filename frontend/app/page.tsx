"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { apiFetch } from "@/lib/api"

export default function Home() {
  const router = useRouter()
  const [checked, setChecked] = useState(false)
  useEffect(()=>{
    apiFetch("/auth/me/").then(r=>{
      if (r.ok) router.replace("/mail")
      else router.replace("/login")
    }).catch(()=> router.replace("/login")).finally(()=> setChecked(true))
  },[router])
  if (!checked) return <div className="min-h-screen flex items-center justify-center text-sm text-muted-foreground">Loading…</div>
  return null
}
