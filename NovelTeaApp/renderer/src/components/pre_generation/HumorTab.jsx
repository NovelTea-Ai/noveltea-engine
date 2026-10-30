import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'

// The project Humor tab: Humor DNA (moved here from Author DNA), the book's
// running gags by payoff state, an AI scan of written chapters for places to add
// a setup, a payoff or a one-off beat (applied as an exact insertion, the old
// chapter kept as a version), and a search over the corpus's humor beats by
// meaning (local nomic embeddings from the Pipeline tab's Humor Index, no AI call).

const parseLines = t => t.split('\n').map(s => s.trim()).filter(Boolean)
const nice = s => String(s || '').replace(/_/g, ' ')
const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = {
  fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)',
  background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
}
const pill = color => ({
  fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 10, textTransform: 'uppercase',
  letterSpacing: '0.04em', color, border: `1px solid ${color}`, whiteSpace: 'nowrap',
})
const KIND_COLOR = { payoff: 'var(--green)', setup: 'var(--accent-light)', beat: 'var(--amber)' }
const DRAG_TYPE = 'application/x-noveltea-humor'   // a corpus humor result being dragged onto My humor instances

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

// part: 'pre' = just the first card (Humor DNA, the targets set before writing); 'post' = everything after it, for after
// the chapter is written; omitted = the whole tab.
export default function HumorTab({ projectId, part }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [corpusRequest, setCorpusRequest] = useState(null)   // { q, n }: "Find in corpus" hands a query to the search card
  const corpusRef = useRef(null)

  const load = useCallback(() => {
    api.humorOverview(projectId)
      .then(r => { setData(r); setErr('') })
      .catch(e => setErr(e.message || 'Could not load the Humor tab'))
  }, [projectId])
  useEffect(() => { load() }, [load])

  function findInCorpus(q, faceSlaps = false) {
    setCorpusRequest({ q, n: Date.now(), faceSlaps })
    corpusRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const setPicks = picks => setData(d => ({ ...d, picks }))
  const setGags = (gags, due_after) => setData(d => ({ ...d, gags, due_after }))
  const setSlaps = (slaps, slap_due_after) => setData(d => ({ ...d, slaps, slap_due_after }))
  const [pickErr, setPickErr] = useState('')
  async function addPick(result) {
    setPickErr('')
    try { setPicks((await api.humorPickOp(projectId, 'add', { source: result })).picks) }
    catch (e) { setPickErr(e.message || 'Could not add it') }
  }

  // The tab area hides overflow; like every other tab, this one scrolls itself.
  if (err && !data) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!data) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 1040 }}>
      {part !== 'post' && <HumorDnaCard projectId={projectId} data={data} onSaved={load} />}
      {part !== 'pre' && <>
      <GagsCard projectId={projectId} data={data} onFind={findInCorpus} setGags={setGags} />
      <SlapsCard projectId={projectId} data={data} setSlaps={setSlaps} onFind={q => findInCorpus(q, true)} />
      <ScanCard projectId={projectId} data={data} reload={load} />
      <div ref={corpusRef}>
        <CorpusCard index={data.index} request={corpusRequest} onAdd={addPick}
          picked={new Set((data.picks || []).map(p => p.source?.text))} />
      </div>
      <PicksCard projectId={projectId} picks={data.picks || []} setPicks={setPicks} setGags={setGags}
        setSlaps={setSlaps} onAdd={addPick} addErr={pickErr} />
      </>}
    </div>
    </div>
  )
}

// ── Humor DNA ─────────────────────────────────────────────────────────────────

function HumorDnaCard({ projectId, data, onSaved }) {
  const [dna, setDna] = useState(data.humor_dna || {})
  const [typesText, setTypesText] = useState((data.humor_dna?.top_types || []).join(', '))
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  // A reload (after a scan or an applied suggestion) must not wipe unsaved edits.
  useEffect(() => {
    if (dirty) return
    setDna(data.humor_dna || {})
    setTypesText((data.humor_dna?.top_types || []).join(', '))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.humor_dna])

  const set = (k, v) => { setDna(d => ({ ...d, [k]: v })); setDirty(true) }
  const setSetup = (k, v) => { setDna(d => ({ ...d, setups: { ...(d.setups || {}), [k]: v } })); setDirty(true) }

  async function save() {
    setBusy(true); setMsg('')
    try {
      await api.saveHumorDna(projectId, { ...dna, top_types: typesText.split(',').map(s => s.trim()).filter(Boolean) })
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
      <Card title="Humor DNA">
        <div style={muted}>This project has no Author DNA yet. Set it up in the Author DNA tab first; Humor DNA is measured from the same voice source.</div>
      </Card>
    )
  }
  const row = { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }
  const label = { fontSize: 10.5, color: 'var(--text-muted)', width: 150 }
  return (
    <Card title="Humor DNA" action={
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {msg && <span style={{ fontSize: 10, color: msg.startsWith('✓') ? 'var(--green)' : 'var(--red)' }}>{msg}</span>}
        <button className="btn-primary" disabled={busy || !dirty} onClick={save} style={{ fontSize: 10, padding: '3px 12px' }}>
          {busy ? '…' : 'Save'}
        </button>
      </div>
    }>
      <div style={{ ...muted, marginBottom: 10 }}>
        Measured from {data.voice_source}, the voice source set in Author DNA (re-applying it there re-measures these).
        It steers every chapter prompt, and the end-of-chapter humor check adds beats when a chapter falls short.
        {!data.humor_dna_saved && <b style={{ color: 'var(--amber)' }}> Not saved in the profile yet; press Save to lock these numbers in.</b>}
      </div>
      <div style={row}>
        <span style={label}>Humor beats per chapter</span>
        <input type="number" min={0} max={10} step={0.1} value={dna.beats_per_chapter ?? ''}
          onChange={e => set('beats_per_chapter', Number(e.target.value))}
          style={{ width: 56, padding: '3px 6px', fontSize: 11, borderRadius: 4 }} />
        {typeof dna.chapters_with_humor === 'number' && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            {Math.round(dna.chapters_with_humor * 100)}% of source chapters have at least one
          </span>
        )}
      </div>
      <div style={row}>
        <span style={label}>Main humor types</span>
        <input value={typesText} onChange={e => { setTypesText(e.target.value); setDirty(true) }}
          placeholder="situational_irony, deadpan_reaction…"
          style={{ flex: 1, minWidth: 220, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
      </div>
      {dna.setups && <HumorSetupsEditor setups={dna.setups} onChange={setSetup} />}
      {dna.face_slaps && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border-soft)' }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, marginBottom: 2 }}>Face slaps</div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6, lineHeight: 1.5 }}>
            About {Math.round((dna.face_slaps.humiliation_share || 0) * 100)}% of source chapters have someone looking down on
            or humiliating a character, and {Math.round((dna.face_slaps.payback_share || 0) * 100)}% pay one back. A
            humiliation is paid back {dna.face_slaps.gap ? `after a median ${dna.face_slaps.gap.median} chapters (most within ${dna.face_slaps.gap.high})` : 'quickly'},
            {' '}{Math.round((dna.face_slaps.same_chapter_share || 0) * 100)}% in the same chapter
            {dna.face_slaps.timing_from ? ` (timing: ${dna.face_slaps.timing_from}; read from chapter summaries' wording, so rough)` : ''}.
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', width: 150 }}>Slap due after</span>
            <input type="number" min={1} value={dna.face_slaps.due_after ?? ''}
              onChange={e => { setDna(d => ({ ...d, face_slaps: { ...(d.face_slaps || {}), due_after: Number(e.target.value) || null } })); setDirty(true) }}
              style={{ width: 56, padding: '3px 6px', fontSize: 11, borderRadius: 4 }} />
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>chapters unpaid, then a humiliation is flagged as due its slap</span>
          </div>
        </div>
      )}
    </Card>
  )
}

// Humor setups: how the corpus sets up jokes and calls back to them (measured
// from its humor logs, broken links and duplicate beats filtered out). due_after
// is what the running-gag list below flags a quiet gag by.
function HumorSetupsEditor({ setups, onChange }) {
  // The textarea keeps its own text so a new empty line survives until blur.
  const [patterns, setPatterns] = useState((setups.gag_patterns || []).join('\n'))
  useEffect(() => {
    const incoming = (setups.gag_patterns || []).join('\n')
    setPatterns(cur => (parseLines(cur).join('\n') === incoming ? cur : incoming))
  }, [setups.gag_patterns])
  const gap = setups.callback_gap || {}
  const rate = setups.callbacks_per_chapter
  const row = { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }
  const label = { fontSize: 10.5, color: 'var(--text-muted)', width: 150 }
  const small = { fontSize: 10, color: 'var(--text-muted)' }
  const num = { width: 56, padding: '3px 6px', fontSize: 11, borderRadius: 4 }
  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border-soft)' }}>
      <div style={{ fontSize: 10.5, fontWeight: 700, marginBottom: 2 }}>Humor setups</div>
      <div style={{ ...small, marginBottom: 6, lineHeight: 1.5 }}>
        How jokes get set up and called back in later chapters, measured from the corpus humor logs
        {setups.timing_from ? ` (timing: ${setups.timing_from})` : ''}.
      </div>
      <div style={row}>
        <span style={label}>Callbacks per chapter</span>
        <input type="number" min={0} max={5} step={0.05} value={rate ?? ''}
          onChange={e => onChange('callbacks_per_chapter', Number(e.target.value))} style={num} />
        {rate > 0 && <span style={small}>≈ one callback to an earlier chapter's joke every {Math.max(1, Math.round(1 / rate))} chapters</span>}
      </div>
      <div style={row}>
        <span style={label}>Setup → callback gap</span>
        <input type="number" min={0} value={gap.low ?? ''}
          onChange={e => onChange('callback_gap', { ...gap, low: Number(e.target.value) })} style={num} />
        <span style={small}>to</span>
        <input type="number" min={0} value={gap.high ?? ''}
          onChange={e => onChange('callback_gap', { ...gap, high: Number(e.target.value) })} style={num} />
        <span style={small}>chapters{gap.median != null ? ` (median ${gap.median})` : ''}</span>
      </div>
      <div style={row}>
        <span style={label}>Gag due after</span>
        <input type="number" min={1} value={setups.due_after ?? ''}
          onChange={e => onChange('due_after', Number(e.target.value) || null)} style={num} />
        <span style={small}>quiet chapters, then the gag is flagged as due a callback</span>
      </div>
      <div style={{ ...label, width: 'auto', marginTop: 4, marginBottom: 3 }}>
        Gag patterns that work in this voice (one per line; the chapter prompt adapts them to your cast)
      </div>
      <textarea value={patterns} rows={4} onChange={e => setPatterns(e.target.value)}
        onBlur={() => onChange('gag_patterns', parseLines(patterns))}
        style={{ width: '100%', padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
    </div>
  )
}

// ── Running gags ──────────────────────────────────────────────────────────────

const GAG_GROUPS = [
  ['needs_payoff', 'Needs payoff', 'Set up in the text, not paid off by a later chapter yet.'],
  ['paid_off', 'Paid off', 'Called back in a later chapter at least once.'],
  ['not_set_up', 'Not in the text yet', 'Named in your craft notes or added here, not written into a chapter yet.'],
]

function GagsCard({ projectId, data, setGags, onFind }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [newName, setNewName] = useState('')
  const [editing, setEditing] = useState(null)   // { id, name }
  const [showRetired, setShowRetired] = useState(false)
  const cancelEdit = useRef(false)

  async function op(kind, fields) {
    setBusy(true); setErr('')
    try {
      const r = await api.gagLedgerOp(projectId, kind, fields)
      setGags(r.gags, r.due_after)
    } catch (e) {
      setErr(e.message || 'Could not update running gags')
    } finally {
      setBusy(false)
    }
  }
  function add() {
    const name = newName.trim()
    if (!name) return
    op('add', { name }); setNewName('')
  }

  const gags = data.gags || []
  const live = gags.filter(g => g.status !== 'retired')
  const retired = gags.filter(g => g.status === 'retired')
  const dueCount = live.filter(g => g.due).length

  // A render helper, not a component: a component defined in here would remount on
  // every keystroke and drop the rename box's focus.
  function renderRow(g) {
    let where = ''
    if (g.state === 'needs_payoff') where = `set up in ch ${g.setup_chapter}`
    if (g.state === 'paid_off') where = `ch ${g.setup_chapter} → ch ${g.payoff_chapters.join(', ')}`
    return (
      <div key={g.id} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 11, lineHeight: 1.75, flexWrap: 'wrap' }}>
        <span style={{ width: 28, color: 'var(--text-muted)', fontWeight: 600 }}>{g.id}</span>
        {g.status === 'candidate' && <span style={pill('var(--amber)')} title="Spotted by the humor check; turns active once a later chapter calls back to it">candidate</span>}
        {editing?.id === g.id ? (
          <input autoFocus value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })}
            onKeyDown={e => {
              if (e.key === 'Enter') e.currentTarget.blur()
              if (e.key === 'Escape') { cancelEdit.current = true; e.currentTarget.blur() }
            }}
            onBlur={() => {
              const name = editing.name.trim()
              if (!cancelEdit.current && name && name !== g.name) op('update', { id: g.id, name })
              cancelEdit.current = false
              setEditing(null)
            }}
            style={{ flex: 1, minWidth: 220, padding: '2px 6px', fontSize: 11 }} />
        ) : (
          <span title="Click to rename" onClick={() => setEditing({ id: g.id, name: g.name })}
            style={{ flex: 1, minWidth: 220, cursor: 'text', color: g.status === 'retired' ? 'var(--text-muted)' : 'var(--text-primary)' }}>
            {g.name}
          </span>
        )}
        {where && <span style={{ color: 'var(--text-muted)' }}>{where}</span>}
        {g.due && <span style={pill('var(--amber)')}>due · quiet {g.quiet}</span>}
        <button style={btn} onClick={() => onFind(g.name)} title="Search the corpus for similar setups and gags">Find in corpus</button>
        {g.status === 'candidate' && <button disabled={busy} style={btn} onClick={() => op('update', { id: g.id, status: 'active' })}>Make active</button>}
        {g.status !== 'retired'
          ? <button disabled={busy} style={btn} onClick={() => op('update', { id: g.id, status: 'retired' })}>Retire</button>
          : <button disabled={busy} style={btn} onClick={() => op('update', { id: g.id, status: 'active' })}>Restore</button>}
        <button disabled={busy} style={btn} title="Delete this gag and its history"
          onClick={() => { if (window.confirm(`Delete "${g.name}" and its history? Retire keeps the history instead.`)) op('delete', { id: g.id }) }}>
          ✕
        </button>
      </div>
    )
  }

  return (
    <Card title="Running gags" action={
      <span style={{ fontSize: 10.5, color: dueCount ? 'var(--amber)' : 'var(--text-muted)' }}>
        {live.length} tracked{dueCount ? ` · ${dueCount} due a callback` : ''}
      </span>
    }>
      <div style={muted}>
        Kept current by the end-of-chapter humor check and by the suggestions you apply below. Active gags go into
        every chapter prompt with when they last appeared; one quiet for more than {data.due_after} chapters is
        flagged as due. Changes here save immediately.
      </div>
      {err && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
      {GAG_GROUPS.map(([state, title, help]) => {
        const rows = live.filter(g => g.state === state)
        return (
          <div key={state} style={{ marginTop: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>
              {title} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({rows.length})</span>
            </div>
            <div style={{ ...muted, fontSize: 10, marginBottom: 4 }}>{help}</div>
            {rows.length ? rows.map(renderRow) : <div style={{ ...muted, fontSize: 10.5 }}>None.</div>}
          </div>
        )
      })}
      {retired.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button style={{ ...btn, border: 'none', background: 'none', padding: 0, color: 'var(--text-muted)' }}
            onClick={() => setShowRetired(v => !v)}>
            {showRetired ? '▾' : '▸'} Retired ({retired.length})
          </button>
          {showRetired && retired.map(renderRow)}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
        <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Add a running gag…"
          onKeyDown={e => { if (e.key === 'Enter') add() }}
          style={{ flex: 1, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
        <button disabled={busy || !newName.trim()} style={btn} onClick={add}>Add</button>
      </div>
    </Card>
  )
}

// ── Chapter scan ──────────────────────────────────────────────────────────────

function ScanCard({ projectId, data, reload }) {
  const chapters = data.chapters || []
  const fromData = () => Object.fromEntries(chapters.filter(c => c.scan).map(c => [c.number, c.scan]))
  const [scans, setScans] = useState(fromData)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setScans(fromData()) }, [data.chapters])
  const [sel, setSel] = useState(() => new Set())
  const [open, setOpen] = useState(() => new Set())
  const [running, setRunning] = useState(null)   // { current, done, total }
  const [errs, setErrs] = useState({})
  const [edits, setEdits] = useState({})         // suggestion id -> edited lines
  const [busyId, setBusyId] = useState(null)

  const toggle = (setter, n) => setter(s => { const x = new Set(s); x.has(n) ? x.delete(n) : x.add(n); return x })

  async function scanSelected() {
    const list = chapters.map(c => c.number).filter(n => sel.has(n))
    setErrs({})
    for (let i = 0; i < list.length; i++) {
      setRunning({ current: list[i], done: i, total: list.length })
      try {
        const r = await api.humorScan(projectId, list[i])
        setScans(s => ({ ...s, [list[i]]: r.scan }))
        setOpen(o => new Set(o).add(list[i]))
      } catch (e) {
        setErrs(x => ({ ...x, [list[i]]: e.message || 'Scan failed' }))
      }
    }
    setRunning(null)
  }

  async function act(n, s, action) {
    setBusyId(s.id)
    setErrs(x => ({ ...x, [s.id]: '' }))
    try {
      const r = await api.humorSuggestion(projectId, n, s.id, action, action === 'apply' ? (edits[s.id] ?? s.lines) : null)
      setScans(sc => ({ ...sc, [n]: { ...sc[n], suggestions: sc[n].suggestions.map(x => (x.id === s.id ? r.suggestion : x)) } }))
      if (action === 'apply') reload()   // gag lists and humor counts changed
    } catch (e) {
      setErrs(x => ({ ...x, [s.id]: e.message || 'Failed' }))
    } finally {
      setBusyId(null)
    }
  }

  const openCount = n => (scans[n]?.suggestions || []).filter(s => s.status === 'open').length
  return (
    <Card title="Find places to add humor" action={
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        {running && <span style={{ fontSize: 10.5, color: 'var(--amber)' }}>Scanning ch {running.current} ({running.done + 1}/{running.total})…</span>}
        <button style={btn} disabled={!!running || !chapters.length}
          onClick={() => setSel(new Set(chapters.map(c => c.number)))}>Select all</button>
        <button className="btn-primary" disabled={!!running || !sel.size} onClick={scanSelected}
          style={{ fontSize: 10, padding: '3px 12px' }}>Scan {sel.size || ''} selected</button>
      </div>
    }>
      <div style={{ ...muted, marginBottom: 8 }}>
        Reads a written chapter and suggests where it could pay off a running gag, plant a setup a later chapter can
        pay off, or take a one-off beat, with corpus examples of similar jokes when the humor index is built. Each
        scan is one AI call with your default model. Nothing changes until you press Apply; the lines go in exactly
        where shown (edit them first if you like), and the old chapter is kept as a version.
      </div>
      {!chapters.length && <div style={{ ...muted, fontSize: 11 }}>No chapters written yet.</div>}
      {chapters.map(c => {
        const h = c.humor
        const scan = scans[c.number]
        return (
          <div key={c.number} style={{ borderTop: '1px solid var(--border-soft)', padding: '6px 0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, flexWrap: 'wrap' }}>
              <input type="checkbox" checked={sel.has(c.number)} disabled={!!running} onChange={() => toggle(setSel, c.number)} />
              <span style={{ fontWeight: 700, width: 44 }}>Ch {c.number}</span>
              <span style={{ color: h && !h.ok ? 'var(--amber)' : 'var(--text-muted)' }}>
                {h ? `${h.after} humor beat${h.after === 1 ? '' : 's'} (target about ${h.average})` : 'humor not counted'}
              </span>
              {h?.gags?.called_back?.length > 0 && <span style={{ color: 'var(--text-muted)' }}>· called back {h.gags.called_back.join('; ')}</span>}
              <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
                {scan ? `${openCount(c.number)} open suggestion${openCount(c.number) === 1 ? '' : 's'} · scanned ${new Date(scan.at * 1000).toLocaleString()}` : 'not scanned'}
              </span>
              {scan && <button style={btn} onClick={() => toggle(setOpen, c.number)}>{open.has(c.number) ? 'Hide' : 'Show'}</button>}
            </div>
            {errs[c.number] && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>{errs[c.number]}</div>}
            {scan && open.has(c.number) && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '8px 0 4px 26px' }}>
                {scan.dropped > 0 && <div style={{ ...muted, fontSize: 10 }}>{scan.dropped} suggestion{scan.dropped === 1 ? '' : 's'} dropped: the spot they quoted isn't in the chapter.</div>}
                {!scan.suggestions?.length && <div style={{ ...muted, fontSize: 11 }}>No places found.</div>}
                {(scan.suggestions || []).map(s => (
                  <Suggestion key={s.id} s={s} busy={busyId === s.id} err={errs[s.id]}
                    lines={edits[s.id] ?? s.lines} onLines={v => setEdits(x => ({ ...x, [s.id]: v }))}
                    onApply={() => act(c.number, s, 'apply')} onDismiss={() => act(c.number, s, 'dismiss')} />
                ))}
                {scan.examples?.length > 0 && (
                  <div style={{ ...muted, fontSize: 10 }}>
                    Corpus examples the scan was shown: {scan.examples.map(e => `${nice(e.type)} (${e.novel_title}${e.chapter ? `, ch ${e.chapter}` : ''})`).join(' · ')}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </Card>
  )
}

function Suggestion({ s, lines, onLines, onApply, onDismiss, busy, err }) {
  const [showPara, setShowPara] = useState(false)
  const done = s.status !== 'open'
  return (
    <div style={{
      border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-sm)', padding: '8px 10px',
      background: 'var(--bg-elevated)', opacity: s.status === 'dismissed' ? 0.55 : 1,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
        <span style={pill(KIND_COLOR[s.kind] || 'var(--text-muted)')}>{s.kind}</span>
        {s.gag && <span style={{ fontSize: 10.5, fontWeight: 600 }}>{s.gag} {s.gag_name}</span>}
        {s.new_gag && <span style={{ fontSize: 10.5, fontWeight: 600 }}>new gag: {s.new_gag}</span>}
        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{nice(s.type)}</span>
      </div>
      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginBottom: 4 }}>
        {s.mode === 'rewrite' ? 'Rewrites the paragraph with: ' : 'New paragraph after the one with: '}
        <i>“{s.anchor}”</i>
        {s.mode === 'rewrite' && s.paragraph && (
          <> <button style={{ ...btn, padding: '0 6px', fontSize: 9.5 }} onClick={() => setShowPara(v => !v)}>{showPara ? 'hide' : 'show'} original</button></>
        )}
      </div>
      {showPara && <div style={{ fontSize: 10.5, color: 'var(--text-muted)', whiteSpace: 'pre-wrap', margin: '2px 0 6px', paddingLeft: 8, borderLeft: '2px solid var(--border)' }}>{s.paragraph}</div>}
      {done ? (
        <div style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{s.applied_lines || s.lines}</div>
      ) : (
        <textarea value={lines} onChange={e => onLines(e.target.value)} rows={Math.min(8, Math.max(2, Math.ceil(lines.length / 110)))}
          style={{ width: '100%', padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
      )}
      {s.why && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>{s.why}</div>}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
        {s.status === 'open' && <>
          <button className="btn-primary" disabled={busy || !lines.trim()} onClick={onApply} style={{ fontSize: 10, padding: '3px 12px' }}>{busy ? '…' : 'Apply'}</button>
          <button style={btn} disabled={busy} onClick={onDismiss}>Dismiss</button>
        </>}
        {s.status === 'applied' && <span style={{ fontSize: 10.5, color: 'var(--green)' }}>✓ Applied; the old chapter is kept as version {s.applied_version}</span>}
        {s.status === 'dismissed' && <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>Dismissed</span>}
        {err && <span style={{ fontSize: 10.5, color: 'var(--red)' }}>{err}</span>}
      </div>
    </div>
  )
}

// ── Corpus gags ───────────────────────────────────────────────────────────────

function CorpusCard({ index, request, onAdd, picked }) {
  const [q, setQ] = useState('')
  const [runningOnly, setRunningOnly] = useState(false)
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const built = (index?.beats || 0) > 0

  const [slapsOnly, setSlapsOnly] = useState(false)
  async function search(query = q, only = runningOnly, slaps = slapsOnly) {
    if (!query.trim()) return
    setBusy(true); setErr('')
    try { setRes((await api.humorCorpusSearch(query, 12, only, slaps)).results) }
    catch (e) { setErr(e.message || 'Search failed') }
    finally { setBusy(false) }
  }
  useEffect(() => {
    if (request?.q && built) {
      setQ(request.q)
      setSlapsOnly(!!request.faceSlaps)
      search(request.q, runningOnly, !!request.faceSlaps)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.n])

  return (
    <Card title="Corpus gags" action={built && <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{index.beats.toLocaleString()} corpus humor beats searchable</span>}>
      <div style={{ ...muted, marginBottom: 8 }}>
        Search the corpus's humor by idea, such as "a gambler who always loses", and see how other novels set it up and
        paid it off. Matched by meaning with local nomic embeddings; no AI call.
      </div>
      {!built ? (
        <div style={{ fontSize: 11, color: 'var(--amber)' }}>
          The corpus humor index isn't built yet. Run Humor Index (nomic) in the Pipeline tab, then come back.
        </div>
      ) : (<>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') search() }}
            placeholder="Describe a joke or running gag…"
            style={{ flex: 1, minWidth: 240, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
          <label style={{ fontSize: 10.5, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={runningOnly} onChange={e => { setRunningOnly(e.target.checked); if (q.trim()) search(q, e.target.checked) }} />
            running gags only
          </label>
          <label style={{ fontSize: 10.5, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={slapsOnly} onChange={e => { setSlapsOnly(e.target.checked); if (q.trim()) search(q, runningOnly, e.target.checked) }} />
            face slaps only
          </label>
          <button className="btn-primary" disabled={busy || !q.trim()} onClick={() => search()} style={{ fontSize: 10, padding: '3px 12px' }}>
            {busy ? '…' : 'Search'}
          </button>
        </div>
        {err && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
        {res && !res.length && <div style={{ ...muted, fontSize: 11, marginTop: 8 }}>Nothing close enough.</div>}
        {res && res.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
            {res.map((r, i) => (
              <div key={i} draggable onDragStart={e => { e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(r)); e.dataTransfer.effectAllowed = 'copy' }}
                title="Drag onto My humor instances below, or press Add to my book"
                style={{ fontSize: 11, lineHeight: 1.55, paddingBottom: 6, borderBottom: '1px solid var(--border-soft)', cursor: 'grab' }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 2 }}>
                  <span style={pill('var(--accent-light)')}>{nice(r.type) || 'humor'}</span>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                    {r.novel_title}{r.chapter ? ` · ch ${r.chapter}` : ''} · {Math.round(r.score * 100)}% match
                  </span>
                  {r.family_size >= 2 && <span style={pill('var(--green)')}>running gag ×{r.family_size}</span>}
                  <span style={{ marginLeft: 'auto' }}>
                    {picked?.has(r.text)
                      ? <span style={{ fontSize: 10, color: 'var(--green)' }}>✓ in my book</span>
                      : <button style={btn} onClick={() => onAdd(r)}>＋ Add to my book</button>}
                  </span>
                </div>
                {r.setup && <div><span style={{ color: 'var(--text-muted)' }}>Setup: </span>{r.setup}</div>}
                {r.payoff && <div><span style={{ color: 'var(--text-muted)' }}>Payoff: </span>{r.payoff}</div>}
              </div>
            ))}
          </div>
        )}
      </>)}
    </Card>
  )
}

// ── My humor instances ────────────────────────────────────────────────────────
// Corpus jokes picked into this book, like the Characters tab's Corpus DNA picker
// pulls a trait: dragged here from Corpus gags (or added with its button), adapted
// to this book's cast in one AI call, edited freely, and optionally turned into a
// running gag whose plan then reaches chapter prompts and scans.

function PicksCard({ projectId, picks, setPicks, setGags, setSlaps, onAdd, addErr }) {
  const [busy, setBusy] = useState(null)       // "id:op" in flight
  const [errs, setErrs] = useState({})
  const [over, setOver] = useState(false)
  const [drafts, setDrafts] = useState({})     // id -> { name, setup, payoff } being edited

  async function op(kind, id, fields = {}) {
    setBusy(`${id}:${kind}`)
    setErrs(x => ({ ...x, [id]: '' }))
    try {
      const r = await api.humorPickOp(projectId, kind, { id, ...fields })
      setPicks(r.picks)
      if (r.ledger) setGags(r.ledger.gags, r.ledger.due_after)
      if (r.slaps) setSlaps(r.slaps, r.slap_due_after)
      if (kind === 'adapt' || kind === 'update') setDrafts(d => { const x = { ...d }; delete x[id]; return x })
    } catch (e) {
      setErrs(x => ({ ...x, [id]: e.message || 'Failed' }))
    } finally {
      setBusy(null)
    }
  }
  const field = (p, k) => drafts[p.id]?.[k] ?? p.adapted?.[k] ?? ''
  const edit = (p, k, v) => setDrafts(d => ({
    ...d, [p.id]: { name: field(p, 'name'), setup: field(p, 'setup'), payoff: field(p, 'payoff'), ...(d[p.id] || {}), [k]: v },
  }))

  function renderPick(p) {
    const s = p.source || {}
    const isBusy = k => busy === `${p.id}:${k}`
    const dirty = !!drafts[p.id]
    return (
      <div key={p.id} style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', background: 'var(--bg-elevated)' }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 3 }}>
          <span style={pill('var(--accent-light)')}>{nice(s.type) || 'humor'}</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>from {s.novel_title}{s.chapter ? ` · ch ${s.chapter}` : ''}</span>
          {s.family_size >= 2 && <span style={pill('var(--green)')}>running gag ×{s.family_size}</span>}
          {p.gag_id && <span style={pill('var(--green)')}>my running gag {p.gag_id}</span>}
          {p.slap_id && <span style={pill('var(--red)')}>my face slap {p.slap_id}</span>}
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.5 }}>
          {s.setup && <div>Setup: {s.setup}</div>}
          {s.payoff && <div>Payoff: {s.payoff}</div>}
        </div>
        {(p.adapted || dirty) && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
            <input value={field(p, 'name')} onChange={e => edit(p, 'name', e.target.value)} placeholder="Name for this joke in your book"
              style={{ padding: '4px 8px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)' }} />
            <textarea value={field(p, 'setup')} onChange={e => edit(p, 'setup', e.target.value)} rows={2} placeholder="How it's set up in your book"
              style={{ padding: '4px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
            <textarea value={field(p, 'payoff')} onChange={e => edit(p, 'payoff', e.target.value)} rows={2} placeholder="How it pays off"
              style={{ padding: '4px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
            {p.adapted?.characters?.length > 0 && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>With: {p.adapted.characters.join(', ')}</div>}
          </div>
        )}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
          <button className="btn-primary" disabled={!!busy} onClick={() => op('adapt', p.id)} style={{ fontSize: 10, padding: '3px 12px' }}
            title="One AI call: rewrite this joke for your own cast and world, keeping what makes it funny">
            {isBusy('adapt') ? 'Adapting…' : p.adapted ? 'Re-adapt' : 'Adapt to my book'}
          </button>
          {!p.adapted && !dirty && <button style={btn} disabled={!!busy} onClick={() => edit(p, 'name', '')}>Write my own version</button>}
          {dirty && <button style={btn} disabled={!!busy} onClick={() => op('update', p.id, { adapted: drafts[p.id] })}>{isBusy('update') ? '…' : 'Save edits'}</button>}
          <button style={btn} disabled={!!busy || dirty}
            title={p.gag_id ? 'Update its running gag with this name and plan' : 'Add it to Running gags with this plan; it then reaches chapter prompts'}
            onClick={() => op('to_gag', p.id)}>{isBusy('to_gag') ? '…' : p.gag_id ? 'Update running gag' : 'Make it a running gag'}</button>
          <button style={btn} disabled={!!busy || dirty}
            title={p.slap_id ? 'Update its face slap with this name and plan' : 'Add it to Face slaps as a planned slap; it then reaches chapter prompts and skeleton planning'}
            onClick={() => op('to_slap', p.id)}>{isBusy('to_slap') ? '…' : p.slap_id ? 'Update face slap' : 'Make it a face slap'}</button>
          <button style={btn} disabled={!!busy} onClick={() => { if (window.confirm('Remove this picked joke?')) op('delete', p.id) }}>Remove</button>
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
      <Card title="My humor instances" action={<span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{picks.length} picked</span>}>
        <div style={{ ...muted, marginBottom: 8 }}>
          Corpus jokes picked for this book: drag one here from Corpus gags, or press its Add to my book. Adapt to my book
          rewrites it for your own cast in one AI call, keeping what makes it funny, and you can edit the result. Make it
          a running gag to put it in the gag lists and chapter prompts with its plan. Adapted picks that aren't running
          gags yet are offered to the chapter scan as ideas.
        </div>
        {addErr && <div style={{ fontSize: 11, color: 'var(--red)', marginBottom: 6 }}>{addErr}</div>}
        {!picks.length ? (
          <div style={{ border: '1px dashed var(--border)', borderRadius: 'var(--radius-sm)', padding: 16, textAlign: 'center', fontSize: 11, color: 'var(--text-muted)' }}>
            Drag a corpus joke here
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{picks.map(renderPick)}</div>
        )}
      </Card>
    </div>
  )
}

// ── Face slaps ────────────────────────────────────────────────────────────────
// Someone looks down on the protagonist (the humiliation); later the protagonist
// turns it back on them in front of others (the slap). Tracked by the end-of-
// chapter humor check (same AI call) and by hand; waiting ones go into chapter
// prompts and skeleton planning, flagged once they're past Humor DNA's due-after.

const SLAP_GROUPS = [
  ['waiting', 'Waiting for the slap', 'Humiliated him in the text, not paid back yet.'],
  ['slapped', 'Slapped', 'Paid back in front of others.'],
  ['planned', 'Planned', 'Added here or from a picked corpus joke, not in the text yet.'],
]

function SlapsCard({ projectId, data, setSlaps, onFind }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [form, setForm] = useState({ name: '', target: '', plan: '' })
  const [editing, setEditing] = useState(null)   // { id, name, target, plan }
  const [showRetired, setShowRetired] = useState(false)

  async function op(kind, fields) {
    setBusy(true); setErr('')
    try {
      const r = await api.slapOp(projectId, kind, fields)
      setSlaps(r.slaps, r.slap_due_after)
      return true
    } catch (e) {
      setErr(e.message || 'Could not update face slaps')
      return false
    } finally {
      setBusy(false)
    }
  }
  async function add() {
    if (!form.name.trim()) return
    if (await op('add', form)) setForm({ name: '', target: '', plan: '' })
  }

  const slaps = data.slaps || []
  const live = slaps.filter(s => s.status !== 'retired')
  const retired = slaps.filter(s => s.status === 'retired')
  const dueCount = live.filter(s => s.due).length
  const input = { padding: '4px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }

  function renderSlap(s) {
    if (editing?.id === s.id) {
      return (
        <div key={s.id} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', margin: '4px 0' }}>
          <span style={{ width: 28, color: 'var(--text-muted)', fontWeight: 600, fontSize: 11 }}>{s.id}</span>
          <input value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} placeholder="Name" style={{ ...input, flex: 1, minWidth: 180 }} />
          <input value={editing.target} onChange={e => setEditing({ ...editing, target: e.target.value })} placeholder="Who looked down on him" style={{ ...input, width: 170 }} />
          <input value={editing.plan} onChange={e => setEditing({ ...editing, plan: e.target.value })} placeholder="How the slap lands (optional)" style={{ ...input, flex: 2, minWidth: 220 }} />
          <button className="btn-primary" disabled={busy} style={{ fontSize: 10, padding: '3px 12px' }}
            onClick={async () => { if (await op('update', editing)) setEditing(null) }}>Save</button>
          <button style={btn} onClick={() => setEditing(null)}>Cancel</button>
        </div>
      )
    }
    let where = ''
    if (s.state === 'waiting') where = `humiliated him in ch ${s.setup_chapters[0]}${s.quiet != null ? ` · waiting ${s.quiet}` : ''}`
    if (s.state === 'slapped') where = `ch ${s.setup_chapters.length ? s.setup_chapters[0] : '?'} → slapped in ch ${s.payoff_chapters.join(', ')}`
    return (
      <div key={s.id} style={{ fontSize: 11, lineHeight: 1.7 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ width: 28, color: 'var(--text-muted)', fontWeight: 600 }}>{s.id}</span>
          <span style={{ flex: 1, minWidth: 200, color: s.status === 'retired' ? 'var(--text-muted)' : 'var(--text-primary)' }}>
            {s.name}{s.target ? <span style={{ color: 'var(--text-muted)' }}> · {s.target}</span> : null}
          </span>
          {where && <span style={{ color: 'var(--text-muted)' }}>{where}</span>}
          {s.due && <span style={pill('var(--amber)')}>due its slap</span>}
          <button style={btn} onClick={() => onFind(`${s.name} ${s.target || ''} looks down on him and gets face-slapped`)}>Find in corpus</button>
          <button style={btn} disabled={busy} onClick={() => setEditing({ id: s.id, name: s.name, target: s.target || '', plan: s.plan || '' })}>Edit</button>
          {s.status !== 'retired'
            ? <button disabled={busy} style={btn} onClick={() => op('update', { id: s.id, status: 'retired' })}>Retire</button>
            : <button disabled={busy} style={btn} onClick={() => op('update', { id: s.id, status: 'active' })}>Restore</button>}
          <button disabled={busy} style={btn} title="Delete this face slap and its history"
            onClick={() => { if (window.confirm(`Delete "${s.name}" and its history? Retire keeps the history instead.`)) op('delete', { id: s.id }) }}>✕</button>
        </div>
        {(s.quote || s.plan) && (
          <div style={{ paddingLeft: 36, fontSize: 10.5, color: 'var(--text-muted)' }}>
            {s.quote && <div>“{s.quote}”</div>}
            {s.plan && <div>Planned slap: {s.plan}</div>}
          </div>
        )}
      </div>
    )
  }

  return (
    <Card title="Face slaps" action={
      <span style={{ fontSize: 10.5, color: dueCount ? 'var(--amber)' : 'var(--text-muted)' }}>
        {live.length} tracked{dueCount ? ` · ${dueCount} due` : ''}
      </span>
    }>
      <div style={muted}>
        Someone looks down on the protagonist; later he turns it back on them in front of others. The end-of-chapter
        humor check spots both halves (same AI call) and matches a payback to the humiliation by who did it. Waiting slaps
        go into chapter prompts and skeleton planning; one unpaid for more than {data.slap_due_after} chapters is
        flagged as due. Changes here save immediately.
      </div>
      {err && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
      {SLAP_GROUPS.map(([state, title, help]) => {
        const rows = live.filter(s => s.state === state)
        return (
          <div key={state} style={{ marginTop: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>{title} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({rows.length})</span></div>
            <div style={{ ...muted, fontSize: 10, marginBottom: 4 }}>{help}</div>
            {rows.length ? rows.map(renderSlap) : <div style={{ ...muted, fontSize: 10.5 }}>None.</div>}
          </div>
        )
      })}
      {retired.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button style={{ ...btn, border: 'none', background: 'none', padding: 0, color: 'var(--text-muted)' }}
            onClick={() => setShowRetired(v => !v)}>{showRetired ? '▾' : '▸'} Retired ({retired.length})</button>
          {showRetired && retired.map(renderSlap)}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
        <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Plan a face slap…"
          onKeyDown={e => { if (e.key === 'Enter') add() }} style={{ ...input, flex: 1, minWidth: 180 }} />
        <input value={form.target} onChange={e => setForm({ ...form, target: e.target.value })} placeholder="Who gets slapped" style={{ ...input, width: 160 }} />
        <input value={form.plan} onChange={e => setForm({ ...form, plan: e.target.value })} placeholder="How it lands (optional)" style={{ ...input, flex: 2, minWidth: 200 }} />
        <button disabled={busy || !form.name.trim()} style={btn} onClick={add}>Add</button>
      </div>
    </Card>
  )
}
