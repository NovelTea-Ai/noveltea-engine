import { useEffect, useState } from 'react'
import { api } from '../../api'

// The Chapter Mechanics corpus data (how each corpus chapter is built: beats with their meaning, purpose and motive, cast
// roles, fights, set-piece runs) for the Cast, Foes and Timeline tabs. Every hit carries its novel and chapter; every quote
// opens the raw passage around it.

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = { fontSize: 10.5, padding: '4px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const KINDS = { chapter: 'Chapter', beat: 'Beat', cast: 'Character', fight: 'Fight', run: 'Set-piece run', device: 'Device' }

// The raw text around a quote (or a chapter's opening), in an overlay.
export function RawPassage({ novel, chapter, quote, onClose }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [around, setAround] = useState(3)
  useEffect(() => {
    setErr('')
    api.rawContext(novel, chapter, quote || '', around).then(setData).catch(e => setErr(e.message || 'Could not load the raw text'))
  }, [novel, chapter, quote, around])
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 400, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', maxWidth: 760, width: '100%', maxHeight: '85vh', overflowY: 'auto', padding: '14px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <b style={{ fontSize: 12.5 }}>{data?.novel_title || novel} · chapter {chapter}</b>
          {data && !data.found && quote && <span style={{ ...muted, color: 'var(--amber)' }}>quote not found word for word; showing the opening</span>}
          <span style={{ flex: 1 }} />
          <button style={btn} onClick={() => setAround(a => a + 4)}>More around it</button>
          <button style={btn} onClick={onClose}>Close</button>
        </div>
        {err && <div style={{ ...muted, color: 'var(--red)' }}>{err}</div>}
        {!data && !err && <div style={muted}>Loading…</div>}
        {(data?.paragraphs || []).map(p => (
          <p key={p.index} style={{ fontSize: 12.5, lineHeight: 1.6, margin: '0 0 8px', padding: p.hit ? '4px 8px' : 0,
            background: p.hit ? 'var(--accent-dim)' : 'transparent', borderLeft: p.hit ? '3px solid var(--accent)' : 'none', color: 'var(--text-primary)' }}>
            <span style={{ ...muted, marginRight: 6 }}>¶{p.index}</span>{p.text}
          </p>
        ))}
      </div>
    </div>
  )
}

// A list of mechanics hits: what kind of record, novel + chapter, the planner-facing text, and the quotes (click = raw passage).
export function MechanicsHits({ hits }) {
  const [raw, setRaw] = useState(null)
  if (!hits) return null
  if (!hits.length) return <div style={muted}>Nothing in the corpus mechanics matches yet (the Chapter Mechanics pipeline may still be building).</div>
  return (
    <div>
      {hits.map((h, i) => {
        const m = h.meta || {}
        const quotes = m.quotes || []
        return (
          <div key={i} style={{ borderTop: i ? '1px solid var(--border-soft)' : 'none', padding: '7px 0', fontSize: 11.5, lineHeight: 1.5 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 9, background: 'var(--accent-dim)', color: 'var(--accent-light)', textTransform: 'uppercase' }}>{KINDS[m.kind] || m.kind || 'mechanics'}</span>
              <b>{h.novel_title || h.novel_id}</b>
              {h.chapter != null && (
                <button style={{ ...btn, padding: '1px 7px' }} title="Open the raw chapter here" onClick={() => setRaw({ novel: h.novel_id, chapter: h.chapter, quote: quotes[0] || '' })}>
                  ch {h.chapter}{m.chapters && m.chapters.length > 1 ? `–${m.chapters[m.chapters.length - 1]}` : ''} ↗
                </button>
              )}
              {h.score != null && <span style={muted}>{Math.round(h.score * 100)}% match</span>}
            </div>
            <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>{h.text}</div>
            {h.run && <div style={muted}>Run: {h.run.set_piece_type} over chapters {h.run.chapters?.[0]}–{h.run.chapters?.[h.run.chapters.length - 1]} ({(h.run.roles || []).map(r => `ch${r.chapter} ${r.role}`).join(', ')})</div>}
            {quotes.map((q, k) => (
              <button key={k} onClick={() => setRaw({ novel: h.novel_id, chapter: h.chapter, quote: q })} title="Open the raw passage around this line"
                style={{ display: 'block', textAlign: 'left', marginTop: 3, padding: '2px 8px', fontSize: 11, fontStyle: 'italic', background: 'transparent', border: 'none', borderLeft: '2px solid var(--border)', color: 'var(--text-primary)', cursor: 'pointer' }}>
                “{q}”
              </button>
            ))}
          </div>
        )
      })}
      {raw && <RawPassage {...raw} onClose={() => setRaw(null)} />}
    </div>
  )
}

// A search card over the mechanics data, for one kind of record (e.g. 'cast' in the Cast tab), with novel + chapter filters.
export function CorpusMechanicsSearch({ kind, title, intro, placeholder, roleFilter }) {
  const [q, setQ] = useState('')
  const [novel, setNovel] = useState('')
  const [chFrom, setChFrom] = useState('')
  const [chTo, setChTo] = useState('')
  const [hits, setHits] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [novels, setNovels] = useState([])
  useEffect(() => { api.registry().then(r => setNovels(r?.novels || [])).catch(() => {}) }, [])
  async function run() {
    if (!q.trim()) return
    setBusy(true); setErr('')
    try {
      const r = await api.referenceSearch(q.trim(), { kind, novel_id: novel || null, chapter_from: chFrom, chapter_to: chTo, top_k: 12 })
      let res = r.results || []
      if (roleFilter) res = res.filter(h => roleFilter((h.meta || {}).cast_role))
      setHits(res)
    } catch (e) { setErr(e.message || 'Search failed') } finally { setBusy(false) }
  }
  return (
    <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '12px 14px', marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>{title}</div>
      {intro && <div style={{ ...muted, marginBottom: 8 }}>{intro}</div>}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && run()} placeholder={placeholder}
          style={{ flex: 1, minWidth: 200, padding: '5px 9px', fontSize: 11.5, borderRadius: 4 }} />
        <select value={novel} onChange={e => setNovel(e.target.value)} style={{ fontSize: 11, padding: '4px 6px', borderRadius: 4, maxWidth: 200 }}>
          <option value="">All novels</option>
          {novels.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
        </select>
        <span style={{ ...muted, display: 'flex', alignItems: 'center', gap: 4 }}>ch
          <input type="number" min={1} value={chFrom} placeholder="from" onChange={e => setChFrom(e.target.value)} style={{ width: 56, padding: '4px 5px', fontSize: 11, borderRadius: 4 }} />–
          <input type="number" min={1} value={chTo} placeholder="to" onChange={e => setChTo(e.target.value)} style={{ width: 56, padding: '4px 5px', fontSize: 11, borderRadius: 4 }} />
        </span>
        <button style={primary} onClick={run} disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
      </div>
      {err && <div style={{ ...muted, color: 'var(--red)' }}>{err}</div>}
      <MechanicsHits hits={hits} />
    </div>
  )
}

// For one timeline event: how the chosen reference novel (or the whole corpus) runs a moment like it.
export function TimelineReference({ projectId, ev }) {
  const [hits, setHits] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function run() {
    setBusy(true); setErr('')
    try { setHits((await api.timelineReference(projectId, ev.chapter || 1, ev.title || '', ev.mc_sees || ev.text || '')).results || []) }
    catch (e) { setErr(e.message || 'Lookup failed') } finally { setBusy(false) }
  }
  return (
    <div style={{ marginTop: 4 }}>
      <button style={btn} onClick={run} disabled={busy || !(ev.title || '').trim()}
        title="How the reference novel chosen in Author DNA (or the whole corpus) builds a moment like this: its chapters, beats and lines">
        {busy ? 'Looking…' : '📚 How the corpus does this'}
      </button>
      {err && <div style={{ ...muted, color: 'var(--red)' }}>{err}</div>}
      {hits && <div style={{ marginTop: 6 }}><MechanicsHits hits={hits} /></div>}
    </div>
  )
}
