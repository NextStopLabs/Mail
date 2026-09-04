"use client"
import { cn, formatDate, initials, avatarColor } from "@/lib/utils"
import { Star, Paperclip, MailOpen, Mail, MailCheck, Trash2 } from "lucide-react"

type Msg = {
  uid:string; subject:string; snippet:string; date:string; read:boolean; starred:boolean; hasAttachments:boolean; sender:{name:string,email:string}
}

export function MessageList({ messages, selectedUid, onSelect, onToggleStar, onToggleRead, onDelete, loading }: {
  messages: Msg[]
  selectedUid?: string
  onSelect: (uid:string)=>void
  onToggleStar: (uid:string)=>void
  onToggleRead: (uid:string)=>void
  onDelete: (uid:string)=>void
  loading?: boolean
}) {
  if (loading) {
    return <div className="divide-y">{Array.from({length:8}).map((_,i)=><div key={i} className="p-4 animate-pulse"><div className="flex gap-3"><div className="w-8 h-8 rounded-full bg-muted" /><div className="flex-1 space-y-2"><div className="h-3 bg-muted rounded w-1/3" /><div className="h-3 bg-muted rounded w-2/3" /></div></div></div>)}</div>
  }
  if (!messages.length) {
    return <div className="flex flex-col items-center justify-center py-16 text-sm text-muted-foreground gap-2"><MailOpen className="w-8 h-8 opacity-30" /> No messages in this folder</div>
  }
  return (
    <div className="divide-y divide-border/60">
      {messages.map(m=>{
        const isSelected = selectedUid === m.uid
        return (
          <div
            key={m.uid}
            onClick={()=>onSelect(m.uid)}
            className={cn(
              "group flex gap-3 px-3 py-3 cursor-pointer hover:bg-accent/50 transition text-sm",
              isSelected && "bg-secondary",
              !m.read && "bg-card",
            )}
          >
            <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-medium text-white shrink-0 mt-0.5", avatarColor(m.sender.email))}>
              {initials(m.sender.name, m.sender.email)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2">
                <span className={cn("truncate text-[13px]", !m.read ? "font-semibold" : "font-medium text-muted-foreground")}>
                  {m.sender.name || m.sender.email}
                </span>
                <span className="ml-auto text-[11px] text-muted-foreground whitespace-nowrap">{formatDate(m.date)}</span>
                <button onClick={e=>{e.stopPropagation(); onToggleRead(m.uid)}} title={m.read ? "Mark unread" : "Mark read"} className="p-1 rounded hover:bg-background text-muted-foreground/40 hover:text-foreground opacity-0 group-hover:opacity-100 focus:opacity-100">
                  {m.read ? <Mail className="w-3.5 h-3.5" /> : <MailCheck className="w-3.5 h-3.5" />}
                </button>
                <button onClick={e=>{e.stopPropagation(); onToggleStar(m.uid)}} className={cn("p-1 rounded hover:bg-background", m.starred ? "text-amber-500" : "text-muted-foreground/40 hover:text-amber-500")}>
                  <Star className={cn("w-3.5 h-3.5", m.starred && "fill-amber-500")} />
                </button>
                <button onClick={e=>{e.stopPropagation(); onDelete(m.uid)}} title="Delete" className="p-1 rounded hover:bg-background text-muted-foreground/40 hover:text-red-500 opacity-0 group-hover:opacity-100 focus:opacity-100">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className={cn("truncate pr-6", !m.read ? "font-medium text-foreground" : "text-muted-foreground")}>{m.subject}</div>
              <div className="truncate text-xs text-muted-foreground flex items-center gap-1.5">
                <span className="truncate">{m.snippet || "—"}</span>
                {m.hasAttachments && <Paperclip className="w-3 h-3 shrink-0 opacity-60" />}
              </div>
            </div>
            {!m.read && <button onClick={e=>{e.stopPropagation(); onToggleRead(m.uid)}} title="Mark read" className="w-2 h-2 rounded-full bg-blue-600 mt-2 shrink-0 hover:ring-4 hover:ring-blue-600/20" />} 
          </div>
        )
      })}
    </div>
  )
}
