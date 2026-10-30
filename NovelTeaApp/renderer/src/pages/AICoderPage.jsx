import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api'

function Spinner({ size = 14 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size,
      border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    }} />
  )
}

const SESSION_KEY = 'nm-aicoder-session'

const ENGINE_NAMES = { nemotron: 'Nemotron', kimi: 'Kimi K3', ollama: 'Ollama', colibri: 'Colibrì' }

// This page's own engine picker: overrides the system Agent Engine for the Workspace
// Assistant only. Same colours as the top-bar dropdown.
const ASSISTANT_ENGINE_OPTIONS = [
  { id: 'kimi', label: 'Kimi K3', color: '#1783ff' },
  { id: 'nemotron', label: 'Nvidia', color: '#76b900' },
  { id: 'ollama', label: 'Ollama', color: '#0ea5e9' },
  { id: 'colibri', label: 'Colibrì (local, slow)', color: '#14b8a6' },
]

// Small stats line under each reply: how long the turn took, how many tokens came back, and the
// model's own speed (tokens over the time spent waiting on it — tool execution isn't counted).
function ResponseStats({ s }) {
  const n = s.estimated ? '~' : ''
  const parts = [
    `${s.seconds < 10 ? s.seconds.toFixed(1) : Math.round(s.seconds)} s`,
    `${n}${s.completion_tokens} tokens`,
    s.tokens_per_sec != null ? `${n}${s.tokens_per_sec} tok/s` : null,
    s.calls > 1 ? `${s.calls} model calls` : null,
  ].filter(Boolean)
  const tip = [
    s.model,
    `Total ${s.seconds}s, of which ${s.model_seconds}s waiting on the model`,
    s.prompt_tokens ? `${s.prompt_tokens} prompt tokens in, ${s.completion_tokens} tokens out` : null,
    s.estimated ? 'Token count estimated (~4 characters a token): this engine reported no usage' : null,
  ].filter(Boolean).join('\n')
  return (
    <div title={tip} style={{ alignSelf: 'flex-start', fontSize: 10, color: 'var(--text-muted)', padding: '0 4px', lineHeight: 1.3 }}>
      {parts.join(' · ')}
    </div>
  )
}

function AssistantEngineSelect({ status, setStatus, disabled }) {
  const [saving, setSaving] = useState(false)
  if (!status?.engine) return null
  const cur = ASSISTANT_ENGINE_OPTIONS.find(o => o.id === status.engine) || ASSISTANT_ENGINE_OPTIONS[1]
  async function onChange(e) {
    setSaving(true)
    try { setStatus(await api.aicoderSetEngine(e.target.value)) } catch {}
    finally { setSaving(false) }
  }
  return (
    <select value={status.engine} onChange={onChange} disabled={saving || disabled}
      title={`Engine for the Workspace Assistant only (overrides the top-bar engine)${status.model ? ' · ' + status.model : ''}`}
      style={{
        fontSize: 11, fontWeight: 700, padding: '3px 6px', borderRadius: 6, cursor: 'pointer',
        background: 'var(--bg-elevated)', border: `1px solid ${cur.color}`, color: cur.color,
      }}>
      {ASSISTANT_ENGINE_OPTIONS.map(o => {
        const avail = status.engines?.[o.id]?.available !== false
        return <option key={o.id} value={o.id} disabled={!avail}>{o.label}{avail ? '' : ' (not set up)'}</option>
      })}
    </select>
  )
}

// Rebuilds the frontend and the backend exe, then relaunches the app. The build runs as its
// own process (Build-NovelTea.ps1) because it has to stop this app to replace the exe, so
// the app goes offline for a few minutes; polling rides that out and reloads the page once
// the new version answers.
function BuildButton() {
  const [st, setSt] = useState(null)          // build_status.json + log tail
  const [confirm, setConfirm] = useState(false)
  const [open, setOpen] = useState(false)
  const btnRef = useRef(null)
  const narrow = typeof window !== 'undefined' && window.innerWidth < 900
  const [offline, setOffline] = useState(false)
  const [err, setErr] = useState('')
  const startedRef = useRef(null)              // the 'started' stamp of the build this page kicked off

  const poll = useCallback(() => {
    api.aicoderBuildStatus().then(s => {
      setOffline(false)
      setSt(s)
      // the relaunched app reports ok: load the new UI
      if (startedRef.current && s.state === 'ok' && s.started !== startedRef.current.before) {
        startedRef.current = null
        setTimeout(() => window.location.reload(), 1200)
      }
    }).catch(() => setOffline(true))
  }, [])

  useEffect(() => { poll() }, [poll])
  const running = st?.state === 'running' || (startedRef.current && st?.state !== 'failed')
  useEffect(() => {
    if (!running && !offline) return
    const t = setInterval(poll, 2000)
    return () => clearInterval(t)
  }, [running, offline, poll])

  async function start() {
    setConfirm(false); setErr('')
    startedRef.current = { before: st?.started }
    try { await api.aicoderBuild(); setOpen(true); poll() }
    catch (e) { startedRef.current = null; setErr(e.message || 'Could not start the build') }
  }

  const label = offline && startedRef.current ? 'Rebuilding… app restarting'
    : running ? (st?.step || 'Building…')
    : st?.state === 'failed' ? 'Build failed' : st?.state === 'ok' ? 'Build' : 'Build'
  const color = st?.state === 'failed' ? 'var(--red)' : running ? 'var(--accent)' : 'var(--text-secondary)'

  return (
    <div style={{ position: 'relative' }}>
      <button ref={btnRef} onClick={() => (running ? setOpen(o => !o) : setConfirm(c => !c))}
        title="Rebuild the frontend and the backend exe, then relaunch NovelTea Engine (also runnable on its own: Build-NovelTea.bat)"
        style={{
          fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 6, maxWidth: 260,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          color, background: 'transparent', border: `1px solid ${running ? 'var(--accent)' : 'var(--border)'}`,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>{running || (offline && startedRef.current) ? <Spinner size={10} /> : '🔨'} {label}</button>

      {(confirm || open || err) && (
        <>
          <div onClick={() => { setConfirm(false); setOpen(false); setErr('') }}
            style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
          <div style={{
            ...(narrow
              ? { position: 'fixed', left: 12, right: 12, top: (btnRef.current?.getBoundingClientRect().bottom || 90) + 6 }
              : { position: 'absolute', right: 0, top: '100%', marginTop: 6, width: 380, maxWidth: '90vw' }),
            zIndex: 41, background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 8, boxShadow: '0 8px 26px rgba(0,0,0,0.45)', padding: 10, fontSize: 11.5,
          }}>
            {confirm && !running && (
              <>
                <div style={{ color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 8 }}>
                  Rebuild the frontend and backend, then relaunch the app. NovelTea Engine goes offline
                  for a few minutes while the exe is rebuilt, which stops anything running in it
                  (generation, pipelines, chats). If the backend build fails, the previous version comes back.
                </div>
                <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                  <button onClick={() => setConfirm(false)} style={{ fontSize: 11, padding: '3px 10px', borderRadius: 6, background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>Cancel</button>
                  <button onClick={start} style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 6, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff' }}>Build &amp; relaunch</button>
                </div>
              </>
            )}
            {err && <div style={{ color: 'var(--red)', marginBottom: 6 }}>{err}</div>}
            {(open || (!confirm && st?.log?.length > 0)) && (
              <>
                <div style={{ fontWeight: 700, marginBottom: 4, color }}>
                  {offline && startedRef.current ? 'App restarting with the new build…' : (st?.step || st?.state)}
                </div>
                <pre style={{
                  margin: 0, maxHeight: 220, overflow: 'auto', fontSize: 10, lineHeight: 1.4,
                  background: 'var(--bg-elevated)', padding: 6, borderRadius: 6, whiteSpace: 'pre-wrap',
                  color: 'var(--text-secondary)',
                }}>{(st?.log || []).join('\n') || 'No build has run yet.'}</pre>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function getOrCreateSessionId() {
  try {
    let id = localStorage.getItem(SESSION_KEY)
    if (!id) {
      id = 'aic_' + Math.random().toString(36).slice(2) + Date.now().toString(36)
      localStorage.setItem(SESSION_KEY, id)
    }
    return id
  } catch {
    return 'aic_' + Math.random().toString(36).slice(2)
  }
}

const CHAT_HISTORY_KEY = 'nm-aicoder-history'      // legacy single-chat store
const CHATS_KEY = 'nm-aicoder-chats'               // all conversations
const ACTIVE_CHAT_KEY = 'nm-aicoder-active-chat'

/**
 * Conversation store. Previously the page kept ONE conversation and "+ New Chat"
 * deleted it outright, so nothing could be revisited. Chats are now a keyed
 * list: {id, title, sessionId, messages, updated}.
 */
function loadChats() {
  try {
    const raw = localStorage.getItem(CHATS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    }
    // One-time migration: keep whatever the old single-chat store held.
    const legacy = localStorage.getItem(CHAT_HISTORY_KEY)
    if (legacy) {
      const msgs = JSON.parse(legacy)
      if (Array.isArray(msgs) && msgs.length) {
        return [{
          id: 'chat_migrated',
          title: chatTitle(msgs),
          sessionId: null,
          messages: msgs,
          updated: Date.now(),
        }]
      }
    }
  } catch { /* fall through to empty */ }
  return []
}

function saveChats(chats) {
  try {
    // Cap both the number of chats and the messages per chat so localStorage
    // (~5MB) can't fill up and start throwing on every write.
    const trimmed = chats.slice(0, 50).map(c => ({ ...c, messages: (c.messages || []).slice(-200) }))
    localStorage.setItem(CHATS_KEY, JSON.stringify(trimmed))
  } catch { /* quota exceeded — keep the in-memory copy */ }
}

/** First user line, condensed, as the sidebar label. */
function chatTitle(msgs) {
  const first = (msgs || []).find(m => m.role === 'user')
  const t = (first?.text || '').trim().replace(/\s+/g, ' ')
  if (!t) return 'New chat'
  return t.length > 42 ? t.slice(0, 42) + '…' : t
}

function relTime(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/* ── File tree (right panel) — lazy-expand: each folder fetches its own
   children on first expand, rather than walking the whole workspace up front. */
function TreeNode({ entry, depth, onOpenFile }) {
  const [expanded, setExpanded] = useState(false)
  const [children, setChildren] = useState(null)
  const [loading, setLoading] = useState(false)

  async function toggle() {
    if (!entry.is_dir) { onOpenFile(entry.path); return }
    if (!expanded && children === null) {
      setLoading(true)
      try {
        const r = await api.aicoderTree(entry.path)
        setChildren(r.entries || [])
      } catch {
        setChildren([])
      } finally {
        setLoading(false)
      }
    }
    setExpanded(e => !e)
  }

  return (
    <div>
      <div
        onClick={toggle}
        style={{
          display: 'flex', alignItems: 'center', gap: 5,
          padding: '3px 6px', paddingLeft: 8 + depth * 14,
          fontSize: 12, cursor: 'pointer', borderRadius: 4,
          color: entry.is_dir ? 'var(--text-primary)' : 'var(--text-secondary)',
          whiteSpace: 'nowrap',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-elevated)'}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
      >
        <span style={{ width: 12, textAlign: 'center', flexShrink: 0 }}>
          {entry.is_dir ? (loading ? <Spinner size={9} /> : (expanded ? '▾' : '▸')) : ''}
        </span>
        <span style={{ flexShrink: 0 }}>{entry.is_dir ? '📁' : '📄'}</span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{entry.name}</span>
      </div>
      {entry.is_dir && expanded && children && children.map(c => (
        <TreeNode key={c.path} entry={c} depth={depth + 1} onOpenFile={onOpenFile} />
      ))}
    </div>
  )
}

function FileTreePanel({ onOpenFile }) {
  const [root, setRoot] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.aicoderTree('').then(r => setRoot(r.entries || [])).catch(e => setError(e.message))
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'hidden' }}>
      <div style={{
        padding: '10px 12px', borderBottom: '1px solid var(--border)',
        fontSize: 11, fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase',
        color: 'var(--text-secondary)',
      }}>
        Workspace Files
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '6px 4px' }}>
        {error && <div style={{ fontSize: 11, color: 'var(--red)', padding: 8 }}>{error}</div>}
        {!root && !error && <div style={{ padding: 10 }}><Spinner size={12} /></div>}
        {root && root.map(e => (
          <TreeNode key={e.path} entry={e} depth={0} onOpenFile={onOpenFile} />
        ))}
      </div>
    </div>
  )
}

function FilePreview({ path, onClose }) {
  const [text, setText] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setText(null); setError(null)
    api.aicoderFile(path).then(r => setText(r.text)).catch(e => setError(e.message))
  }, [path])

  return (
    <div style={{
      position: 'absolute', inset: 0, background: 'var(--bg-primary)', zIndex: 5,
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
        borderBottom: '1px solid var(--border)', flexShrink: 0,
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {path}
        </span>
        <div style={{ flex: 1 }} />
        <button onClick={onClose} style={{
          fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 6,
          color: 'var(--text-secondary)', background: 'transparent', border: '1px solid var(--border)',
        }}>✕ Close</button>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 12 }}>
        {error && <div style={{ fontSize: 12, color: 'var(--red)' }}>{error}</div>}
        {text === null && !error && <Spinner size={12} />}
        {text !== null && (
          <pre style={{
            margin: 0, fontSize: 12, fontFamily: 'ui-monospace, Consolas, monospace',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-primary)',
          }}>{text}</pre>
        )}
      </div>
    </div>
  )
}

// Icon + accent per tool, so a glance tells you what kind of work happened.
const TOOL_STYLE = {
  exec_bash_command: { icon: '❯', color: '#c084fc', label: 'bash' },
  read_file:         { icon: '📄', color: '#60a5fa', label: 'read' },
  write_file:        { icon: '✎', color: '#fbbf24', label: 'write' },
  edit_file:         { icon: '✎', color: '#fbbf24', label: 'edit' },
  grep_files:        { icon: '🔍', color: '#34d399', label: 'grep' },
  glob_files:        { icon: '🔍', color: '#34d399', label: 'glob' },
  list_files:        { icon: '📁', color: '#94a3b8', label: 'ls' },
}

const mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

/**
 * One tool call: the invocation line, plus its result. Expandable so bash
 * stdout/stderr and grep hits can be inspected without flooding the chat.
 */
function ToolStep({ call, result }) {
  const [open, setOpen] = useState(false)
  const name = call?.data?.tool || result?.data?.tool || 'tool'
  const st = TOOL_STYLE[name] || { icon: '•', color: 'var(--text-muted)', label: name }
  const d = result?.data || {}
  const failed = d.ok === false
  const hasDetail = !!(d.stdout || d.stderr || (d.matches || []).length || d.error)

  // Green added / red removed, like a diff summary.
  const added = d.added, removed = d.removed
  const showDiff = (name === 'edit_file' || name === 'write_file') && (added != null || removed != null)

  return (
    <div style={{ borderLeft: `2px solid ${failed ? 'var(--red)' : st.color}`, paddingLeft: 9, margin: '2px 0' }}>
      <div
        onClick={() => hasDetail && setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap',
          fontSize: 11.5, fontFamily: mono,
          cursor: hasDetail ? 'pointer' : 'default',
        }}>
        <span style={{ color: st.color, fontWeight: 700 }}>{st.icon} {st.label}</span>
        <span style={{ color: 'var(--text-secondary)', wordBreak: 'break-all' }}>
          {call?.data?.target || call?.msg || ''}
        </span>
        {showDiff && (
          <span style={{ fontWeight: 700 }}>
            <span style={{ color: '#22c55e' }}>+{added || 0}</span>
            {' '}
            <span style={{ color: '#ef4444' }}>-{removed || 0}</span>
          </span>
        )}
        {result && !showDiff && (
          <span style={{ color: failed ? 'var(--red)' : 'var(--text-muted)' }}>{result.msg}</span>
        )}
        {hasDetail && <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{open ? '▾' : '▸'}</span>}
      </div>

      {open && (
        <div style={{
          marginTop: 4, padding: '6px 8px', borderRadius: 6,
          background: 'var(--bg-surface)', border: '1px solid var(--border-soft)',
          fontFamily: mono, fontSize: 11, maxHeight: 280, overflow: 'auto',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {d.error && <div style={{ color: 'var(--red)' }}>{d.error}</div>}
          {d.stdout && <div style={{ color: 'var(--text-primary)' }}>{d.stdout}</div>}
          {d.stderr && <div style={{ color: '#f59e0b' }}>{d.stderr}</div>}
          {(d.matches || []).map((m, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)' }}>
              {m.file ? `${m.file}:${m.line}: ${m.text}` : (m.path || JSON.stringify(m))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Pairs each "tool" entry with its "tool_result" and renders them in order. */
function ToolTranscript({ steps, live }) {
  const pairs = []
  for (let i = 0; i < steps.length; i++) {
    const e = steps[i]
    if (e.kind !== 'tool') continue
    const next = steps[i + 1]
    pairs.push({ call: e, result: next?.kind === 'tool_result' ? next : null })
  }
  if (!pairs.length) return null

  return (
    <div style={{
      alignSelf: 'flex-start', maxWidth: '95%', width: '100%',
      background: 'var(--bg-card)', border: '1px solid var(--border-soft)',
      borderRadius: 8, padding: '7px 10px',
    }}>
      <div style={{
        fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
        color: 'var(--text-muted)', marginBottom: 4,
      }}>
        {live ? 'Working' : `${pairs.length} tool call${pairs.length === 1 ? '' : 's'}`}
      </div>
      {pairs.map((p, i) => <ToolStep key={i} call={p.call} result={p.result} />)}
    </div>
  )
}

export default function AICoderPage() {
  // Conversations. Each chat carries its own backend session id, so switching
  // chats switches the agent's server-side context too — without that, a new
  // chat would inherit the previous conversation's memory.
  const [chats, setChats] = useState(loadChats)
  const [activeId, setActiveId] = useState(() => {
    try {
      const saved = localStorage.getItem(ACTIVE_CHAT_KEY)
      if (saved) return saved
    } catch {}
    const first = loadChats()[0]
    return first ? first.id : null
  })
  const [historyOpen, setHistoryOpen] = useState(false)

  const activeChat = chats.find(c => c.id === activeId) || null
  const sessionIdRef = useRef(activeChat?.sessionId || getOrCreateSessionId())

  const [status, setStatus] = useState(null)
  const [messages, setMessages] = useState(() => activeChat?.messages || [])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const histBtnRef = useRef(null)
  const [previewPath, setPreviewPath] = useState(null)
  const [progressLine, setProgressLine] = useState('')
  // Tool activity for the turn currently running. Flushed into the assistant
  // message when the turn completes, so past turns keep their transcript.
  const [steps, setSteps] = useState([])
  const scrollRef = useRef(null)
  const isNarrow = typeof window !== 'undefined' && window.innerWidth < 900

  useEffect(() => {
    api.aicoderStatus().then(setStatus).catch(() => setStatus({ workspace_available: false, cli_ready: false }))
  }, [])

  // Persist the live message list into whichever chat is active. A chat row is
  // created lazily on the first message, so an untouched "New chat" never
  // clutters the history list.
  useEffect(() => {
    if (!messages.length) return
    setChats(prev => {
      const id = activeId || ('chat_' + Date.now().toString(36))
      const idx = prev.findIndex(c => c.id === id)
      const row = {
        id,
        title: chatTitle(messages),
        sessionId: sessionIdRef.current,
        messages,
        updated: Date.now(),
      }
      const next = idx >= 0
        ? [row, ...prev.filter(c => c.id !== id)]        // bump to most-recent
        : [row, ...prev]
      saveChats(next)
      if (!activeId) {
        setActiveId(id)
        try { localStorage.setItem(ACTIVE_CHAT_KEY, id) } catch {}
      }
      return next
    })
  }, [messages, activeId])

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, busy])

  // Live activity while a turn runs. Every entry is kept (not just the latest)
  // so the chat shows the full tool transcript — what was called, what came
  // back — the way an IDE agent panel does. `since` is tracked so each poll
  // only fetches new entries.
  useEffect(() => {
    if (!busy) { setProgressLine(''); return }
    let stopped = false
    let since = -1
    const tick = async () => {
      try {
        const r = await api.aicoderProgress(sessionIdRef.current, since)
        const entries = r?.entries || []
        if (stopped || !entries.length) return
        since = entries[entries.length - 1].i
        setSteps(prev => [...prev, ...entries])
        const last = entries[entries.length - 1]
        if (last.kind !== 'tool_result') setProgressLine(last.msg)
      } catch { /* quiet */ }
    }
    const iv = setInterval(tick, 500)
    tick()
    return () => { stopped = true; clearInterval(iv) }
  }, [busy])

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setMessages(m => [...m, { role: 'user', text }])
    setSteps([])            // fresh transcript for this turn
    setBusy(true)
    let collected = []
    try {
      const r = await api.aicoderChat(sessionIdRef.current, text)
      // Final poll: the turn can finish between ticks, so grab anything the
      // 500ms poller hasn't seen yet before the transcript is frozen.
      try {
        const p = await api.aicoderProgress(sessionIdRef.current, -1)
        collected = p?.entries || []
      } catch { /* fall back to whatever the poller captured */ }
      setSteps(prev => {
        const final = collected.length ? collected : prev
        setMessages(m => [...m, {
          role: 'assistant',
          text: r.reply || '(no response)',
          stats: r.stats || null,
          steps: final.filter(e => e.kind === 'tool' || e.kind === 'tool_result'),
        }])
        return []
      })
    } catch (e) {
      const msg = (e.message || 'Request failed').includes('499')
        ? 'Aborted.'
        : e.message || 'Request failed'
      setMessages(m => [...m, { role: 'error', text: msg, steps }])
      setSteps([])
    } finally {
      setBusy(false)
    }
  }, [input, busy, steps])

  async function abort() {
    try { await api.aicoderAbort(sessionIdRef.current) } catch {}
  }

  /** Start a fresh conversation. The previous one is KEPT in history. */
  async function newChat() {
    if (busy) await abort()
    // A brand-new backend session, so the agent doesn't carry over context
    // from the chat we're leaving.
    const sid = 'aic_' + Math.random().toString(36).slice(2) + Date.now().toString(36)
    sessionIdRef.current = sid
    try { localStorage.setItem(SESSION_KEY, sid) } catch {}
    setActiveId(null)          // the next message lazily creates the chat row
    try { localStorage.removeItem(ACTIVE_CHAT_KEY) } catch {}
    setMessages([])
    setSteps([])
    setHistoryOpen(false)
  }

  /** Reopen an earlier conversation, restoring its server-side session too. */
  async function openChat(id) {
    if (busy) await abort()
    const c = chats.find(x => x.id === id)
    if (!c) return
    sessionIdRef.current = c.sessionId || ('aic_' + Math.random().toString(36).slice(2))
    try {
      localStorage.setItem(SESSION_KEY, sessionIdRef.current)
      localStorage.setItem(ACTIVE_CHAT_KEY, id)
    } catch {}
    setActiveId(id)
    setMessages(c.messages || [])
    setSteps([])
    setHistoryOpen(false)
  }

  function deleteChat(id, e) {
    e?.stopPropagation()
    setChats(prev => {
      const next = prev.filter(c => c.id !== id)
      saveChats(next)
      return next
    })
    if (id === activeId) {
      setActiveId(null)
      setMessages([])
      try { localStorage.removeItem(ACTIVE_CHAT_KEY) } catch {}
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  if (status && !status.workspace_available) {
    return (
      <div style={{ padding: 30, maxWidth: 560 }}>
        <h2 style={{ margin: '0 0 8px' }}>Workspace Assistant</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
          Not available — this NovelTea Engine install isn't running from inside its own source
          checkout, so there's no workspace root to read or edit. This feature only works when
          run from the NovelTeaOS project folder.
        </p>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: isNarrow ? 'column' : 'row', height: '100%', minHeight: 0, overflow: 'hidden' }}>
      {/* ── Chat (left) ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, borderRight: isNarrow ? 'none' : '1px solid var(--border)' }}>
        <div style={{
          display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: isNarrow ? '8px 8px' : '6px 10px',
          padding: isNarrow ? '8px 12px' : '10px 16px', minWidth: 0,
          borderBottom: '1px solid var(--border)', flexShrink: 0,
        }}>
          <span style={{ fontSize: 13, fontWeight: 700, flexShrink: 0 }}>Workspace Assistant</span>
          <AssistantEngineSelect status={status} setStatus={setStatus} disabled={busy} />
          {status?.model && !isNarrow && (
            <span title={status.model} style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{status.model}</span>
          )}
          {status && !status.cli_ready && (
            <span style={{ fontSize: 11, color: 'var(--red)', flexBasis: isNarrow ? '100%' : undefined, minWidth: 0 }}>
              {status.note || 'Engine not configured'} — see Settings → CLI Accounts
            </span>
          )}
          <div style={{ flex: 1, minWidth: 0 }} />

          {/* the three action buttons stay together: right-aligned on desktop, their own row on a phone */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
            flexBasis: isNarrow ? '100%' : undefined, justifyContent: isNarrow ? 'flex-start' : 'flex-end',
          }}>
          <BuildButton />

          {/* History — earlier conversations are kept, not discarded on New Chat */}
          <div style={{ position: 'relative' }}>
            <button onClick={() => setHistoryOpen(o => !o)}
              title="Previous conversations"
              ref={histBtnRef}
              style={{
                fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 6,
                color: 'var(--text-secondary)', background: 'transparent',
                border: '1px solid var(--border)',
              }}>🕘 History{chats.length ? ` (${chats.length})` : ''}</button>

            {historyOpen && (
              <>
                {/* click-away backdrop */}
                <div onClick={() => setHistoryOpen(false)}
                  style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
                <div style={{
                  ...(isNarrow
                    ? { position: 'fixed', left: 12, right: 12, top: (histBtnRef.current?.getBoundingClientRect().bottom || 90) + 6, maxHeight: '60vh' }
                    : { position: 'absolute', right: 0, top: '100%', marginTop: 6, width: 300, maxHeight: 380 }),
                  zIndex: 41, overflowY: 'auto',
                  background: 'var(--bg-card)', border: '1px solid var(--border)',
                  borderRadius: 8, boxShadow: '0 8px 26px rgba(0,0,0,0.45)', padding: 5,
                }}>
                  {chats.length === 0 ? (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '10px 8px' }}>
                      No previous chats yet.
                    </div>
                  ) : chats.map(c => (
                    <div key={c.id} onClick={() => openChat(c.id)} style={{
                      display: 'flex', alignItems: 'center', gap: 6, padding: '7px 8px',
                      borderRadius: 6, cursor: 'pointer',
                      background: c.id === activeId ? 'var(--bg-elevated)' : 'transparent',
                      border: `1px solid ${c.id === activeId ? 'var(--accent)' : 'transparent'}`,
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 12, color: 'var(--text-primary)',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>{c.title || 'Untitled'}</div>
                        <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                          {(c.messages || []).length} msg · {relTime(c.updated)}
                        </div>
                      </div>
                      <button onClick={e => deleteChat(c.id, e)} title="Delete this chat"
                        style={{
                          fontSize: 12, lineHeight: 1, padding: '2px 5px', borderRadius: 4,
                          background: 'transparent', border: 'none', color: 'var(--text-muted)',
                        }}>✕</button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          <button onClick={newChat} title="Start a fresh conversation (the current one is saved to History)" style={{
            fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 6,
            color: 'var(--text-secondary)', background: 'transparent', border: '1px solid var(--border)',
          }}>+ New Chat</button>
          </div>
        </div>

        <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {messages.length === 0 && (
            <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 20 }}>
              Ask for anything — read a file, make a change, run a build, explain some code.
              Runs on the {ENGINE_NAMES[status?.engine] || 'Nemotron'} agent (the Agent Engine picked in Settings), with grep,
              glob, read, edit, write and allowlisted bash across the whole workspace.
              Every tool call is shown inline; click one to see its output.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} style={{
              alignSelf: m.role === 'user' ? 'flex-end' : 'stretch',
              maxWidth: m.role === 'user' ? '85%' : '100%',
              display: 'flex', flexDirection: 'column', gap: 6,
            }}>
              {/* Tool transcript for this turn, above the reply that used it */}
              {m.role !== 'user' && m.steps?.length > 0 && <ToolTranscript steps={m.steps} />}
              <div style={{
                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: m.role === 'user' ? '100%' : '85%',
                background: m.role === 'user' ? 'var(--accent)' : m.role === 'error' ? 'rgba(239,68,68,0.12)' : 'var(--bg-elevated)',
                color: m.role === 'user' ? '#fff' : m.role === 'error' ? 'var(--red)' : 'var(--text-primary)',
                border: m.role === 'assistant' ? '1px solid var(--border)' : 'none',
                borderRadius: 10, padding: '9px 13px', fontSize: 13, lineHeight: 1.55,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {m.text}
              </div>
              {m.role === 'assistant' && m.stats && <ResponseStats s={m.stats} />}
            </div>
          ))}
          {/* Live transcript for the turn in flight */}
          {busy && steps.length > 0 && <ToolTranscript steps={steps.filter(e => e.kind === 'tool' || e.kind === 'tool_result')} live />}
          {busy && (
            <div style={{
              alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: 8,
              fontSize: 12, color: 'var(--text-secondary)', padding: '6px 4px',
            }}>
              <Spinner size={12} />
              <span>{progressLine || `${ENGINE_NAMES[status?.engine] || 'The assistant'} is working…`}</span>
              <button onClick={abort} style={{
                marginLeft: 6, fontSize: 11, fontWeight: 700, padding: '2px 9px', borderRadius: 6,
                color: '#fff', background: '#ef4444', border: '1px solid #ef4444',
              }}>⛔ Abort</button>
            </div>
          )}
        </div>

        <div style={{ padding: 12, borderTop: '1px solid var(--border)', flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Message the Workspace Assistant… (Enter to send, Shift+Enter for newline)"
              rows={2}
              disabled={busy || (status && !status.cli_ready)}
              style={{
                flex: 1, minWidth: 0, resize: 'vertical', minHeight: 40, maxHeight: 200,
                padding: '9px 11px', borderRadius: 8, border: '1px solid var(--border)',
                background: 'var(--bg-elevated)', color: 'var(--text-primary)',
                fontSize: 13, fontFamily: 'inherit', lineHeight: 1.5,
              }}
            />
            <button
              onClick={send}
              disabled={busy || !input.trim() || (status && !status.cli_ready)}
              style={{
                padding: '9px 16px', borderRadius: 8, fontSize: 13, fontWeight: 700,
                color: '#fff', background: 'var(--accent)', border: 'none',
                opacity: (busy || !input.trim()) ? 0.5 : 1,
                cursor: (busy || !input.trim()) ? 'default' : 'pointer',
              }}
            >Send</button>
          </div>
        </div>
      </div>

      {/* ── File tree (right) ── */}
      <div style={{
        width: isNarrow ? '100%' : 320, flexShrink: 0, position: 'relative',
        height: isNarrow ? 280 : '100%', borderTop: isNarrow ? '1px solid var(--border)' : 'none',
      }}>
        <FileTreePanel onOpenFile={setPreviewPath} />
        {previewPath && <FilePreview path={previewPath} onClose={() => setPreviewPath(null)} />}
      </div>
    </div>
  )
}
