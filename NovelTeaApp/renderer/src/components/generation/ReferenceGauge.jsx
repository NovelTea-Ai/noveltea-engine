import { useEffect, useState } from 'react'
import { api } from '../../api'

// Reference gauge: how much a chapter of the Author DNA novel actually holds (words, scenes, words per scene type,
// story events, dialogue lines) beside this chapter's plan, with suggested scene budgets. Pure measurement on the
// server, no AI call. Nothing in the plan changes until Apply is pressed (the project is backed up first).
const pretty = id => (id || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

export default function ReferenceGauge({ projectId, chapterNum, onApplied }) {
  const [g, setG] = useState(null)
  const [err, setErr] = useState('')
  const [applying, setApplying] = useState(false)
  const [done, setDone] = useState('')

  const load = () => {
    setErr(''); setG(null)
    api.referenceGauge(projectId, chapterNum).then(setG).catch(e => setErr(e.message || 'Could not measure the reference'))
  }
  useEffect(() => { setDone(''); load() }, [projectId, chapterNum]) // eslint-disable-line react-hooks/exhaustive-deps

  async function apply() {
    if (!g?.plan) return
    setApplying(true); setErr('')
    try {
      const r = await api.referenceGaugeApply(projectId, chapterNum, g.plan.scenes.map(s => s.suggested))
      setDone(`Applied — ${r.total} words (backup ${r.backup}).`)
      load()
      onApplied && onApplied()
    } catch (e) { setErr(e.message || 'Could not apply') }
    finally { setApplying(false) }
  }

  const box = { border: '1px solid var(--border)', borderRadius: 10, padding: 10, marginTop: 0, fontSize: 11, color: 'var(--text-secondary)' }
  if (err) return <div style={box}><b>Reference gauge</b> — <span style={{ color: 'var(--red)' }}>{err}</span></div>
  if (!g) return <div style={box}><b>Reference gauge</b> — measuring…</div>
  if (!g.ok) return <div style={box}><b>Reference gauge</b> — {g.reason}</div>

  const same = g.same_chapter?.[0]
  const name = g.novels.map(pretty).join(' + ')
  const p = g.plan
  const changed = p && p.scenes.some(s => s.planned !== s.suggested)
  const loadColor = { balanced: 'var(--green)', 'over-packed': 'var(--amber)', thin: 'var(--amber)' }
  const th = { textAlign: 'left', fontWeight: 600, padding: '3px 6px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }
  const td = { padding: '3px 6px', whiteSpace: 'nowrap' }

  return (
    <div style={box}>
      <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>Reference gauge · {name}</div>
      <div style={{ lineHeight: 1.6 }}>
        {same
          ? <>Their ch{g.chapter}: <b>{same.words.toLocaleString()}w</b> · {same.scenes.length} scenes · {same.events} events · {same.dialogue_lines} dialogue lines<br /></>
          : <>Their ch{g.chapter} isn't in the corpus — using the median only.<br /></>}
        Ch{g.window[0]}–{g.window[1]} median ({g.chapters_measured} chapters): <b>{Math.round(g.median.words).toLocaleString()}w</b> · {g.median.scenes} scenes
        · ~{g.median.words_per_scene}w/scene · {g.median.events} events · {Math.round(g.median.dialogue_lines)} dialogue lines<br />
        Target for this chapter: <b>{g.target.words.toLocaleString()}w</b> · ~{g.target.events} events · ~{g.target.dialogue_lines} dialogue lines
        {g.target.words >= g.cap ? ` (held to the ${g.cap}-word cap)` : ''}
      </div>

      {p ? (
        <>
          <div style={{ overflowX: 'auto', marginTop: 8 }}>
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead><tr><th style={th}>Scene</th><th style={th}>Type</th><th style={th}>Plan</th><th style={th}>Their type</th><th style={th}>Suggested</th></tr></thead>
              <tbody>
                {p.scenes.map(s => (
                  <tr key={s.scene} style={{ borderTop: '1px solid var(--border-soft, var(--border))' }}>
                    <td style={td}>{s.scene}</td>
                    <td style={td}>{s.type.replace(/_/g, ' ')}</td>
                    <td style={td}>{s.planned ?? '—'}w</td>
                    <td style={{ ...td, color: 'var(--text-muted)' }}>~{s.reference_type_median}w</td>
                    <td style={{ ...td, fontWeight: 700, color: s.planned === s.suggested ? 'inherit' : 'var(--accent-light, var(--accent))' }}>{s.suggested}w</td>
                  </tr>
                ))}
                <tr style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={td} colSpan={2}><b>Total</b></td><td style={td}><b>{p.words}w</b></td><td style={td} />
                  <td style={{ ...td, fontWeight: 700 }}>{p.suggested_total}w</td>
                </tr>
              </tbody>
            </table>
          </div>
          {p.content.load && (
            <div style={{ marginTop: 6, lineHeight: 1.5 }}>
              Content: <b style={{ color: loadColor[p.content.load] }}>{p.content.load}</b> — your plan gives each of its {p.beats} beats
              ~{p.content.plan_words_per_beat}w; {name} spends ~{p.content.reference_words_per_event}w per story event.
              {p.content.load === 'over-packed' && ' Too many beats for the length: cut beats or give the scenes more words.'}
              {p.content.load === 'thin' && ' Few beats for the length: the scenes will need padding unless you add beats.'}
            </div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
            <button onClick={apply} disabled={applying || !changed} className="btn-primary"
              style={{ padding: '5px 14px', fontSize: 11, opacity: changed ? 1 : 0.5 }}
              title="Write the suggested budgets into this chapter's plan (the project is backed up first)">
              {applying ? 'Applying…' : changed ? 'Apply suggested budgets' : 'Plan already matches'}</button>
            {done && <span style={{ color: 'var(--green)' }}>{done}</span>}
          </div>
        </>
      ) : <div style={{ marginTop: 6 }}>This chapter has no plan yet.</div>}
    </div>
  )
}
