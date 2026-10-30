import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import { ARC_COLORS } from './ConspiracyTab'
import { TimelineReference } from '../corpus/CorpusMechanics'

// Timeline tab (Pre-generation): the book chapter by chapter, from the hero's point of view. Arcs carry his realm and where he is;
// the author's events and every Conspiracy-tree slip pinned to a chapter sit on that chapter, colour-coded. Tree slips show what the
// hero sees (their surface); the Truth switch shows what is really going on. The author's own events are editable here; tree slips are
// edited in the Plot tab. "Suggest" on an arc asks the author's brain for that stretch's events (grounded in this book's canon and in
// what comparable published novels put on the page there); they show as dashed slips to accept or decline, and nothing is saved until
// the author accepts them and presses Save.

export const TL_CATS = {
  fight:        { label: 'Fight',        color: '#c2412d' },
  breakthrough: { label: 'Breakthrough', color: '#c8a24a' },
  reveal:       { label: 'Reveal',       color: '#8b5cf6' },
  clue:         { label: 'Clue',         color: '#2e9aa6' },
  plot:         { label: 'Plot',         color: '#d08a2b' },
  character:    { label: 'Character',    color: '#4a76b0' },
  place:        { label: 'Place',        color: '#4f9a3a' },
  personal:     { label: 'Personal',     color: '#c0466a' },
}
const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = { fontSize: 10.5, padding: '4px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const field = { width: '100%', padding: '5px 8px', fontSize: 11.5, borderRadius: 4, boxSizing: 'border-box' }
const arcColor = a => ARC_COLORS[((a || 1) - 1) % ARC_COLORS.length]
const newId = () => `t${Date.now() % 1e10}${Math.floor(Math.random() * 1000)}`

function EventForm({ ev, onSave, onCancel, onDelete, hero }) {
  const [e, setE] = useState(ev)
  const set = (k, v) => setE(x => ({ ...x, [k]: v }))
  const num = v => (v === '' ? null : parseInt(v, 10) || null)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <label style={{ ...muted, flex: '1 1 70px' }}>Chapter<input style={field} inputMode="numeric" value={e.chapter ?? ''} onChange={x => set('chapter', num(x.target.value))} /></label>
        <label style={{ ...muted, flex: '1 1 70px' }}>To chapter<input style={field} inputMode="numeric" placeholder="(one chapter)" value={e.end_chapter ?? ''} onChange={x => set('end_chapter', num(x.target.value))} /></label>
        <label style={{ ...muted, flex: '2 1 120px' }}>Kind
          <select style={field} value={e.category} onChange={x => set('category', x.target.value)}>
            {Object.entries(TL_CATS).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}
          </select></label>
      </div>
      <label style={muted}>What happens<input style={field} value={e.title} onChange={x => set('title', x.target.value)} /></label>
      <label style={muted}>What {hero} sees and feels<textarea rows={2} style={field} value={e.mc_sees} onChange={x => set('mc_sees', x.target.value)} /></label>
      <label style={muted}>Notes (the truth behind it, for you and the planners)<textarea rows={2} style={field} value={e.text} onChange={x => set('text', x.target.value)} /></label>
      <div style={{ display: 'flex', gap: 6 }}>
        <button style={primary} disabled={!e.chapter || !e.title.trim()} onClick={() => onSave(e)}>Done</button>
        <button style={btn} onClick={onCancel}>Cancel</button>
        {onDelete && <button style={{ ...btn, marginLeft: 'auto', color: 'var(--red)' }} onClick={onDelete}>Delete</button>}
      </div>
    </div>
  )
}

function Chip({ ev, truth, onClick }) {
  const c = TL_CATS[ev.category] || TL_CATS.plot
  const line = ev.from_tree ? (truth || ev.revealed ? ev.text : (ev.mc_sees || ev.text)) : (truth ? (ev.text || ev.mc_sees) : (ev.mc_sees || ev.text))
  return (
    <button onClick={onClick} title={line}
      style={{ textAlign: 'left', display: 'block', width: '100%', padding: '5px 9px', borderRadius: 4, cursor: 'pointer',
        background: 'var(--bg-surface)', border: '1px solid var(--border-soft)', borderLeft: `4px solid ${c.color}`, color: 'var(--text-primary)' }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9.5, color: c.color, fontWeight: 700 }}>{c.label}{ev.end_chapter ? `, to ch ${ev.end_chapter}` : ''}</span>
        <span style={{ fontSize: 12, fontWeight: 600 }}>{ev.title}</span>
        {ev.from_tree && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>from the Plot tree</span>}
      </div>
      {line && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2, lineHeight: 1.45, fontStyle: !truth && ev.from_tree && !ev.revealed ? 'italic' : 'normal' }}>{line}</div>}
    </button>
  )
}

function SuggestChip({ ev, truth, onAccept, onDecline }) {
  const c = TL_CATS[ev.category] || TL_CATS.plot
  const line = truth ? (ev.text || ev.mc_sees) : (ev.mc_sees || ev.text)
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', padding: '5px 9px', borderRadius: 4, background: 'transparent',
      border: '1px dashed var(--border)', borderLeft: `4px dashed ${c.color}` }}>
      <div style={{ flex: 1, minWidth: 0 }} title={ev.text}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 9.5, color: c.color, fontWeight: 700 }}>Suggested · {c.label}{ev.end_chapter ? `, to ch ${ev.end_chapter}` : ''}</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{ev.title}</span>
        </div>
        {line && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2, lineHeight: 1.45 }}>{line}</div>}
        {!truth && ev.text && <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 2, lineHeight: 1.45 }}>Why: {ev.text}</div>}
      </div>
      <button onClick={onAccept} title="Keep this event" style={{ ...btn, padding: '3px 8px', color: 'var(--green)', flexShrink: 0 }}>✓</button>
      <button onClick={onDecline} title="Drop this suggestion" style={{ ...btn, padding: '3px 8px', color: 'var(--red)', flexShrink: 0 }}>✕</button>
    </div>
  )
}

export default function TimelineTab({ projectId }) {
  const [data, setData] = useState(null)
  const [events, setEvents] = useState([])
  const [arcInfo, setArcInfo] = useState({})
  const [dirty, setDirty] = useState(false)
  const [truth, setTruth] = useState(false)
  const [showEmpty, setShowEmpty] = useState(false)
  const [showTree, setShowTree] = useState(true)
  const [hidden, setHidden] = useState(() => new Set())
  const [editing, setEditing] = useState(null)        // an event being added or edited
  const [viewTree, setViewTree] = useState(null)      // a tree slip being looked at
  const [editArc, setEditArc] = useState(null)
  const [sugFor, setSugFor] = useState(null)          // the arc whose suggest form is open: {volume, first, last, note}
  const [proposed, setProposed] = useState([])       // suggested events waiting for accept / decline (not saved)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const listRef = useRef(null)

  const load = useCallback(() => api.timeline(projectId).then(r => { setData(r); setEvents(r.events || []); setArcInfo(r.arc_info || {}); setDirty(false); setErr('') })
    .catch(e => setErr(e.message || 'Could not load the Timeline')), [projectId])
  useEffect(() => { load() }, [load])

  const all = useMemo(() => [...events, ...(showTree && data ? data.tree_events : []), ...proposed.map(e => ({ ...e, _sug: true }))]
    .filter(e => !hidden.has(e.category)), [events, data, showTree, hidden, proposed])
  const byChapter = useMemo(() => {
    const m = new Map()
    all.forEach(e => {
      const end = e.end_chapter || e.chapter
      for (let c = e.chapter; c <= end; c += 1) { if (!m.has(c)) m.set(c, []); m.get(c).push(c === e.chapter ? e : { ...e, _cont: true }) }
    })
    return m
  }, [all])

  async function run(name, fn) {
    setBusy(name); setErr(''); setMsg('')
    try { await fn() } catch (e) { setErr(e.message || 'That failed') } finally { setBusy('') }
  }
  const save = () => run('save', async () => { const r = await api.timelineSave(projectId, events, arcInfo); setEvents(r.events); setArcInfo(r.arc_info); setDirty(false); setMsg('✓ Saved. Events on a chapter now go to that chapter\'s planner and writer.') })
  const undo = () => run('undo', async () => { const r = await api.timelineUndo(projectId); setEvents(r.events); setArcInfo(r.arc_info); setDirty(false); setMsg('Undone.') })
  const suggest = () => run('suggest', async () => {
    const r = await api.timelineSuggest(projectId, sugFor.first, sugFor.last, sugFor.note || '')
    const got = (r.proposed || []).map(e => ({ ...e, id: newId() }))
    setProposed(p => [...p.filter(x => x.chapter < r.first || x.chapter > r.last), ...got].sort((a, b) => a.chapter - b.chapter))
    setSugFor(null)
    setMsg(`${got.length} suggested event(s) for chapters ${r.first}-${r.last}${r.grounded ? ', grounded in how comparable novels pace this stretch' : ''}. ✓ keeps one, ✕ drops it; Save when done.`)
    if (got.length) setTimeout(() => jump(got[0].chapter), 50)
  })
  const accept = e => { const { _sug, ...ev } = e; setEvents(es => [...es, ev].sort((a, b) => a.chapter - b.chapter)); setProposed(p => p.filter(x => x.id !== e.id)); setDirty(true) }
  const decline = e => setProposed(p => p.filter(x => x.id !== e.id))
  const acceptAll = () => { setEvents(es => [...es, ...proposed].sort((a, b) => a.chapter - b.chapter)); setProposed([]); setDirty(true) }
  const openSuggest = a => {
    if (sugFor?.volume === a.volume) { setSugFor(null); return }
    const lastEv = events.filter(e => e.chapter >= a.chapters[0] && e.chapter <= a.chapters[1]).reduce((m, e) => Math.max(m, e.end_chapter || e.chapter), a.chapters[0] - 1)
    const first = Math.min(a.chapters[1], lastEv + 1)
    setSugFor({ volume: a.volume, first, last: Math.min(a.chapters[1], first + 39), note: '' })
  }
  const jump = ch => {
    const el = listRef.current?.querySelector(`[data-ch="${ch}"]`) || [...(listRef.current?.querySelectorAll('[data-ch]') || [])].find(x => +x.dataset.ch >= ch)
    if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  if (err && !data) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!data) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  const total = data.chapters
  const hero = data.hero || 'The hero'
  const counts = Object.fromEntries(Object.keys(TL_CATS).map(k => [k, [...events, ...data.tree_events].filter(e => e.category === k).length]))

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '12px 14px', gap: 10, minWidth: 0 }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>{hero}'s timeline</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <div role="group" aria-label="Point of view" style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
              {[[false, 'What he sees'], [true, 'Truth']].map(([v, l]) => (
                <button key={l} onClick={() => setTruth(v)} aria-pressed={truth === v}
                  style={{ fontSize: 10.5, padding: '4px 11px', border: 'none', background: truth === v ? 'var(--bg-elevated)' : 'transparent', color: truth === v ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: truth === v ? 700 : 400 }}>{l}</button>
              ))}
            </div>
            <button style={btn} onClick={() => setShowEmpty(v => !v)}>{showEmpty ? 'Hide empty chapters' : 'Show every chapter'}</button>
            <button style={btn} onClick={() => setShowTree(v => !v)}>{showTree ? 'Hide Plot slips' : 'Show Plot slips'}</button>
            <button style={btn} disabled={!!busy} onClick={undo}>↶ Undo</button>
            <button style={primary} onClick={() => setEditing({ id: newId(), chapter: null, end_chapter: null, category: 'fight', title: '', mc_sees: '', text: '' })}>＋ Add event</button>
            <button style={primary} disabled={!!busy || !dirty} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
        <div style={muted}>Every chapter of the book, as {hero} lives it. Your events and the Plot tree's slips sit on their chapter; Plot slips show what he sees, the Truth switch shows what is really happening. Events you add here go to that chapter's planner and writer.</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {Object.entries(TL_CATS).map(([k, c]) => {
            const off = hidden.has(k)
            return (
              <button key={k} aria-pressed={!off} onClick={() => setHidden(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })}
                style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, padding: '3px 8px', borderRadius: 3, background: 'transparent', border: '1px solid var(--border-soft)', color: off ? 'var(--text-muted)' : 'var(--text-secondary)', opacity: off ? 0.5 : 1 }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: c.color }} />{c.label}<span style={{ color: 'var(--text-muted)' }}>{counts[k]}</span>
              </button>)
          })}
        </div>
        {/* the whole book at a glance: arc bands, one tick per event; click to jump */}
        <div style={{ position: 'relative', height: 30, borderRadius: 4, overflow: 'hidden', cursor: 'pointer', border: '1px solid var(--border-soft)' }}
          onClick={e => { const r = e.currentTarget.getBoundingClientRect(); jump(Math.max(1, Math.round(((e.clientX - r.left) / r.width) * total))) }}
          title="Click to jump to that part of the book">
          {data.arcs.map(a => (
            <div key={a.volume} style={{ position: 'absolute', top: 0, bottom: 0, left: `${((a.chapters[0] - 1) / total) * 100}%`, width: `${((a.chapters[1] - a.chapters[0] + 1) / total) * 100}%`, background: arcColor(a.volume), borderRight: '1px solid rgba(0,0,0,0.4)' }}>
              <span style={{ position: 'absolute', left: 3, top: 1, fontSize: 9, color: '#e8dcc0' }}>{a.volume}</span>
            </div>
          ))}
          {all.map(e => (
            <div key={e.id} style={{ position: 'absolute', bottom: 2, width: 2, height: 12, left: `${((e.chapter - 1) / total) * 100}%`, background: (TL_CATS[e.category] || TL_CATS.plot).color }} />
          ))}
        </div>
        {msg && <div style={{ ...muted, color: 'var(--green)' }}>{msg}</div>}
        {err && <div style={{ ...muted, color: 'var(--red)' }}>{err}</div>}
        {dirty && <div style={muted}>Unsaved changes.</div>}
        {proposed.length > 0 && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ ...muted, color: 'var(--text-secondary)' }}>{proposed.length} suggestion(s) waiting on their chapters.</span>
            <button style={btn} onClick={acceptAll}>✓ Accept all</button>
            <button style={btn} onClick={() => setProposed([])}>✕ Decline all</button>
          </div>
        )}
      </div>

      {(editing || viewTree) && (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-lg)', padding: 12 }}>
          {editing && <EventForm ev={editing} hero={hero} onCancel={() => setEditing(null)}
            onDelete={events.some(x => x.id === editing.id) ? () => { setEvents(es => es.filter(x => x.id !== editing.id)); setDirty(true); setEditing(null) } : null}
            onSave={e => { setEvents(es => (es.some(x => x.id === e.id) ? es.map(x => (x.id === e.id ? e : x)) : [...es, e]).sort((a, b) => a.chapter - b.chapter)); setDirty(true); setEditing(null); setTimeout(() => jump(e.chapter), 50) }} />}
          {editing && <TimelineReference key={editing.id} projectId={projectId} ev={editing} />}
          {viewTree && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontWeight: 700, fontSize: 12.5 }}>{viewTree.title} <span style={{ ...muted, fontWeight: 400 }}>(Plot tree, ch {viewTree.chapter})</span></div>
              <div style={{ fontSize: 11.5 }}><b>What he sees:</b> {viewTree.mc_sees || '—'}</div>
              <div style={{ fontSize: 11.5 }}><b>The truth:</b> {viewTree.text || '—'}</div>
              <div style={muted}>Edit this slip in the Plot tab.</div>
              <button style={{ ...btn, alignSelf: 'flex-start' }} onClick={() => setViewTree(null)}>Close</button>
            </div>
          )}
        </div>
      )}

      <div ref={listRef} style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
        {data.arcs.map(a => {
          const info = arcInfo[String(a.volume)] || {}
          const chs = []
          for (let c = a.chapters[0]; c <= a.chapters[1]; c += 1) if (showEmpty || byChapter.has(c)) chs.push(c)
          return (
            <div key={a.volume} style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', overflow: 'hidden', flexShrink: 0 }}>
              <div data-ch={a.chapters[0]} style={{ background: arcColor(a.volume), color: '#efe4c8', padding: '8px 12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
                  <span style={{ fontWeight: 700, fontSize: 13 }}>Arc {a.volume}{data.arc_labels?.[a.volume - 1] ? `: ${data.arc_labels[a.volume - 1]}` : ''}{info.place ? `, ${info.place}` : ''}</span>
                  <span style={{ fontSize: 10.5, opacity: 0.85 }}>chapters {a.chapters[0]}-{a.chapters[1]}
                    <button onClick={() => setEditArc(editArc === a.volume ? null : a.volume)} style={{ marginLeft: 8, fontSize: 10, background: 'none', border: '1px solid rgba(255,255,255,0.3)', color: '#efe4c8', borderRadius: 3, padding: '0 6px' }}>✎</button>
                    <button onClick={() => openSuggest(a)} title="Suggest this stretch's events" style={{ marginLeft: 6, fontSize: 10, background: 'none', border: '1px solid rgba(255,255,255,0.3)', color: '#efe4c8', borderRadius: 3, padding: '0 6px' }}>✨ Suggest</button></span>
                </div>
                {info.realm && <div style={{ fontSize: 11, marginTop: 3 }}>{hero}: <b>{info.realm}</b></div>}
                {(info.fights || info.escapes || info.untouchable) && (
                  <div style={{ fontSize: 10.5, marginTop: 2, opacity: 0.9, lineHeight: 1.5 }}>
                    {info.fights && <div>Can fight: {info.fights}</div>}
                    {info.escapes && <div>Can only escape: {info.escapes}</div>}
                    {info.untouchable && <div>Untouchable: {info.untouchable}</div>}
                  </div>
                )}
                {sugFor?.volume === a.volume && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 8 }}>
                    <label style={{ fontSize: 10, color: '#efe4c8', width: 76 }}>From ch
                      <input style={field} inputMode="numeric" value={sugFor.first} onChange={e => setSugFor(s => ({ ...s, first: parseInt(e.target.value, 10) || a.chapters[0] }))} /></label>
                    <label style={{ fontSize: 10, color: '#efe4c8', width: 76 }}>To ch
                      <input style={field} inputMode="numeric" value={sugFor.last} onChange={e => setSugFor(s => ({ ...s, last: parseInt(e.target.value, 10) || s.first }))} /></label>
                    <label style={{ fontSize: 10, color: '#efe4c8', flex: '1 1 200px' }}>Anything you want in it (optional)
                      <input style={field} value={sugFor.note} placeholder="e.g. a sect tournament, he loses once" onChange={e => setSugFor(s => ({ ...s, note: e.target.value }))} /></label>
                    <button style={primary} disabled={!!busy || sugFor.last < sugFor.first} onClick={suggest}>{busy === 'suggest' ? 'Thinking like an author…' : 'Suggest events'}</button>
                    <span style={{ fontSize: 10, color: '#efe4c8', opacity: 0.85, width: '100%' }}>Up to 80 chapters at a time. Uses your arcs, Plot tree pins, canon and events, plus how comparable published novels pace this stretch.</span>
                  </div>
                )}
                {editArc === a.volume && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 6, marginTop: 8 }}>
                    {[['place', 'Where he is'], ['realm', 'His realm'], ['fights', 'Can fight'], ['escapes', 'Can only escape'], ['untouchable', 'Untouchable']].map(([k, l]) => (
                      <label key={k} style={{ fontSize: 10, color: '#efe4c8' }}>{l}
                        <input style={field} value={info[k] || ''} onChange={e => { setArcInfo(x => ({ ...x, [a.volume]: { ...(x[a.volume] || {}), [k]: e.target.value } })); setDirty(true) }} /></label>
                    ))}
                  </div>
                )}
              </div>
              <div style={{ background: 'var(--bg-card)' }}>
                {chs.length === 0 && <div style={{ ...muted, padding: '8px 12px' }}>Nothing on this arc yet.</div>}
                {chs.map(c => {
                  const evs = (byChapter.get(c) || []).filter(e => !e._cont || showEmpty)
                  return (
                    <div key={c} data-ch={c} style={{ display: 'flex', gap: 10, padding: '6px 12px', borderTop: '1px solid var(--border-soft)', alignItems: 'flex-start' }}>
                      <button onClick={() => setEditing({ id: newId(), chapter: c, end_chapter: null, category: 'fight', title: '', mc_sees: '', text: '' })}
                        title="Add an event to this chapter" style={{ width: 54, flexShrink: 0, textAlign: 'left', fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)', background: 'none', border: 'none', padding: '4px 0', cursor: 'pointer' }}>Ch {c}</button>
                      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {evs.length === 0 && <span style={{ ...muted, padding: '4px 0' }}>—</span>}
                        {evs.map(e => (e._sug
                          ? (!e._cont && <SuggestChip key={e.id} ev={e} truth={truth} onAccept={() => accept(e)} onDecline={() => decline(e)} />)
                          : <Chip key={e.id + (e._cont ? '-c' : '')} ev={e} truth={truth}
                            onClick={() => (e.from_tree ? setViewTree(e) : setEditing(events.find(x => x.id === e.id)))} />
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
