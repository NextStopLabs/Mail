import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }
export function formatDate(dateStr?: string) {
  if (!dateStr) return ""
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const days = diff / (1000*60*60*24)
  if (days < 1 && d.getDate() === now.getDate()) {
    return d.toLocaleTimeString([], {hour: 'numeric', minute:'2-digit'})
  }
  if (days < 7) {
    return d.toLocaleDateString([], {weekday: 'short'})
  }
  if (d.getFullYear() === now.getFullYear()) {
    return d.toLocaleDateString([], {month: 'short', day: 'numeric'})
  }
  return d.toLocaleDateString([], {month: 'short', day: 'numeric', year:'numeric'})
}
export function initials(name: string, email: string) {
  if (name && name.trim()) {
    return name.trim().split(/\s+/).slice(0,2).map(s=>s[0].toUpperCase()).join("")
  }
  return email.slice(0,2).toUpperCase()
}
export function avatarColor(str: string) {
  let h = 0
  for (let i=0;i<str.length;i++) h = str.charCodeAt(i) + ((h<<5)-h)
  const colors = ["bg-violet-500","bg-blue-500","bg-emerald-500","bg-amber-500","bg-rose-500","bg-cyan-500","bg-orange-500","bg-indigo-500"]
  return colors[Math.abs(h)%colors.length]
}
