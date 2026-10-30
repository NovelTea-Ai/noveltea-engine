import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import { CorpusMechanicsSearch } from '../corpus/CorpusMechanics'

// The project Antagonists tab (Pre-generation): the standing plan of the people and forces that get in the hero's way, from the petty
// annoyance to the hidden mastermind. It is always in the prompts (chapter planning, chapter writing, the final plan gate). Built from the
// corpus's own antagonist research; any named corpus antagonist can be looked up in full, live.

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = {
  fontSize: 10.5, padding: '4px 11px', borderRadius: 'var(--radius-sm)',
  background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
}
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const TIER_COLOR = { annoyance: 'var(--amber)', rival: 'var(--cyan)', enemy: 'var(--red)', nemesis: '#a855f7', boss: '#ef4444' }
const pill = color => ({
  fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 10, textTransform: 'uppercase',
  letterSpacing: '0.04em', color, border: `1px solid ${color}`, whiteSpace: 'nowrap',
})
const FIELDS = [
  ['who', 'Who they are'], ['personality', 'Personality'], ['speech', 'How they talk'], ['tells', 'Tells'], ['wants', 'Wants'],
  ['strength', 'Strength'], ['weakness', 'Weakness'], ['comeuppance', 'How they are faced'], ['ties', 'Ties in this world'],
]
const LISTS = [['how_they_obstruct', 'How they get in the hero\'s way'], ['annoyance_beats', 'Recurring nuisance beats'], ['escalation', 'Escalation ladder']]
const asLines = v => (Array.isArray(v) ? v : (v ? [v] : [])).join('\n')

function Card({ title, action, children }) {
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.06em', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{title}</span>
        {action}
      </div>
      {children}
    </div>
  )
}

function Entry({ e, onEdit, onDelete, onProfile }) {
  const [open, setOpen] = useState(false)
  const col = TIER_COLOR[e.tier] || 'var(--text-muted)'
  return (
    <div style={{ border: '1px solid var(--border-soft)', borderLeft: `3px solid ${col}`, borderRadius: 'var(--radius)', padding: '9px 11px', background: 'var(--bg-elevated)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <b style={{ fontSize: 12.5 }}>{e.name}</b>
        <span style={pill(col)}>{e.tier}</span>
        {e.archetype && <span style={{ ...muted, fontStyle: 'italic' }}>{e.archetype}</span>}
        <span style={{ ...muted, marginLeft: 'auto' }}>
          {e.first_chapter ? `from ch ${e.first_chapter}` : ''}{e.active_chapters ? ` · active ${e.active_chapters}` : ''}{e.status && e.status !== 'planned' ? ` · ${e.status}` : ''}
        </span>
      </div>
      {e.who && <div style={{ fontSize: 11.5, marginTop: 4, lineHeight: 1.5 }}>{e.who}</div>}
      {(e.how_they_obstruct || []).length > 0 && (
        <div style={{ ...muted, marginTop: 4 }}><b>Gets in the way:</b> {(e.how_they_obstruct || []).join(' · ')}</div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
        <button style={btn} onClick={() => setOpen(o => !o)}>{open ? 'Hide detail' : 'Detail'}</button>
        <button style={btn} onClick={() => onEdit(e)}>✎ Edit</button>
        <button style={{ ...btn, color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => onDelete(e)}>✕</button>
      </div>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5, fontSize: 11, lineHeight: 1.5 }}>
          {FIELDS.map(([k, lab]) => e[k] ? <div key={k}><b style={{ color: 'var(--text-secondary)' }}>{lab}:</b> {e[k]}</div> : null)}
          {LISTS.map(([k, lab]) => (e[k] || []).length > 0 ? (
            <div key={k}><b style={{ color: 'var(--text-secondary)' }}>{lab}:</b>
              <ol style={{ margin: '2px 0 0 18px', padding: 0 }}>{e[k].map((x, i) => <li key={i}>{x}</li>)}</ol></div>
          ) : null)}
          {(e.corpus_sources || []).length > 0 && (
            <div><b style={{ color: 'var(--text-secondary)' }}>Adapted from the corpus:</b> {(e.corpus_sources || []).map((s, i) => <span key={i} style={{ ...muted, marginRight: 8 }}>{String(s)}</span>)}</div>
          )}
        </div>
      )}
    </div>
  )
}

function EditModal({ entry, onSave, onClose }) {
  const [f, setF] = useState(() => ({ ...entry, ...Object.fromEntries(LISTS.map(([k]) => [k, asLines(entry[k])])) }))
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const field = { width: '100%', padding: '5px 8px', fontSize: 11.5, borderRadius: 4, boxSizing: 'border-box' }
  function save() {
    const out = { ...f }
    LISTS.forEach(([k]) => { out[k] = String(f[k] || '').split('\n').map(s => s.trim()).filter(Boolean) })
    out.first_chapter = f.first_chapter === '' || f.first_chapter == null ? null : Number(f.first_chapter)
    onSave(out)
  }
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 300, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12 }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 16, width: 'min(640px, 100%)', maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <input style={{ ...field, flex: 1, minWidth: 160 }} placeholder="Name" value={f.name || ''} onChange={e => set('name', e.target.value)} />
          <select style={{ ...field, width: 120 }} value={f.tier || 'annoyance'} onChange={e => set('tier', e.target.value)}>
            {['annoyance', 'rival', 'enemy', 'nemesis', 'boss'].map(t => <option key={t}>{t}</option>)}
          </select>
          <input style={{ ...field, width: 90 }} placeholder="First ch" type="number" value={f.first_chapter ?? ''} onChange={e => set('first_chapter', e.target.value)} />
          <input style={{ ...field, width: 100 }} placeholder="Active 1-10" value={f.active_chapters || ''} onChange={e => set('active_chapters', e.target.value)} />
        </div>
        <input style={{ ...field, marginBottom: 8 }} placeholder="Archetype" value={f.archetype || ''} onChange={e => set('archetype', e.target.value)} />
        {FIELDS.map(([k, lab]) => (
          <div key={k} style={{ marginBottom: 7 }}>
            <div style={muted}>{lab}</div>
            <textarea rows={2} style={field} value={f[k] || ''} onChange={e => set(k, e.target.value)} />
          </div>
        ))}
        {LISTS.map(([k, lab]) => (
          <div key={k} style={{ marginBottom: 7 }}>
            <div style={muted}>{lab} (one per line)</div>
            <textarea rows={3} style={field} value={f[k] || ''} onChange={e => set(k, e.target.value)} />
          </div>
        ))}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button style={btn} onClick={onClose}>Cancel</button>
          <button style={primary} onClick={save} disabled={!String(f.name || '').trim()}>Save</button>
        </div>
      </div>
    </div>
  )
}

function ProfileView({ profile }) {
  if (!profile) return null
  return (
    <div style={{ marginTop: 8, padding: 10, background: 'var(--bg-elevated)', borderRadius: 'var(--radius)', fontSize: 11, lineHeight: 1.55 }}>
      <b>{profile.name}</b> <span style={muted}>[{profile.novel_id || 'corpus'}]</span>
      {!profile.entity && !(profile.templates || []).length && !(profile.passages || []).length && <div style={muted}>The corpus holds nothing more on this name.</div>}
      {profile.entity && <div>{profile.entity.role || profile.entity.type}{(profile.entity.aliases || []).length ? ` · aka ${(profile.entity.aliases || []).join(', ')}` : ''} {profile.entity.notes}</div>}
      {(profile.entity?.facts || []).map((f, i) => <div key={i} style={muted}>- {f}</div>)}
      {profile.character_profile && <div style={muted}>Profile: {(profile.character_profile.traits || []).join('; ')}</div>}
      {(profile.templates || []).map((t, i) => <div key={i} style={{ marginTop: 4 }}><b>{t.template_id}</b> (ch {JSON.stringify(t.chapters)}): {t.pattern}<div style={muted}>{t.variation_notes}</div></div>)}
      {(profile.passages || []).map((p, i) => <div key={i} style={muted}>[{p.kind} ch{p.chapter}] {p.text}</div>)}
    </div>
  )
}

// All the corpus's antagonist templates, each with a brief and its characters: filter, pick, look a character up in full, build from the picks.
function Catalogue({ selected, setSelected, onBuild, busy, hasRoster }) {
  const [cat, setCat] = useState(null)
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [novel, setNovel] = useState('')
  const [onlyPicked, setOnlyPicked] = useState(false)
  const [chFrom, setChFrom] = useState('')     // chapter range: a row shows when any of its characters appears in it
  const [chTo, setChTo] = useState('')
  const [limit, setLimit] = useState(40)
  const [profile, setProfile] = useState(null)
  const [profileFor, setProfileFor] = useState('')
  const [looking, setLooking] = useState('')
  useEffect(() => { api.antagonistsCatalogue().then(setCat).catch(e => setErr(e.message || 'Could not load the catalogue')) }, [])
  if (err) return <Card title="Corpus antagonists catalogue"><div style={{ ...muted, color: 'var(--red)' }}>{err}</div></Card>
  if (!cat) return <Card title="Corpus antagonists catalogue"><div style={muted}>Loading the catalogue…</div></Card>
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const lo = chFrom === '' ? null : Number(chFrom), hi = chTo === '' ? null : Number(chTo)
  const chs = e => (Array.isArray(e.chapters) ? e.chapters : []).map(Number).filter(n => Number.isFinite(n))
  const inRange = r => (lo == null && hi == null) || r.entities.some(e => chs(e).some(n => (lo == null || n >= lo) && (hi == null || n <= hi)))
  const rows = cat.rows.filter(r => (!novel || r.novel === novel) && (!onlyPicked || selected.has(r.key)) && inRange(r) && words.every(w =>
    (r.brief + ' ' + r.pattern + ' ' + r.template_id + ' ' + r.novel + ' ' + r.entities.map(e => e.name).join(' ')).toLowerCase().includes(w)))
  const toggle = k => setSelected(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  async function look(name, novelId, key) {
    setLooking(name); setProfileFor(key)
    try { setProfile(await api.antagonistsProfile(name, novelId)) } catch (e) { setProfile({ name, novel_id: novelId }) } finally { setLooking('') }
  }
  return (
    <Card title={`Corpus antagonists catalogue · ${cat.total}`} action={
      <button style={primary} disabled={!selected.size || !!busy} onClick={onBuild}
        title="Adapt every selected corpus antagonist into this book's roster">
        {busy === 'picked' ? '✦ Adapting… (a few minutes)' : `✦ ${hasRoster ? 'Add' : 'Build'} from ${selected.size} selected`}
      </button>}>
      <div style={{ ...muted, marginBottom: 8 }}>Every recurring antagonist pattern in the corpus, with the characters who play it. Tick the ones you want, click a name to see everything the corpus holds on that character, then build. Names are never copied: each pick's situation, status, intentions and methods are adapted into a new person of your world.</div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        <input value={q} onChange={e => { setQ(e.target.value); setLimit(40) }} placeholder="Filter: young master, clerk, elder, betrayal, a name…"
          style={{ flex: 1, minWidth: 180, padding: '5px 9px', fontSize: 11.5, borderRadius: 4 }} />
        <select value={novel} onChange={e => { setNovel(e.target.value); setLimit(40) }} style={{ fontSize: 11, padding: '4px 6px', borderRadius: 4, maxWidth: 220 }}>
          <option value="">All {cat.novels.length} novels</option>
          {cat.novels.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <span style={{ ...muted, display: 'flex', alignItems: 'center', gap: 4 }}
          title="Only patterns with a character appearing in these chapters (leave either box empty for an open end)">
          ch
          <input type="number" min={1} value={chFrom} placeholder="from" onChange={e => { setChFrom(e.target.value); setLimit(40) }}
            style={{ width: 56, padding: '4px 5px', fontSize: 11, borderRadius: 4 }} />
          –
          <input type="number" min={1} value={chTo} placeholder="to" onChange={e => { setChTo(e.target.value); setLimit(40) }}
            style={{ width: 56, padding: '4px 5px', fontSize: 11, borderRadius: 4 }} />
        </span>
        <label style={{ ...muted, display: 'flex', alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={onlyPicked} onChange={e => setOnlyPicked(e.target.checked)} /> selected only
        </label>
        {selected.size > 0 && <button style={btn} onClick={() => setSelected(new Set())}>Clear {selected.size}</button>}
      </div>
      <div style={{ ...muted, marginBottom: 6 }}>{rows.length} shown</div>
      {rows.slice(0, limit).map(r => (
        <div key={r.key} style={{ borderTop: '1px solid var(--border-soft)', padding: '7px 0', fontSize: 11.5, lineHeight: 1.5,
          background: selected.has(r.key) ? 'var(--accent-dim)' : 'transparent' }}>
          <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer' }}>
            <input type="checkbox" checked={selected.has(r.key)} onChange={() => toggle(r.key)} style={{ marginTop: 3 }} />
            <span style={{ flex: 1 }}>
              <b>{nice(r.template_id)}</b> <span style={muted}>· {r.novel} · {r.instances} appearance{r.instances !== 1 ? 's' : ''}</span>
              <div>{r.brief}</div>
            </span>
          </label>
          <div style={{ display: 'flex', gap: 5, marginTop: 4, marginLeft: 24, flexWrap: 'wrap' }}>
            {r.entities.map(e => (
              <button key={e.name} style={{ ...btn, padding: '2px 8px' }} disabled={looking === e.name}
                onClick={() => look(e.name, r.novel_id, r.key)} title="Look up everything the corpus holds about this character">
                {looking === e.name ? '…' : '🔎'} {e.name}
                {chs(e).length > 0 && <span style={muted}> · ch {Math.min(...chs(e))}{chs(e).length > 1 ? `–${Math.max(...chs(e))}` : ''}</span>}
              </button>
            ))}
          </div>
          {profileFor === r.key && profile && <div style={{ marginLeft: 24 }}><ProfileView profile={profile} /></div>}
        </div>
      ))}
      {rows.length > limit && <button style={{ ...btn, marginTop: 8 }} onClick={() => setLimit(l => l + 60)}>Show more ({rows.length - limit} left)</button>}
    </Card>
  )
}

const nice = s => String(s || '').replace(/_/g, ' ')

function CorpusSearch({ onUse }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [profile, setProfile] = useState(null)
  const [looking, setLooking] = useState('')
  async function run() {
    if (!q.trim()) return
    setBusy(true); setErr(''); setProfile(null)
    try { setHits((await api.antagonistsSearch(q.trim())).hits) } catch (e) { setErr(e.message || 'Search failed') } finally { setBusy(false) }
  }
  async function look(name, novel) {
    setLooking(name); setErr('')
    try { setProfile(await api.antagonistsProfile(name, novel)) } catch (e) { setErr(e.message || 'Lookup failed') } finally { setLooking('') }
  }
  return (
    <Card title="Search the corpus's antagonists">
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && run()}
          placeholder="e.g. a clerk who blocks him with fees · a rival who mocks him in public · a boss with a fatal flaw"
          style={{ flex: 1, padding: '5px 9px', fontSize: 11.5, borderRadius: 4 }} />
        <button style={primary} onClick={run} disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
      </div>
      {err && <div style={{ ...muted, color: 'var(--red)' }}>{err}</div>}
      {hits && hits.length === 0 && <div style={muted}>No matching antagonists found.</div>}
      {(hits || []).map((h, i) => (
        <div key={i} style={{ borderTop: i ? '1px solid var(--border-soft)' : 'none', padding: '7px 0', fontSize: 11.5, lineHeight: 1.5 }}>
          <div><b>{h.novel}</b> <span style={muted}>{Math.round(h.score * 100)}% match</span></div>
          <div>{h.pattern}</div>
          {h.variation_notes && <div style={muted}>How it escalated: {h.variation_notes}</div>}
          <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
            {(h.entities || []).map(n => (
              <button key={n} style={btn} disabled={looking === n} onClick={() => look(n, h.novel)} title="Look up everything the corpus holds about this character">
                {looking === n ? '…' : '🔎'} {n}
              </button>
            ))}
            <button style={btn} onClick={() => onUse(h)}>＋ Use as a basis</button>
          </div>
        </div>
      ))}
      <ProfileView profile={profile} />
    </Card>
  )
}

export default function AntagonistsTab({ projectId }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [edit, setEdit] = useState(null)
  const [filter, setFilter] = useState('all')
  const [msg, setMsg] = useState('')
  const [selected, setSelected] = useState(() => new Set())
  const [dec, setDec] = useState({})
  const load = useCallback(() => {
    api.antagonists(projectId).then(r => { setData(r); setErr('') }).catch(e => setErr(e.message || 'Could not load the Antagonists tab'))
  }, [projectId])
  useEffect(() => { load() }, [load])

  async function generate(mode, picked = null, arc = null) {
    setBusy(arc ? `arc${arc.arc}` : picked ? 'picked' : mode); setErr(''); setMsg('')
    try {
      const picks = picked || (selected.size ? [...selected] : null)   // the catalogue picks are used by every generate button
      const r = await api.antagonistsGenerate(projectId, mode, arc ? 8 : 12, picks, arc?.chapters[0], arc?.chapters[1])
      if (picks) setSelected(new Set())
      setData(d => ({ ...d, pending: r.pending })); setDec({})
      setMsg(`✓ ${r.proposed} foes proposed${arc ? ` for arc ${arc.arc}` : ''}, from ${r.research_used} corpus archetypes. Accept or decline them below.`)
    } catch (e) { setErr(e.message || 'Generation failed') } finally { setBusy('') }
  }
  async function decide() {
    setBusy('decide'); setErr('')
    try {
      const accept = Object.keys(dec).filter(k => dec[k] === 'accept'), decline = Object.keys(dec).filter(k => dec[k] === 'decline')
      const r = await api.antagonistsDecide(projectId, accept, decline)
      setData(d => ({ ...d, ...r })); setDec({}); setMsg(`✓ ${accept.length} foes added. The previous roster is on Undo.`)
    } catch (e) { setErr(e.message || 'Saving failed') } finally { setBusy('') }
  }
  async function persist(roster) {
    try {
      const r = await api.antagonistsSave(projectId, roster)
      setData(d => ({ ...d, overview: r.overview, rules: r.rules, roster: r.roster })); load()
    } catch (e) { setErr(e.message || 'Save failed') }
  }
  async function undo() {
    try { const r = await api.antagonistsUndo(projectId); setData(d => ({ ...d, overview: r.overview, rules: r.rules, roster: r.roster })); setMsg('Undone.') }
    catch (e) { setErr(e.message || 'Nothing to undo') }
  }
  function useAsBasis(h) {
    // The corpus character's situation and methods carry over; the name never does - the author names the adapted person.
    setEdit({ name: '', tier: 'annoyance', archetype: String(h.pattern).slice(0, 80), who: String(h.pattern).slice(0, 400),
             corpus_sources: [`${h.novel}: ${(h.entities || []).slice(0, 2).join(', ')} - ${String(h.pattern).slice(0, 120)}`], status: 'planned', _new: true })
  }

  if (err && !data) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!data) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  const roster = data.roster || []
  const shown = filter === 'all' ? roster : roster.filter(e => e.tier === filter)
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1000 }}>
        <Card title="Antagonists & obstacles" action={
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button style={primary} disabled={!!busy} onClick={() => generate(roster.length ? 'add' : 'replace')}>
              {busy === 'add' || busy === 'replace' ? '✦ Researching the corpus… (a few minutes)' : roster.length ? '✦ Fill the gaps' : '✦ Build the roster from the corpus'}
            </button>
            {roster.length > 0 && <button style={btn} disabled={!!busy} onClick={() => generate('replace')} title="Proposes a whole new roster; accepting it replaces the current one (kept on Undo)">Rebuild all</button>}
            <button style={btn} onClick={() => setEdit({ name: '', tier: 'annoyance', status: 'planned', _new: true })}>＋ Add by hand</button>
            <button style={btn} onClick={undo}>↶ Undo</button>
          </div>}>
          <div style={muted}>
            The people and forces that get in the hero's way, from the petty annoyance to the hidden mastermind. This plan is always in the prompts: every
            chapter plan, every chapter and the final plan gate see who is in play, how each one obstructs the hero, and where each one's escalation stands.
            Fill the gaps reads the arc view below (what the timeline says he fights, escapes and cannot touch in each arc, who is in play, the cast's
            antagonists with no entry) and proposes foes for the thin arcs. Everything generated is a proposal you accept or decline.
          </div>
          {data.overview && <div style={{ fontSize: 11.5, marginTop: 8, lineHeight: 1.55 }}>{data.overview}</div>}
          {(data.rules || []).length > 0 && <ul style={{ margin: '6px 0 0 18px', padding: 0, ...muted }}>{data.rules.map((r, i) => <li key={i}>{r}</li>)}</ul>}
          {msg && <div style={{ ...muted, color: 'var(--green)', marginTop: 6 }}>{msg}</div>}
          {err && <div style={{ ...muted, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
        </Card>

        {(data.pending?.roster || []).length > 0 && (
          <Card title={`Proposed foes · ${data.pending.roster.length}${data.pending.replace ? ' · rebuild (accepting replaces the roster)' : ''}`} action={
            <div style={{ display: 'flex', gap: 6 }}>
              <button style={btn} onClick={() => setDec(Object.fromEntries(data.pending.roster.map(e => [e.id, 'accept'])))}>Accept all</button>
              <button style={btn} onClick={() => setDec(Object.fromEntries(data.pending.roster.map(e => [e.id, 'decline'])))}>Decline all</button>
              <button style={primary} disabled={!!busy || !Object.keys(dec).length} onClick={decide}>{busy === 'decide' ? 'Saving…' : 'Apply decisions'}</button>
            </div>}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {data.pending.roster.map(e => (
                <div key={e.id} style={{ opacity: dec[e.id] === 'decline' ? 0.45 : 1 }}>
                  <Entry e={e} onEdit={() => {}} onDelete={() => setDec(x => ({ ...x, [e.id]: 'decline' }))} />
                  <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                    {e.realm && <span style={muted}>{e.realm}</span>}
                    {['accept', 'decline'].map(d => (
                      <button key={d} onClick={() => setDec(x => ({ ...x, [e.id]: d }))} aria-pressed={dec[e.id] === d}
                        style={{ ...btn, ...(dec[e.id] === d ? { background: d === 'accept' ? 'var(--green)' : 'var(--red)', color: '#fff', borderColor: 'transparent', fontWeight: 700 } : {}) }}>{d === 'accept' ? 'Accept' : 'Decline'}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card title="Foes by arc">
          <div style={muted}>What the timeline says the hero fights, escapes and cannot touch in each arc, the foes in play there, and the gaps.</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
            {(data.coverage || []).map(c => (
              <div key={c.arc} style={{ border: '1px solid var(--border-soft)', borderLeft: `3px solid ${c.gaps.length ? 'var(--amber)' : 'var(--green)'}`, borderRadius: 'var(--radius)', padding: '7px 10px', background: 'var(--bg-elevated)' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <b style={{ fontSize: 12 }}>Arc {c.arc}</b>
                  <span style={muted}>ch {c.chapters[0]}-{c.chapters[1]}{c.place ? ` · ${c.place}` : ''}</span>
                  <button style={{ ...btn, marginLeft: 'auto' }} disabled={!!busy} onClick={() => generate('add', null, c)}>
                    {busy === `arc${c.arc}` ? 'Planning… (a few minutes)' : 'Generate for this arc'}</button>
                </div>
                {(c.fights || c.escapes) && <div style={muted}>Fights: {c.fights || '-'} · Escapes: {c.escapes || '-'} · Untouchable: {c.untouchable || '-'}</div>}
                <div style={muted}>In play: {c.active.length ? c.active.map(a => `${a.name} (${a.tier})`).join(', ') : 'nobody'}{c.new.length ? ` · new here: ${c.new.join(', ')}` : ''}</div>
                {c.gaps.map((g, k) => <div key={k} style={{ ...muted, color: 'var(--amber)' }}>Gap: {g}</div>)}
              </div>
            ))}
          </div>
        </Card>

        <Card title={`Roster · ${roster.length}`} action={
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {['all', ...(data.tiers || [])].map(t => (
              <button key={t} onClick={() => setFilter(t)} style={{ ...btn, padding: '2px 9px', ...(filter === t ? { borderColor: 'var(--accent)', color: 'var(--accent-light)' } : {}) }}>{t}</button>
            ))}
          </div>}>
          {shown.length === 0 && <div style={muted}>{roster.length ? 'No antagonists in this tier.' : 'No roster yet. Build it from the corpus, or add one by hand.'}</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {shown.map(e => (
              <Entry key={e.id || e.name} e={e} onEdit={setEdit}
                onDelete={x => persist(roster.filter(r => r !== x))} />
            ))}
          </div>
        </Card>

        <Catalogue selected={selected} setSelected={setSelected} busy={busy} hasRoster={roster.length > 0}
          onBuild={() => generate(roster.length ? 'add' : 'replace', [...selected])} />

        <CorpusSearch onUse={useAsBasis} />

        <CorpusMechanicsSearch kind="cast" title="How corpus opponents behave, chapter by chapter"
          intro="Opponents and rivals in the corpus's built chapters: what each does in that chapter, why (purpose and motive), and their real lines. Filter by novel and chapter; click a chapter or a line for the raw passage."
          placeholder="e.g. a young master who mocks him in public, then challenges him · a rival who brings a stronger backer"
          roleFilter={r => ['opponent', 'rival', 'patron_or_backer', 'elder'].includes(r)} />
      </div>
      {edit && (
        <EditModal entry={edit} onClose={() => setEdit(null)}
          onSave={out => {
            const { _new, ...clean } = out
            persist(_new ? [...roster, clean] : roster.map(r => (r.id === edit.id && r.name === edit.name ? clean : r)))
            setEdit(null)
          }} />
      )}
    </div>
  )
}
