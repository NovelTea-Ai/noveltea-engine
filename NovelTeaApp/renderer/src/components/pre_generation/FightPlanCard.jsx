import { useEffect, useState } from 'react'
import { api } from '../../api'

// Fight plan (Combat tab, before writing): a short interview that plans one chapter's fight beat by beat against a word budget.
// The budget comes from the chapter plan's fight scene (or the Combat DNA), every option shows its word cost with a running total,
// and the finished fight card (a proposal) goes to the chapter writer once accepted. Corpus fight passages matched to the foe are
// tagged for free (beat, technique, crowd, outmatched) and can be picked into My fight moves for the chapter.

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = { fontSize: 11, padding: '6px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)', minHeight: 32 }
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const field = { fontSize: 11.5, padding: '6px 8px', borderRadius: 4, background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }
const chip = c => ({ fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: c, border: `1px solid ${c}`, whiteSpace: 'nowrap' })

function Spinner() {
  return <span style={{ display: 'inline-block', width: 11, height: 11, border: '2px solid var(--border)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 0.7s linear infinite', marginRight: 6, verticalAlign: -1 }} />
}

function Bar({ running, budget }) {
  const pct = Math.min(100, Math.round(100 * running / Math.max(1, budget)))
  const over = running > budget * 1.1
  return (
    <div>
      <div style={{ height: 6, borderRadius: 3, background: 'var(--bg-elevated)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: over ? 'var(--red)' : 'var(--accent)', transition: 'width 0.25s' }} />
      </div>
      <div style={{ ...muted, marginTop: 3, color: over ? 'var(--red)' : 'var(--text-muted)' }}>{running} of {budget} words so far{over ? ' (over the budget)' : ''}</div>
    </div>
  )
}

export default function FightPlanCard({ projectId }) {
  const [ch, setCh] = useState('')
  const [budgetIn, setBudgetIn] = useState('')
  const [info, setInfo] = useState(null)      // budget preview
  const [foe, setFoe] = useState('')
  const [sess, setSess] = useState(null)      // { session_id, beat, options, running, budget, recommended, corpus }
  const [custom, setCustom] = useState('')
  const [customWords, setCustomWords] = useState('')
  const [card, setCard] = useState(null)      // a proposed fight card
  const [saved, setSaved] = useState([])      // accepted cards
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [moves, setMoves] = useState(null)
  const [msg, setMsg] = useState('')

  const loadOverview = () => api.fightPlan(projectId).then(r => setSaved((r.chapters || []).filter(c => c.card))).catch(() => {})
  useEffect(() => { loadOverview() }, [projectId])

  const chapter = parseInt(ch, 10) || null
  async function preview(nextCh = chapter, nextBudget = budgetIn) {
    if (!nextCh) { setInfo(null); return }
    try {
      const r = await api.fightPlanBudget(projectId, nextCh, parseInt(nextBudget, 10) || null)
      setInfo(r); if (!foe || !r.foes.find(f => f.name === foe)) setFoe(r.foes[0]?.name || '')
      if (r.pending) setCard(r.pending)
    } catch (e) { setErr(e.message || 'Could not read the chapter') }
  }
  useEffect(() => { setMoves(null); setCard(null); preview() }, [ch, budgetIn])  // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (name, fn) => { setBusy(name); setErr(''); setMsg(''); try { await fn() } catch (e) { setErr(e.message || 'Failed') } finally { setBusy('') } }
  const start = () => run('start', async () => {
    const r = await api.fightPlanStart(projectId, chapter, foe || null, parseInt(budgetIn, 10) || null)
    setSess(r); setCard(null); setCustom(''); setCustomWords('')
  })
  const step = body => run('answer', async () => {
    const r = await api.fightPlanAnswer(projectId, sess.session_id, body)
    setCustom(''); setCustomWords('')
    if (r.done) { setCard(r.card); setSess(null) } else setSess(s => ({ ...s, ...r }))
  })
  const decide = action => run('decide', async () => {
    await api.fightPlanDecide(projectId, chapter || card.chapter, action)
    if (action === 'accept') setMsg('✓ Saved. The chapter writer and the chapter interview now follow this fight card.')
    setCard(null); loadOverview(); preview()
  })
  const getMoves = () => run('moves', async () => setMoves((await api.fightPlanMoves(projectId, chapter, foe || null)).moves))
  const pickMove = m => run('pick', async () => {
    const r = await api.fightPickOp(projectId, 'add', { source: { novel_id: m.novel_id, novel_title: m.novel_title, chapter: m.chapter, type: m.type, text: m.text } })
    const mine = (r.picks || []).find(p => p.source?.text === m.text)
    if (mine) await api.fightPickOp(projectId, 'update', { id: mine.id, chapter })
    setMsg(`✓ Added to My fight moves for chapter ${chapter}. Adapt it there to this book.`)
  })

  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 14 }}>
      <div style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.06em', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 6 }}>Fight plan</div>
      <div style={muted}>
        Plan a chapter's fight before it is written, beat by beat, against a word budget. Each option shows what it costs; the finished card is a proposal you accept
        or decline, and the accepted card is what the chapter writer and the interview follow.
      </div>

      {!sess && !card && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
          <label style={muted}>Chapter<br /><input style={{ ...field, width: 80 }} inputMode="numeric" value={ch} onChange={e => setCh(e.target.value.replace(/\D/g, ''))} placeholder="e.g. 1" /></label>
          <label style={muted}>Opponent<br />
            <select style={{ ...field, minWidth: 150 }} value={foe} onChange={e => setFoe(e.target.value)}>
              {(info?.foes || []).length === 0 && <option value="">(none in play)</option>}
              {(info?.foes || []).map(f => <option key={f.name} value={f.name}>{f.name} · {f.tier}</option>)}
            </select></label>
          <label style={muted}>Fight words<br /><input style={{ ...field, width: 90 }} inputMode="numeric" value={budgetIn} onChange={e => setBudgetIn(e.target.value.replace(/\D/g, ''))} placeholder={info ? String(info.budget.words) : 'auto'} /></label>
          <button style={primary} disabled={!chapter || !!busy} onClick={start}>{busy === 'start' ? <><Spinner />Planning… (about a minute)</> : 'Start the fight interview'}</button>
          <button style={btn} disabled={!chapter || !!busy} onClick={getMoves}>{busy === 'moves' ? <><Spinner />Searching…</> : 'Corpus moves for this fight'}</button>
        </div>
      )}
      {info && !sess && !card && (
        <div style={{ ...muted, marginTop: 8 }}>
          Budget {info.budget.words} words ({info.budget.source}){info.budget.chapter_words ? `, of a ${info.budget.chapter_words}-word chapter plan` : ''}. {info.hero.name} is
          {' '}{info.hero.realm || 'at an unknown realm'}; he can fight {info.hero.fights || '-'}.
          {info.budget.notes.map((n, i) => <div key={i} style={{ color: 'var(--amber)' }}>{n}</div>)}
          {info.card && <div style={{ color: 'var(--green)' }}>This chapter already has an accepted fight card (below). Starting again makes a new proposal.</div>}
        </div>
      )}

      {sess && (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
            <b style={{ fontSize: 12.5 }}>{sess.beat.label}</b>
            <span style={muted}>Question {sess.beat.step} of {sess.beat.of} · chapter {sess.chapter}{sess.foe ? ` · against ${sess.foe}` : ''} · about {sess.beat.words} words</span>
          </div>
          <Bar running={sess.running} budget={sess.budget} />
          {(sess.items || []).length > 0 && (
            <details>
              <summary style={{ ...muted, cursor: 'pointer' }}>This chapter also carries {(sess.items || []).length} planned things (clues, reveals, arrivals); {(sess.left || []).length} not placed in the fight yet</summary>
              {(sess.items || []).map(it => <div key={it.id} style={{ ...muted, margin: '3px 0 3px 10px', textDecoration: (sess.left || []).includes(it.id) ? 'none' : 'line-through' }}>({it.kind}) {it.text}</div>)}
            </details>
          )}
          {sess.options.map((o, i) => (
            <div key={i} style={{ border: `1px solid ${i === sess.recommended ? 'var(--accent)' : 'var(--border-soft)'}`, borderRadius: 'var(--radius)', padding: '8px 10px', background: 'var(--bg-elevated)', opacity: busy === 'answer' ? 0.6 : 1 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <b style={{ fontSize: 12 }}>{o.label}</b>
                {i === sess.recommended && <span style={chip('var(--accent-light)')}>suggested</span>}
                <span style={{ ...chip(o.over ? 'var(--red)' : 'var(--text-muted)'), marginLeft: 'auto' }}>~{o.words} words{o.over ? ' · over budget' : ''}</span>
              </div>
              <div style={{ fontSize: 11.5, marginTop: 4, lineHeight: 1.5 }}>{o.text}</div>
              {o.source && <div style={muted}>🧬 adapts a move from {o.source}</div>}
              {(o.weave || []).map(id => { const it = (sess.items || []).find(x => x.id === id); return it ? <div key={id} style={{ ...muted, color: 'var(--cyan)' }}>＋ carries ({it.kind}): {it.text}</div> : null })}
              <button style={{ ...btn, marginTop: 6 }} disabled={!!busy} onClick={() => step({ choice: i })}>Use this</button>
            </div>
          ))}
          {sess.corpus?.length > 0 && (
            <details>
              <summary style={{ ...muted, cursor: 'pointer' }}>The corpus passages these options adapt ({sess.corpus.length})</summary>
              {sess.corpus.map((c, i) => <div key={i} style={{ ...muted, margin: '4px 0' }}><b>{c.novel_title}</b> {c.tags.family.map(f => <span key={f} style={chip('var(--cyan)')}>{f}</span>)} {c.tags.crowd && <span style={chip('var(--amber)')}>crowd</span>} {c.tags.outmatched && <span style={chip('var(--red)')}>outmatched</span>}<br />{c.text}</div>)}
            </details>
          )}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <input style={{ ...field, flex: '1 1 220px' }} value={custom} onChange={e => setCustom(e.target.value)} placeholder="Or write this beat yourself" />
            <input style={{ ...field, width: 74 }} inputMode="numeric" value={customWords} onChange={e => setCustomWords(e.target.value.replace(/\D/g, ''))} placeholder="words" />
            <button style={btn} disabled={!custom.trim() || !!busy} onClick={() => step({ custom, custom_words: parseInt(customWords, 10) || null })}>Use mine</button>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {sess.beat.step > 1 && <button style={btn} disabled={!!busy} onClick={() => step({ back: true })}>← Back</button>}
            <button style={btn} disabled={!!busy} onClick={() => { setSess(null); setErr('') }}>Cancel</button>
            {busy === 'answer' && <span style={muted}><Spinner />Planning the next beat…</span>}
          </div>
        </div>
      )}

      {card && !sess && (
        <div style={{ marginTop: 12, border: '1px solid var(--accent)', borderRadius: 'var(--radius)', padding: 10 }}>
          <div style={{ fontWeight: 700, fontSize: 12 }}>Proposed fight card · chapter {card.chapter} · {card.foe} · {card.budget} words</div>
          {card.beats.map((b, i) => <div key={i} style={{ fontSize: 11.5, marginTop: 5, lineHeight: 1.5 }}><b>{i + 1}. {b.label}</b> <span style={muted}>~{b.words} words</span><br />{b.text}
            {(b.weave || []).map((w, k) => <div key={k} style={{ ...muted, color: 'var(--cyan)' }}>＋ {w.kind}: {w.text}</div>)}</div>)}
          {(card.unplaced || []).length > 0 && <div style={{ ...muted, marginTop: 6 }}>Not in the fight (the writer places these in other scenes): {card.unplaced.map(u => u.text).join(' · ')}</div>}
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <button style={primary} disabled={!!busy} onClick={() => decide('accept')}>Accept</button>
            <button style={btn} disabled={!!busy} onClick={() => decide('decline')}>Decline</button>
          </div>
        </div>
      )}

      {moves && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 11.5, marginBottom: 4 }}>Corpus moves matched to this fight (free search, tagged)</div>
          {Object.entries(moves).map(([beat, list]) => (
            <details key={beat} open={beat === 'reversal'} style={{ marginBottom: 4 }}>
              <summary style={{ ...muted, cursor: 'pointer', textTransform: 'capitalize' }}>{beat} ({list.length})</summary>
              {list.map((m, i) => (
                <div key={i} style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius)', padding: '6px 8px', margin: '4px 0', background: 'var(--bg-elevated)' }}>
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                    <b style={{ fontSize: 11 }}>{m.novel_title}</b>
                    {m.tags.family.map(f => <span key={f} style={chip('var(--cyan)')}>{f}</span>)}
                    {m.tags.crowd && <span style={chip('var(--amber)')}>crowd</span>}
                    {m.tags.outmatched && <span style={chip('var(--red)')}>outmatched</span>}
                  </div>
                  <div style={{ fontSize: 11, marginTop: 3, lineHeight: 1.5 }}>{m.text.slice(0, 380)}</div>
                  <button style={{ ...btn, marginTop: 4 }} disabled={!!busy} onClick={() => pickMove(m)}>＋ Pick for chapter {chapter}</button>
                </div>
              ))}
            </details>
          ))}
        </div>
      )}

      {saved.length > 0 && !sess && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 11.5, marginBottom: 4 }}>Accepted fight cards</div>
          {saved.map(c => (
            <details key={c.chapter} style={{ marginBottom: 4 }}>
              <summary style={{ ...muted, cursor: 'pointer' }}>Chapter {c.chapter} · {c.card.foe} · {c.card.budget} words · {c.card.beats.length} beats</summary>
              {c.card.beats.map((b, i) => <div key={i} style={{ fontSize: 11, margin: '3px 0 3px 10px' }}><b>{b.label}</b> <span style={muted}>~{b.words}</span>: {b.text}{(b.weave || []).map((w, k) => <div key={k} style={{ ...muted, color: 'var(--cyan)' }}>＋ {w.kind}: {w.text}</div>)}</div>)}
              <button style={{ ...btn, marginTop: 4, color: 'var(--red)' }} onClick={() => api.fightPlanDecide(projectId, c.chapter, 'remove').then(loadOverview)}>Remove this card</button>
            </details>
          ))}
        </div>
      )}
      {msg && <div style={{ ...muted, color: 'var(--green)', marginTop: 6 }}>{msg}</div>}
      {err && <div style={{ ...muted, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
    </div>
  )
}
