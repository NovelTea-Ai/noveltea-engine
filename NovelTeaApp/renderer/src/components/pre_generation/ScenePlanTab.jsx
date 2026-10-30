import { useEffect, useState } from 'react'
import { api } from '../../api'

// Scene plans (before writing): the fight-plan interview for every other kind of scene (a conversation, a discovery, learning, a place, the fallout).
// Each scene is planned beat by beat against its word budget; options show their cost, can carry the chapter's planned clues, reveals and arrivals,
// and the finished card (a proposal) goes to the chapter writer once accepted. Fights have their own planner in the Combat tab.

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = { fontSize: 11, padding: '6px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)', minHeight: 32 }
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const field = { fontSize: 11.5, padding: '6px 8px', borderRadius: 4, background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }
const chip = c => ({ fontSize: 9, fontWeight: 700, padding: '1px 7px', borderRadius: 10, textTransform: 'uppercase', letterSpacing: '0.04em', color: c, border: `1px solid ${c}`, whiteSpace: 'nowrap' })
const Spinner = () => <span style={{ display: 'inline-block', width: 11, height: 11, border: '2px solid var(--border)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 0.7s linear infinite', marginRight: 6, verticalAlign: -1 }} />

function Bar({ running, budget }) {
  const pct = Math.min(100, Math.round(100 * running / Math.max(1, budget)))
  const over = running > budget * 1.1
  return (
    <div>
      <div style={{ height: 6, borderRadius: 3, background: 'var(--bg-elevated)', overflow: 'hidden' }}><div style={{ width: `${pct}%`, height: '100%', background: over ? 'var(--red)' : 'var(--accent)', transition: 'width 0.25s' }} /></div>
      <div style={{ ...muted, marginTop: 3, color: over ? 'var(--red)' : 'var(--text-muted)' }}>{running} of {budget} words so far{over ? ' (over the budget)' : ''}</div>
    </div>
  )
}

function CardView({ c }) {
  return (
    <div>
      {c.beats.map((b, i) => (
        <div key={i} style={{ fontSize: 11.5, marginTop: 5, lineHeight: 1.5 }}><b>{i + 1}. {b.label}</b> <span style={muted}>~{b.words} words</span><br />{b.text}
          {(b.weave || []).map((w, k) => <div key={k} style={{ ...muted, color: 'var(--cyan)' }}>＋ {w.kind}: {w.text}</div>)}</div>
      ))}
      {(c.unplaced || []).length > 0 && <div style={{ ...muted, marginTop: 6 }}>Not in this scene (the writer places these elsewhere): {c.unplaced.map(u => u.text).join(' · ')}</div>}
    </div>
  )
}

export default function ScenePlanTab({ projectId }) {
  const [ch, setCh] = useState('')
  const [sceneNo, setSceneNo] = useState('')
  const [kind, setKind] = useState('dialogue')
  const [wordsIn, setWordsIn] = useState('')
  const [info, setInfo] = useState(null)
  const [kinds, setKinds] = useState({})
  const [people, setPeople] = useState([])
  const [sess, setSess] = useState(null)
  const [pending, setPending] = useState({})   // slot -> proposed card
  const [saved, setSaved] = useState({})
  const [custom, setCustom] = useState('')
  const [customWords, setCustomWords] = useState('')
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => { api.scenePlan(projectId).then(r => setKinds(r.kinds || {})).catch(() => {}) }, [projectId])
  const chapter = parseInt(ch, 10) || null

  async function preview(c = chapter, s = sceneNo, k = kind, w = wordsIn) {
    if (!c) { setInfo(null); return }
    try {
      const r = await api.scenePlanBudget(projectId, c, parseInt(s, 10) || null, s ? null : k, parseInt(w, 10) || null)
      setInfo(r); setSaved(r.cards || {}); setPending(r.pending || {})
      if (s && r.kind !== kind) setKind(r.kind)
    } catch (e) { setErr(e.message || 'Could not read the chapter') }
  }
  useEffect(() => { preview() }, [ch, sceneNo, kind, wordsIn])  // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (name, fn) => { setBusy(name); setErr(''); setMsg(''); try { await fn() } catch (e) { setErr(e.message || 'Failed') } finally { setBusy('') } }
  const start = () => run('start', async () => {
    const r = await api.scenePlanStart(projectId, chapter, parseInt(sceneNo, 10) || null, kind, parseInt(wordsIn, 10) || null, people)
    setSess(r); setCustom(''); setCustomWords('')
  })
  const step = body => run('answer', async () => {
    const r = await api.scenePlanAnswer(projectId, sess.session_id, body)
    setCustom(''); setCustomWords('')
    if (r.done) { setPending(p => ({ ...p, [r.slot]: r.card })); setSess(null) } else setSess(s => ({ ...s, ...r }))
  })
  const decide = (slot, action) => run('decide', async () => {
    await api.scenePlanDecide(projectId, chapter, slot, action)
    if (action === 'accept') setMsg('✓ Saved. The chapter writer and the chapter interview now follow this scene plan.')
    preview()
  })
  const toggle = n => setPeople(p => p.includes(n) ? p.filter(x => x !== n) : [...p, n].slice(0, 6))

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
      <div style={{ maxWidth: 1000, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.06em', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 6 }}>Scene plans</div>
          <div style={muted}>
            Plan a scene before it is written: five beats, one question each, against the scene's word budget. Every option shows what it costs. It can carry the chapter's
            planned clues, reveals and new faces, so they happen inside the scene. The card is a proposal you accept or decline; accepted cards go to the chapter writer and the
            interview. Fights have their own planner in the Combat tab.
          </div>

          {!sess && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
              <label style={muted}>Chapter<br /><input style={{ ...field, width: 80 }} inputMode="numeric" value={ch} onChange={e => { setCh(e.target.value.replace(/\D/g, '')); setSceneNo('') }} placeholder="e.g. 1" /></label>
              <label style={muted}>Scene in the plan<br />
                <select style={{ ...field, minWidth: 190 }} value={sceneNo} onChange={e => setSceneNo(e.target.value)}>
                  <option value="">(no plan scene: choose a kind)</option>
                  {(info?.scenes || []).filter(s => !s.fight).map(s => <option key={s.number} value={s.number}>Scene {s.number} · {s.type || 'scene'}{s.words ? ` · ${s.words} words` : ''}</option>)}
                </select></label>
              <label style={muted}>Kind of scene<br />
                <select style={field} value={kind} onChange={e => { setKind(e.target.value); setSceneNo('') }}>
                  {Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                </select></label>
              <label style={muted}>Scene words<br /><input style={{ ...field, width: 90 }} inputMode="numeric" value={wordsIn} onChange={e => setWordsIn(e.target.value.replace(/\D/g, ''))} placeholder={info ? String(info.words) : 'auto'} /></label>
              <button style={primary} disabled={!chapter || !!busy} onClick={start}>{busy === 'start' ? <><Spinner />Planning… (about a minute)</> : 'Start the scene interview'}</button>
            </div>
          )}
          {info && !sess && (
            <div style={{ ...muted, marginTop: 8 }}>
              {info.label}: {info.words} words ({info.source}){info.chapter_words ? `, of a ${info.chapter_words}-word chapter plan` : ''}.
              {info.notes.map((n, i) => <div key={i} style={{ color: 'var(--amber)' }}>{n}</div>)}
              {(info.people || []).length > 0 && (
                <div style={{ marginTop: 6 }}>Who is in it (pick up to 6; their voices guide the options):<br />
                  {info.people.map(n => <button key={n} onClick={() => toggle(n)} aria-pressed={people.includes(n)} style={{ ...btn, minHeight: 26, padding: '2px 9px', margin: '3px 4px 0 0', ...(people.includes(n) ? { borderColor: 'var(--accent)', color: 'var(--accent-light)' } : {}) }}>{n}</button>)}
                </div>
              )}
            </div>
          )}

          {sess && (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                <b style={{ fontSize: 12.5 }}>{sess.beat.label}</b>
                <span style={muted}>Question {sess.beat.step} of {sess.beat.of} · chapter {sess.chapter} · {sess.label} · about {sess.beat.words} words</span>
              </div>
              <Bar running={sess.running} budget={sess.budget} />
              {(sess.items || []).length > 0 && (
                <details>
                  <summary style={{ ...muted, cursor: 'pointer' }}>This chapter also carries {(sess.items || []).length} planned things; {(sess.left || []).length} not placed in this scene yet</summary>
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
                  {o.source && <div style={muted}>🧬 adapts a moment from {o.source}</div>}
                  {(o.weave || []).map(id => { const it = (sess.items || []).find(x => x.id === id); return it ? <div key={id} style={{ ...muted, color: 'var(--cyan)' }}>＋ carries ({it.kind}): {it.text}</div> : null })}
                  <button style={{ ...btn, marginTop: 6 }} disabled={!!busy} onClick={() => step({ choice: i })}>Use this</button>
                </div>
              ))}
              {sess.corpus?.length > 0 && (
                <details><summary style={{ ...muted, cursor: 'pointer' }}>The corpus passages these options adapt ({sess.corpus.length})</summary>
                  {sess.corpus.map((c, i) => <div key={i} style={{ ...muted, margin: '4px 0' }}><b>{c.novel_title}</b><br />{c.text}</div>)}</details>
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
          {msg && <div style={{ ...muted, color: 'var(--green)', marginTop: 6 }}>{msg}</div>}
          {err && <div style={{ ...muted, color: 'var(--red)', marginTop: 6 }}>{err}</div>}
        </div>

        {!sess && Object.keys(pending).length > 0 && Object.entries(pending).map(([slot, c]) => (
          <div key={slot} style={{ border: '1px solid var(--accent)', borderRadius: 'var(--radius-lg)', padding: 12, background: 'var(--bg-card)' }}>
            <div style={{ fontWeight: 700, fontSize: 12 }}>Proposed scene plan · chapter {c.chapter}{c.scene ? ` · scene ${c.scene}` : ''} · {c.label} · {c.budget} words{(c.people || []).length ? ` · with ${c.people.join(', ')}` : ''}</div>
            <CardView c={c} />
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              <button style={primary} disabled={!!busy} onClick={() => decide(slot, 'accept')}>Accept</button>
              <button style={btn} disabled={!!busy} onClick={() => decide(slot, 'decline')}>Decline</button>
            </div>
          </div>
        ))}

        {!sess && Object.keys(saved).length > 0 && (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 12 }}>
            <div style={{ fontWeight: 700, fontSize: 11.5, marginBottom: 4 }}>Accepted scene plans for chapter {chapter}</div>
            {Object.entries(saved).map(([slot, c]) => (
              <details key={slot} style={{ marginBottom: 4 }}>
                <summary style={{ ...muted, cursor: 'pointer' }}>{c.scene ? `Scene ${c.scene} · ` : ''}{c.label} · {c.budget} words</summary>
                <CardView c={c} />
                <button style={{ ...btn, marginTop: 4, color: 'var(--red)' }} onClick={() => decide(slot, 'remove')}>Remove this plan</button>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
