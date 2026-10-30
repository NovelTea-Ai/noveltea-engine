import { useEffect, useState } from 'react'
import useStore from '../../store/useStore'
import { api } from '../../api'

function Spinner({ size = 14 }) {
  return <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite', fontSize: size }}>⟳</span>
}

const logColor = { info: 'var(--text-secondary)', success: 'var(--green)', warn: 'var(--amber)', error: 'var(--red)' }

// Compact mode: collapse consecutive identical lines (e.g. one per retry
// attempt) into a single ×N line, so a slow multi-retry generation doesn't
// bury the meaningful step lines under a wall of duplicates. Raw mode shows
// every line untouched, exactly as the backend sent it.
function compactLines(lines) {
  const out = []
  for (const l of lines) {
    const prev = out[out.length - 1]
    if (prev && prev.msg === l.msg && prev.type === l.type) {
      prev.count = (prev.count || 1) + 1
      prev.t = l.t
      continue
    }
    out.push({ ...l, count: 1 })
  }
  return out
}

// The actual log body — traffic-light header + scrolling line list. Shared
// between the standalone floating console and the merged-into-a-popup strip,
// so both stay visually/behaviorally identical.
function ConsoleBody({ isNarrow, compact = false }) {
  const { consoleLines, consoleCompact, consoleRunning, consoleField, consoleAbortKey, toggleConsoleCompact, clearConsoleLines, closeConsole } = useStore()
  const [copied, setCopied] = useState(false)
  const [sent, setSent] = useState(false)
  const [sending, setSending] = useState(false)

  async function copyLog() {
    const text = consoleLines.map(l => `[${l.t}] ${l.msg}`).join('\n') || '(no activity yet)'
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Clipboard API can be blocked (no HTTPS/focus) — fall back to a hidden textarea + execCommand.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch {}
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  async function sendLog() {
    const ok = window.confirm('Send this console log to the workspace (debug_logs/) so it can be reviewed later?')
    if (!ok) return
    const text = consoleLines.map(l => `[${l.t}] ${l.msg}`).join('\n') || '(no activity yet)'
    setSending(true)
    try {
      const r = await api.aicoderSaveLog(text, consoleField || '')
      const { appendConsoleLine } = useStore.getState()
      appendConsoleLine(`📝 Log sent to workspace: ${r.path}`, 'success')
      setSent(true)
      setTimeout(() => setSent(false), 1800)
    } catch (e) {
      const { appendConsoleLine } = useStore.getState()
      appendConsoleLine(`✗ Send log failed: ${e.message}`, 'error')
    } finally {
      setSending(false)
    }
  }

  async function abort() {
    const { consoleField: field, consoleAbortKey: abortKey, consoleAbortFn: abortFn,
            appendConsoleLine, clearConsoleRunning, setConsoleAborted } = useStore.getState()
    if (!field && !abortKey) return
    setConsoleAborted(true)   // lets a batch loop (e.g. "AI Generate All") stop advancing to the next field
    appendConsoleLine(`⏹ Aborting "${field || consoleRunning}"…`, 'warn')
    try {
      // A caller with no project_id (e.g. Blueprint's paste-to-LLM extraction)
      // registers its OWN abort function via setConsoleRunningAbortable —
      // route to that instead of the project-scoped abandonGeneration, which
      // has no (project_id, field) key to match against for this kind of call.
      if (abortKey && abortFn) {
        const r = await abortFn(abortKey)
        appendConsoleLine(r?.killed ? '⏹ Aborted — call stopped.' : '⏹ Aborted — nothing was still running.', 'warn')
      } else {
        const r = await api.abandonGeneration(useStore.getState().activeProjectId, field)
        appendConsoleLine(r.process_killed ? '⏹ Aborted — generation stopped.' : '⏹ Aborted — you can retry now.', 'warn')
      }
    } catch (e) {
      appendConsoleLine(`Abort request failed: ${e.message}`, 'error')
    } finally {
      clearConsoleRunning()
    }
  }

  const lines = consoleCompact ? compactLines(consoleLines) : consoleLines.map(l => ({ ...l, count: 1 }))

  return (
    <>
      <div className="engine-console-bar" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '6px 12px',
        background: 'linear-gradient(90deg,#0b1220,#111a2e)', borderBottom: '1px solid rgba(56,189,248,0.25)' }}>
        {!isNarrow && !compact && <span style={{ display: 'flex', gap: 5 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ff5f57', display: 'inline-block' }} />
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#febc2e', display: 'inline-block' }} />
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#28c840', display: 'inline-block' }} />
        </span>}
        <span style={{ fontSize: isNarrow ? 11 : 12, fontWeight: 700, color: '#dceeff' }}>
          {isNarrow ? '' : 'Engine Console — '}{consoleRunning || 'idle'}
        </span>
        {consoleRunning && <Spinner size={11} />}
        <div style={{ flex: 1 }} />
        {consoleRunning && (consoleField || consoleAbortKey) && (
          <button onClick={abort} title="Kills the running LLM call and unblocks the UI" style={{
            fontSize: 11, fontWeight: 700, padding: '2px 11px', borderRadius: 6,
            color: '#fff', background: '#ef4444', border: '1px solid #ef4444', whiteSpace: 'nowrap',
          }}>⛔ Abort</button>
        )}
        <button onClick={toggleConsoleCompact} title="Compact collapses repeated consecutive lines (e.g. retry attempts) into one ×N line" style={{
          fontSize: 11, fontWeight: 600, padding: '2px 9px', borderRadius: 6,
          color: consoleCompact ? '#34d399' : '#9fd4ff',
          background: 'transparent', border: `1px solid ${consoleCompact ? 'rgba(52,211,153,0.4)' : 'rgba(127,208,255,0.35)'}`,
        }}>{consoleCompact ? 'Compact' : 'Raw'}</button>
        <button onClick={copyLog} title="Copy the full log to clipboard" style={{
          fontSize: 11, fontWeight: 600, padding: '2px 9px', borderRadius: 6,
          color: copied ? '#34d399' : '#7fd0ff',
          background: 'transparent', border: `1px solid ${copied ? 'rgba(52,211,153,0.4)' : 'rgba(127,208,255,0.35)'}`,
          whiteSpace: 'nowrap',
        }}>{copied ? '✓ Copied' : '⧉ Copy'}</button>
        <button onClick={sendLog} disabled={sending} title="Send the full log to the workspace (debug_logs/) so you can debug it later" style={{
          fontSize: 11, fontWeight: 600, padding: '2px 9px', borderRadius: 6,
          color: sent ? '#34d399' : '#7fd0ff',
          background: 'transparent', border: `1px solid ${sent ? 'rgba(52,211,153,0.4)' : 'rgba(127,208,255,0.35)'}`,
          whiteSpace: 'nowrap', opacity: sending ? 0.6 : 1,
        }}>{sent ? '✓ Sent' : (sending ? 'Sending…' : '📤 Send Log')}</button>
        {!consoleRunning && (
          <button onClick={clearConsoleLines} style={{
            fontSize: 11, fontWeight: 600, padding: '2px 11px', borderRadius: 6,
            color: '#7fd0ff', background: 'transparent', border: '1px solid rgba(127,208,255,0.35)',
          }}>Clear</button>
        )}
        {!compact && (
          <button onClick={closeConsole} style={{
            fontSize: 11, fontWeight: 600, padding: '2px 11px', borderRadius: 6,
            color: '#7fd0ff', background: 'transparent', border: '1px solid rgba(127,208,255,0.35)',
          }}>{consoleRunning ? 'Hide' : 'Close'}</button>
        )}
      </div>
      <div style={{
        height: compact ? 110 : (isNarrow ? 180 : 260), overflowY: 'auto', background: '#05070d', color: '#7fd0ff',
        padding: '10px 12px', fontFamily: 'Consolas, "SF Mono", monospace',
        fontSize: isNarrow ? 10.5 : 11.5, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      }}>
        {lines.map((l, i) => (
          <div key={i}>
            <span style={{ opacity: 0.5 }}>[{l.t}]</span> <span style={{ color: logColor[l.type] || '#7fd0ff' }}>{l.msg}</span>
            {l.count > 1 && <span style={{ opacity: 0.6, fontWeight: 700 }}> ×{l.count}</span>}
          </div>
        ))}
        {consoleRunning && <div style={{ color: '#5b7a99' }}>▊ working…</div>}
        {consoleLines.length === 0 && !consoleRunning && <div style={{ opacity: 0.5 }}>No activity yet.</div>}
      </div>
    </>
  )
}

// Standalone floating console — used when no interactive/wizard popup is
// open. Docked bottom-right so it doesn't cover page content the way a
// centered modal would; a running generation is still visible at a glance
// via the TitleBar toggle's badge even while this is closed. Renders
// nothing while any popup has EngineConsoleMerged mounted (consoleMergedCount
// > 0), so it never shows as a second overlay alongside a merged one.
export default function EngineConsole() {
  const consoleOpen = useStore(s => s.consoleOpen)
  const mergedElsewhere = useStore(s => s.consoleMergedCount > 0)
  const isNarrow = typeof window !== 'undefined' && window.innerWidth < 768
  if (!consoleOpen || mergedElsewhere) return null

  return (
    <div style={{
      position: 'fixed', zIndex: 250,
      right: isNarrow ? 10 : 20, left: isNarrow ? 10 : 'auto', bottom: isNarrow ? 10 : 20,
      width: isNarrow ? 'auto' : 460, maxWidth: '100%',
      border: '1px solid rgba(56,189,248,0.4)', borderRadius: 10, overflow: 'hidden',
      boxShadow: '0 6px 28px rgba(0,0,0,0.5)',
    }}>
      <ConsoleBody isNarrow={isNarrow} />
    </div>
  )
}

// Merged form — rendered INSIDE an already-open interactive/wizard popup's
// own card (which sits at zIndex 300, above this component's standalone
// zIndex 250) instead of floating as a second overlay. Callers should only
// render this when `consoleOpen` AND their own popup is open; check via
// useStore(s => s.consoleOpen) at the call site.
export function EngineConsoleMerged() {
  const isNarrow = typeof window !== 'undefined' && window.innerWidth < 768
  useEffect(() => {
    const { registerConsoleMerged, unregisterConsoleMerged } = useStore.getState()
    registerConsoleMerged()
    return unregisterConsoleMerged
  }, [])
  return (
    <div style={{
      marginTop: 4, border: '1px solid rgba(56,189,248,0.4)', borderRadius: 8, overflow: 'hidden',
    }}>
      <ConsoleBody isNarrow={isNarrow} compact />
    </div>
  )
}
