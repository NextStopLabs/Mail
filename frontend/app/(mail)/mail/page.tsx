"use client"
import { useEffect, useState, useCallback, useRef } from "react"
import { apiFetch, apiJson } from "@/lib/api"
import { Sidebar } from "@/components/mail/sidebar"
import { MessageList } from "@/components/mail/message-list"
import { MessageView } from "@/components/mail/message-view"
import { Compose } from "@/components/mail/compose"
import { Search, Menu, X, ChevronLeft, Settings, Moon, Sun, Keyboard } from "lucide-react"
import { useTheme } from "@/components/theme-provider"

type Mailbox = { id:string; fullName:string; name:string; role:string; unseen:number; total:number }

export default function MailPage() {
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([])
  const [selectedMailbox, setSelectedMailbox] = useState("INBOX")
  const [messages, setMessages] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [selectedUid, setSelectedUid] = useState<string | null>(null)
  const [selectedMsg, setSelectedMsg] = useState<any | null>(null)
  const [msgLoading, setMsgLoading] = useState(false)
  const [showSidebar, setShowSidebar] = useState(false)
  const [composeOpen, setComposeOpen] = useState(false)
  const [composeInitial, setComposeInitial] = useState<any>(null)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const { theme, setTheme } = useTheme()
  const [userEmail, setUserEmail] = useState("")

  const selectedMailboxRef = useRef(selectedMailbox)
  selectedMailboxRef.current = selectedMailbox

  const loadMailboxes = useCallback(async ()=>{
    try {
      const data = await apiJson<Mailbox[]>("/mailboxes/")
      setMailboxes(data)
      // Don't clobber user's selection: only default if current selection vanished
      const current = selectedMailboxRef.current
      if (data.length && !data.find(m=>m.fullName===current)) {
        setSelectedMailbox(data[0].fullName)
      }
    } catch {}
  },[])

  // Debounce search input -> query (prevents hammering IMAP on every keystroke)
  const [searchInput, setSearchInput] = useState("")
  const [searchQuery, setSearchQuery] = useState("")
  useEffect(()=>{
    const id = setTimeout(()=> setSearchQuery(searchInput.trim()), 400)
    return ()=> clearTimeout(id)
  },[searchInput])

  const loadMessages = useCallback(async (mailbox:string, p:number, q:string)=>{
    setLoading(true)
    try {
      const params = new URLSearchParams({page: String(p), page_size: "50"})
      if (q) params.set("q", q)
      const data = await apiJson<any>(`/mailboxes/${encodeURIComponent(mailbox)}/messages/?${params}`)
      setMessages(data.messages || [])
      setTotal(data.total || 0)
    } catch {
      setMessages([])
    } finally {
      setLoading(false)
    }
  },[])

  useEffect(()=>{
    apiJson<any>("/auth/me/").then(d=> setUserEmail(d.email)).catch(()=>{})
    loadMailboxes()
    // Poll counts in background so Inbox badge stays fresh (new mail, other clients)
    const poll = setInterval(()=> loadMailboxes(), 30000)
    function onFocus(){ loadMailboxes() }
    window.addEventListener("focus", onFocus)
    return ()=>{ clearInterval(poll); window.removeEventListener("focus", onFocus) }
  },[loadMailboxes])

  useEffect(()=>{ loadMessages(selectedMailbox, page, searchQuery) }, [selectedMailbox, page, searchQuery, loadMessages])

  // reset page when mailbox/search changes
  useEffect(()=>{ setPage(1); setSelectedUid(null); setSelectedMsg(null) }, [selectedMailbox, searchQuery])

  // --- Unseen-count helpers: keep sidebar badge in sync without full refresh ---
  function adjustUnseen(mailbox:string, delta:number) {
    if (!delta) return
    setMailboxes(prev=>prev.map(m=>m.fullName===mailbox ? {...m, unseen: Math.max(0, (m.unseen||0)+delta)} : m))
  }

  async function openMessage(uid:string) {
    setSelectedUid(uid)
    setMsgLoading(true)
    const mailbox = selectedMailboxRef.current
    try {
      const msg = await apiJson<any>(`/messages/${encodeURIComponent(mailbox)}/${uid}/?thread=1`)
      setSelectedMsg(msg)
      // mark read (only if currently unread) + decrement badge optimistically
      const listEntry = messages.find(m=>m.uid===uid)
      const wasUnread = msg.read === false || (listEntry && !listEntry.read)
      if (wasUnread) {
        setMessages(prev=>prev.map(m=>m.uid===uid?{...m, read:true}:m))
        setSelectedMsg((prev:any)=>prev ? {...prev, read:true} : prev)
        adjustUnseen(mailbox, -1)
        try {
          await apiFetch(`/messages/${encodeURIComponent(mailbox)}/${uid}/read/`, {method:"POST", body: JSON.stringify({read:true})})
        } catch {
          // revert on failure
          setMessages(prev=>prev.map(m=>m.uid===uid?{...m, read:false}:m))
          adjustUnseen(mailbox, +1)
        }
      }
    } catch {
      // fallback without thread
      try {
        const msg2 = await apiJson<any>(`/messages/${encodeURIComponent(mailbox)}/${uid}/`)
        setSelectedMsg(msg2)
      } catch {}
    }
    finally { setMsgLoading(false) }
  }

  async function handleAction(action:string, data?:any) {
    if (!selectedUid || !selectedMsg) return
    const uid = selectedUid
    const mailbox = selectedMailbox
    try {
      if (action === "read") {
        const next = Boolean(data.read)
        const was = Boolean(selectedMsg.read)
        if (next === was) return
        // optimistic
        setSelectedMsg({...selectedMsg, read: next})
        setMessages(prev=>prev.map(m=>m.uid===uid?{...m, read:next}:m))
        adjustUnseen(mailbox, next ? -1 : +1)
        try {
          await apiFetch(`/messages/${encodeURIComponent(mailbox)}/${uid}/read/`, {method:"POST", body: JSON.stringify(data)})
        } catch {
          setSelectedMsg({...selectedMsg, read: was})
          setMessages(prev=>prev.map(m=>m.uid===uid?{...m, read:was}:m))
          adjustUnseen(mailbox, next ? +1 : -1)
        }
      } else if (action === "star") {
        await apiFetch(`/messages/${encodeURIComponent(mailbox)}/${uid}/flag/`, {method:"POST", body: JSON.stringify({flagged: data.starred})})
        setSelectedMsg({...selectedMsg, starred: data.starred})
        setMessages(prev=>prev.map(m=>m.uid===uid?{...m, starred:data.starred}:m))
      } else if (action === "delete") {
        const wasUnread = !selectedMsg.read
        await apiFetch(`/messages/${encodeURIComponent(mailbox)}/${uid}/delete/`, {method:"POST", body:"{}"})
        setMessages(prev=>prev.filter(m=>m.uid!==uid))
        setTotal(t=>Math.max(0, t-1))
        if (wasUnread) adjustUnseen(mailbox, -1)
        setSelectedMsg(null); setSelectedUid(null)
        loadMailboxes()
      } else if (action === "archive") {
        const wasUnread = !selectedMsg.read
        const archiveBox = mailboxes.find(m=>m.role==="archive")?.fullName || "Archive"
        await apiFetch(`/messages/${encodeURIComponent(mailbox)}/${uid}/move/`, {method:"POST", body: JSON.stringify({dest: archiveBox})})
        setMessages(prev=>prev.filter(m=>m.uid!==uid))
        setTotal(t=>Math.max(0, t-1))
        if (wasUnread) adjustUnseen(mailbox, -1)
        // destination counts changed too — refresh in background
        loadMailboxes()
        setSelectedMsg(null); setSelectedUid(null)
      } else if (action === "reply" || action === "replyAll" || action === "forward") {
        const from = selectedMsg.from?.[0]
        const subj = selectedMsg.subject || ""
        let to: string[] = []
        let subject = subj
        let body = ""
        if (action === "reply") {
          to = [from?.email || ""]
          subject = subj.toLowerCase().startsWith("re:") ? subj : `Re: ${subj}`
          body = `\n\nOn ${selectedMsg.date}, ${from?.name || from?.email} wrote:\n> ${(selectedMsg.text || "").split("\n").join("\n> ")}`
        } else if (action === "replyAll") {
          const all = [...(selectedMsg.from||[]), ...(selectedMsg.to||[]), ...(selectedMsg.cc||[])].map((a:any)=>a.email).filter((e:string)=>e!==userEmail)
          to = Array.from(new Set(all))
          subject = subj.toLowerCase().startsWith("re:") ? subj : `Re: ${subj}`
          body = `\n\nOn ${selectedMsg.date}, ${from?.name || from?.email} wrote:\n> ${(selectedMsg.text || "").split("\n").join("\n> ")}`
        } else {
          subject = subj.toLowerCase().startsWith("fwd:") ? subj : `Fwd: ${subj}`
          body = `\n\n---------- Forwarded message ----------\nFrom: ${from?.email}\nDate: ${selectedMsg.date}\nSubject: ${subj}\n\n${selectedMsg.text || ""}`
        }
        setComposeInitial({to, subject, text: body, inReplyTo: selectedMsg.messageId})
        setComposeOpen(true)
      }
    } catch (e) {}
  }

  async function toggleStar(uid:string){
    const msg = messages.find(m=>m.uid===uid)
    if (!msg) return
    const next = !msg.starred
    setMessages(prev=>prev.map(m=>m.uid===uid?{...m, starred:next}:m))
    if (selectedUid===uid) setSelectedMsg((prev:any)=>prev?{...prev, starred:next}:prev)
    try { await apiFetch(`/messages/${encodeURIComponent(selectedMailbox)}/${uid}/flag/`, {method:"POST", body: JSON.stringify({flagged: next})}) } catch {
      setMessages(prev=>prev.map(m=>m.uid===uid?{...m, starred:!next}:m))
    }
  }

  async function toggleRead(uid:string){
    const msg = messages.find(m=>m.uid===uid)
    if (!msg) return
    const next = !msg.read
    setMessages(prev=>prev.map(m=>m.uid===uid?{...m, read:next}:m))
    if (selectedUid===uid) setSelectedMsg((prev:any)=>prev?{...prev, read:next}:prev)
    adjustUnseen(selectedMailbox, next ? -1 : +1)
    try { await apiFetch(`/messages/${encodeURIComponent(selectedMailbox)}/${uid}/read/`, {method:"POST", body: JSON.stringify({read: next})}) } catch {
      setMessages(prev=>prev.map(m=>m.uid===uid?{...m, read:!next}:m))
      adjustUnseen(selectedMailbox, next ? +1 : -1)
    }
  }

  // Keyboard shortcuts — use refs so handler never goes stale
  const stateRef = useRef<any>({})
  stateRef.current = { selectedUid, messages, composeOpen, showShortcuts, selectedMsg, selectedMailbox }
  useEffect(()=>{
    function onKey(e: KeyboardEvent) {
      const s = stateRef.current
      if ((e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "TEXTAREA") return
      if (e.key === "c") setComposeOpen(true)
      if (e.key === "r" && s.selectedUid) handleAction("reply")
      if (e.key === "a" && s.selectedUid) handleAction("replyAll")
      if (e.key === "f" && s.selectedUid) handleAction("forward")
      if (e.key === "e" && s.selectedUid) handleAction("archive")
      if (e.key === "#" && s.selectedUid) handleAction("delete")
      if (e.key === "j") {
        const idx = s.messages.findIndex((m:any)=>m.uid===s.selectedUid)
        if (idx >=0 && idx < s.messages.length-1) openMessage(s.messages[idx+1].uid)
      }
      if (e.key === "k") {
        const idx = s.messages.findIndex((m:any)=>m.uid===s.selectedUid)
        if (idx > 0) openMessage(s.messages[idx-1].uid)
      }
      if (e.key === "?" ) setShowShortcuts(v=>!v)
      if (e.key === "Escape") { if (s.composeOpen) setComposeOpen(false); else if (s.showShortcuts) setShowShortcuts(false) }
    }
    window.addEventListener("keydown", onKey)
    return ()=> window.removeEventListener("keydown", onKey)
  },[])

  async function handleLogout(){
    await apiFetch("/auth/logout/", {method:"POST"})
    window.location.href = "/login"
  }

  const isDraftsMailbox = (mailboxes.find(m=>m.fullName===selectedMailbox)?.role === "drafts")
  const [cleanupLoading, setCleanupLoading] = useState(false)
  const [cleanupMsg, setCleanupMsg] = useState("")
  async function handleDraftCleanup(){
    setCleanupLoading(true); setCleanupMsg("")
    try {
      const data = await apiJson<any>("/drafts/", {method:"POST", body: JSON.stringify({action:"cleanup", keep: 10, mailbox: selectedMailbox})})
      setCleanupMsg(`Kept ${data.kept}, deleted ${data.deleted}.`)
      loadMessages(selectedMailbox, 1, searchQuery)
      loadMailboxes()
    } catch (e:any) {
      setCleanupMsg(e.message || "Cleanup failed")
    } finally { setCleanupLoading(false) }
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Top bar */}
      <header className="h-14 border-b flex items-center gap-2 px-3 shrink-0 bg-card">
        <button onClick={()=>setShowSidebar(!showSidebar)} className="p-2 hover:bg-accent rounded-lg lg:hidden"><Menu className="w-5 h-5" /></button>
        <div className="hidden lg:flex items-center gap-2 font-semibold text-sm">
          <div className="w-7 h-7 rounded-md bg-foreground text-background flex items-center justify-center text-xs">N</div>
          <span>Mail</span>
          <span className="text-muted-foreground font-normal">· {userEmail}</span>
        </div>
        <div className="flex-1 max-w-xl mx-2 lg:mx-6 relative">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
          <input
            value={searchInput}
            onChange={e=>setSearchInput(e.target.value)}
            placeholder="Search mail (sender, subject, text)"
            className="w-full pl-9 pr-3 py-2 rounded-full bg-secondary border-0 text-sm focus:outline-none focus:ring-2 focus:ring-ring placeholder:text-muted-foreground/70"
          />
          {searchInput && <button onClick={()=>{setSearchInput(""); setSearchQuery("")}} className="absolute right-3 top-2.5 text-muted-foreground"><X className="w-4 h-4" /></button>}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={()=>setTheme(theme==="dark"?"light":"dark")} className="p-2 hover:bg-accent rounded-lg">{theme==="dark"?<Sun className="w-4 h-4" />:<Moon className="w-4 h-4" />}</button>
          <button onClick={()=>setShowShortcuts(true)} className="p-2 hover:bg-accent rounded-lg hidden sm:inline-flex" title="Shortcuts (?)"><Keyboard className="w-4 h-4" /></button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className={`${showSidebar ? "flex" : "hidden"} lg:flex w-[260px] border-r bg-card shrink-0 flex-col`}>
          <Sidebar
            mailboxes={mailboxes}
            selected={selectedMailbox}
            onSelect={(f)=>{setSelectedMailbox(f); setShowSidebar(false)}}
            onCompose={()=>{setComposeInitial(null); setComposeOpen(true)}}
            onLogout={handleLogout}
          />
        </aside>

        {/* Message list */}
        <div className={`flex flex-col border-r bg-background shrink-0 ${selectedUid ? "hidden lg:flex lg:w-[380px] xl:w-[420px]" : "flex flex-1 lg:w-[380px] xl:w-[420px] lg:flex-none"}`}>
          <div className="px-3 py-2 border-b flex items-center justify-between text-xs text-muted-foreground bg-card sticky top-0">
            <span className="font-medium text-foreground">{mailboxes.find(m=>m.fullName===selectedMailbox)?.name || selectedMailbox}</span>
            <span>{total} messages · page {page}</span>
          </div>
          {isDraftsMailbox && total > 10 && (
            <div className="px-3 py-2 border-b bg-amber-50 dark:bg-amber-950/20 text-xs flex items-center gap-2">
              <span className="flex-1 text-amber-900 dark:text-amber-200">You have {total} drafts. Autosave now keeps one per compose — clean up the old pile?</span>
              <button onClick={handleDraftCleanup} disabled={cleanupLoading} className="px-3 py-1 rounded-full bg-amber-600 text-white text-xs font-medium disabled:opacity-50">
                {cleanupLoading ? "Cleaning…" : "Keep newest 10"}
              </button>
            </div>
          )}
          {cleanupMsg && isDraftsMailbox && (
            <div className="px-3 py-1.5 border-b text-xs text-muted-foreground">{cleanupMsg}</div>
          )}
          <div className="flex-1 overflow-y-auto">
            <MessageList messages={messages} selectedUid={selectedUid||undefined} onSelect={openMessage} onToggleStar={toggleStar} onToggleRead={toggleRead} loading={loading} />
          </div>
          <div className="p-2 border-t flex items-center justify-between text-xs bg-card">
            <button disabled={page<=1} onClick={()=>setPage(p=>Math.max(1,p-1))} className="px-3 py-1 rounded-full border disabled:opacity-40">Previous</button>
            <span className="text-muted-foreground">Page {page} of {Math.max(1, Math.ceil(total/50))}</span>
            <button disabled={page>=Math.ceil(total/50)} onClick={()=>setPage(p=>p+1)} className="px-3 py-1 rounded-full border disabled:opacity-40">Next</button>
          </div>
        </div>

        {/* Reader */}
        <div className={`flex-1 flex flex-col min-w-0 bg-card ${!selectedUid ? "hidden lg:flex" : "flex"}`}>
          {selectedUid ? (
            msgLoading ? <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">Loading message…</div>
            : <MessageView message={selectedMsg} mailbox={selectedMailbox} onAction={handleAction} onClose={()=>{setSelectedUid(null); setSelectedMsg(null)}} />
          ) : (
            <div className="flex-1 hidden lg:flex flex-col items-center justify-center p-8 text-center text-sm text-muted-foreground gap-3">
              <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center">✉️</div>
              <div className="font-medium text-foreground">Select a message to read</div>
              <div className="max-w-xs">Choose from your conversations. Use <kbd className="px-1.5 py-0.5 rounded bg-secondary border text-xs">j</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-secondary border text-xs">k</kbd> to navigate.</div>
              <button onClick={()=>setComposeOpen(true)} className="mt-2 px-4 py-2 rounded-full bg-foreground text-background text-sm font-medium">Compose</button>
            </div>
          )}
          {/* Mobile back */}
          {selectedUid && (
            <button onClick={()=>{setSelectedUid(null); setSelectedMsg(null)}} className="lg:hidden fixed bottom-6 left-6 p-3 rounded-full bg-foreground text-background shadow-lg">
              <ChevronLeft className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>

      <Compose open={composeOpen} onClose={()=>setComposeOpen(false)} initial={composeInitial} onSent={()=>{setPage(1); loadMessages(selectedMailbox,1,searchQuery); loadMailboxes()}} />

      {showShortcuts && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50" onClick={()=>setShowShortcuts(false)}>
          <div onClick={e=>e.stopPropagation()} className="bg-card rounded-xl border shadow-xl w-full max-w-lg p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Keyboard shortcuts</h3>
              <button onClick={()=>setShowShortcuts(false)} className="p-1 hover:bg-accent rounded"><X className="w-4 h-4" /></button>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {[
                ["c","Compose"], ["r","Reply"], ["a","Reply all"], ["f","Forward"],
                ["e","Archive"], ["#","Delete"], ["j","Next message"], ["k","Prev message"],
                ["Enter","Open"], ["Shift+I","Mark read"], ["Shift+U","Mark unread"], ["?","Help"]
              ].map(([k,desc])=>(
                <div key={k} className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-accent">
                  <span className="text-muted-foreground">{desc}</span>
                  <kbd className="px-1.5 py-0.5 rounded bg-secondary border text-xs font-mono">{k}</kbd>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
