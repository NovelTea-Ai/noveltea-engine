import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import FightPlanCard from './FightPlanCard'

// The project Combat tab: Combat DNA measured from the corpus's own fights (it goes
// into the chapter prompt only for chapters whose plan has a fight), a free check of
// every written chapter's fights against it (the end-of-chapter polish adds what a
// fight is missing, per the switches here), and a search over the corpus's labelled
// fight passages: hits landing, attacks, threats, power reveals (no AI call).

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = {
  fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)',
  background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
}
const pill = color => ({
  fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 10, textTransform: 'uppercase',
  letterSpacing: '0.04em', color, border: `1px solid ${color}`, whiteSpace: 'nowrap',
})
const num = { width: 56, padding: '3px 6px', fontSize: 11, borderRadius: 4 }
const label = { fontSize: 10.5, color: 'var(--text-muted)', width: 190 }
const row = { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }
const nice = s => String(s || '').replace(/_/g, ' ')
const ELEMENTS = [
  ['sounds', 'Fight sounds', 'per 1,000 words of fighting'],
  ['hits', 'Hits landing on a body', 'in a fight chapter'],
  ['threats', 'Ruthless lines (threats, taunts)', 'in a fight chapter'],
  ['crowd', 'Onlookers reacting', 'in a fight chapter'],
]
const TYPE_COLOR = { combat_reaction: 'var(--red)', combat_technique: 'var(--amber)', dialogue_threat: 'var(--accent-light)', power_reveal: 'var(--green)' }
const DRAG_TYPE = 'application/x-noveltea-fight'   // a corpus fight result being dragged onto My fight moves

function Card({ title, action, children }) {
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.06em', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
          {title}
        </span>
        {action}
      </div>
      {children}
    </div>
  )
}

// part: 'pre' = everything done before writing (Combat DNA, the fight plan interview, the corpus fight search and My fight moves);
// 'post' = the free check of every written chapter's fights; omitted = the whole tab.
export default function CombatTab({ projectId, part }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = useCallback(() => {
    api.combatOverview(projectId)
      .then(r => { setData(r); setErr('') })
      .catch(e => setErr(e.message || 'Could not load the Combat tab'))
  }, [projectId])
  useEffect(() => { load() }, [load])

  const [pickErr, setPickErr] = useState('')
  const setPicks = picks => setData(d => ({ ...d, picks }))
  async function addPick(result) {
    setPickErr('')
    try { setPicks((await api.fightPickOp(projectId, 'add', { source: result })).picks) }
    catch (e) { setPickErr(e.message || 'Could not add it') }
  }

  // The tab area hides overflow; like every other tab, this one scrolls itself.
  if (err && !data) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!data) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 1040 }}>
      {part !== 'post' && <>
      <CombatDnaCard projectId={projectId} data={data} onSaved={load} />
      <FightPlanCard projectId={projectId} />
      <FightSearchCard data={data} onAdd={addPick} picked={new Set((data.picks || []).map(p => p.source?.text))} />
      <FightPicksCard projectId={projectId} data={data} picks={data.picks || []} setPicks={setPicks} onAdd={addPick} addErr={pickErr} />
      </>}
      {part !== 'pre' && <ChaptersCard data={data} />}
    </div>
    </div>
  )
}

// ── Combat DNA ────────────────────────────────────────────────────────────────

function RangeEdit({ value, onChange, step = 1 }) {
  const v = value || {}
  const set = (k, x) => onChange({ ...v, [k]: x === '' ? null : Number(x) })
  return (
    <>
      <input type="number" step={step} value={v.target ?? ''} onChange={e => set('target', e.target.value)} style={num} title="Target" />
      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>usually</span>
      <input type="number" step={step} value={v.low ?? ''} onChange={e => set('low', e.target.value)} style={num} title="Low end" />
      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>to</span>
      <input type="number" step={step} value={v.high ?? ''} onChange={e => set('high', e.target.value)} style={num} title="High end" />
    </>
  )
}

function CombatDnaCard({ projectId, data, onSaved }) {
  const [dna, setDna] = useState(data.combat_dna || {})
  const [lists, setLists] = useState({ sounds: (data.combat_dna?.top_sounds || []).join(', '), words: (data.combat_dna?.top_violent_words || []).join(', ') })
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    if (dirty) return
    setDna(data.combat_dna || {})
    setLists({ sounds: (data.combat_dna?.top_sounds || []).join(', '), words: (data.combat_dna?.top_violent_words || []).join(', ') })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.combat_dna])

  const set = (k, v) => { setDna(d => ({ ...d, [k]: v })); setDirty(true) }
  const setFix = (k, v) => set('fix_missing', { ...(dna.fix_missing || {}), [k]: v })
  const setElement = (k, wp) => set('elements', { ...(dna.elements || {}), [k]: { ...((dna.elements || {})[k] || {}), when_present: wp } })
  const split = t => t.split(',').map(s => s.trim()).filter(Boolean)

  async function save() {
    setBusy(true); setMsg('')
    try {
      await api.saveCombatDna(projectId, { ...dna, top_sounds: split(lists.sounds), top_violent_words: split(lists.words) })
      setDirty(false)
      setMsg('✓ Saved')
      onSaved()
    } catch (e) {
      setMsg(e.message || 'Could not save')
    } finally {
      setBusy(false)
      setTimeout(() => setMsg(''), 3000)
    }
  }

  if (!data.has_profile) {
    return (
      <Card title="Combat DNA">
        <div style={muted}>This project has no Author DNA yet. Set it up in the Author DNA tab first; Combat DNA is measured from the same voice source.</div>
      </Card>
    )
  }
  if (!dna || !Object.keys(dna).length) {
    return <Card title="Combat DNA"><div style={muted}>No corpus fight measurements are available yet.</div></Card>
  }
  const mix = Object.entries(dna.fight_pacing_mix || {})
  const ex = dna.examples || {}
  return (
    <Card title="Combat DNA" action={
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {msg && <span style={{ fontSize: 10, color: msg.startsWith('✓') ? 'var(--green)' : 'var(--red)' }}>{msg}</span>}
        <button className="btn-primary" disabled={busy || !dirty} onClick={save} style={{ fontSize: 10, padding: '3px 12px' }}>{busy ? '…' : 'Save'}</button>
      </div>
    }>
      <div style={{ ...muted, marginBottom: 10 }}>
        How {data.voice_source === 'whole corpus' ? 'the corpus writes' : `${data.voice_source} writes`} its fights, measured from
        {' '}{dna.measured_chapters} fight chapters' own text{dna.timing_from ? ` (rates: ${dna.timing_from})` : ''}. It goes into the
        chapter prompt only for chapters whose plan has a fight, and the end-of-chapter polish adds what a fight is missing
        wherever "add if missing" is on. Re-applying the voice source in Author DNA re-measures these.
        {!data.combat_dna_saved && <b style={{ color: 'var(--amber)' }}> Not saved in the profile yet; press Save to lock these numbers in.</b>}
      </div>

      <div style={row}>
        <span style={label}>Chapters with a fight</span>
        <span style={{ fontSize: 11 }}>{dna.fight_chapter_share != null ? `${Math.round(dna.fight_chapter_share * 100)}% of source chapters` : '—'}</span>
      </div>
      <div style={row}>
        <span style={label}>Fight pace</span>
        <span style={{ fontSize: 11 }}>
          {mix.map(([k, v]) => `${nice(k)} ${Math.round(v * 100)}%`).join(' · ') || '—'}
          {dna.fight_tension ? ` · tension about ${dna.fight_tension}/10` : ''}
        </span>
      </div>
      <div style={row}>
        <span style={label}>Words of fighting per fight chapter</span>
        <RangeEdit value={dna.fight_words} onChange={v => set('fight_words', v)} />
      </div>
      <div style={row}>
        <span style={label}>Violent words per 1,000 words of fighting</span>
        <RangeEdit value={dna.violent_per_1k} onChange={v => set('violent_per_1k', v)} step={0.1} />
        <label style={{ fontSize: 10.5, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={!!dna.fix_missing?.violent} onChange={e => setFix('violent', e.target.checked)} />
          sharpen soft fight verbs
        </label>
      </div>

      <div style={{ fontSize: 10.5, fontWeight: 700, margin: '10px 0 4px' }}>Fight elements</div>
      <div style={{ ...muted, fontSize: 10, marginBottom: 6 }}>
        How many corpus fight chapters have each one (a floor: the check only spots the corpus's commonest phrasings), and how much when they do.
      </div>
      {ELEMENTS.map(([k, name, unit]) => {
        const e = (dna.elements || {})[k] || {}
        return (
          <div key={k} style={row}>
            <span style={label}>{name}</span>
            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', width: 120 }}>in {Math.round((e.share || 0) * 100)}% of corpus fights</span>
            <RangeEdit value={e.when_present} onChange={v => setElement(k, v)} step={k === 'sounds' ? 0.1 : 1} />
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{unit}</span>
            <label style={{ fontSize: 10.5, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <input type="checkbox" checked={!!dna.fix_missing?.[k]} onChange={ev => setFix(k, ev.target.checked)} />
              add if missing
            </label>
          </div>
        )
      })}

      <div style={{ ...row, marginTop: 8 }}>
        <span style={label}>Fight sounds to draw on</span>
        <input value={lists.sounds} onChange={e => { setLists(l => ({ ...l, sounds: e.target.value })); setDirty(true) }}
          style={{ flex: 1, minWidth: 220, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
      </div>
      <div style={row}>
        <span style={label}>Violent words the corpus uses most</span>
        <input value={lists.words} onChange={e => { setLists(l => ({ ...l, words: e.target.value })); setDirty(true) }}
          style={{ flex: 1, minWidth: 220, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
      </div>
      <div style={row}>
        <span style={label}>Also measured</span>
        <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
          {dna.short_sentences_in_fights ? `short sentences (8 words or fewer) in fights: ${Math.round(dna.short_sentences_in_fights.target * 100)}%` : ''}
          {dna.swearing_share != null ? ` · ${Math.round(dna.swearing_share * 100)}% of characters swear` : ''}
        </span>
      </div>
      {['hit', 'threat', 'technique'].some(k => ex[k]?.length) && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, marginBottom: 4 }}>Corpus examples (the chapter prompt shows one of each, names never reused)</div>
          {[['hit', 'Getting hit'], ['threat', 'Ruthless speech'], ['technique', 'Attacks']].map(([k, t]) => (ex[k] || []).slice(0, 2).map((x, i) => (
            <div key={`${k}${i}`} style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 3 }}>
              <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{t}: </span>{x}
            </div>
          )))}
        </div>
      )}
    </Card>
  )
}

// ── Chapter fight check ───────────────────────────────────────────────────────

function ChaptersCard({ data }) {
  const chapters = data.chapters || []
  return (
    <Card title="Fight check" action={<span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>free · measured now</span>}>
      <div style={{ ...muted, marginBottom: 8 }}>
        Each written chapter's fights against Combat DNA. A chapter counts as having a fight when its plan has one, or
        when it has 150+ words of fighting. The end-of-chapter polish fixes what's marked missing; edits since then are
        measured here live.
      </div>
      {!chapters.length && <div style={{ ...muted, fontSize: 11 }}>No chapters written yet.</div>}
      {chapters.map(c => {
        const chk = c.check || {}
        const before = c.polish?.before?.metrics
        const after = c.polish?.after?.metrics
        return (
          <div key={c.number} style={{ borderTop: '1px solid var(--border-soft)', padding: '6px 0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 700, width: 44 }}>Ch {c.number}</span>
              {c.plan_fight && <span style={pill('var(--amber)')}>fight planned</span>}
              {!chk.fight && <span style={{ color: 'var(--text-muted)' }}>no fight</span>}
              {chk.fight && chk.missing?.length > 0 && <span style={{ color: 'var(--amber)' }}>missing: {chk.missing.join(', ')}</span>}
              {chk.fight && !chk.missing?.length && <span style={{ color: 'var(--green)' }}>✓ fight matches Combat DNA</span>}
              {before && after && (
                <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-muted)' }}>
                  polish: sounds {before.sounds}→{after.sounds}, hits {before.hits}→{after.hits}, ruthless lines {before.threats}→{after.threats}
                </span>
              )}
            </div>
            {chk.fight && (chk.signals || []).length > 0 && (
              <div style={{ margin: '4px 0 2px 6px' }}>
                {chk.signals.map((s, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '14px minmax(0, 1fr) auto', columnGap: 8, fontSize: 10.5, lineHeight: 1.55, padding: '2px 0' }}>
                    <span style={{ color: s.ok ? 'var(--green)' : 'var(--amber)', fontWeight: 700 }}>{s.ok ? '✓' : '✗'}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{s.label}</span>
                    <span style={{ fontWeight: 600, textAlign: 'right', color: s.ok ? 'var(--text-primary)' : 'var(--amber)' }}>{s.value}</span>
                    <span style={{ gridColumn: '2 / 4', fontSize: 10, color: 'var(--text-muted)' }}>target {s.target}{s.report_only ? ' · report only' : ''}{s.fix === false && !s.report_only ? ' · not added if missing' : ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </Card>
  )
}

// ── Corpus fight search ───────────────────────────────────────────────────────

function FightSearchCard({ data, onAdd, picked }) {
  const types = data.types || {}
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(() => new Set(Object.keys(types)))
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const total = Object.values(data.searchable || {}).reduce((a, b) => a + b, 0)

  async function search() {
    if (!q.trim() || !sel.size) return
    setBusy(true); setErr('')
    try { setRes((await api.combatCorpusSearch(q, [...sel], 12)).results) }
    catch (e) { setErr(e.message || 'Search failed') }
    finally { setBusy(false) }
  }
  const toggle = t => setSel(s => { const x = new Set(s); x.has(t) ? x.delete(t) : x.add(t); return x })

  return (
    <Card title="Corpus fights" action={total > 0 && <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{total.toLocaleString()} labelled passages searchable</span>}>
      <div style={{ ...muted, marginBottom: 8 }}>
        Search the corpus's labelled fight passages by what happens, such as "a punch that sends him flying into a wall" or
        "a young master threatening to cripple him". Matched by meaning with local embeddings; no AI call.
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        {Object.entries(types).map(([t, name]) => (
          <label key={t} style={{ fontSize: 10.5, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={sel.has(t)} onChange={() => toggle(t)} />
            {name} <span style={{ color: 'var(--text-muted)' }}>({(data.searchable || {})[t] ?? 0})</span>
          </label>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') search() }}
          placeholder="Describe a fight moment…"
          style={{ flex: 1, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
        <button className="btn-primary" disabled={busy || !q.trim() || !sel.size} onClick={search} style={{ fontSize: 10, padding: '3px 12px' }}>
          {busy ? '…' : 'Search'}
        </button>
      </div>
      {err && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
      {res && !res.length && <div style={{ ...muted, fontSize: 11, marginTop: 8 }}>Nothing close enough.</div>}
      {res && res.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
          {res.map((r, i) => (
            <div key={i} draggable onDragStart={e => { e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(r)); e.dataTransfer.effectAllowed = 'copy' }}
              title="Drag onto My fight moves below, or press Add to my book"
              style={{ fontSize: 11, lineHeight: 1.55, paddingBottom: 6, borderBottom: '1px solid var(--border-soft)', cursor: 'grab' }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 2 }}>
                <span style={pill(TYPE_COLOR[r.type] || 'var(--text-muted)')}>{types[r.type] || nice(r.type)}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {r.novel_title}{r.chapter ? ` · ch ${r.chapter}` : ''} · {Math.round(r.score * 100)}% match
                </span>
                <span style={{ marginLeft: 'auto' }}>
                  {picked?.has(r.text)
                    ? <span style={{ fontSize: 10, color: 'var(--green)' }}>✓ in my book</span>
                    : <button style={btn} onClick={() => onAdd(r)}>＋ Add to my book</button>}
                </span>
              </div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{r.text}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// Saves on Enter or leaving the box, not per keystroke (each save is a request,
// and the box is disabled while one runs, which ate the second digit of "12").
function ChapterInput({ value, disabled, onCommit }) {
  const [v, setV] = useState(value ? String(value) : '')
  useEffect(() => { setV(value ? String(value) : '') }, [value])
  const commit = () => { const n = Number(v) || 0; if (n !== (value || 0)) onCommit(n) }
  return (
    <input type="number" min={0} value={v} placeholder="any" disabled={disabled}
      onChange={e => setV(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
      title="The chapter it's planned for; empty = any chapter whose plan has a fight"
      style={{ width: 54, padding: '2px 6px', fontSize: 11 }} />
  )
}

// ── My fight moves ────────────────────────────────────────────────────────────
// The fight twin of the Humor tab's picker: corpus fight passages dragged here (or
// added with their button), adapted to this book's cast and power system in one AI
// call, or rewritten by hand, then planned for a chapter or left for any fight
// chapter. Adapted, ready moves reach those chapters' prompts.

function FightPicksCard({ projectId, data, picks, setPicks, onAdd, addErr }) {
  const [busy, setBusy] = useState(null)       // "id:op" in flight
  const [errs, setErrs] = useState({})
  const [over, setOver] = useState(false)
  const [drafts, setDrafts] = useState({})     // id -> { name, text } being edited
  const types = data.types || {}
  const written = new Set((data.chapters || []).map(c => c.number))

  async function op(kind, id, fields = {}) {
    setBusy(`${id}:${kind}`)
    setErrs(x => ({ ...x, [id]: '' }))
    try {
      setPicks((await api.fightPickOp(projectId, kind, { id, ...fields })).picks)
      if (kind === 'adapt' || (kind === 'update' && fields.adapted)) setDrafts(d => { const x = { ...d }; delete x[id]; return x })
    } catch (e) {
      setErrs(x => ({ ...x, [id]: e.message || 'Failed' }))
    } finally {
      setBusy(null)
    }
  }
  const field = (p, k) => drafts[p.id]?.[k] ?? p.adapted?.[k] ?? ''
  const edit = (p, k, v) => setDrafts(d => ({ ...d, [p.id]: { name: field(p, 'name'), text: field(p, 'text'), ...(d[p.id] || {}), [k]: v } }))

  function renderPick(p) {
    const s = p.source || {}
    const isBusy = k => busy === `${p.id}:${k}`
    const dirty = !!drafts[p.id]
    const usable = !!p.adapted?.text
    return (
      <div key={p.id} style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-sm)', padding: '8px 10px',
        background: 'var(--bg-elevated)', opacity: p.status === 'used' ? 0.6 : 1 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 3 }}>
          <span style={pill(TYPE_COLOR[s.type] || 'var(--text-muted)')}>{types[s.type] || nice(s.type) || 'fight'}</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>from {s.novel_title}{s.chapter ? ` · ch ${s.chapter}` : ''}</span>
          {p.status === 'used' && <span style={pill('var(--text-muted)')}>used</span>}
          {usable && p.status !== 'used' && <span style={pill('var(--green)')}>{p.chapter ? `planned for ch ${p.chapter}` : 'any fight chapter'}</span>}
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{s.text}</div>
        {(p.adapted || dirty) && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
            <input value={field(p, 'name')} onChange={e => edit(p, 'name', e.target.value)} placeholder="Name for this move in your book"
              style={{ padding: '4px 8px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)' }} />
            <textarea value={field(p, 'text')} onChange={e => edit(p, 'text', e.target.value)} rows={3} placeholder="The move as it plays in your book"
              style={{ padding: '4px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
            {p.adapted?.characters?.length > 0 && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>With: {p.adapted.characters.join(', ')}</div>}
          </div>
        )}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
          <button className="btn-primary" disabled={!!busy} onClick={() => op('adapt', p.id)} style={{ fontSize: 10, padding: '3px 12px' }}
            title="One AI call: rewrite this passage for your own cast, techniques and world, keeping how the move lands">
            {isBusy('adapt') ? 'Adapting…' : p.adapted ? 'Re-adapt' : 'Adapt to my book'}
          </button>
          {!p.adapted && !dirty && <button style={btn} disabled={!!busy} onClick={() => edit(p, 'name', '')}>Write my own version</button>}
          {dirty && <button style={btn} disabled={!!busy} onClick={() => op('update', p.id, { adapted: drafts[p.id] })}>{isBusy('update') ? '…' : 'Save edits'}</button>}
          {usable && (
            <label style={{ fontSize: 10.5, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
              chapter
              <ChapterInput value={p.chapter} disabled={!!busy} onCommit={v => op('update', p.id, { chapter: v })} />
              {p.chapter && written.has(p.chapter) && <span title="That chapter is already written; the move reaches it if you regenerate it">(written)</span>}
            </label>
          )}
          {usable && <button style={btn} disabled={!!busy} onClick={() => op('update', p.id, { status: p.status === 'used' ? 'ready' : 'used' })}>
            {p.status === 'used' ? 'Use again' : 'Mark used'}
          </button>}
          <button style={btn} disabled={!!busy} onClick={() => { if (window.confirm('Remove this picked fight move?')) op('delete', p.id) }}>Remove</button>
          {errs[p.id] && <span style={{ fontSize: 10.5, color: 'var(--red)' }}>{errs[p.id]}</span>}
        </div>
      </div>
    )
  }

  return (
    <div onDragOver={e => { if (e.dataTransfer.types.includes(DRAG_TYPE)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setOver(true) } }}
      onDragLeave={() => setOver(false)}
      onDrop={e => {
        setOver(false)
        const raw = e.dataTransfer.getData(DRAG_TYPE)
        if (!raw) return
        e.preventDefault()
        try { onAdd(JSON.parse(raw)) } catch { /* not one of ours */ }
      }}
      style={{ borderRadius: 'var(--radius-lg)', outline: over ? '2px dashed var(--accent-light)' : 'none', outlineOffset: 2 }}>
      <Card title="My fight moves" action={<span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{picks.length} picked</span>}>
        <div style={{ ...muted, marginBottom: 8 }}>
          Corpus fight moments picked for this book: drag one here from Corpus fights, or press its Add to my book. Adapt
          to my book rewrites it for your cast, techniques and world in one AI call, keeping how the move lands, and you
          can edit the result. A move planned for a chapter goes into that chapter's prompt; one left on "any" goes into
          any chapter whose plan has a fight (three at most per chapter). Only adapted moves are used, so another
          novel's names never reach your chapters.
        </div>
        {addErr && <div style={{ fontSize: 11, color: 'var(--red)', marginBottom: 6 }}>{addErr}</div>}
        {!picks.length ? (
          <div style={{ border: '1px dashed var(--border)', borderRadius: 'var(--radius-sm)', padding: 16, textAlign: 'center', fontSize: 11, color: 'var(--text-muted)' }}>
            Drag a corpus fight moment here
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{picks.map(renderPick)}</div>
        )}
      </Card>
    </div>
  )
}
