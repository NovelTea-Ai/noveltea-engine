import { useEffect, useState } from 'react'
import { coverImageUrl } from '../shared/projectUi'

/* ── Front Cover: the cover card from the old top bar, as its own tool and a lot bigger. The cover editor (emoji,
   gradient, uploaded image) is the same modal as before; the title is edited right here, since the top bar that held
   it is gone in the workspace layout. ── */
export function FrontCoverTool({ project, gradient, onEditCover, onSaveTitle }) {
  const [title, setTitle] = useState(project.title || '')
  useEffect(() => { setTitle(project.title || '') }, [project.title])
  const img = coverImageUrl(project)
  const commit = () => {
    const t = title.trim()
    if (t && t !== project.title) onSaveTitle(t)
    else setTitle(project.title || '')
  }
  return (
    <div style={{
      flex: 1, minWidth: 0, overflowY: 'auto', padding: '24px 20px 40px',
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 22,
    }}>
      <button onClick={onEditCover} aria-label="Edit front cover" title="Edit the front cover" style={{
        // as big as fits: capped by the screen height too, so the title and the button under it stay in view
        width: 'min(100%, 480px, calc((100vh - 340px) * 0.6667))', aspectRatio: '2 / 3', flexShrink: 0, position: 'relative', overflow: 'hidden',
        borderRadius: 20, background: img ? '#000' : gradient, cursor: 'pointer',
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 'clamp(96px, 24vw, 170px)',
        border: '1px solid rgba(255,255,255,0.14)',
        boxShadow: '0 28px 70px rgba(0,0,0,0.6), 0 6px 18px rgba(0,0,0,0.45), 0 0 0 1px rgba(0,0,0,0.3)',
      }}>
        {img
          ? <img src={img} alt="" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
          : (project.cover_emoji || '⚡')}
        <span style={{
          position: 'absolute', left: 0, right: 0, bottom: 0, padding: '28px 12px 12px', fontSize: 12, fontWeight: 700, color: '#fff',
          background: 'linear-gradient(transparent, rgba(0,0,0,0.7))',
        }}>✎ Edit cover</span>
      </button>

      <div style={{ width: 'min(100%, 480px)', textAlign: 'center' }}>
        <input value={title} aria-label="Title" onChange={e => setTitle(e.target.value)} onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { setTitle(project.title || ''); e.currentTarget.blur() } }}
          style={{
            width: '100%', boxSizing: 'border-box', textAlign: 'center', fontSize: 26, fontWeight: 800, color: 'var(--text-primary)',
            background: 'transparent', border: 'none', borderBottom: '1px dashed var(--border)', padding: '4px 0',
          }} />
        {project.tagline && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', fontStyle: 'italic', marginTop: 8 }}>"{project.tagline}"</div>
        )}
        <button className="btn-primary" onClick={onEditCover} style={{ marginTop: 18, padding: '9px 22px', fontSize: 12 }}>✎ Change front cover</button>
      </div>
    </div>
  )
}
