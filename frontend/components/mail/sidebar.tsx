"use client"
import { cn } from "@/lib/utils"
import { Inbox, Send, FileText, Archive, Trash2, ShieldAlert, Star, Folder, PenSquare, LogOut, Settings } from "lucide-react"

type Mailbox = { id:string; fullName:string; name:string; role:string; unseen:number; total:number }

const roleIcon: Record<string, any> = {
  inbox: Inbox,
  sent: Send,
  drafts: FileText,
  archive: Archive,
  trash: Trash2,
  spam: ShieldAlert,
  starred: Star,
}

export function Sidebar({ mailboxes, selected, onSelect, onCompose, onLogout, collapsed }: {
  mailboxes: Mailbox[]
  selected: string
  onSelect: (fullName:string)=>void
  onCompose: ()=>void
  onLogout: ()=>void
  collapsed?: boolean
}) {
  return (
    <div className="flex flex-col h-full">
      <div className="p-3">
        <button onClick={onCompose} className="w-full inline-flex items-center justify-center gap-2 rounded-full bg-foreground text-background py-2.5 text-sm font-medium hover:bg-foreground/90 transition shadow-sm">
          <PenSquare className="w-4 h-4" /> {!collapsed && "Compose"}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {mailboxes.map(mb=>{
          const Icon = roleIcon[mb.role] || Folder
          const isActive = selected === mb.fullName
          return (
            <button
              key={mb.fullName}
              onClick={()=>onSelect(mb.fullName)}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-1.5 rounded-lg text-sm text-left transition",
                isActive ? "bg-secondary font-medium" : "hover:bg-accent text-muted-foreground hover:text-foreground",
              )}
              title={mb.fullName}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && <span className="flex-1 truncate">{mb.name}</span>}
              {!collapsed && mb.unseen > 0 && (
                <span className={cn("text-xs px-1.5 py-0.5 rounded-full min-w-5 text-center", isActive ? "bg-foreground text-background" : "bg-secondary text-foreground")}>
                  {mb.unseen}
                </span>
              )}
            </button>
          )
        })}
      </div>
      <div className="p-2 border-t space-y-1">
        <button onClick={onLogout} className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm hover:bg-accent text-muted-foreground">
          <LogOut className="w-4 h-4" /> {!collapsed && "Sign out"}
        </button>
      </div>
    </div>
  )
}
