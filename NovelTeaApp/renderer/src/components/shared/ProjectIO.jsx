import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'

// Project import and export (the "noveltea-project" bundle).
//   <ExportMenu />          a small drop-down: the whole project as a bundle (.zip), or the manuscript as Markdown or plain text
//   <ImportProjectButton /> choose a bundle (.zip) or a manuscript (.txt, .md, .docx), see what is inside, then import it as a new project
const btn = {
  fontSize: 11, fontWeight: 600, padding: '5px 12px', borderRadius: 'var(--radius-sm)',
  background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)', cursor: 'pointer',
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

export function ExportMenu({ projectId, compact = false, manuscriptOnly = false, label = '⤓ Export' }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })      // top, or bottom when the menu opens upward
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])

  const items = manuscriptOnly
    ? [['markdown', 'Manuscript (Markdown)', 'The chapters in order, as one .md file'], ['txt', 'Manuscript (plain text)', 'The chapters in order, as one .txt file']]
    : [['bundle', 'Project bundle (.zip)', 'Everything: plan, chapters, version history. Imports back into NovelTea Engine'],
       ['markdown', 'Manuscript (Markdown)', 'The chapters in order, as one .md file'],
       ['txt', 'Manuscript (plain text)', 'The chapters in order, as one .txt file']]

  async function run(fmt) {
    setBusy(fmt); setError('')
    try {
      const { blob, name } = await api.projectExport(projectId, fmt)
      saveBlob(blob, name)
      setOpen(false)
    } catch (e) {
      setError(String(e.message || e).slice(0, 200))
    } finally { setBusy(null) }
  }

  function toggle(e) {
    e.stopPropagation()
    if (!open) {
      const r = e.currentTarget.getBoundingClientRect()
      const left = Math.max(8, Math.min(r.left, window.innerWidth - 330))
      // open upward when there is not enough room below (a project card sits near the bottom of the window)
      if (window.innerHeight - r.bottom < 240 && r.top > 240) setPos({ bottom: window.innerHeight - r.top + 4, left })
      else setPos({ top: r.bottom + 4, left })
    }
    setError('')
    setOpen(o => !o)
  }

  return (
    <span ref={ref} style={{ position: 'relative', display: 'inline-block' }} onClick={e => e.stopPropagation()}>
      <button onClick={toggle} title={manuscriptOnly ? 'Export the manuscript' : 'Export this project'}
        style={compact ? { ...btn, padding: '5px 10px', color: 'var(--text-muted)' } : btn}>
        {compact ? '⤓' : label}
      </button>
      {open && (
        <div style={{
          position: 'fixed', top: pos.top, bottom: pos.bottom, left: pos.left, zIndex: 600, width: 320, padding: 6,
          background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
          boxShadow: '0 12px 32px rgba(0,0,0,0.25)',
        }}>
          {items.map(([fmt, title, desc]) => (
            <button key={fmt} onClick={() => run(fmt)} disabled={!!busy} style={{
              display: 'block', width: '100%', textAlign: 'left', padding: '8px 10px', borderRadius: 'var(--radius-sm)',
              background: 'transparent', border: 'none', cursor: busy ? 'default' : 'pointer', color: 'var(--text-primary)',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-elevated)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>{busy === fmt ? 'Preparing…' : title}</div>
              <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 2 }}>{desc}</div>
            </button>
          ))}
          {error && <div style={{ margin: '6px 10px 4px', fontSize: 11, color: 'var(--red)' }}>{error}</div>}
        </div>
      )}
    </span>
  )
}

export function ImportProjectButton({ onImported, style, label = '⤒ Import project' }) {
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState(null)   // what the chosen file contains
  const [title, setTitle] = useState('')
  const [importing, setImporting] = useState(false)

  async function chosen(e) {
    const file = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!file) return
    setBusy(true); setError('')
    try {
      const p = await api.projectImportPreview(file)
      setPreview(p); setTitle(p.title || '')
    } catch (err) {
      setError(String(err.message || err).slice(0, 300))
    } finally { setBusy(false) }
  }

  async function commit() {
    setImporting(true); setError('')
    try {
      const r = await api.projectImportCommit(preview.token, title.trim() !== preview.title ? title.trim() : null)
      setPreview(null)
      onImported && onImported(r)
    } catch (err) {
      setError(String(err.message || err).slice(0, 300))
    } finally { setImporting(false) }
  }

  const rows = preview ? [
    ['Written chapters', preview.chapters], ['Words', Number(preview.words || 0).toLocaleString()],
    ...(preview.kind === 'bundle' ? [['Planned chapters', preview.planned_chapters], ['Characters', preview.characters], ['Arcs', preview.arcs]] : []),
  ] : []

  return (
    <>
      <input ref={inputRef} type="file" accept=".zip,.txt,.md,.docx" onChange={chosen} style={{ display: 'none' }} />
      <button onClick={() => inputRef.current && inputRef.current.click()} disabled={busy}
        title="Import a project bundle (.zip) or a manuscript (.txt, .md, .docx)" style={{ ...btn, ...(style || {}) }}>
        {busy ? 'Reading the file…' : label}
      </button>
      {error && !preview && (
        <div role="alert" onClick={() => setError('')} style={{
          position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 700, maxWidth: 480, padding: '10px 14px',
          background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)', borderRadius: 'var(--radius)', fontSize: 12, cursor: 'pointer',
        }}>{error}</div>
      )}
      {preview && (
        <div onClick={() => !importing && setPreview(null)} style={{
          position: 'fixed', inset: 0, zIndex: 700, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 14,
        }}>
          <div onClick={e => e.stopPropagation()} style={{
            width: 440, maxWidth: '100%', padding: 20, background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)',
          }}>
            <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 2 }}>Import this project?</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 14 }}>
              {preview.kind === 'bundle'
                ? `A project bundle${preview.source_app ? ` exported from ${preview.source_app}` : ''}${preview.exported_at ? ` on ${String(preview.exported_at).slice(0, 10)}` : ''}.`
                : 'A manuscript. It is split into chapters on "Chapter N" headings; the planning tabs start empty.'}
              {' '}It is added as a <b>new</b> project; nothing existing is changed.
            </div>
            <label style={{ display: 'block', fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 5 }}>Title</label>
            <input value={title} onChange={e => setTitle(e.target.value)} maxLength={200}
              style={{ width: '100%', padding: '7px 10px', fontSize: 13, marginBottom: 12, borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 8, marginBottom: 12 }}>
              {rows.map(([k, v]) => (
                <div key={k} style={{ padding: '8px 10px', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>{v}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{k}</div>
                </div>
              ))}
            </div>
            {(preview.warnings || []).map((w, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--amber)', marginBottom: 4 }}>⚠ {w}</div>
            ))}
            {preview.skipped_count > 0 && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                {preview.skipped_count} file{preview.skipped_count === 1 ? '' : 's'} in the bundle will be left out (not part of a project).
              </div>
            )}
            {error && <div style={{ fontSize: 12, color: 'var(--red)', margin: '8px 0' }}>{error}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
              <button onClick={() => setPreview(null)} disabled={importing} style={btn}>Cancel</button>
              <button onClick={commit} disabled={importing || !title.trim()} className="btn-primary" style={{ padding: '6px 18px', fontSize: 12, fontWeight: 700 }}>
                {importing ? 'Importing…' : 'Import project'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
