import { useEffect, useState } from 'react'
import { api } from '../../api'
import useNarrowLayout from '../../hooks/useNarrowLayout'
import { FieldSurveyButton, Panel, PanelTitle, Spinner } from '../shared/projectUi'
import { ARRAY_FIELDS, ENGINE_FIELDS, LONG_FIELDS, SYSTEM_ENGINES } from './systemEngines'
import { WorldTab } from './WorldTab'

/* ── AI generate button ── */
export function AIGenBtn({ label, field, projectId, corpusCount = 3, onDone, small = false, grepMode = null }) {
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState(null)

  async function run() {
    setRunning(true)
    setErr(null)
    try {
      const res = await api.generateField(projectId, field, corpusCount, null, null, grepMode || window.__nmGrep || null)
      if (onDone) onDone(res)
    } catch (e) {
      const msg = e.message || 'Generation failed'
      if (msg.includes('No API key')) {
        setErr('No API key — add one in Settings.')
      } else {
        setErr(msg.slice(0, 80))
      }
    } finally {
      setRunning(false)
    }
  }

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
      <button onClick={run} disabled={running} style={{
        display: 'flex', alignItems: 'center', gap: 5,
        padding: small ? '3px 10px' : '5px 13px',
        fontSize: small ? 10 : 11, fontWeight: 600,
        background: 'linear-gradient(135deg, var(--accent), #06b6d4)',
        color: '#fff', borderRadius: 'var(--radius-sm)',
        opacity: running ? 0.7 : 1,
        boxShadow: running ? 'none' : '0 0 12px rgba(124,58,237,0.3)',
        transition: 'all 0.15s',
      }}>
        {running ? <Spinner size={11} /> : <span style={{ fontSize: 10 }}>✦</span>}
        {running ? 'Generating…' : label}
      </button>
      {err && <div style={{ fontSize: 9, color: 'var(--red)', maxWidth: 200, textAlign: 'right' }}>{err}</div>}
    </div>
  )
}

export const SYSTEMS_FIELDS = new Set(['power_levels','techniques','weapons','alchemy','arrays','artifact_forging','treasures_materials','wars','relationships','encounters'])

export const PLANNING_FIELDS = new Set(['world','arcs','characters','chapter_skeleton','premise','tagline','themes'])

export function AIUpdateBtn({ field, projectId, onDone, small = false }) {
  const [running, setRunning] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const [err, setErr] = useState(null)
  const [canUndo, setCanUndo] = useState(false)

  // Check on mount whether a prior update can be rolled back
  useEffect(() => {
    let alive = true
    api.undoStatus(projectId)
      .then(r => { if (alive) setCanUndo((r.undoable?.[field] || 0) > 0) })
      .catch(() => {})
    return () => { alive = false }
  }, [projectId, field])

  async function run() {
    setRunning(true)
    setErr(null)
    try {
      // Systems and planning fields can update without chapters (cross-system awareness is in the prompt)
      const noChaptersOk = SYSTEMS_FIELDS.has(field) || PLANNING_FIELDS.has(field) || field.startsWith('custom_')
      let summaries = null
      try {
        const r = await api.getChapterSummaries(projectId)
        summaries = r.summaries && r.summaries.length > 0 ? r.summaries : null
      } catch (_) { /* no summaries available */ }

      if (!summaries && !noChaptersOk) {
        setErr('No chapters written yet — write some chapters first.')
        return
      }
      const res = await api.generateField(projectId, field, 3, null, summaries, window.__nmGrep || null)
      setCanUndo(res.can_undo !== false)
      if (onDone) onDone(res)
    } catch (e) {
      const msg = e.message || 'Update failed'
      if (msg.includes('No API key')) {
        setErr('No API key — add one in Settings.')
      } else {
        setErr(msg.slice(0, 80))
      }
    } finally {
      setRunning(false)
    }
  }

  async function undo() {
    setUndoing(true)
    setErr(null)
    try {
      const res = await api.undoField(projectId, field)
      setCanUndo(res.can_undo === true)
      if (onDone) onDone({ field, result: null, undone: true })
    } catch (e) {
      setErr((e.message || 'Undo failed').slice(0, 80))
    } finally {
      setUndoing(false)
    }
  }

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {canUndo && (
          <button onClick={undo} disabled={running || undoing} title="Undo the last AI update — restore the previous version" style={{
            display: 'flex', alignItems: 'center', gap: 4,
            padding: small ? '3px 9px' : '5px 11px',
            fontSize: small ? 10 : 11, fontWeight: 600,
            background: 'var(--bg-elevated)', color: 'var(--text-muted)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            opacity: undoing ? 0.7 : 1, transition: 'all 0.15s',
          }}>
            {undoing ? <Spinner size={11} /> : <span style={{ fontSize: 11 }}>⤺</span>}
            {undoing ? 'Undoing…' : 'Undo'}
          </button>
        )}
        <button onClick={run} disabled={running || undoing} title="Update this section using all Systems data, written chapters, and corpus" style={{
          display: 'flex', alignItems: 'center', gap: 5,
          padding: small ? '3px 10px' : '5px 13px',
          fontSize: small ? 10 : 11, fontWeight: 600,
          background: 'linear-gradient(135deg, #059669, #0891b2)',
          color: '#fff', borderRadius: 'var(--radius-sm)',
          opacity: running ? 0.7 : 1,
          boxShadow: running ? 'none' : '0 0 12px rgba(5,150,105,0.3)',
          transition: 'all 0.15s',
        }}>
          {running ? <Spinner size={11} /> : <span style={{ fontSize: 11 }}>↻</span>}
          {running ? 'Updating…' : 'Update with AI'}
        </button>
      </div>
      {err && <div style={{ fontSize: 9, color: 'var(--red)', maxWidth: 220, textAlign: 'right' }}>{err}</div>}
    </div>
  )
}

// Paste-and-generate box for the Systems tab: the author pastes freeform
// notes/content for ONE system (power levels, techniques, whatever engine is
// active) and this does a single one-shot generate treating that pasted text
// as the highest-priority basis — not just extra inspiration alongside
// corpus/Blueprint search, but the actual content to build from. Collapsed
// by default (small toggle) since most systems get built via Interactive/
// Generate, not paste — this is for when the author already has real
// material (notes, a doc, a chat draft) to seed a system from directly.
export function PasteGenerateBox({ field, label, projectId, onDone, small = false }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState(null)

  async function run() {
    if (!text.trim() || running) return
    setRunning(true)
    setErr(null)
    try {
      const res = await api.generateField(projectId, field, 3, null, null, window.__nmGrep || null, text.trim())
      if (onDone) onDone(res)
      setText('')
      setOpen(false)
    } catch (e) {
      const msg = e.message || 'Generation failed'
      setErr(msg.includes('No API key') ? 'No API key — add one in Settings.' : msg.slice(0, 100))
    } finally {
      setRunning(false)
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} title={`Paste your own content for ${label} and generate from it directly`} style={{
        fontSize: small ? 10 : 11, fontWeight: 600, padding: small ? '3px 10px' : '5px 13px',
        borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)',
        color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 5,
      }}>📋 Paste & Generate</button>
    )
  }

  return (
    <div style={{
      width: '100%', display: 'flex', flexDirection: 'column', gap: 6, padding: 10,
      background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        📋 Paste content for {label} — one-shot generate from this
      </div>
      <textarea value={text} onChange={e => setText(e.target.value)} rows={6} disabled={running}
        placeholder={`Paste notes, a draft, or any content describing ${label} — the AI will build the ${label} system directly from this (still checked against Blueprint/world consistency), instead of inventing it from scratch.`}
        style={{ padding: '8px 10px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical', fontFamily: 'inherit' }} />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={run} disabled={!text.trim() || running} style={{
          fontSize: 11, fontWeight: 700, padding: '6px 14px', borderRadius: 'var(--radius-sm)',
          background: text.trim() ? 'linear-gradient(135deg, var(--accent), #06b6d4)' : 'var(--bg-card)',
          color: text.trim() ? '#fff' : 'var(--text-muted)', border: 'none',
          display: 'flex', alignItems: 'center', gap: 5, opacity: running ? 0.7 : 1,
        }}>{running ? <Spinner size={11} /> : '✦'} {running ? 'Generating…' : 'Generate'}</button>
        <button onClick={() => { setOpen(false); setErr(null) }} disabled={running}
          style={{ fontSize: 10, color: 'var(--text-muted)' }}>Cancel</button>
        {err && <div style={{ fontSize: 9, color: 'var(--red)' }}>{err}</div>}
      </div>
    </div>
  )
}

export const CUSTOM_COLORS = ['#06b6d4','#a855f7','#f59e0b','#10b981','#ec4899','#3b82f6','#f97316','#ef4444','#14b8a6','#8b5cf6','#0ea5e9','#84cc16']

export const CUSTOM_ICONS  = ['✦','🌀','💠','🔮','🌊','🌪','🔥','❄','⚡','🌑','🗡','🛡','👁','🌿','💀','🎭','🌌','🔑','🌠','🧿','🪐','🌋']

export function NewEngineModal({ onConfirm, onClose }) {
  const [label, setLabel] = useState('')
  const [desc,  setDesc]  = useState('')
  const [icon,  setIcon]  = useState('✦')
  const [color, setColor] = useState('#06b6d4')
  const [itemLabel, setItemLabel] = useState('')
  const [fieldStr, setFieldStr] = useState('name, type, description, effect')

  function confirm() {
    if (!label.trim()) return
    const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
    const key = `custom_${slug}_${Date.now().toString(36)}`
    const fields = fieldStr.split(',').map(s => s.trim().toLowerCase().replace(/\s+/g,'_')).filter(Boolean)
    onConfirm({ key, label: label.trim(), desc: desc.trim(), icon, color, listLabel: (itemLabel.trim() || 'Entries'), fields })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 24, width: 420, maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>New Custom Engine</div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Engine Name *</div>
          <input value={label} onChange={e => setLabel(e.target.value)} placeholder="e.g. Dimensional Rifts & Portals"
            style={{ width: '100%', padding: '6px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)' }} />
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Description</div>
          <textarea value={desc} onChange={e => setDesc(e.target.value)} placeholder="What this engine covers…" rows={2}
            style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Item/Entry Label (plural)</div>
          <input value={itemLabel} onChange={e => setItemLabel(e.target.value)} placeholder="e.g. Portals, Rifts, Phenomena"
            style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>Fields (comma-separated — these become the edit form columns)</div>
          <textarea value={fieldStr} onChange={e => setFieldStr(e.target.value)} rows={2}
            style={{ width: '100%', padding: '6px 10px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical', fontFamily: 'monospace' }} />
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 3 }}>e.g. name, type, location, danger_level, description, effect, conditions, rewards</div>
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>Icon</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {CUSTOM_ICONS.map(ic => (
              <button key={ic} onClick={() => setIcon(ic)} style={{
                fontSize: 16, padding: '3px 6px', borderRadius: 6,
                background: icon === ic ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                border: icon === ic ? '1px solid var(--accent)' : '1px solid var(--border)',
              }}>{ic}</button>
            ))}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>Colour</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {CUSTOM_COLORS.map(c => (
              <button key={c} onClick={() => setColor(c)} style={{
                width: 24, height: 24, borderRadius: '50%', background: c,
                border: color === c ? '2px solid #fff' : '2px solid transparent',
                outline: color === c ? `2px solid ${c}` : 'none',
              }} />
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          <button onClick={confirm} disabled={!label.trim()} className="btn-primary" style={{ flex: 1, padding: '8px', fontSize: 12, fontWeight: 700 }}>
            ✦ Create Engine
          </button>
          <button onClick={onClose} className="btn-ghost" style={{ padding: '7px 16px', fontSize: 12 }}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

// Character picker for a new character-linked power system — see
// SystemsTab's "character_power_systems" handling. Doesn't write anything to
// project.json itself (there's nothing to save until a generation actually
// runs); just tells the caller which character name to point the new engine
// view at, same as picking any other engine in the sidebar.
export function NewCharPowerModal({ characters, existingNames, onConfirm, onClose }) {
  const available = characters.filter(c => c.name && !existingNames.includes(c.name))
  const [selected, setSelected] = useState(available[0]?.name || '')

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 24, width: 380, maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>New Character Power System</div>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Pick a character whose power works differently from the world's standard system — e.g. the protagonist's
          own variant awakening. Their progression stays cross-referenced against the world system, but tracked separately.
        </div>
        {available.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '10px 0' }}>
            {characters.length === 0
              ? 'No characters yet — add or generate the cast first.'
              : 'Every character already has their own power system.'}
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Character *</div>
            <select value={selected} onChange={e => setSelected(e.target.value)}
              style={{ width: '100%', padding: '7px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
              {available.map(c => <option key={c.name} value={c.name}>{c.name}{c.role ? ` (${c.role})` : ''}</option>)}
            </select>
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          <button onClick={() => selected && onConfirm(selected)} disabled={!selected} className="btn-primary" style={{ flex: 1, padding: '8px', fontSize: 12, fontWeight: 700 }}>
            🗡️ Create
          </button>
          <button onClick={onClose} className="btn-ghost" style={{ padding: '7px 16px', fontSize: 12 }}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

export function RenameEngineModal({ engine, onConfirm, onClose }) {
  const [label, setLabel] = useState(engine.label)
  const [desc,  setDesc]  = useState(engine.desc || '')
  const [icon,  setIcon]  = useState(engine.icon)
  const [color, setColor] = useState(engine.color)
  const [itemLabel, setItemLabel] = useState(engine.listLabel || 'Entries')
  const [fieldStr,  setFieldStr]  = useState((engine.fields || []).join(', '))

  function confirm() {
    if (!label.trim()) return
    const fields = fieldStr.split(',').map(s => s.trim().toLowerCase().replace(/\s+/g,'_')).filter(Boolean)
    onConfirm({ label: label.trim(), desc: desc.trim(), icon, color, listLabel: itemLabel.trim() || 'Entries', fields })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 24, width: 420, maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Edit Engine</div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Engine Name *</div>
          <input value={label} onChange={e => setLabel(e.target.value)}
            style={{ width: '100%', padding: '6px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)' }} />
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Description</div>
          <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={2}
            style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Item/Entry Label (plural)</div>
          <input value={itemLabel} onChange={e => setItemLabel(e.target.value)}
            style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>Fields (comma-separated)</div>
          <textarea value={fieldStr} onChange={e => setFieldStr(e.target.value)} rows={2}
            style={{ width: '100%', padding: '6px 10px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical', fontFamily: 'monospace' }} />
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>Icon</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {CUSTOM_ICONS.map(ic => (
              <button key={ic} onClick={() => setIcon(ic)} style={{
                fontSize: 16, padding: '3px 6px', borderRadius: 6,
                background: icon === ic ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                border: icon === ic ? '1px solid var(--accent)' : '1px solid var(--border)',
              }}>{ic}</button>
            ))}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>Colour</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {CUSTOM_COLORS.map(c => (
              <button key={c} onClick={() => setColor(c)} style={{
                width: 24, height: 24, borderRadius: '50%', background: c,
                border: color === c ? '2px solid #fff' : '2px solid transparent',
                outline: color === c ? `2px solid ${c}` : 'none',
              }} />
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          <button onClick={confirm} disabled={!label.trim()} className="btn-primary" style={{ flex: 1, padding: '8px', fontSize: 12, fontWeight: 700 }}>
            ✓ Save Changes
          </button>
          <button onClick={onClose} className="btn-ghost" style={{ padding: '7px 16px', fontSize: 12 }}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

// Import entries from a saved Blueprint into the project's Systems tab. The
// blueprint's item list uses the same field names as the engine editor, so
// the picked entries are appended as they are (entries whose name already
// exists are skipped).
export function ImportBlueprintBtn({ engine, items, listKey, overview, rules, onImport, small }) {
  const [open, setOpen] = useState(false)
  const [list, setList] = useState(null)
  const [bp, setBp] = useState(null)
  const [picked, setPicked] = useState({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const have = new Set(items.map(i => String(i.name || '').trim().toLowerCase()).filter(Boolean))

  async function openDialog() {
    setOpen(true); setBp(null); setErr(''); setList(null)
    try {
      const r = await api.blueprintList(engine.key)
      setList(r.standards || [])
    } catch (e) { setErr(String(e.message || e)); setList([]) }
  }
  async function choose(std) {
    setBusy(true); setErr('')
    try {
      const d = await api.blueprintGet(engine.key, std.standard_id)
      const entries = d[listKey] || []
      setBp({ ...d, entries })
      const sel = {}
      entries.forEach((it, i) => { sel[i] = !have.has(String(it.name || '').trim().toLowerCase()) })
      setPicked(sel)
    } catch (e) { setErr(String(e.message || e)) }
    setBusy(false)
  }
  async function doImport() {
    const chosen = bp.entries.filter((_, i) => picked[i])
    if (!chosen.length) return
    setBusy(true)
    await onImport([...items, ...chosen], {
      overview: overview || bp.overview || '',
      rules: rules.length ? rules : (bp.rules || []),
    })
    setBusy(false); setOpen(false)
  }
  const count = bp ? Object.values(picked).filter(Boolean).length : 0
  return (
    <>
      <button onClick={openDialog} title="Copy entries from a saved Blueprint into this Systems tab"
        style={{ fontSize: small ? 10 : 11, padding: small ? '3px 10px' : '5px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>⬇ Import Blueprint</button>
      {open && (
        <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 400, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', width: 'min(560px, 100%)', maxHeight: '80vh', display: 'flex', flexDirection: 'column', padding: 16, gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontWeight: 700, fontSize: 13 }}>Import {engine.label} from a Blueprint</div>
              <button onClick={() => setOpen(false)} className="btn-ghost" style={{ fontSize: 11, padding: '2px 8px' }}>✕</button>
            </div>
            {err && <div style={{ fontSize: 11, color: 'var(--red)' }}>{err}</div>}
            {!bp && (list === null ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Loading…</div>
              : list.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No saved Blueprints for {engine.label} yet. Create one on the Blueprints page.</div>
              : <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {list.map(s => (
                    <button key={s.standard_id} onClick={() => choose(s)} disabled={busy}
                      style={{ textAlign: 'left', padding: '8px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>
                      <div style={{ fontSize: 12, fontWeight: 700 }}>{s.display_name} <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>· {s.item_count} entries</span></div>
                      {s.overview && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{s.overview.slice(0, 140)}</div>}
                    </button>
                  ))}
                </div>)}
            {bp && (
              <>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11 }}>
                  <button className="btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }} onClick={() => setBp(null)}>‹ Back</button>
                  <span style={{ fontWeight: 700 }}>{bp.display_name}</span>
                  <span style={{ flex: 1 }} />
                  <button className="btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }} onClick={() => setPicked(Object.fromEntries(bp.entries.map((_, i) => [i, true])))}>All</button>
                  <button className="btn-ghost" style={{ fontSize: 10, padding: '2px 8px' }} onClick={() => setPicked({})}>None</button>
                </div>
                <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {bp.entries.map((it, i) => {
                    const dup = have.has(String(it.name || '').trim().toLowerCase())
                    return (
                      <label key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border-soft)', cursor: 'pointer' }}>
                        <input type="checkbox" checked={!!picked[i]} onChange={e => setPicked(p => ({ ...p, [i]: e.target.checked }))} style={{ marginTop: 3 }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 12, fontWeight: 600 }}>{it.name || it.rank || `Entry ${i + 1}`}{dup && <span style={{ fontSize: 9, color: '#f59e0b', marginLeft: 6 }}>already in project</span>}</div>
                          {(it.description || it.effect || it.ability) && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{String(it.description || it.effect || it.ability).slice(0, 140)}</div>}
                        </div>
                      </label>
                    )
                  })}
                </div>
                <button onClick={doImport} disabled={busy || !count} className="btn-primary" style={{ fontSize: 11, padding: '6px 14px', alignSelf: 'flex-end' }}>
                  {busy ? 'Importing…' : `Import ${count} ${count === 1 ? 'entry' : 'entries'}`}
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}

export function SystemsTab({ project, projectId, afterGenerate, onSave }) {
  const [activeEngine, setActiveEngine] = useState(SYSTEM_ENGINES[0].key)

  // Mobile: collapsible engine-nav drawer (same pattern as GenerateTab)
  const isNarrow = useNarrowLayout()
  const [navOpen, setNavOpen] = useState(() => !isNarrow)
  useEffect(() => { if (!isNarrow) setNavOpen(true) }, [isNarrow])

  const [editIdx, setEditIdx] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [editOverview, setEditOverview] = useState(false)
  const [overviewDraft, setOverviewDraft] = useState('')
  const [rulesDraft, setRulesDraft] = useState([])
  const [saving, setSaving] = useState(false)
  const [showNewEngine, setShowNewEngine] = useState(false)
  const [showRenameEngine, setShowRenameEngine] = useState(false)
  const [confirmDeleteCustom, setConfirmDeleteCustom] = useState(false)
  const [showNewCharPower, setShowNewCharPower] = useState(false)
  const [confirmDeleteCharPower, setConfirmDeleteCharPower] = useState(false)
  const [stageDropdownIdx, setStageDropdownIdx] = useState(0)   // selected stage in a character power system's dropdown
  // A character just picked via "+ New Character Power System" but with no
  // data yet (systems.character_power_systems has no entry for them until
  // the first Interactive/Generate/Paste run actually saves something) —
  // without tracking this separately, switching to their new (empty) engine
  // view would immediately bounce back to allEngines[0] since the key
  // wouldn't resolve to anything in charPowerNames yet.
  const [pendingCharPower, setPendingCharPower] = useState(null)

  const systems = project.systems || {}

  // Custom engines stored in project.systems.custom_engines (array of engine defs)
  const customEngines = systems.custom_engines || []

  // Character-linked power systems — stored as systems.character_power_systems
  // = { "Lu Jian": {overview, rules, levels: [...]}, ... }, one per character
  // whose progression is a genuine VARIANT of the world's standard power_levels
  // (see _build_prompt's "character_power_system::" branch on the backend).
  // Each existing entry becomes its own engine in the sidebar, keyed
  // "character_power_system::<name>" so it routes through the exact same
  // Interactive/Generate/Paste-and-Generate machinery every other systems
  // engine uses — just pointed at a per-character storage slot instead of a
  // flat systems[key].
  const charPowerSystems = systems.character_power_systems || {}
  // Include the just-picked pending name (see pendingCharPower above) so its
  // engine view is reachable before any data has actually been generated —
  // dropped automatically once real data lands, since it's superseded by the
  // real entry in charPowerSystems.
  const charPowerNames = Array.from(new Set([
    ...Object.keys(charPowerSystems),
    ...(pendingCharPower && !charPowerSystems[pendingCharPower] ? [pendingCharPower] : []),
  ]))

  // All engines: built-in + custom + character power systems
  const allEngines = [
    ...SYSTEM_ENGINES,
    ...customEngines.map(ce => ({
      key: ce.key,
      label: ce.label,
      icon: ce.icon,
      color: ce.color,
      desc: ce.desc || '',
      listKey: 'entries',
      listLabel: ce.listLabel || 'Entries',
      isCustom: true,
      fields: ce.fields || ['name', 'type', 'description', 'effect'],
      renderItem: item => (
        <div>
          <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name || item[Object.keys(item)[0]] || '—'}</div>
          {Object.entries(item).filter(([k]) => k !== 'name').slice(0, 4).map(([k, v]) => v ? (
            <div key={k} style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 2 }}>
              <span style={{ color: ce.color, fontWeight: 600 }}>{k.replace(/_/g,' ')}: </span>{String(v).slice(0, 120)}
            </div>
          ) : null)}
        </div>
      ),
    })),
    ...charPowerNames.map(name => ({
      key: `character_power_system::${name}`,
      label: `${name}'s Power System`,
      icon: '🗡️',
      color: '#ec4899',
      desc: `${name}'s own power progression — a variant of the world's standard system`,
      listKey: 'levels',
      listLabel: 'Stages',
      isCharPower: true,
      charName: name,
      renderItem: item => (
        <div>
          <div style={{ fontWeight: 700, fontSize: 13 }}>{item.rank != null ? `${item.rank}. ` : ''}{item.name}</div>
          {item.dao_law && item.dao_law !== 'none' && <div style={{ fontSize: 10, color: '#a855f7', marginTop: 2 }}>Dao/Law: {item.dao_law}</div>}
          {item.description && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>{item.description}</div>}
          {item.requirement && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>Requirement: {item.requirement}</div>}
          {item.breakthrough && <div style={{ fontSize: 10, color: '#ec4899', marginTop: 2 }}>Breakthrough: {item.breakthrough}</div>}
          {item.equivalent_world_tier && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, fontStyle: 'italic' }}>≈ World tier: {item.equivalent_world_tier}</div>}
        </div>
      ),
    })),
  ]

  const engine = allEngines.find(e => e.key === activeEngine) || allEngines[0]
  const isCustomEngine = engine.isCustom || false
  const isWorldBible = engine.isWorldBible || false
  const isCharPower = engine.isCharPower || false
  // World Bible doesn't live under project.systems at all (project.world_bible
  // instead, kept as its own top-level field so existing code that reads it
  // stays unaffected) and doesn't use the generic overview/rules/items[]
  // editor below — WorldTab (rendered separately further down) owns its own
  // data entirely. These stay empty/inert for it rather than touching
  // systems['world'], which is never written.
  // Character power systems live at systems.character_power_systems[charName]
  // — engine.key for these is "character_power_system::<name>", not a flat
  // systems key, so it needs its own lookup/save path, same reasoning as
  // World Bible's special case above.
  const engineData = isWorldBible ? {} : isCharPower ? (charPowerSystems[engine.charName] || {}) : (systems[engine.key] || {})
  const listKey = engine.listKey || 'entries'
  const items = engineData[listKey] || []
  const rules = engineData.rules || []
  const overview = engineData.overview || ''

  // The field list for the current engine's item editor (unused for World Bible)
  const activeFields = isCustomEngine
    ? (engine.fields || ['name', 'type', 'description', 'effect'])
    : isCharPower
    ? ['rank', 'name', 'description', 'requirement', 'breakthrough', 'dao_law', 'equivalent_world_tier']
    : (ENGINE_FIELDS[activeEngine] || ['name', 'description'])

  function switchEngine(key) {
    setActiveEngine(key)
    setEditIdx(null)
    setEditForm(null)
    setEditOverview(false)
    setConfirmDeleteCustom(false)
    setConfirmDeleteCharPower(false)
    if (isNarrow) setNavOpen(false)   // show the engine content right away on mobile
  }

  function onGenDone(res) {
    setEditIdx(null)
    setEditForm(null)
    afterGenerate(res)
  }

  async function saveItems(newItems) {
    setSaving(true)
    if (isCharPower) {
      await onSave({ systems: { ...systems, character_power_systems: { ...charPowerSystems, [engine.charName]: { ...engineData, [listKey]: newItems } } } })
    } else {
      await onSave({ systems: { ...systems, [engine.key]: { ...engineData, [listKey]: newItems } } })
    }
    setSaving(false)
  }

  async function importFromBlueprint(newItems, extra) {
    setSaving(true)
    await onSave({ systems: { ...systems, [engine.key]: { ...engineData, [listKey]: newItems, overview: extra.overview, rules: extra.rules } } })
    setSaving(false)
  }

  async function saveOverviewRules() {
    setSaving(true)
    if (isCharPower) {
      await onSave({ systems: { ...systems, character_power_systems: { ...charPowerSystems, [engine.charName]: { ...engineData, overview: overviewDraft, rules: rulesDraft } } } })
    } else {
      await onSave({ systems: { ...systems, [engine.key]: { ...engineData, overview: overviewDraft, rules: rulesDraft } } })
    }
    setEditOverview(false)
    setSaving(false)
  }

  async function handleDeleteCharPower() {
    const next = { ...charPowerSystems }
    delete next[engine.charName]
    setSaving(true)
    await onSave({ systems: { ...systems, character_power_systems: next } })
    setSaving(false)
    setConfirmDeleteCharPower(false)
    if (pendingCharPower === engine.charName) setPendingCharPower(null)
    setActiveEngine(SYSTEM_ENGINES[0].key)
  }

  function startEdit(i) {
    setEditIdx(i)
    setEditForm({ ...items[i] })
  }

  function startAdd() {
    const blank = Object.fromEntries(activeFields.map(f => [f, ARRAY_FIELDS.has(f) ? [] : '']))
    setEditIdx(items.length)
    setEditForm(blank)
  }

  async function saveEdit() {
    const cleaned = { ...editForm }
    activeFields.forEach(f => {
      if (ARRAY_FIELDS.has(f) && typeof cleaned[f] === 'string') {
        cleaned[f] = cleaned[f].split(',').map(s => s.trim()).filter(Boolean)
      }
    })
    const newItems = editIdx < items.length
      ? items.map((it, i) => i === editIdx ? cleaned : it)
      : [...items, cleaned]
    setEditIdx(null)
    setEditForm(null)
    await saveItems(newItems)
  }

  async function deleteItem(i) {
    if (editIdx === i) { setEditIdx(null); setEditForm(null) }
    await saveItems(items.filter((_, idx) => idx !== i))
  }

  function fieldLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }

  async function handleNewEngine(def) {
    // Add to custom_engines list and create empty data bucket
    const newCustomEngines = [...customEngines, def]
    await onSave({ systems: { ...systems, custom_engines: newCustomEngines, [def.key]: { overview: '', rules: [], entries: [] } } })
    setShowNewEngine(false)
    setActiveEngine(def.key)
  }

  async function handleRenameEngine(updates) {
    const newCustomEngines = customEngines.map(ce =>
      ce.key === engine.key ? { ...ce, ...updates } : ce
    )
    await onSave({ systems: { ...systems, custom_engines: newCustomEngines } })
    setShowRenameEngine(false)
  }

  async function handleDeleteCustomEngine() {
    const newCustomEngines = customEngines.filter(ce => ce.key !== engine.key)
    const newSystems = { ...systems, custom_engines: newCustomEngines }
    delete newSystems[engine.key]
    await onSave({ systems: newSystems })
    setConfirmDeleteCustom(false)
    setActiveEngine(SYSTEM_ENGINES[0].key)
  }

  const EF = editForm || {}

  return (
    <>
      {showNewEngine && <NewEngineModal onConfirm={handleNewEngine} onClose={() => setShowNewEngine(false)} />}
      {showRenameEngine && isCustomEngine && <RenameEngineModal engine={engine} onConfirm={handleRenameEngine} onClose={() => setShowRenameEngine(false)} />}

    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
      {/* mobile: drawer toggle */}
      {isNarrow && (
        <button onClick={() => setNavOpen(o => !o)} title={navOpen ? 'Hide engines' : 'Show engines'} style={{
          position: 'absolute', top: 10, left: navOpen ? 160 : 8, zIndex: 60,
          width: 34, height: 34, borderRadius: '50%', fontSize: 15, fontWeight: 700,
          background: 'var(--accent)', color: '#fff', border: 'none',
          boxShadow: '0 2px 10px rgba(0,0,0,0.4)', cursor: 'pointer',
          transition: 'left 0.25s ease',
        }}>{navOpen ? '‹' : '☰'}</button>
      )}
      {/* mobile: scrim behind open drawer */}
      {isNarrow && navOpen && (
        <div onClick={() => setNavOpen(false)} style={{
          position: 'absolute', inset: 0, zIndex: 40, background: 'rgba(0,0,0,0.45)',
        }} />
      )}

      {/* left nav (drawer on mobile) — with SYSTEM_ENGINES now at 13 built-in
          entries plus any custom engines, this list overflows more often on
          a short mobile viewport than it used to; overflowY:auto already
          made it scrollable, but on mobile Safari/Chrome a plain auto-scroll
          region with no visible affordance can read as "the list is just
          cut off" rather than "swipe to see more" — WebkitOverflowScrolling
          gives it real momentum/inertia (not just a hard snap-scroll), and
          scrollbarGutter reserves space so a thin always-visible scrollbar
          (styled below via .nm-engine-nav) doesn't overlap the button text. */}
      <div className="nm-engine-nav" style={{
        width: 190, flexShrink: 0, borderRight: '1px solid var(--border-soft)', overflowY: 'auto',
        WebkitOverflowScrolling: 'touch', scrollbarGutter: 'stable',
        padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 4,
        ...(isNarrow ? {
          position: 'absolute', top: 0, bottom: 0, left: 0, zIndex: 50,
          background: 'var(--bg-surface, var(--bg-card))',
          transform: navOpen ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 0.25s ease',
          boxShadow: navOpen ? '4px 0 24px rgba(0,0,0,0.4)' : 'none',
        } : {}),
      }}>
        {/* built-in engines */}
        {SYSTEM_ENGINES.map(eng => {
          // World Bible lives at project.world_bible (three lists), not
          // project.systems[eng.key] like every other engine here.
          const count = eng.isWorldBible
            ? (() => { const wb = project.world_bible || {}
                return (wb.factions?.length || 0) + (wb.key_locations?.length || 0) + (wb.races?.length || 0) })()
            : ((project.systems || {})[eng.key] || {})[eng.listKey]?.length || 0
          const isActive = activeEngine === eng.key
          return (
            <button key={eng.key} onClick={() => switchEngine(eng.key)} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
              borderRadius: 'var(--radius)', textAlign: 'left',
              background: isActive ? `${eng.color}18` : 'transparent',
              border: isActive ? `1px solid ${eng.color}55` : '1px solid transparent',
              color: isActive ? eng.color : 'var(--text-secondary)',
              transition: 'all 0.12s',
            }}>
              <span style={{ fontSize: 16 }}>{eng.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: isActive ? 700 : 400, lineHeight: 1.2 }}>{eng.label}</div>
                {count > 0 && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>{count} {eng.isWorldBible ? 'entries' : eng.listLabel}</div>}
              </div>
            </button>
          )
        })}

        {/* custom engines */}
        {customEngines.length > 0 && (
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '8px 4px 2px', borderTop: '1px solid var(--border-soft)', marginTop: 4 }}>
            Custom
          </div>
        )}
        {customEngines.map(ce => {
          const d = (project.systems || {})[ce.key] || {}
          const count = (d.entries || []).length
          const isActive = activeEngine === ce.key
          return (
            <button key={ce.key} onClick={() => switchEngine(ce.key)} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
              borderRadius: 'var(--radius)', textAlign: 'left',
              background: isActive ? `${ce.color}18` : 'transparent',
              border: isActive ? `1px solid ${ce.color}55` : '1px solid transparent',
              color: isActive ? ce.color : 'var(--text-secondary)',
              transition: 'all 0.12s',
            }}>
              <span style={{ fontSize: 16 }}>{ce.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: isActive ? 700 : 400, lineHeight: 1.2 }}>{ce.label}</div>
                {count > 0 && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>{count} {ce.listLabel || 'Entries'}</div>}
              </div>
            </button>
          )
        })}

        {/* character power systems */}
        {charPowerNames.length > 0 && (
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '8px 4px 2px', borderTop: '1px solid var(--border-soft)', marginTop: 4 }}>
            Character Power Systems
          </div>
        )}
        {charPowerNames.map(name => {
          const key = `character_power_system::${name}`
          const count = (charPowerSystems[name]?.levels || []).length
          const isActive = activeEngine === key
          return (
            <button key={key} onClick={() => { switchEngine(key); setStageDropdownIdx(0) }} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
              borderRadius: 'var(--radius)', textAlign: 'left',
              background: isActive ? '#ec489918' : 'transparent',
              border: isActive ? '1px solid #ec489955' : '1px solid transparent',
              color: isActive ? '#ec4899' : 'var(--text-secondary)',
              transition: 'all 0.12s',
            }}>
              <span style={{ fontSize: 16 }}>🗡️</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: isActive ? 700 : 400, lineHeight: 1.2 }}>{name}</div>
                {count > 0 && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>{count} Stages</div>}
              </div>
            </button>
          )
        })}

        {/* new engine buttons */}
        <button onClick={() => setShowNewEngine(true)} style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '7px 10px', marginTop: 4,
          borderRadius: 'var(--radius)', textAlign: 'left', border: '1px dashed var(--border)',
          color: 'var(--text-muted)', background: 'transparent', fontSize: 11, transition: 'all 0.12s',
        }}>
          <span style={{ fontSize: 14 }}>+</span> New Engine
        </button>
        <button onClick={() => setShowNewCharPower(true)} title="Give a character their own variant power progression, separate from the world's standard system" style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '7px 10px',
          borderRadius: 'var(--radius)', textAlign: 'left', border: '1px dashed var(--border)',
          color: 'var(--text-muted)', background: 'transparent', fontSize: 11, transition: 'all 0.12s',
        }}>
          <span style={{ fontSize: 14 }}>+</span> New Character Power System
        </button>
      </div>
      {showNewCharPower && (
        <NewCharPowerModal
          characters={project.character_list || []}
          existingNames={charPowerNames}
          onConfirm={name => {
            setShowNewCharPower(false)
            setPendingCharPower(name)
            setActiveEngine(`character_power_system::${name}`)
            setStageDropdownIdx(0)
          }}
          onClose={() => setShowNewCharPower(false)}
        />
      )}

      {/* main list */}
      {isWorldBible ? (
        // World Bible has its own bespoke editor (3 lists + meta fields) —
        // doesn't fit the generic overview/items/edit-drawer shape below at
        // all, so it's mounted directly here instead of falling through.
        // Still gets the same header row (icon/label/desc + Generate/Update),
        // just no "+ Add" (WorldTab has its own Add buttons per section).
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 20 }}>{engine.icon}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 14, color: engine.color }}>{engine.label}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{engine.desc}</div>
            </div>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              <FieldSurveyButton field={engine.key} projectId={projectId} onDone={onGenDone} small
                label="⚡ Interactive" />
              <AIUpdateBtn field={engine.key} projectId={projectId} onDone={onGenDone} small />
              <AIGenBtn label="✦ Generate" field={engine.key} projectId={projectId} onDone={onGenDone} small />
            </div>
          </div>
          <PasteGenerateBox field={engine.key} label={engine.label} projectId={projectId} onDone={onGenDone} small />
          <WorldTab project={project} projectId={projectId} afterGenerate={onGenDone} onSave={onSave} />
        </div>
      ) : (
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 20 }}>{engine.icon}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: engine.color }}>{engine.label}</div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{engine.desc}</div>
          </div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {isCustomEngine && (
              <>
                <button onClick={() => setShowRenameEngine(true)} style={{ fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>✎ Edit Engine</button>
                {confirmDeleteCustom ? (
                  <>
                    <button onClick={handleDeleteCustomEngine} style={{ fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)', fontWeight: 700 }}>Confirm Delete</button>
                    <button onClick={() => setConfirmDeleteCustom(false)} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>Cancel</button>
                  </>
                ) : (
                  <button onClick={() => setConfirmDeleteCustom(true)} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--red)' }}>✕</button>
                )}
              </>
            )}
            {isCharPower && (
              confirmDeleteCharPower ? (
                <>
                  <button onClick={handleDeleteCharPower} style={{ fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)', fontWeight: 700 }}>Confirm Delete</button>
                  <button onClick={() => setConfirmDeleteCharPower(false)} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>Cancel</button>
                </>
              ) : (
                <button onClick={() => setConfirmDeleteCharPower(true)} title="Delete this character's power system" style={{ fontSize: 10, padding: '3px 8px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--red)' }}>✕</button>
              )
            )}
            {!isCustomEngine && !isCharPower && !isWorldBible && <ImportBlueprintBtn engine={engine} items={items} listKey={listKey} overview={overview} rules={rules} onImport={importFromBlueprint} small />}
            <button onClick={startAdd} style={{ fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add</button>
            <FieldSurveyButton field={engine.key} projectId={projectId} onDone={onGenDone} small label="⚡ Interactive" />
            <AIUpdateBtn field={engine.key} projectId={projectId} onDone={onGenDone} small />
            <AIGenBtn label="✦ Generate" field={engine.key} projectId={projectId} onDone={onGenDone} small />
          </div>
        </div>

        <PasteGenerateBox field={engine.key} label={engine.label} projectId={projectId} onDone={onGenDone} small />

        {/* overview / rules — editable */}
        {(overview || rules.length > 0 || editOverview) && (
          <Panel>
            {editOverview ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>Overview</div>
                <textarea value={overviewDraft} onChange={e => setOverviewDraft(e.target.value)} rows={3}
                  style={{ padding: '6px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>Rules (one per line)</div>
                <textarea value={rulesDraft.join('\n')} onChange={e => setRulesDraft(e.target.value.split('\n'))} rows={4}
                  style={{ padding: '6px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={saveOverviewRules} disabled={saving} className="btn-primary" style={{ fontSize: 10, padding: '4px 12px' }}>{saving ? 'Saving…' : '✓ Save'}</button>
                  <button onClick={() => setEditOverview(false)} className="btn-ghost" style={{ fontSize: 10, padding: '3px 10px' }}>Cancel</button>
                </div>
              </div>
            ) : (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6, flex: 1 }}>{overview}</div>
                  <button onClick={() => { setOverviewDraft(overview); setRulesDraft([...rules]); setEditOverview(true) }}
                    style={{ fontSize: 10, padding: '1px 7px', marginLeft: 8, borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)', flexShrink: 0 }}>✎ Edit</button>
                </div>
                {rules.length > 0 && (
                  <>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>System Rules</div>
                    {rules.map((r, i) => (
                      <div key={i} style={{ fontSize: 11, color: 'var(--text-secondary)', padding: '3px 0', borderBottom: '1px solid var(--border-soft)', display: 'flex', gap: 6 }}>
                        <span style={{ color: engine.color, fontWeight: 700 }}>{i + 1}.</span>
                        <span>{r}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}
          </Panel>
        )}

        {/* items list */}
        {items.length === 0 && editIdx === null ? (
          <Panel>
            <div style={{ textAlign: 'center', padding: '30px 0', color: 'var(--text-muted)' }}>
              <div style={{ fontSize: 32, marginBottom: 10 }}>{engine.icon}</div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>No {engine.listLabel} yet</div>
              <div style={{ fontSize: 11, marginBottom: 14 }}>Generate with AI or add one manually.</div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                <button onClick={startAdd} style={{ fontSize: 11, padding: '5px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add Manually</button>
                {!isCustomEngine && !isCharPower && !isWorldBible && <ImportBlueprintBtn engine={engine} items={items} listKey={listKey} overview={overview} rules={rules} onImport={importFromBlueprint} />}
                <AIGenBtn label={`✦ Generate ${engine.label}`} field={engine.key} projectId={projectId} onDone={onGenDone} />
              </div>
            </div>
          </Panel>
        ) : isCharPower ? (
          // Character power systems can run long (a full Dao/comprehension
          // ladder, 10-12+ stages with rich per-stage text) — a stacked card
          // list gets unwieldy at that length, so this shows a dropdown to
          // pick ONE stage at a time instead, with its full details below.
          <Panel>
            <PanelTitle>{items.length} {engine.listLabel}</PanelTitle>
            <select value={Math.min(stageDropdownIdx, Math.max(items.length - 1, 0))}
              onChange={e => setStageDropdownIdx(Number(e.target.value))}
              style={{ width: '100%', padding: '8px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', marginBottom: 10 }}>
              {items.map((item, i) => (
                <option key={i} value={i}>{i + 1}. {item.name || `Stage ${i + 1}`}</option>
              ))}
            </select>
            {items[stageDropdownIdx] && (
              <div style={{
                padding: '10px 12px', borderRadius: 'var(--radius)',
                background: 'var(--bg-elevated)', border: `1px solid ${engine.color}33`,
                borderLeft: `3px solid ${engine.color}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                  <div style={{ flex: 1 }}>{engine.renderItem(items[stageDropdownIdx])}</div>
                  <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                    <button onClick={() => startEdit(stageDropdownIdx)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                    <button onClick={() => { deleteItem(stageDropdownIdx); setStageDropdownIdx(0) }} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                  </div>
                </div>
              </div>
            )}
          </Panel>
        ) : (
          <Panel>
            <PanelTitle>{items.length} {engine.listLabel}</PanelTitle>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {items.map((item, i) => (
                <div key={i} style={{
                  padding: '8px 10px', borderRadius: 'var(--radius)',
                  background: editIdx === i ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: editIdx === i ? `1px solid var(--accent)` : `1px solid ${engine.color}22`,
                  borderLeft: `3px solid ${editIdx === i ? 'var(--accent)' : engine.color}`,
                  display: 'flex', gap: 8, alignItems: 'flex-start',
                }}>
                  <div style={{ flex: 1 }}>{engine.renderItem(item)}</div>
                  <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                    <button onClick={() => startEdit(i)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                    <button onClick={() => deleteItem(i)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        )}
      </div>
      )}

      {/* edit panel — slides in on right (full-screen drawer on mobile, same
          treatment as the Chapter Skeleton edit panel above) — not used by
          World Bible, which has its own inline edit sections in WorldTab. */}
      {editIdx !== null && editForm && (
        <div style={{
          width: 300, flexShrink: 0, borderLeft: '1px solid var(--border)',
          background: 'var(--bg-surface)', overflowY: 'auto',
          padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 10,
          ...(isNarrow ? {
            position: 'absolute', top: 0, bottom: 0, right: 0, zIndex: 50,
            width: 'min(300px, 92vw)',
            boxShadow: '-4px 0 24px rgba(0,0,0,0.4)',
          } : {}),
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: engine.color, marginBottom: 4 }}>
            {editIdx < items.length ? `Edit ${engine.listLabel.replace(/s$/, '')}` : `New ${engine.listLabel.replace(/s$/, '')}`}
          </div>

          {activeFields.map(field => {
            const val = EF[field]
            const displayVal = Array.isArray(val) ? val.join(', ') : (val ?? '')
            const isLong = LONG_FIELDS.has(field)
            const isArr = ARRAY_FIELDS.has(field)
            return (
              <div key={field}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>
                  {fieldLabel(field)}{isArr ? ' (comma separated)' : ''}
                </div>
                {isLong ? (
                  <textarea
                    value={displayVal}
                    onChange={e => setEditForm(f => ({ ...f, [field]: e.target.value }))}
                    rows={3}
                    style={{ width: '100%', padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }}
                  />
                ) : (
                  <input
                    value={displayVal}
                    onChange={e => setEditForm(f => ({ ...f, [field]: e.target.value }))}
                    style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}
                  />
                )}
              </div>
            )
          })}

          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <button onClick={saveEdit} disabled={saving} className="btn-primary" style={{ flex: 1, padding: '6px', fontSize: 11 }}>
              {saving ? 'Saving…' : '✓ Save'}
            </button>
            <button onClick={() => { setEditIdx(null); setEditForm(null) }} className="btn-ghost" style={{ padding: '5px 12px', fontSize: 11 }}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
    </>
  )
}
