import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../api'

// Pre-generation Lore is PROJECT-WIDE (not tied to any chapter). Chapter Lore cards (the WHY behind one chapter) live only in the Post tab:
// part="post": after reading or listening, give feedback -> a proposed change to the CARD (shown as a difference) -> approve ->
// only the paragraphs that change touches are rewritten (the previous text is saved as a version).

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = { fontSize: 10.5, padding: '4px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const field = { width: '100%', padding: '5px 8px', fontSize: 11.5, borderRadius: 4, boxSizing: 'border-box' }
const lines = v => (Array.isArray(v) ? v : []).join('\n')
const toList = s => String(s || '').split('\n').map(x => x.trim()).filter(Boolean)

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

function CardEditor({ card, onChange }) {
  const set = (k, v) => onChange({ ...card, [k]: v })
  const why = card.why || []
  const kn = card.knowledge || []
  const upd = (key, list, i, patch) => set(key, list.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
      <label style={muted}>One line<input style={field} value={card.summary || ''} onChange={e => set('summary', e.target.value)} /></label>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
        <label style={muted}>Where<textarea rows={2} style={field} value={card.where || ''} onChange={e => set('where', e.target.value)} /></label>
        <label style={muted}>When<textarea rows={2} style={field} value={card.when || ''} onChange={e => set('when', e.target.value)} /></label>
        <label style={muted}>Atmosphere<textarea rows={2} style={field} value={card.atmosphere || ''} onChange={e => set('atmosphere', e.target.value)} /></label>
      </div>
      <div>
        <div style={{ ...muted, fontWeight: 700 }}>Why it happens</div>
        {why.map((w, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, marginTop: 5, flexWrap: 'wrap' }}>
            <input style={{ ...field, flex: '1 1 180px' }} placeholder="What happens" value={w.event} onChange={e => upd('why', why, i, { event: e.target.value })} />
            <input style={{ ...field, flex: '2 1 260px' }} placeholder="...because" value={w.because} onChange={e => upd('why', why, i, { because: e.target.value })} />
            <button style={btn} onClick={() => set('why', why.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <button style={{ ...btn, marginTop: 6 }} onClick={() => set('why', [...why, { event: '', because: '' }])}>＋ Add a cause</button>
      </div>
      <label style={muted}>Ongoing background (one per line)<textarea rows={3} style={field} value={lines(card.background)} onChange={e => set('background', toList(e.target.value))} /></label>
      <div>
        <div style={{ ...muted, fontWeight: 700 }}>Who knows what</div>
        {kn.map((k, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, marginTop: 5, flexWrap: 'wrap' }}>
            <input style={{ ...field, flex: '1 1 110px' }} placeholder="Who" value={k.who} onChange={e => upd('knowledge', kn, i, { who: e.target.value })} />
            <input style={{ ...field, flex: '2 1 220px' }} placeholder="Knows" value={k.knows} onChange={e => upd('knowledge', kn, i, { knows: e.target.value })} />
            <input style={{ ...field, flex: '1 1 140px' }} placeholder="Hidden from" value={k.hidden_from} onChange={e => upd('knowledge', kn, i, { hidden_from: e.target.value })} />
            <button style={btn} onClick={() => set('knowledge', kn.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <button style={{ ...btn, marginTop: 6 }} onClick={() => set('knowledge', [...kn, { who: '', knows: '', hidden_from: '' }])}>＋ Add</button>
      </div>
      <label style={muted}>Must stay unexplained to the reader - show by action only (one per line)
        <textarea rows={3} style={field} value={lines(card.reader_hidden)} onChange={e => set('reader_hidden', toList(e.target.value))} /></label>
    </div>
  )
}

function Diff({ current, proposed, changes }) {
  const cw = new Set((current.why || []).map(w => `${w.event}|${w.because}`))
  const cl = k => new Set(current[k] || [])
  return (
    <div style={{ fontSize: 11.5, lineHeight: 1.55 }}>
      {(changes || []).map((c, i) => <div key={i}>• {c}</div>)}
      <div style={{ marginTop: 6 }}>
        {(proposed.why || []).filter(w => !cw.has(`${w.event}|${w.because}`)).map((w, i) => (
          <div key={i} style={{ color: 'var(--green)' }}>+ {w.event} BECAUSE {w.because}</div>
        ))}
        {(current.why || []).filter(w => !(proposed.why || []).some(p => p.event === w.event && p.because === w.because)).map((w, i) => (
          <div key={i} style={{ color: 'var(--red)', textDecoration: 'line-through' }}>− {w.event} BECAUSE {w.because}</div>
        ))}
        {['background', 'reader_hidden'].flatMap(k => (proposed[k] || []).filter(x => !cl(k).has(x)).map((x, i) => <div key={k + i} style={{ color: 'var(--green)' }}>+ ({k === 'background' ? 'background' : 'unexplained'}) {x}</div>))}
        {['where', 'when', 'atmosphere'].filter(k => proposed[k] !== current[k]).map(k => <div key={k} style={{ color: 'var(--amber)' }}>~ {k}: {proposed[k]}</div>)}
      </div>
    </div>
  )
}

function ChapterLore({ projectId, part, afterGenerate }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [ch, setCh] = useState(null)
  const [draft, setDraft] = useState(null)       // the card being edited
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [feedback, setFeedback] = useState('')
  const [proposal, setProposal] = useState(null)
  const [result, setResult] = useState(null)
  const post = part === 'post'

  const load = useCallback(() => api.lore(projectId).then(r => { setData(r); setErr(''); return r }).catch(e => setErr(e.message || 'Could not load the Lore tab')), [projectId])
  useEffect(() => { load() }, [load])

  const chapters = useMemo(() => (data ? (post ? data.written : data.plans) : []), [data, post])
  useEffect(() => {
    if (!data || ch != null) return
    const list = post ? data.written : data.plans
    if (!list.length) return
    setCh(post ? list[list.length - 1] : (list.find(n => !data.cards[String(n)]) ?? list[list.length - 1]))
  }, [data, ch, post])
  const card = data && ch != null ? data.cards[String(ch)] : null
  useEffect(() => { setDraft(card ? JSON.parse(JSON.stringify(card)) : null); setDirty(false); setProposal(null); setResult(null); setMsg('') }, [ch, card && card.updated]) // eslint-disable-line

  async function run(name, fn) {
    setBusy(name); setErr(''); setMsg('')
    try { await fn() } catch (e) { setErr(e.message || 'That failed') } finally { setBusy('') }
  }
  const drawUp = () => run('draft', async () => { await api.loreDraft(projectId, ch); await load(); setMsg('✓ Drafted from the plan' + (post ? ' and the chapter' : '') + '. Read it, edit it, then approve.') })
  const save = approve => run('save', async () => { await api.loreSave(projectId, ch, draft, approve); await load(); setMsg(approve ? '✓ Approved: the next generation of this chapter will use it.' : '✓ Saved.') })
  const undo = () => run('undo', async () => { await api.loreUndo(projectId, ch); await load(); setMsg('Undone.') })
  const propose = () => run('propose', async () => { setResult(null); setProposal(await api.loreFeedback(projectId, ch, feedback)) })
  const apply = () => run('apply', async () => {
    const r = await api.loreApply(projectId, ch, proposal.card, feedback)
    setResult(r); setProposal(null); setFeedback(''); await load(); afterGenerate && afterGenerate({})
  })

  if (err && !data) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!data) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 900 }}>
        <Card title={post ? 'Lore · after reading' : 'Lore · before generating'} action={
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {chapters.map(n => (
              <button key={n} onClick={() => setCh(n)} style={{ ...btn, padding: '2px 9px', ...(ch === n ? { borderColor: 'var(--accent)', color: 'var(--accent-light)' } : {}) }}>
                {n}{data.cards[String(n)] ? (data.cards[String(n)].status === 'approved' ? ' ✓' : ' ·') : ''}
              </button>
            ))}
          </div>}>
          <div style={muted}>
            {post
              ? 'Read or listen, then say what you want to understand or change. It becomes a change to the chapter\'s lore card (shown here as a difference); once you approve it, only the paragraphs it touches are rewritten, and the previous text is saved as a version.'
              : 'The why behind a chapter: where and when it is, why things happen in it, what is going on in the background, who knows what, and what must stay unexplained. It goes into the chapter as canon, and it is never explained in the prose, only shown.'}
          </div>
          {!chapters.length && <div style={{ ...muted, marginTop: 8 }}>{post ? 'No chapter has been written yet.' : 'No chapter has a plan yet.'}</div>}
        </Card>

        {ch != null && (
          <Card title={`Chapter ${ch}`} action={
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button style={primary} disabled={!!busy} onClick={drawUp}>{busy === 'draft' ? '✦ Drafting…' : card ? '✦ Redraft' : '✦ Draft the card'}</button>
              {card && <button style={btn} disabled={!!busy} onClick={undo}>↶ Undo</button>}
            </div>}>
            {msg && <div style={{ ...muted, color: 'var(--green)', marginBottom: 6 }}>{msg}</div>}
            {err && <div style={{ ...muted, color: 'var(--red)', marginBottom: 6 }}>{err}</div>}
            {!draft && <div style={muted}>This chapter has no card yet. Draft one from its plan{post ? ' and the written chapter' : ''}.</div>}
            {draft && !post && (
              <>
                <CardEditor card={draft} onChange={c => { setDraft(c); setDirty(true) }} />
                <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                  <button style={btn} disabled={!!busy || !dirty} onClick={() => save(false)}>Save</button>
                  <button style={primary} disabled={!!busy} onClick={() => save(true)}>Approve</button>
                  <span style={{ ...muted, alignSelf: 'center' }}>{card && card.status === 'approved' ? '✓ approved' : 'draft'}</span>
                </div>
              </>
            )}
            {draft && post && (
              <>
                <div style={{ fontSize: 11.5, lineHeight: 1.55 }}>
                  {draft.summary && <div style={{ marginBottom: 4 }}><b>{draft.summary}</b></div>}
                  {[draft.where, draft.when, draft.atmosphere].filter(Boolean).length > 0 && <div style={muted}>{[draft.where, draft.when, draft.atmosphere].filter(Boolean).join(' · ')}</div>}
                  {(draft.why || []).map((w, i) => <div key={i}>• {w.event} <span style={muted}>because</span> {w.because}</div>)}
                </div>
                <div style={{ marginTop: 10 }}>
                  <div style={{ ...muted, fontWeight: 700 }}>What did you want to understand or change?</div>
                  <textarea rows={3} style={{ ...field, marginTop: 4 }} value={feedback} onChange={e => setFeedback(e.target.value)}
                    placeholder="e.g. I couldn't tell why the enforcers were there. Make it clear Qian collects for the city's protection market." />
                  <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                    <button style={primary} disabled={!!busy || !feedback.trim()} onClick={propose}>{busy === 'propose' ? 'Working out the change…' : 'Propose a change to the lore'}</button>
                  </div>
                </div>
              </>
            )}
          </Card>
        )}

        {proposal && (
          <Card title="Proposed change to the card" action={
            <div style={{ display: 'flex', gap: 6 }}>
              <button style={btn} onClick={() => setProposal(null)}>Discard</button>
              <button style={primary} disabled={!!busy} onClick={apply}>{busy === 'apply' ? 'Rewriting the affected paragraphs… (a few minutes)' : 'Approve and rewrite the affected paragraphs'}</button>
            </div>}>
            <Diff current={proposal.current} proposed={proposal.card} changes={proposal.changes} />
          </Card>
        )}

        {result && (
          <Card title="Done">
            <div style={{ fontSize: 11.5, lineHeight: 1.55 }}>
              {result.message || result.summary}
              {(result.edited || []).map(e => (
                <div key={e.paragraph} style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--border-soft)' }}>
                  <div style={muted}>Paragraph {e.paragraph + 1} · {e.why}</div>
                  <div style={{ color: 'var(--red)', textDecoration: 'line-through' }}>{e.before}</div>
                  <div style={{ color: 'var(--green)' }}>{e.after}</div>
                </div>
              ))}
              {(result.edited || []).length > 0 && <div style={{ ...muted, marginTop: 8 }}>
                The previous text is saved as a version (Reader tab) and narration audio was cleared. {result.orange_after > 0 ? `${result.orange_after} paragraph(s) are marked orange by the gate: click one on the page to fix it.` : 'No paragraph is marked by the gate.'}
              </div>}
            </div>
          </Card>
        )}

        {card && (card.history || []).length > 0 && (
          <Card title="Changes to this card">
            {[...card.history].reverse().map((h, i) => <div key={i} style={muted}>{new Date(h.ts * 1000).toLocaleString()} · {h.note}</div>)}
          </Card>
        )}
      </div>
    </div>
  )
}


// Project-wide lore: free-form canon entries (history, powers, places, customs) that go into the premise, arcs, plans and every chapter once approved.
function WorldLore({ projectId }) {
  const [entries, setEntries] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')

  const load = useCallback(() => api.lore(projectId).then(r => { setEntries(r.world || []); setDirty(false); setErr('') }).catch(e => setErr(e.message || 'Could not load the Lore tab')), [projectId])
  useEffect(() => { load() }, [load])

  const edit = (i, patch) => { setEntries(es => es.map((e, j) => (j === i ? { ...e, ...patch } : e))); setDirty(true) }
  const add = () => { setEntries(es => [...es, { title: '', kind: '', text: '', status: 'draft' }]); setDirty(true) }
  const del = i => { setEntries(es => es.filter((_, j) => j !== i)); setDirty(true) }
  async function run(name, fn) {
    setBusy(name); setErr(''); setMsg('')
    try { await fn() } catch (e) { setErr(e.message || 'That failed') } finally { setBusy('') }
  }
  const save = () => run('save', async () => { const r = await api.loreWorldSave(projectId, entries); setEntries(r.world); setDirty(false); setMsg('✓ Saved. Approved entries are now canon for the premise, arcs, plans and every chapter.') })
  const suggest = () => run('draft', async () => {
    if (dirty) await api.loreWorldSave(projectId, entries)
    const r = await api.loreWorldDraft(projectId, note); setEntries(r.world); setDirty(false); setMsg('✓ New entries added as drafts. Read them, edit them, then approve the ones you want.')
  })

  if (err && !entries) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!entries) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  const approved = entries.filter(e => e.status === 'approved').length
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 900 }}>
        <Card title="Lore · the world" action={
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button style={btn} onClick={add}>＋ Add lore</button>
            <button style={primary} disabled={!!busy} onClick={suggest}>{busy === 'draft' ? '✦ Thinking…' : '✦ Suggest lore'}</button>
            <button style={primary} disabled={!!busy || !dirty} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
          </div>}>
          <div style={muted}>
            The history and facts behind the world. It is not tied to any chapter: every approved entry is canon for the premise, the arcs, the chapter plans and every chapter, as background that is shown by action and never explained. Chapter-by-chapter lore lives in the Lore tab after writing.
            {' '}{approved} of {entries.length} approved.
          </div>
          <input style={{ ...field, marginTop: 8 }} value={note} onChange={e => setNote(e.target.value)} placeholder="Optional: what should “Suggest lore” focus on? e.g. how the guilds really work" />
          {msg && <div style={{ ...muted, color: 'var(--green)', marginTop: 6 }}>{msg}</div>}
          {err && <div style={{ ...muted, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
        </Card>
        {entries.length === 0 && <div style={muted}>No lore yet. Add some, or let it suggest entries from the premise and world rules.</div>}
        {entries.map((e, i) => (
          <Card key={e.id || i} title={e.title || `Lore ${i + 1}`} action={
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ ...muted, color: e.status === 'approved' ? 'var(--green)' : 'var(--text-muted)' }}>{e.status === 'approved' ? '✓ approved' : 'draft'}</span>
              <button style={e.status === 'approved' ? btn : primary} onClick={() => edit(i, { status: e.status === 'approved' ? 'draft' : 'approved' })}>{e.status === 'approved' ? 'Unapprove' : 'Approve'}</button>
              <button style={btn} onClick={() => del(i)}>✕</button>
            </div>}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <input style={{ ...field, flex: '2 1 200px' }} placeholder="Title" value={e.title} onChange={ev => edit(i, { title: ev.target.value })} />
              <input style={{ ...field, flex: '1 1 120px' }} placeholder="Kind (history, power, place...)" value={e.kind} onChange={ev => edit(i, { kind: ev.target.value })} />
            </div>
            <textarea rows={3} style={{ ...field, marginTop: 6 }} placeholder="The lore, in plain sentences" value={e.text} onChange={ev => edit(i, { text: ev.target.value })} />
          </Card>
        ))}
        {dirty && <div style={muted}>You have unsaved changes.</div>}
      </div>
    </div>
  )
}

export default function LoreTab({ projectId, part, afterGenerate }) {
  return part === 'post'
    ? <ChapterLore projectId={projectId} part="post" afterGenerate={afterGenerate} />
    : <WorldLore projectId={projectId} />
}
