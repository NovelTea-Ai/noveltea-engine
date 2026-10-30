import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'

// Splits prose into paragraphs exactly the way the backend does (_paragraphs_of in generate.py:
// blank-line separated, trimmed; single newlines only if there are no blank lines) — the gate's
// per-paragraph marks are matched back to the page by position, so both sides must agree.
export function paragraphsOf(text) {
  const t = text || ''
  let paras = t.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean)
  if (paras.length <= 1 && t.includes('\n')) paras = t.split('\n').map(p => p.trim()).filter(Boolean)
  return paras
}

// The house-style gate's verdict on each part, per paragraph (POST /gate-report — pure Python, no AI
// call). Debounced; returns null until it arrives, so a stale report is never drawn over new text.
export function useGateReport(parts, enabled, earlier = [], ids = null, flagged = []) {
  const [report, setReport] = useState(null)
  const key = useMemo(() => JSON.stringify([parts || [], earlier, ids, flagged]), [parts, earlier, ids, flagged])
  useEffect(() => {
    if (!enabled || !parts?.length) { setReport(null); return }
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const r = await api.gateReport(parts, earlier, ids, flagged)
        if (!cancelled) setReport({ key, parts: r.parts || [] })
      } catch { if (!cancelled) setReport(null) }
    }, 350)
    return () => { cancelled = true; clearTimeout(t) }
  }, [key, enabled]) // eslint-disable-line react-hooks/exhaustive-deps
  return report && report.key === key ? report.parts : null
}

function Spinner({ size = 12 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, flexShrink: 0,
      border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    }} />
  )
}

// Flagged paragraphs are ORANGE (not red): a burnt orange for text so it stays readable on the white page,
// a brighter orange for the side bar, borders and the Fix button. The page sets --flag / --flag-text.
const FLAG = 'var(--flag, #ea580c)'
const FLAG_TEXT = 'var(--flag-text, #c2410c)'

// One part of the chapter, drawn as paragraphs. A paragraph the gate flagged is written in orange; click it
// to see which rules it breaks and send just that paragraph back through the gate. `mark` is the report
// entry for THIS text (or null); `fixable` is false for the draft that is still awaiting Keep / Try again
// (it isn't saved yet, so there is nothing on the server to patch).
import ElapsedTimer from '../shared/ElapsedTimer'

export default function PartView({ index, label, text, mark, fixable, fixingKey, fixMessage, onFix, onEdit, pending, latest, dropCap, reading = -1, onRewind, laterParts = 0 }) {
  const [open, setOpen] = useState(null)
  const [askRewind, setAskRewind] = useState(false)    // "Back to here" is two steps: it drops the later parts
  const [editing, setEditing] = useState(null)     // the paragraph being edited by hand
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')
  const local = useMemo(() => paragraphsOf(text), [text])
  // a fix or an edit can split a paragraph and shift the ones after it, so nothing stays open across a change of text
  useEffect(() => { setOpen(null); setEditing(null); setEditError('') }, [text])

  const startEdit = (i, p) => { setEditing(i); setDraft(p); setEditError('') }
  async function saveEdit(i, original) {
    if (!draft.trim() || saving) return
    setSaving(true); setEditError('')
    try { await onEdit(index, i, original, draft) }       // the text prop changes, which closes the editor
    catch (e) { setEditError(e.message || 'Could not save that') }
    finally { setSaving(false) }
  }
  // only trust the marks if they were computed for exactly these paragraphs
  const marks = mark && mark.paragraphs && mark.paragraphs.length === local.length
    && mark.paragraphs.every((p, i) => p.text === local[i]) ? mark.paragraphs : null
  const partLevel = mark?.part_failures || []
  const flagged = marks ? marks.filter(p => p.failures.length).length : 0

  return (
    <section className="ws-anim" style={{ marginBottom: 22, position: 'relative' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
        color: pending ? FLAG_TEXT : latest ? 'var(--amber)' : 'var(--text-muted)', fontFamily: 'var(--font-ui, system-ui, sans-serif)',
        marginBottom: 8, userSelect: 'none',
      }}>
        <span style={{ fontWeight: 700 }}>{label}</span>
        <span style={{ flex: 1, height: 1, background: 'var(--border-soft)' }} />
        {onRewind && !pending && (askRewind ? (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, textTransform: 'none', letterSpacing: 0, flexWrap: 'wrap' }}>
            <span style={{ color: FLAG_TEXT }}>Drop {laterParts} later part{laterParts === 1 ? '' : 's'}?</span>
            <button onClick={() => { setAskRewind(false); onRewind(index + 1) }}
              style={{ fontSize: 11, fontWeight: 700, padding: '2px 10px', minHeight: 26, borderRadius: 6, background: FLAG, color: '#fff', border: 'none' }}>Go back</button>
            <button onClick={() => setAskRewind(false)}
              style={{ fontSize: 11, padding: '2px 8px', minHeight: 26, borderRadius: 6, background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>Cancel</button>
          </span>
        ) : (
          <button onClick={() => setAskRewind(true)} title="Go back to this part: the question that followed it is asked again, and the parts after it are dropped (a backup is kept)"
            style={{ fontSize: 11, fontWeight: 600, padding: '2px 10px', minHeight: 26, borderRadius: 6, textTransform: 'none', letterSpacing: 0,
              background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)', cursor: 'pointer' }}>↩ Back to this part</button>
        ))}
        {flagged > 0 && <span style={{ color: FLAG_TEXT, fontWeight: 700 }}>{flagged} flagged</span>}
        {mark && mark.passed && !pending && <span style={{ color: 'var(--green)' }}>✓ gate</span>}
      </div>

      {partLevel.map((f, k) => (
        <div key={k} title={f.hint || ''} style={{
          fontSize: 11, fontFamily: 'var(--font-ui, system-ui, sans-serif)', color: FLAG_TEXT, lineHeight: 1.5,
          border: `1px dashed ${FLAG}`, borderRadius: 6, padding: '6px 10px', marginBottom: 10,
          background: 'rgba(234,88,12,0.06)',
        }}>
          <b>{f.rule}</b>{f.detail ? ` — ${f.detail}` : ''}
          <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>
            This rule is about the whole part (its rhythm), so it can't be fixed one paragraph at a time.
          </div>
        </div>
      ))}

      {local.map((p, i) => {
        const failures = marks ? marks[i].failures : []
        const bad = failures.length > 0
        const overBudget = failures.some(f => /word budget/i.test(f.rule))   // a segment kept over its budget: Fix = Shorten
        const key = `${index}:${i}`
        const isOpen = open === i && bad
        const fixing = fixingKey === key
        const msg = fixMessage && fixMessage.key === key ? fixMessage : null
        return (
          <div key={i}>
            <p className={dropCap && i === 0 && !bad && p.length > 60 ? 'ws-dropcap' : undefined}
              data-reading={reading === i ? 'true' : undefined}
              onClick={bad ? () => setOpen(isOpen ? null : i) : undefined}
              title={bad ? 'Flagged by the house-style gate — click to see why and fix it' : undefined}
              style={{
                margin: '0 0 0.85em', padding: bad ? '6px 10px' : '6px 0', borderRadius: 4,
                color: bad ? FLAG_TEXT : 'inherit',
                background: bad ? 'rgba(234,88,12,0.09)' : reading === i ? 'rgba(124,58,237,0.10)' : 'transparent',
                boxShadow: reading === i ? 'inset 0 0 0 2px rgba(124,58,237,0.38)' : 'none', transition: 'background 0.25s, box-shadow 0.25s',
                borderLeft: `3px solid ${bad ? FLAG : 'transparent'}`, cursor: bad ? 'pointer' : 'text',
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>{p}</p>
            {(isOpen || fixing || (msg && bad)) && (
              <div style={{
                margin: '-4px 0 14px', padding: '10px 12px', borderRadius: 8,
                border: `1px solid ${FLAG}`, background: 'var(--bg-elevated)', color: 'var(--text-primary)',
                fontFamily: 'var(--font-ui, system-ui, sans-serif)', fontSize: 12, lineHeight: 1.5,
              }}>
                {failures.map((f, k) => (
                  <div key={k} style={{ marginBottom: 6 }}>
                    <div style={{ fontWeight: 700, color: FLAG_TEXT }}>{f.rule}</div>
                    {f.detail && <div style={{ color: 'var(--text-secondary)' }}>{f.detail}</div>}
                    {f.hint && <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>{f.hint}</div>}
                  </div>
                ))}
                {msg && !msg.passed && (
                  <div style={{ color: FLAG_TEXT, marginBottom: 6 }}>
                    {msg.error ? `Couldn't fix it: ${msg.error}` : `Still fails the gate after ${msg.attempts} attempt${msg.attempts === 1 ? '' : 's'} — nothing was changed.`}
                  </div>
                )}
                {fixable && editing === i ? (
                  <div>
                    <textarea value={draft} onChange={e => setDraft(e.target.value)} autoFocus disabled={saving}
                      rows={Math.min(16, Math.max(4, Math.ceil(draft.length / 68)))}
                      aria-label="Edit this paragraph"
                      style={{
                        width: '100%', boxSizing: 'border-box', padding: '10px 12px', borderRadius: 8, resize: 'vertical',
                        border: `2px solid ${FLAG}`, background: '#ffffff', color: '#1f2937',
                        fontFamily: 'Georgia, "Times New Roman", serif', fontSize: 15, lineHeight: 1.7,
                      }} />
                    <div style={{ color: 'var(--text-muted)', fontSize: 11, margin: '4px 0 8px' }}>
                      Your wording is saved as you write it, then this passage is checked by the gate — the orange goes only if it passes.
                      A blank line starts a new paragraph.
                    </div>
                    {editError && <div style={{ color: FLAG_TEXT, marginBottom: 6 }}>{editError}</div>}
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <button onClick={() => saveEdit(i, p)} disabled={saving || !draft.trim()}
                        style={{
                          padding: '4px 12px', minHeight: 28, fontSize: 12, fontWeight: 700, borderRadius: 6,
                          background: FLAG, color: '#fff', border: 'none', opacity: !draft.trim() ? 0.5 : 1,
                        }}>{saving ? <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><ElapsedTimer /> Saving…</span> : 'Save & check'}</button>
                      <button onClick={() => { setEditing(null); setEditError('') }} disabled={saving}
                        style={{ fontSize: 12, padding: '4px 10px', minHeight: 28, borderRadius: 6, background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>Cancel</button>
                    </div>
                  </div>
                ) : fixable ? (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button onClick={() => onFix(index, i, p)} disabled={!!fixingKey}
                      title={overBudget ? 'Cut this whole segment to its word budget: same content, the other gate rules kept. If it fits, the orange goes.'
                        : 'Send only this paragraph, with the rules it broke, back through the gate. If it passes, the red goes.'}
                      style={{
                        padding: '4px 12px', minHeight: 28, fontSize: 12, fontWeight: 700, borderRadius: 6,
                        background: fixingKey ? 'var(--bg-base)' : FLAG, color: '#fff', border: 'none',
                        opacity: fixingKey && !fixing ? 0.5 : 1,
                      }}>{fixing ? <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><ElapsedTimer /> {overBudget ? 'Shortening…' : 'Fixing…'}</span> : (overBudget ? 'Shorten this segment' : 'Fix this paragraph')}</button>
                    {onEdit && (
                      <button onClick={() => startEdit(i, p)} disabled={!!fixingKey}
                        title="Rewrite it yourself — your edit is saved, then checked by the gate"
                        style={{
                          padding: '4px 12px', minHeight: 28, fontSize: 12, fontWeight: 700, borderRadius: 6,
                          background: 'transparent', color: FLAG_TEXT, border: `1px solid ${FLAG}`, opacity: fixingKey ? 0.5 : 1,
                        }}>✎ Edit by hand</button>
                    )}
                    <button onClick={() => setOpen(null)} style={{ fontSize: 11, color: 'var(--text-muted)', padding: '6px 8px' }}>Close</button>
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                    This draft isn't saved yet — choose <b>Keep it as written</b> or <b>Try rewriting again</b> in the interview. Once it's part of the chapter you can fix its paragraphs here.
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </section>
  )
}
