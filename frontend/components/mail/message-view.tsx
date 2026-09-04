"use client"
import { useState, useEffect, useMemo } from "react"
import { formatDate, initials, avatarColor, cn } from "@/lib/utils"
import { apiUrl } from "@/lib/api"
import { Reply, ReplyAll, Forward, Star, Trash2, Archive, Paperclip, Download, ChevronDown, ChevronUp, X, Users, Mail } from "lucide-react"

function HtmlBody({ html }: { html: string }) {
  const clean = useMemo(() => {
    let c = html.trim()
    const bodyMatch = c.match(/<body[^>]*>([\s\S]*)<\/body\s*>/i)
    if (bodyMatch) c = bodyMatch[1]
    else c = c.replace(/<\/?html[^>]*>/gi, "").replace(/<\/?head[^>]*>[\s\S]*?<\/head\s*>/gi, "")
    return c
  }, [html])
  return (
    <div className="email-body font-sans text-[14px] leading-[1.6] break-words px-1 py-1 text-foreground">
      <style>{`
        .email-body *{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif !important;max-width:100%;box-sizing:border-box}
        .email-body p{margin:0 0 8px}.email-body p:last-child{margin-bottom:0}
        .email-body a{color:#2563eb;text-decoration:underline;word-break:break-all}
        .email-body img{max-width:100%;height:auto;border-radius:4px}
        .email-body blockquote{margin:8px 0;padding:4px 12px;border-left:2px solid #e4e4e7;color:#71717a}
        .email-body pre{white-space:pre-wrap;word-break:break-word;background:#f4f4f5;padding:8px;border-radius:6px;overflow:auto;font-family:ui-monospace,monospace !important}
        .email-body table{border-collapse:collapse;width:auto}
        .email-body p:empty,.email-body div:empty{display:none}
        .dark .email-body a{color:#93c5fd !important}
        .dark .email-body blockquote{border-left-color:#27272a !important;color:#a1a1aa !important}
        .dark .email-body pre{background:#18181b !important;color:#e4e4e7 !important}
        .dark .email-body p,.dark .email-body div,.dark .email-body span,.dark .email-body td,.dark .email-body th,.dark .email-body li,.dark .email-body h1,.dark .email-body h2,.dark .email-body h3,.dark .email-body h4,.dark .email-body h5,.dark .email-body h6,.dark .email-body font,.dark .email-body center{color:#e4e4e7 !important}
        .dark .email-body div,.dark .email-body p,.dark .email-body span,.dark .email-body td,.dark .email-body th,.dark .email-body table,.dark .email-body tbody,.dark .email-body thead,.dark .email-body tr,.dark .email-body ul,.dark .email-body ol,.dark .email-body li,.dark .email-body section,.dark .email-body article{ background:transparent !important;background-color:transparent !important;border-color:#27272a !important}
        .dark .email-body font[color],.dark .email-body [color]{color:#e4e4e7 !important}
      `}</style>
      <div dangerouslySetInnerHTML={{ __html: clean }} />
    </div>
  )
}

type Attachment = { filename:string; mime:string; size:number; cid?:string }
type Sender = { name:string; email:string }

function QuotedMessage({ quoted, depth=0 }: { quoted: any; depth?: number }) {
  const [expanded, setExpanded] = useState(false)
  if (!quoted) return null
  const sender = quoted.sender || quoted.from?.[0] || { name: "", email: "" }
  const hasNested = quoted.quotedMessages && quoted.quotedMessages.length > 0
  return (
    <div className={cn("mt-2 border-l-2 pl-3", depth > 0 ? "ml-2 border-muted-foreground/20" : "border-muted-foreground/30")}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground py-1"
      >
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        <span className="font-medium">
          {sender.name || sender.email ? `Quoted from ${sender.name || sender.email}` : "Show quoted message"}
          {quoted.timestamp || quoted.date ? ` · ${formatDate(quoted.timestamp || quoted.date)}` : ""}
        </span>
        <span className="text-[11px] opacity-70">▸ {depth+1}</span>
      </button>
      {expanded && (
        <div className="mt-1.5 rounded-lg bg-secondary/40 dark:bg-secondary/30 p-3 text-sm">
          <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
            <span className="font-medium text-foreground">{sender.name || "Unknown"}</span>
            {sender.email && <span>&lt;{sender.email}&gt;</span>}
            {(quoted.timestamp || quoted.date) && <span>· {formatDate(quoted.timestamp || quoted.date)}</span>}
          </div>
          {quoted.html ? (
            <div className="email-body text-[13px] leading-[1.55] font-sans break-words text-foreground">
              <style>{`.email-body *{font-family:Inter,system-ui,sans-serif !important} .dark .email-body *{color:#e4e4e7 !important;background:transparent !important} .dark .email-body a{color:#93c5fd !important}`}</style>
              <div dangerouslySetInnerHTML={{ __html: quoted.html }} />
            </div>
          ) : (
            <div className="whitespace-pre-wrap font-sans text-[13.5px] leading-[1.55] break-words text-foreground">{quoted.text || quoted.body?.plain_text || "—"}</div>
          )}
          {hasNested && (
            <div className="mt-2 space-y-2">
              {quoted.quotedMessages.map((nq:any, idx:number) => (
                <QuotedMessage key={nq.id || idx} quoted={nq} depth={depth+1} />
              ))}
            </div>
          )}
        </div>
      )}
      {!expanded && hasNested && (
        <div className="text-[11px] text-muted-foreground ml-5">+ {quoted.quotedMessages.length} older quoted</div>
      )}
    </div>
  )
}

function MessageCard({ msg, mailbox, isExpandedDefault, isNewest, onReply }: {
  msg:any; mailbox:string; isExpandedDefault:boolean; isNewest:boolean; onReply?:(m:any)=>void
}) {
  const [expanded, setExpanded] = useState(isExpandedDefault)
  const [showRecipients, setShowRecipients] = useState(false)
  const [showQuoted, setShowQuoted] = useState(false)
  useEffect(()=>{ setExpanded(isExpandedDefault) }, [isExpandedDefault])
  const from: Sender = msg.from?.[0] || msg.sender || { name: "", email: "" }
  const toList = msg.to || msg.recipients?.to || []
  const ccList = msg.cc || msg.recipients?.cc || []
  const rawHtml: string = msg.html || msg.body?.html || ""
  const rawText: string = msg.text || msg.body?.plain_text || ""
  return (
    <div className={cn("rounded-xl border bg-card overflow-hidden", isNewest ? "ring-1 ring-primary/10 shadow-sm" : "shadow-sm")}>
      <button
        onClick={()=> setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/30 transition"
      >
        <div className={cn("w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-medium text-white shrink-0", avatarColor(from.email || from.name || "?"))}>
          {initials(from.name, from.email)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="font-medium text-sm truncate">{from.name || from.email}</span>
            <span className="text-xs text-muted-foreground truncate hidden sm:inline">&lt;{from.email}&gt;</span>
            {isNewest && <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary text-primary-foreground">Latest</span>}
          </div>
          <div className="text-xs text-muted-foreground truncate">
            To: {toList.map((t:any)=> t.email || t).join(", ") || "—"} {ccList.length ? ` · Cc: ${ccList.map((t:any)=>t.email).join(", ")}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground whitespace-nowrap">{formatDate(msg.date || msg.timestamp)}</span>
          {expanded ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          <div className="flex items-center gap-2 text-xs">
            <button onClick={()=> setShowRecipients(!showRecipients)} className="text-muted-foreground hover:text-foreground flex items-center gap-1">
              <Mail className="w-3 h-3" /> {showRecipients ? "Hide details" : "Show details"}
            </button>
            {msg.subject && <span className="text-muted-foreground truncate">· {msg.subject}</span>}
          </div>
          {showRecipients && (
            <div className="rounded-lg bg-secondary/50 p-3 text-xs space-y-1.5">
              <div><span className="font-medium">From:</span> {from.name ? `${from.name} <${from.email}>` : from.email}</div>
              <div><span className="font-medium">To:</span> {toList.map((t:any)=> t.name ? `${t.name} <${t.email}>` : t.email).join(", ") || "—"}</div>
              {ccList.length >0 && <div><span className="font-medium">Cc:</span> {ccList.map((t:any)=> t.name? `${t.name} <${t.email}>` : t.email).join(", ")}</div>}
              <div><span className="font-medium">Date:</span> {msg.date || msg.timestamp || "—"}</div>
              <div><span className="font-medium">Subject:</span> {msg.subject || "(no subject)"}</div>
            </div>
          )}

          {msg.attachments?.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {msg.attachments.map((a:Attachment, i:number)=>(
                <a
                  key={i}
                  href={apiUrl(`/messages/${encodeURIComponent(mailbox)}/${msg.uid || msg.id}/attachments/?filename=${encodeURIComponent(a.filename)}&part=${i}`)}
                  target="_blank"
                  rel="noopener"
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border bg-secondary/50 text-xs hover:bg-secondary"
                >
                  <Paperclip className="w-3.5 h-3.5" />
                  <span className="font-medium">{a.filename}</span>
                  <span className="text-muted-foreground">{a.mime} · {(a.size/1024).toFixed(1)} KB</span>
                  <Download className="w-3 h-3 ml-1" />
                </a>
              ))}
            </div>
          )}

          <div className={cn(rawHtml ? "pt-2" : "pt-1")}>
            {rawHtml ? (
              <HtmlBody html={rawHtml} />
            ) : (
              <div className="whitespace-pre-wrap text-[14px] leading-[1.6] font-sans text-foreground break-words px-1 py-1">
                {rawText || "—"}
              </div>
            )}
          </div>

          {msg.quotedMessages && msg.quotedMessages.length > 0 && (
            <div className="pt-1">
              <button
                onClick={()=> setShowQuoted(!showQuoted)}
                className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1.5"
              >
                {showQuoted ? <ChevronUp className="w-3 h-3"/> : <ChevronDown className="w-3 h-3"/>}
                {showQuoted ? "Hide quoted" : `▸ Show ${msg.quotedMessages.length} previous message${msg.quotedMessages.length>1?"s":""}`}
              </button>
              {showQuoted && (
                <div className="space-y-2">
                  {msg.quotedMessages.map((q:any, idx:number)=>(
                    <QuotedMessage key={q.id || idx} quoted={q} depth={q.quote_depth || 0} />
                  ))}
                </div>
              )}
            </div>
          )}

          {onReply && (
            <div className="flex gap-2 pt-2">
              <button onClick={()=>onReply(msg)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs hover:bg-accent"><Reply className="w-3.5 h-3.5"/> Reply</button>
              <button onClick={()=>onReply(msg)} className="text-xs text-muted-foreground hover:text-foreground">Forward</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function MessageView({ message, mailbox, onClose, onAction }: {
  message: any
  mailbox: string
  onClose?: ()=>void
  onAction: (action:string, data?:any)=>void
}) {
  const [showOlder, setShowOlder] = useState(false)
  if (!message) return <div className="flex items-center justify-center h-full text-sm text-muted-foreground p-8">Select a message</div>
  const threadMessages: any[] = message.messages || (message.thread?.messages) || []
  const hasThread = threadMessages.length > 1
  const conversation = message.conversation || message.thread?.conversation
  const displayMessages = hasThread ? threadMessages : [message]
  const newestIdx = displayMessages.length -1
  const visibleMessages = hasThread && displayMessages.length > 5 && !showOlder
    ? displayMessages.slice(-3)
    : displayMessages
  const hiddenCount = hasThread ? displayMessages.length - visibleMessages.length : 0

  return (
    <div className="flex flex-col h-full bg-background">
      <div className="flex items-center gap-1 px-3 py-2 border-b sticky top-0 bg-card z-10">
        <button onClick={()=>onAction("archive")} className="p-2 hover:bg-accent rounded-lg" title="Archive (e)"><Archive className="w-4 h-4" /></button>
        <button onClick={()=>onAction("delete")} className="p-2 hover:bg-accent rounded-lg" title="Delete (#)"><Trash2 className="w-4 h-4" /></button>
        <div className="w-px h-4 bg-border mx-1" />
        <button onClick={()=>onAction("read", {read: !message.read})} className="p-2 hover:bg-accent rounded-lg text-xs">{message.read ? "Mark unread" : "Mark read"}</button>
        <button onClick={()=>onAction("star", {starred: !message.starred})} className="p-2 hover:bg-accent rounded-lg"><Star className={`w-4 h-4 ${message.starred ? "fill-amber-500 text-amber-500" : ""}`} /></button>
        <div className="flex-1" />
        <button onClick={()=>onAction("reply")} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium hover:bg-accent"><Reply className="w-3.5 h-3.5" /> Reply</button>
        <button onClick={()=>onAction("replyAll")} className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium hover:bg-accent"><ReplyAll className="w-3.5 h-3.5" /> Reply all</button>
        <button onClick={()=>onAction("forward")} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-foreground text-background text-xs font-medium"><Forward className="w-3.5 h-3.5" /> Forward</button>
        {onClose && <button onClick={onClose} className="p-2 hover:bg-accent rounded-lg lg:hidden"><X className="w-4 h-4" /></button>}
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="p-4 space-y-3 max-w-3xl mx-auto w-full">
          <div className="px-1 py-2">
            <h2 className="text-base font-semibold leading-tight">{message.subject || conversation?.subject || "(no subject)"}</h2>
            {conversation?.participants && (
              <div className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                <Users className="w-3 h-3" /> {conversation.participants.length} participants · {displayMessages.length} messages
              </div>
            )}
          </div>

          {hasThread && hiddenCount > 0 && (
            <button
              onClick={()=> setShowOlder(true)}
              className="w-full py-2.5 rounded-xl border border-dashed text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              ▸ Show {hiddenCount} older message{hiddenCount>1?"s":""}
            </button>
          )}

          {visibleMessages.map((m:any, idx:number)=>{
            const globalIdx = hasThread ? displayMessages.indexOf(m) : 0
            const isNewest = globalIdx === newestIdx
            const defaultExpanded = isNewest || (hasThread ? globalIdx >= displayMessages.length-2 : true)
            return (
              <MessageCard
                key={m.uid || m.id || idx}
                msg={m}
                mailbox={mailbox}
                isExpandedDefault={defaultExpanded}
                isNewest={isNewest}
                onReply={(msg)=> onAction("reply", msg)}
              />
            )
          })}

          <details className="text-xs pt-2">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Show headers</summary>
            <div className="mt-2 font-mono bg-secondary rounded-lg p-3 break-all text-[11px] leading-relaxed">
              <div>Message-ID: {message.messageId || message.message_id}</div>
              <div>Date: {message.date || message.timestamp}</div>
              <div>From: {message.from?.map((f:any)=>`${f.name} <${f.email}>`).join(", ")}</div>
              <div>To: {message.to?.map((f:any)=>f.email).join(", ")}</div>
              {message.thread && <div>Thread: {message.thread.threadId}</div>}
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
