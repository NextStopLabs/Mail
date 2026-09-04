"use client"
import { useState, useEffect, useRef } from "react"
import { X, Paperclip, Send, Trash2, Minus, Expand } from "lucide-react"
import { apiFetch, apiJson } from "@/lib/api"

type Props = {
  open: boolean
  onClose: ()=>void
  initial?: { to?:string[], cc?:string[], bcc?:string[], subject?:string, text?:string, html?:string, inReplyTo?:string, replyMode?: "reply"|"replyAll"|"forward", draftUid?:string, draftMailbox?:string }
  onSent?: ()=>void
}

type Attachment = {filename:string, mime:string, content:string}

export function Compose({ open, onClose, initial, onSent }: Props) {
  const [to, setTo] = useState(initial?.to?.join(", ") || "")
  const [cc, setCc] = useState(initial?.cc?.join(", ") || "")
  const [bcc, setBcc] = useState(initial?.bcc?.join(", ") || "")
  const [showCc, setShowCc] = useState(Boolean(initial?.cc?.length || initial?.bcc?.length))
  const [subject, setSubject] = useState(initial?.subject || "")
  const [body, setBody] = useState(initial?.text || "")
  const [sending, setSending] = useState(false)
  const [error, setError] = useState("")
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const [minimized, setMinimized] = useState(false)

  // --- Single-draft tracking: one IMAP draft per compose session ---
  // draftUid/draftMailbox are returned by POST /drafts/ and reused on every
  // subsequent save, so the backend replaces the same message instead of
  // appending a new one. This is what stops the "hundreds of drafts" pile-up.
  const [draftUid, setDraftUid] = useState<string | null>(initial?.draftUid || null)
  const [draftMailbox, setDraftMailbox] = useState<string | null>(initial?.draftMailbox || null)
  const [saveState, setSaveState] = useState<"idle"|"saving"|"saved"|"error">("idle")
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const savingRef = useRef(false)
  const sessionRef = useRef(0)
  const lastHashRef = useRef("")

  // Reset per compose session: when dialog (re)opens with a new initial, start fresh.
  useEffect(()=>{
    if (open) {
      sessionRef.current += 1
      setTo(initial?.to?.join(", ") || "")
      setCc(initial?.cc?.join(", ") || "")
      setBcc(initial?.bcc?.join(", ") || "")
      setShowCc(Boolean(initial?.cc?.length || initial?.bcc?.length))
      setSubject(initial?.subject || "")
      setBody(initial?.text || "")
      setAttachments([])
      setError("")
      setMinimized(false)
      setDraftUid(initial?.draftUid || null)
      setDraftMailbox(initial?.draftMailbox || null)
      setSaveState("idle")
      setSavedAt(null)
      lastHashRef.current = ""
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[open])

  function contentHash() {
    return JSON.stringify([to, cc, bcc, subject, body, attachments])
  }

  async function saveDraft(manual = false): Promise<boolean> {
    if (!open || sending || savingRef.current) return false
    const hash = contentHash()
    // Skip if nothing changed (unless manual) or if completely empty
    if (!manual && hash === lastHashRef.current) return false
    if (!to.trim() && !subject.trim() && !body.trim() && attachments.length === 0) return false
    savingRef.current = true
    setSaveState("saving")
    try {
      const data = await apiJson<{uid?:string, mailbox?:string}>("/drafts/", {
        method: "POST",
        body: JSON.stringify({
          to: to.split(",").map(s=>s.trim()).filter(Boolean),
          cc: cc.split(",").map(s=>s.trim()).filter(Boolean),
          bcc: bcc.split(",").map(s=>s.trim()).filter(Boolean),
          subject, text: body,
          html: `<div>${body.replace(/\n/g,"<br/>")}</div>`,
          attachments,
          draftUid, mailbox: draftMailbox || undefined,
        }),
      })
      if (data.uid) setDraftUid(data.uid)
      if (data.mailbox) setDraftMailbox(data.mailbox)
      lastHashRef.current = contentHash()
      setSaveState("saved")
      setSavedAt(new Date().toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}))
      return true
    } catch {
      setSaveState("error")
      return false
    } finally {
      savingRef.current = false
    }
  }

  // Debounced autosave: 2.5s after the user stops typing.
  useEffect(()=>{
    if (!open) return
    const id = setTimeout(()=>{ saveDraft(false) }, 2500)
    return ()=>clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[open, to, cc, bcc, subject, body, attachments, draftUid, draftMailbox])

  function closeAndKeepDraft() {
    // Save once on close so no work is lost, then close (draft stays in Drafts).
    saveDraft(false).finally(()=> onClose())
  }

  async function handleDiscard() {
    // Delete the IMAP draft so discarded composes don't linger.
    const uid = draftUid
    const mbox = draftMailbox
    onClose()
    if (uid) {
      try {
        await apiFetch("/drafts/", {
          method: "DELETE",
          body: JSON.stringify({ draftUid: uid, mailbox: mbox }),
        })
      } catch {}
    }
    setDraftUid(null); setDraftMailbox(null)
  }

  if (!open) return null
  if (minimized) {
    return (
      <div className="fixed bottom-0 right-6 bg-card border rounded-t-xl shadow-xl w-80 p-3 flex items-center justify-between">
        <span className="text-sm truncate">{subject || "New message"}</span>
        <div className="flex gap-1 items-center">
          {saveState==="saving" && <span className="text-[11px] text-muted-foreground">Saving…</span>}
          {saveState==="saved" && savedAt && <span className="text-[11px] text-muted-foreground">Saved {savedAt}</span>}
          <button onClick={()=>setMinimized(false)} className="p-1 hover:bg-accent rounded"><Expand className="w-4 h-4" /></button>
          <button onClick={closeAndKeepDraft} className="p-1 hover:bg-accent rounded"><X className="w-4 h-4" /></button>
        </div>
      </div>
    )
  }

  async function handleSend() {
    setError("")
    if (!to.trim()) { setError("Recipient required"); return }
    setSending(true)
    // Final save first so a failed send still leaves exactly one draft.
    await saveDraft(true)
    try {
      const toArr = to.split(",").map(s=>s.trim()).filter(Boolean)
      const ccArr = cc.split(",").map(s=>s.trim()).filter(Boolean)
      const bccArr = bcc.split(",").map(s=>s.trim()).filter(Boolean)
      const res = await apiFetch("/send/", {
        method:"POST",
        body: JSON.stringify({to: toArr, cc: ccArr, bcc: bccArr, subject, text: body, html: `<div style="font-family:system-ui">${body.replace(/\n/g,"<br/>")}</div>`, inReplyTo: initial?.inReplyTo, attachments, draftUid, draftMailbox })
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Send failed")
      // Sent OK — backend deletes the draft; clear local tracking.
      setDraftUid(null); setDraftMailbox(null)
      lastHashRef.current = ""
      onSent?.()
      onClose()
      // reset fields for next compose
      setTo(""); setCc(""); setBcc(""); setSubject(""); setBody(""); setAttachments([])
    } catch (e:any) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  function handleFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files) return
    Array.from(files).forEach(file=>{
      if (file.size > 25*1024*1024) { setError(`${file.name} too large (25MB limit)`); return }
      const reader = new FileReader()
      reader.onload = ()=>{
        const b64 = (reader.result as string).split(",")[1]
        setAttachments(prev=>[...prev, {filename: file.name, mime: file.type || "application/octet-stream", content: b64}])
      }
      reader.readAsDataURL(file)
    })
    if (fileRef.current) fileRef.current.value = ""
  }

  return (
    <div className="fixed inset-0 sm:inset-auto sm:bottom-0 sm:right-6 sm:w-[560px] sm:h-[78vh] bg-card sm:rounded-t-xl shadow-2xl border flex flex-col z-50">
      <div className="flex items-center justify-between px-4 py-2 border-b bg-secondary/50 sm:rounded-t-xl">
        <span className="text-sm font-medium">New message</span>
        <div className="flex items-center gap-1">
          {saveState==="saving" && <span className="text-[11px] text-muted-foreground mr-1">Saving…</span>}
          {saveState==="saved" && savedAt && <span className="text-[11px] text-muted-foreground mr-1">Draft saved {savedAt}</span>}
          {saveState==="error" && <span className="text-[11px] text-amber-600 mr-1">Draft save failed</span>}
          <button onClick={()=>setMinimized(true)} className="p-1.5 hover:bg-background rounded"><Minus className="w-4 h-4" /></button>
          <button onClick={closeAndKeepDraft} className="p-1.5 hover:bg-background rounded"><X className="w-4 h-4" /></button>
        </div>
      </div>

      <div className="flex flex-col flex-1 overflow-hidden">
        <div className="px-4 py-2 space-y-2 border-b">
          <div className="flex items-center gap-2 text-sm">
            <span className="w-10 text-xs text-muted-foreground">To</span>
            <input value={to} onChange={e=>setTo(e.target.value)} placeholder="recipients@example.com" className="flex-1 py-1.5 bg-transparent outline-none placeholder:text-muted-foreground/60" />
            {!showCc && <button onClick={()=>setShowCc(true)} className="text-xs text-muted-foreground hover:text-foreground px-2">Cc/Bcc</button>}
          </div>
          {showCc && (
            <>
              <div className="flex items-center gap-2 text-sm">
                <span className="w-10 text-xs text-muted-foreground">Cc</span>
                <input value={cc} onChange={e=>setCc(e.target.value)} className="flex-1 py-1 bg-transparent outline-none" />
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span className="w-10 text-xs text-muted-foreground">Bcc</span>
                <input value={bcc} onChange={e=>setBcc(e.target.value)} className="flex-1 py-1 bg-transparent outline-none" />
              </div>
            </>
          )}
          <div className="flex items-center gap-2 text-sm border-t pt-2">
            <input value={subject} onChange={e=>setSubject(e.target.value)} placeholder="Subject" className="flex-1 py-1 bg-transparent outline-none font-medium" />
          </div>
        </div>

        <textarea
          value={body}
          onChange={e=>setBody(e.target.value)}
          onKeyDown={e=>{ if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleSend() }}
          placeholder="Write your message…"
          className="flex-1 p-4 text-sm outline-none resize-none bg-transparent"
        />

        {attachments.length > 0 && (
          <div className="px-4 py-2 border-t flex flex-wrap gap-2">
            {attachments.map((a,i)=>(
              <span key={i} className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-secondary text-xs">
                {a.filename} <button onClick={()=>setAttachments(prev=>prev.filter((_,idx)=>idx!==i))} className="hover:text-red-600"><X className="w-3 h-3" /></button>
              </span>
            ))}
          </div>
        )}

        {error && <div className="mx-4 mb-2 text-xs text-red-600 bg-red-50 dark:bg-red-950/30 border border-red-200 rounded px-3 py-2">{error}</div>}

        <div className="flex items-center justify-between px-4 py-3 border-t bg-card">
          <div className="flex items-center gap-2">
            <button onClick={handleSend} disabled={sending} className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-foreground text-background text-sm font-medium hover:bg-foreground/90 disabled:opacity-50">
              <Send className="w-4 h-4" /> {sending ? "Sending…" : "Send"}
            </button>
            <button onClick={()=>fileRef.current?.click()} className="p-2 hover:bg-accent rounded-lg" title="Attach"><Paperclip className="w-4 h-4" /></button>
            <input ref={fileRef} type="file" multiple hidden onChange={handleFiles} />
            <button onClick={handleDiscard} className="p-2 hover:bg-accent rounded-lg" title="Discard draft"><Trash2 className="w-4 h-4" /></button>
          </div>
          <span className="text-[11px] text-muted-foreground hidden sm:inline">Press ⌘+Enter to send</span>
        </div>
      </div>
    </div>
  )
}
