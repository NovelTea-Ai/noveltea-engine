import { useState } from 'react'

// Shown on the house-style gate's "keep it or try again" decision: exactly which
// rules the segment failed, what was measured, the offending text, and the draft
// itself — the popup used to show only rule names, so there was no way to see
// why a segment kept failing before deciding whether to keep it.
export default function GateFailureDetails({ reasons, preview }) {
  const [showDraft, setShowDraft] = useState(false)
  if (!reasons?.length && !preview) return null
  return (
    <div style={{
      border: '1px solid var(--amber)', borderRadius: 'var(--radius-sm)',
      background: 'rgba(245,158,11,0.07)', padding: '10px 12px',
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        Why it failed
      </div>
      {(reasons || []).map((r, i) => (
        <div key={i} style={{ fontSize: 11, lineHeight: 1.5 }}>
          <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{r.rule}</div>
          {r.detail && <div style={{ color: 'var(--text-secondary)' }}>{r.detail}</div>}
          {(r.examples || []).map((ex, j) => (
            <div key={j} style={{
              marginTop: 3, paddingLeft: 8, borderLeft: '2px solid var(--amber)',
              color: 'var(--text-muted)', fontStyle: 'italic',
            }}>“{ex}”</div>
          ))}
        </div>
      ))}
      {preview && (
        <div>
          <button onClick={() => setShowDraft(v => !v)} style={{ fontSize: 10, color: 'var(--accent-light)' }}>
            {showDraft ? '▲ Hide the failing draft' : '▼ Show the failing draft'}
          </button>
          {showDraft && (
            <div style={{
              marginTop: 6, maxHeight: 220, overflowY: 'auto', whiteSpace: 'pre-wrap',
              fontSize: 11, lineHeight: 1.6, color: 'var(--text-secondary)',
              background: 'var(--bg-base)', border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-sm)', padding: '8px 10px',
            }}>{preview}</div>
          )}
        </div>
      )}
    </div>
  )
}
