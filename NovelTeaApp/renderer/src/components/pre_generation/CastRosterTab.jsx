import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import { CorpusMechanicsSearch } from '../corpus/CorpusMechanics'

// Cast roster (Pre-generation): everyone who is not an enemy, each with the chapter they are introduced in, planned at the pace the book's
// style novel introduces new people. Generate drafts new characters for an arc as proposals (accept / decline); Find likeness shows the
// closest characters in the corpus with a real line of theirs. A character's intro chapter goes to that chapter's planner and writer.

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = { fontSize: 10.5, padding: '4px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const field = { width: '100%', padding: '5px 8px', fontSize: 11.5, borderRadius: 4, boxSizing: 'border-box' }
const ROLE_COLORS = { protagonist: '#c8a24a', ally: '#4f9a3a', mentor: '#4a76b0', 'rival-ally': '#d08a2b', 'love interest': '#c0466a', merchant: '#2e9aa6',
  'comic relief': '#8b5cf6', neutral: '#7a7a7a', supporting: '#5a7f9a', antagonist: '#c2412d', noble: '#a07c3a' }
const roleColor = r => ROLE_COLORS[String(r || '').toLowerCase()] || '#5a7f9a'
const TIERS = ['major', 'supporting', 'minor']

function Editor({ c, onChange, onDelete, projectId, arcs, stints }) {
  const set = (k, v) => onChange({ ...c, [k]: v })
  const [matches, setMatches] = useState(null)
  const [busy, setBusy] = useState(false)
  const find = async () => {
    setBusy(true)
    try { const r = await api.castLikeness(projectId, `${c.role} ${c.archetype} ${(c.personality_traits || []).join(' ')} ${c.motivation}`); setMatches(r.matches) }
    catch (e) { setMatches([]) } finally { setBusy(false) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 0' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6 }}>
        <label style={muted}>Name<input style={field} value={c.name || ''} onChange={e => set('name', e.target.value)} /></label>
        <label style={muted}>Role<input style={field} value={c.role || ''} onChange={e => set('role', e.target.value)} /></label>
        <label style={muted}>Tier<select style={field} value={c.tier || 'supporting'} onChange={e => set('tier', e.target.value)}>{TIERS.map(t => <option key={t}>{t}</option>)}</select></label>
        <label style={muted}>Introduced in chapter<input style={field} inputMode="numeric" value={c.intro_chapter ?? ''} placeholder="already in play" onChange={e => set('intro_chapter', parseInt(e.target.value, 10) || null)} /></label>
        <label style={muted}>Faction<input style={field} value={c.faction || ''} onChange={e => set('faction', e.target.value)} /></label>
      </div>
      <label style={muted}>Who they are<textarea rows={2} style={field} value={c.archetype || ''} onChange={e => set('archetype', e.target.value)} /></label>
      <label style={muted}>What they want<input style={field} value={c.motivation || ''} onChange={e => set('motivation', e.target.value)} /></label>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 6 }}>
        <label style={muted}>Traits (comma separated)<input style={field} value={(c.personality_traits || []).join(', ')} onChange={e => set('personality_traits', e.target.value.split(',').map(x => x.trim()).filter(Boolean))} /></label>
        <label style={muted}>How they speak<input style={field} value={c.speech_style || ''} onChange={e => set('speech_style', e.target.value)} /></label>
      </div>
      {c.likeness && <div style={muted}>Modelled on: {c.likeness}</div>}
      <label style={muted}>Voice (how they talk; the writer gets this for every chapter they are in)<textarea rows={2} style={field} value={c.voice || ''} onChange={e => set('voice', e.target.value)} /></label>
      <label style={muted}>Sample lines (one per line; they show the voice, the writer never repeats them)<textarea rows={3} style={field} value={(c.voice_lines || []).join('\n')} onChange={e => set('voice_lines', e.target.value.split('\n'))} /></label>
      {c.voice_from && <div style={muted}>Voice adapted from: {c.voice_from}</div>}
      <div style={muted}>Around in: {stints && stints.length ? stints.map(([a, b]) => `ch ${a}-${b}`).join(', ') : 'not scheduled'}</div>
      <div>
        <div style={{ ...muted, fontWeight: 700 }}>Journey across the arcs</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
          {(arcs || []).filter(a => !c.intro_chapter || a.chapters[1] >= c.intro_chapter).map(a => {
            const j = (c.journey || []).find(x => x.arc === a.arc) || { arc: a.arc, standing: '', realm: '', note: '' }
            const setJ = (k, v) => {
              const rest = (c.journey || []).filter(x => x.arc !== a.arc)
              const nj = { ...j, [k]: v }
              set('journey', (nj.standing || nj.realm || nj.note ? [...rest, nj] : rest).sort((x, y) => x.arc - y.arc))
            }
            return (
              <div key={a.arc} style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ width: 44, fontSize: 10.5, color: 'var(--text-muted)' }}>Arc {a.arc}</span>
                <select style={{ ...field, width: 110 }} value={j.standing} onChange={e => setJ('standing', e.target.value)}>
                  {['', 'stranger', 'ally', 'friend', 'rival', 'love', 'enemy', 'betrayed', 'absent', 'dead', 'ascended'].map(o => <option key={o} value={o}>{o || '—'}</option>)}
                </select>
                <input style={{ ...field, width: 150 }} placeholder="realm" value={j.realm} onChange={e => setJ('realm', e.target.value)} />
                <input style={{ ...field, flex: '1 1 180px' }} placeholder="what they do this arc" value={j.note} onChange={e => setJ('note', e.target.value)} />
              </div>
            )
          })}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label style={{ ...muted, width: 110 }}>Exit chapter<input style={field} inputMode="numeric" value={c.exit?.chapter ?? ''} placeholder="stays to the end"
          onChange={e => { const v = parseInt(e.target.value, 10); set('exit', v ? { kind: 'leaves', note: '', ...(c.exit || {}), chapter: v } : null) }} /></label>
        {c.exit && <label style={{ ...muted, width: 120 }}>How<select style={field} value={c.exit.kind} onChange={e => set('exit', { ...c.exit, kind: e.target.value })}>
          {['leaves', 'dies', 'betrays', 'ascends'].map(o => <option key={o}>{o}</option>)}</select></label>}
        {c.exit && <label style={{ ...muted, flex: '1 1 180px' }}>Note<input style={field} value={c.exit.note || ''} onChange={e => set('exit', { ...c.exit, note: e.target.value })} /></label>}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button style={btn} disabled={busy} onClick={find}>{busy ? 'Searching the corpus…' : 'Find likeness in the corpus'}</button>
        {onDelete && <button style={{ ...btn, color: 'var(--red)', marginLeft: 'auto' }} onClick={onDelete}>Remove from cast</button>}
      </div>
      {matches && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {matches.length === 0 && <div style={muted}>No close matches.</div>}
          {matches.map((m, i) => (
            <div key={i} style={{ padding: '6px 8px', border: '1px solid var(--border-soft)', borderRadius: 4, background: 'var(--bg-surface)' }}>
              <div style={{ fontSize: 11.5, fontWeight: 600 }}>{m.name} <span style={{ ...muted, fontWeight: 400 }}>({m.novel.replace(/_/g, ' ')}, {m.role})</span></div>
              <div style={{ fontSize: 10.5, color: 'var(--text-secondary)' }}>{m.notes}</div>
              {m.line && <div style={{ fontSize: 10.5, fontStyle: 'italic', color: 'var(--text-muted)', marginTop: 2 }}>"{m.line}"</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function CastRosterTab({ projectId }) {
  const [data, setData] = useState(null)
  const [cast, setCast] = useState([])
  const [pending, setPending] = useState([])
  const [decisions, setDecisions] = useState({})
  const [open, setOpen] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [filter, setFilter] = useState('')
  const [pj, setPj] = useState({})
  const [pv, setPv] = useState({})
  const [vdec, setVdec] = useState({})
  const [jdec, setJdec] = useState({})
  const [showFlags, setShowFlags] = useState(false)
  const rev = useRef(null)

  const load = useCallback(() => api.castRoster(projectId).then(r => {
    setData(r); setCast(r.cast || []); setPending(r.pending || []); setPj(r.pending_journeys || {}); setPv(r.pending_voices || {}); rev.current = r.rev; setDirty(false); setErr('')
  }).catch(e => setErr(e.message || 'Could not load the cast')), [projectId])
  useEffect(() => { load() }, [load])

  async function run(name, fn) {
    setBusy(name); setErr(''); setMsg('')
    try { await fn() } catch (e) { setErr(e.message || 'That failed'); if (String(e.message || '').includes('changed since')) load() } finally { setBusy('') }
  }
  const persist = async (c, p) => { const r = await api.castSave(projectId, c, p, rev.current); rev.current = r.rev; setCast(r.cast); setPending(r.pending); setDirty(false); return r }
  const save = () => run('save', async () => { await persist(cast, pending); setMsg('✓ Saved. Each new character goes to the planner and writer of their intro chapter.') })
  const undo = () => run('undo', async () => { const r = await api.castUndo(projectId); rev.current = r.rev; setCast(r.cast); setPending(r.pending); setMsg('Undone.') })
  const generate = (a) => run('gen' + a.arc, async () => {
    if (dirty) await persist(cast, pending)
    const r = await api.castGenerate(projectId, a.chapters[0], a.chapters[1], null, note)
    rev.current = r.rev; setPending(r.pending); setDecisions({})
    setMsg(`${r.added} new characters proposed for arc ${a.arc}${r.dropped?.length ? ` (${r.dropped.length} dropped: name already used or taken from the corpus)` : ''}. Accept or decline them below.`)
  })
  const giveVoices = () => run('voices', async () => {
    if (dirty) await persist(cast, pending)
    const r = await api.castVoices(projectId); rev.current = r.rev; setPv(r.pending_voices || {}); setVdec({})
    setMsg(`Voices proposed for ${Object.keys(r.pending_voices || {}).length} characters. Accept or decline them below.`)
  })
  const decideVoices = () => run('vdecide', async () => {
    const accept = Object.keys(vdec).filter(n => vdec[n] === 'accept'), decline = Object.keys(vdec).filter(n => vdec[n] === 'decline')
    const r = await api.castVoiceDecide(projectId, accept, decline, rev.current); rev.current = r.rev; setCast(r.cast); setPv(r.pending_voices || {}); setVdec({})
    setMsg(`✓ ${accept.length} voices added.`); load()
  })
  const planJourneys = () => run('journeys', async () => {
    if (dirty) await persist(cast, pending)
    const r = await api.castJourneys(projectId); rev.current = r.rev; setPj(r.pending_journeys || {}); setJdec({})
    setMsg(`Journeys proposed for ${Object.keys(r.pending_journeys || {}).length} characters. Accept or decline them below.`)
  })
  const decideJourneys = () => run('jdecide', async () => {
    const accept = Object.keys(jdec).filter(n => jdec[n] === 'accept'), decline = Object.keys(jdec).filter(n => jdec[n] === 'decline')
    const r = await api.castJourneyDecide(projectId, accept, decline, rev.current); rev.current = r.rev; setCast(r.cast); setPj(r.pending_journeys || {}); setJdec({})
    setMsg(`✓ ${accept.length} journeys added.`); load()
  })
  const post = () => run('post', async () => {
    const keep = pending.filter(c => decisions[c.id] === 'accept')
    const rest = pending.filter(c => !decisions[c.id])
    await persist([...cast, ...keep.map(({ id, ...c }) => c)], rest)
    setDecisions({}); setMsg(`✓ ${keep.length} characters added to the cast.`)
  })

  const arcOf = ch => (data?.arcs || []).find(a => ch >= a.chapters[0] && ch <= a.chapters[1])?.arc
  const shown = useMemo(() => cast.map((c, i) => ({ c, i })).filter(({ c }) => !filter || `${c.name} ${c.role} ${c.faction} ${c.archetype}`.toLowerCase().includes(filter.toLowerCase())), [cast, filter])
  const groups = useMemo(() => {
    const g = new Map([[0, []]]); (data?.arcs || []).forEach(a => g.set(a.arc, []))
    shown.forEach(x => { const a = x.c.intro_chapter ? (arcOf(x.c.intro_chapter) || 0) : 0; if (!g.has(a)) g.set(a, []); g.get(a).push(x) })
    g.forEach(list => list.sort((a, b) => (a.c.intro_chapter || 0) - (b.c.intro_chapter || 0)))
    return g
  }, [shown, data]) // eslint-disable-line

  if (err && !data) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!data) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  const rate = data.rate
  const accepted = pending.filter(c => decisions[c.id] === 'accept').length

  const row = (c, i) => (
    <div key={(c.id || c.name) + i} style={{ borderTop: '1px solid var(--border-soft)', padding: '6px 12px' }}>
      <button onClick={() => setOpen(open === i ? null : i)} style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', textAlign: 'left', background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text-primary)' }}>
        <span style={{ width: 4, alignSelf: 'stretch', borderRadius: 2, background: roleColor(c.role) }} />
        <span style={{ width: 52, fontSize: 10.5, color: 'var(--text-muted)' }}>{c.intro_chapter ? `ch ${c.intro_chapter}` : 'in play'}</span>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{c.name}</span>
        <span style={{ fontSize: 10.5, color: roleColor(c.role) }}>{c.role}</span>
        {c.tier && c.tier !== 'supporting' && <span style={{ fontSize: 9.5, color: 'var(--text-muted)' }}>{c.tier}</span>}
        <span style={{ ...muted, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.faction}</span>
      </button>
      {open === i && <Editor c={c} projectId={projectId} arcs={data.arcs} stints={data.stints?.[c.name]} onChange={n => { setCast(cs => cs.map((x, j) => (j === i ? n : x))); setDirty(true) }}
        onDelete={() => { setCast(cs => cs.filter((_, j) => j !== i)); setOpen(null); setDirty(true) }} />}
    </div>
  )

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
      <details style={{ flexShrink: 0 }}>
        <summary style={{ fontSize: 12, fontWeight: 700, cursor: 'pointer', padding: '4px 0' }}>📚 How the corpus uses a character like this</summary>
        <CorpusMechanicsSearch kind="cast" title="Corpus allies and cast"
          intro="Every named character in the corpus's built chapters, with the role they play there, what they do, why (purpose and motive), how their bond with the hero changes, and their real lines. Filter by novel and chapter; click a chapter or a line to read the raw passage."
          placeholder="e.g. a loyal servant who escalates the hero's insults · a mentor who doubts him, then is won over" />
      </details>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 12, display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>Cast roster</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button style={btn} onClick={() => { setCast(cs => [...cs, { name: 'New character', role: 'ally', tier: 'supporting', intro_chapter: null, faction: '', archetype: '', motivation: '', personality_traits: [] }]); setOpen(cast.length); setDirty(true) }}>＋ Add character</button>
            <button style={btn} disabled={!!busy} onClick={undo}>↶ Undo</button>
            <button style={primary} disabled={!!busy || !dirty} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
        <div style={muted}>
          Everyone who is not an enemy (enemies live in Foes). Pace from {rate.novels.map(n => n.replace(/_/g, ' ')).join(', ')}: {rate.bands.map(b => `${b.per_chapter} new named characters per chapter in chapters ${b.from}-${b.to}`).join('; ')}, about {Math.round(rate.non_enemy_share * 100)}% of them not enemies. {rate.note}
        </div>
        <div style={muted}>On stage: supporting characters stay about {data.presence?.supporting_stint} chapters after their introduction and minor ones about {data.presence?.minor_stint}; major characters are around for every arc their journey keeps them in. {data.presence?.note}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <button style={btn} onClick={() => setShowFlags(v => !v)}>{(data.flags || []).length} loose ends and gaps {showFlags ? '▴' : '▾'}</button>
          <button style={primary} disabled={!!busy} onClick={planJourneys}>{busy === 'journeys' ? 'Planning journeys… (a few minutes)' : 'Plan journeys for major characters'}</button>
          <button style={primary} disabled={!!busy} onClick={giveVoices}>{busy === 'voices' ? 'Writing voices… (a few minutes)' : `Give voices (${cast.filter(c => !(c.voice_lines || []).length).length} without)`}</button>
        </div>
        {showFlags && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {(data.flags || []).map((f, k) => (
              <div key={k} style={{ fontSize: 11, color: f.kind === 'contradiction' ? 'var(--red)' : 'var(--text-secondary)' }}>
                <b>{f.name}</b> <span style={{ color: 'var(--text-muted)' }}>({f.kind})</span>: {f.text}
              </div>
            ))}
          </div>
        )}
        <input style={field} value={note} onChange={e => setNote(e.target.value)} placeholder="Optional: steer the next generate (e.g. a love interest, an old smith who knew the hero's father)" />
        <input style={field} value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter the cast by name, role or faction" />
        {msg && <div style={{ ...muted, color: 'var(--green)' }}>{msg}</div>}
        {err && <div style={{ ...muted, color: 'var(--red)' }}>{err}</div>}
        {dirty && <div style={muted}>Unsaved changes.</div>}
      </div>

      {Object.keys(pv).length > 0 && (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-lg)', padding: 12, flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontWeight: 700, fontSize: 12.5 }}>Proposed voices for {Object.keys(pv).length} characters</span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button style={btn} onClick={() => setVdec(Object.fromEntries(Object.keys(pv).map(n => [n, 'accept'])))}>Accept all</button>
              <button style={primary} disabled={!!busy || !Object.keys(vdec).length} onClick={decideVoices}>{busy === 'vdecide' ? 'Saving…' : 'Apply decisions'}</button>
            </div>
          </div>
          {Object.entries(pv).map(([n, v]) => (
            <div key={n} style={{ padding: '6px 8px', borderTop: '1px solid var(--border-soft)', opacity: vdec[n] === 'decline' ? 0.45 : 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>{n}</div>
              {v.voice && <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{v.voice}</div>}
              {(v.voice_lines || []).map((l, k) => <div key={k} style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-secondary)' }}>“{l}”</div>)}
              {v.voice_from && <div style={{ ...muted, fontSize: 10 }}>Adapted from: {v.voice_from}</div>}
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                {['accept', 'decline'].map(d => (
                  <button key={d} onClick={() => setVdec(x => ({ ...x, [n]: d }))} aria-pressed={vdec[n] === d}
                    style={{ ...btn, ...(vdec[n] === d ? { background: d === 'accept' ? 'var(--green)' : 'var(--red)', color: '#fff', borderColor: 'transparent', fontWeight: 700 } : {}) }}>{d === 'accept' ? 'Accept' : 'Decline'}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {Object.keys(pj).length > 0 && (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-lg)', padding: 12, flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontWeight: 700, fontSize: 12.5 }}>Proposed journeys for {Object.keys(pj).length} characters</span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button style={btn} onClick={() => setJdec(Object.fromEntries(Object.keys(pj).map(n => [n, 'accept'])))}>Accept all</button>
              <button style={primary} disabled={!!busy || !Object.keys(jdec).length} onClick={decideJourneys}>{busy === 'jdecide' ? 'Saving…' : 'Apply decisions'}</button>
            </div>
          </div>
          {Object.entries(pj).map(([n, j]) => (
            <div key={n} style={{ padding: '6px 8px', borderTop: '1px solid var(--border-soft)', opacity: jdec[n] === 'decline' ? 0.45 : 1 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>{n}{j.exit ? <span style={{ ...muted, fontWeight: 400 }}> (exit: {j.exit.kind}, ch {j.exit.chapter})</span> : null}</div>
              {(j.journey || []).map(x => <div key={x.arc} style={{ fontSize: 10.5, color: 'var(--text-secondary)' }}>Arc {x.arc}: <b>{x.standing}</b>{x.realm ? `, ${x.realm}` : ''}{x.note ? `: ${x.note}` : ''}</div>)}
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                {['accept', 'decline'].map(d => (
                  <button key={d} onClick={() => setJdec(x => ({ ...x, [n]: d }))} aria-pressed={jdec[n] === d}
                    style={{ ...btn, ...(jdec[n] === d ? { background: d === 'accept' ? 'var(--green)' : 'var(--red)', color: '#fff', borderColor: 'transparent', fontWeight: 700 } : {}) }}>{d === 'accept' ? 'Accept' : 'Decline'}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {pending.length > 0 && (
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-lg)', padding: 12, flexShrink: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontWeight: 700, fontSize: 12.5 }}>{pending.length} proposed characters</span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button style={btn} onClick={() => setDecisions(Object.fromEntries(pending.map(c => [c.id, 'accept'])))}>Accept all</button>
              <button style={btn} onClick={() => setDecisions(Object.fromEntries(pending.map(c => [c.id, 'decline'])))}>Decline all</button>
              <button style={primary} disabled={!!busy || !accepted} onClick={post}>{busy === 'post' ? 'Adding…' : `Add ${accepted} to the cast`}</button>
              <button style={btn} disabled={!!busy} onClick={() => run('discard', async () => { await persist(cast, []); setMsg('Proposals discarded.') })}>Discard all</button>
            </div>
          </div>
          {pending.map(c => (
            <div key={c.id} style={{ padding: '6px 8px', borderTop: '1px solid var(--border-soft)', opacity: decisions[c.id] === 'decline' ? 0.45 : 1 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>ch {c.intro_chapter}</span>
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>{c.name}</span>
                <span style={{ fontSize: 10.5, color: roleColor(c.role) }}>{c.role}, {c.tier}</span>
                <span style={muted}>{c.faction}</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{c.archetype}</div>
              {c.likeness && <div style={muted}>Modelled on {c.likeness}</div>}
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                {['accept', 'decline'].map(d => (
                  <button key={d} onClick={() => setDecisions(x => ({ ...x, [c.id]: d }))} aria-pressed={decisions[c.id] === d}
                    style={{ ...btn, ...(decisions[c.id] === d ? { background: d === 'accept' ? 'var(--green)' : 'var(--red)', color: '#fff', borderColor: 'transparent', fontWeight: 700 } : {}) }}>{d === 'accept' ? 'Accept' : 'Decline'}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {[...groups.entries()].map(([a, list]) => {
        const arc = data.arcs.find(x => x.arc === a)
        const planned = arc ? cast.filter(c => c.intro_chapter && arcOf(c.intro_chapter) === a).length : list.length
        return (
          <div key={a} style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', overflow: 'hidden', flexShrink: 0, background: 'var(--bg-card)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center', padding: '8px 12px', background: 'var(--bg-elevated)' }}>
              <span style={{ fontWeight: 700, fontSize: 12.5 }}>{arc ? `Arc ${a} (chapters ${arc.chapters[0]}-${arc.chapters[1]})` : 'Already in play (no intro chapter)'}</span>
              {arc && (
                <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: 10.5, color: planned >= arc.target ? 'var(--green)' : 'var(--text-muted)' }}>{planned} of {arc.target} new characters at the pace</span>
                  <button style={primary} disabled={!!busy} onClick={() => generate(arc)}>{busy === 'gen' + a ? 'Generating… (a few minutes)' : `Generate ${Math.max(1, arc.target - planned)}`}</button>
                </span>
              )}
            </div>
            {list.length === 0 && <div style={{ ...muted, padding: '8px 12px' }}>No characters introduced here yet.</div>}
            {list.map(({ c, i }) => row(c, i))}
          </div>
        )
      })}
    </div>
  )
}
