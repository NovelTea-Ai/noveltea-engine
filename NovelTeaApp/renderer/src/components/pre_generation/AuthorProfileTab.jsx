import { useEffect, useState } from 'react'
import { api } from '../../api'
import { Panel, PanelTitle, Spinner } from '../shared/projectUi'

/**
 * Sequential arc generation — one arc per call, each generated with every prior
 * arc in full context. Replaces the old single call that produced all 3-8 arcs
 * at once and gave each roughly two sentences.
 *
 * Has its own console (engine="arcs") so its progress doesn't interleave with
 * other generators writing to the same project stream.
 */
/**
 * Author DNA — the project's writing profile: style distributions, target reader
 * psychology, POV and genre contracts. Seeded from the corpus (1,441 deltas) and
 * fed into every arc and skeleton prompt, so it steers generation rather than
 * just describing it.
 */
// Whose style DNA the Author DNA's targets are averaged from: the whole corpus,
// one novel, or a mix of several. Nothing changes until Apply, which re-averages
// ONLY the style DNA from that source and keeps everything else on the tab.
export const VOICE_CORPUS = '__corpus__', VOICE_MIX = '__mix__'

export function VoiceSourcePicker({ sources, value, onChange, applied, onApply, busy }) {
  const sel = value.mode === 'mix' ? VOICE_MIX
    : value.mode === 'novel' && value.novels?.[0] ? value.novels[0] : VOICE_CORPUS
  const key = vs => `${vs.mode}:${[...(vs.novels || [])].sort().join(',')}`
  const pending = key(value) !== key(applied)
  const mixNovels = value.mode === 'mix' ? (value.novels || []) : []
  const canApply = value.mode !== 'mix' || mixNovels.length >= 2
  return (
    <div style={{
      marginBottom: 14, padding: '10px 12px', background: 'var(--bg-elevated)',
      border: `1px solid ${pending ? 'var(--amber)' : 'var(--border-soft)'}`, borderRadius: 'var(--radius-sm)',
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>Match the voice of</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={sel} disabled={busy}
          onChange={e => {
            const v = e.target.value
            if (v === VOICE_CORPUS) onChange({ mode: 'corpus', novels: [] })
            else if (v === VOICE_MIX) onChange({ mode: 'mix', novels: value.novels || [] })
            else onChange({ mode: 'novel', novels: [v] })
          }}
          style={{
            flex: 1, minWidth: 200, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)',
          }}>
          <option value={VOICE_CORPUS}>Whole corpus — all {sources.length} novels</option>
          <option value={VOICE_MIX}>Mix of several novels…</option>
          <optgroup label="One novel">
            {sources.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}
          </optgroup>
        </select>
        <button onClick={onApply} disabled={busy || !canApply}
          title="Re-average the style, voice, pacing and humor targets from this source — keeps everything else on this tab"
          style={{
            fontSize: 10, padding: '4px 12px', borderRadius: 'var(--radius-sm)', fontWeight: 600,
            background: pending && canApply ? 'var(--accent)' : 'var(--bg-surface)',
            border: `1px solid ${pending && canApply ? 'var(--accent)' : 'var(--border)'}`,
            color: pending && canApply ? '#fff' : 'var(--text-secondary)',
          }}>
          {busy ? <Spinner size={10} /> : 'Apply'}
        </button>
      </div>
      {value.mode === 'mix' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: '3px 10px', marginTop: 8 }}>
          {sources.map(s => {
            const on = mixNovels.includes(s.id)
            return (
              <label key={s.id} style={{
                display: 'flex', alignItems: 'center', gap: 5, fontSize: 10.5, cursor: 'pointer',
                color: on ? 'var(--text-primary)' : 'var(--text-muted)',
              }}>
                <input type="checkbox" checked={on} disabled={busy}
                  onChange={() => onChange({ mode: 'mix', novels: on ? mixNovels.filter(n => n !== s.id) : [...mixNovels, s.id] })} />
                {s.title}
              </label>
            )
          })}
        </div>
      )}
      <div style={{ fontSize: 10, color: pending ? 'var(--amber)' : 'var(--text-muted)', marginTop: 6, lineHeight: 1.5 }}>
        {value.mode === 'mix' && mixNovels.length < 2
          ? 'Tick at least two novels to blend — each contributes equally.'
          : pending
            ? 'Not applied yet — press Apply to re-average the style, voice, pacing and humor targets below from this source.'
            : 'The style, voice, pacing and humor targets below are averaged from this source.'}
      </div>
    </div>
  )
}

export const VOICE_LABELS = {
  exclamations: ['Exclamation marks', 'per 100 sentences'],
  questions: ['Questions', 'per 100 sentences'],
  ellipses: ['Trailing ellipses (...)', 'per 100 sentences'],
  em_dashes: ['Em-dashes (—)', 'per 100 sentences'],
  triplets: ['"X, Y and Z" triplets', 'per 100 sentences'],
  dialogue_share: ['Dialogue share', '% of text'],
}

export function VoiceTargetsEditor({ voice, fallback, onChange }) {
  const entries = Object.entries(voice || {}).filter(([k]) => VOICE_LABELS[k])
  if (!entries.length) return null
  // Editing a target slides its range with it (same width either side): the
  // end-of-chapter check enforces the range, not the single number.
  const setTarget = (k, shown) => {
    const cur = voice[k]
    const t = Math.max(0, Number(shown) || 0) / 100
    const below = cur.target - cur.low, above = cur.high - cur.target
    onChange({ ...voice, [k]: { target: +t.toFixed(4), low: +Math.max(0, t - below).toFixed(4), high: +(t + above).toFixed(4) } })
  }
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 2 }}>Corpus voice</div>
      <div style={{ fontSize: 10, color: fallback ? 'var(--amber)' : 'var(--text-muted)', marginBottom: 6, lineHeight: 1.5 }}>
        {fallback
          ? 'Measured from your voice source — not saved in this profile yet. Press Save to lock them in.'
          : 'Punctuation habits measured from the voice source — stated in every chapter prompt and enforced in the end-of-chapter polish.'}
      </div>
      {entries.map(([k, v]) => {
        const [label, unit] = VOICE_LABELS[k]
        return (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', width: 150 }}>{label}</span>
            <input type="number" min={0} step={k === 'dialogue_share' ? 1 : 0.5}
              value={+(v.target * 100).toFixed(1)} onChange={e => setTarget(k, e.target.value)}
              style={{ width: 64, padding: '3px 6px', fontSize: 11, borderRadius: 4 }} />
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {unit} · range {+(v.low * 100).toFixed(1)}–{+(v.high * 100).toFixed(1)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export function AuthorProfileTab({ projectId }) {
  const [profile, setProfile] = useState(null)
  const [defaults, setDefaults] = useState(null)
  const [seededNow, setSeededNow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  // Voice source — whose style DNA this profile averages: the whole corpus, one
  // novel, or a mix of several (see _corpus_author_defaults' `novels`).
  const [voiceSources, setVoiceSources] = useState([])
  const [voiceSource, setVoiceSource] = useState({ mode: 'corpus', novels: [] })
  const [voiceFallback, setVoiceFallback] = useState(false)   // targets shown aren't saved in the profile yet

  useEffect(() => {
    let dead = false
    api.getAuthorProfile(projectId)
      .then(r => {
        if (dead) return
        const p = r.profile || {}
        // A profile saved before voice targets existed: show the ones in force
        // (from its voice source) so they can be reviewed/edited and saved.
        if (!p.style_dna?.voice && r.effective_voice && Object.keys(r.effective_voice).length) {
          p.style_dna = { ...(p.style_dna || {}), voice: r.effective_voice }
          setVoiceFallback(true)
        }
        // Same for the pacing section added after many profiles were saved.
        // (Humor DNA has its own tab, which fills in its own.)
        if (!p.pacing_dna && r.effective_pacing && Object.keys(r.effective_pacing).length) {
          p.pacing_dna = r.effective_pacing
          setVoiceFallback(true)
        }
        setProfile(p)
        setDefaults(r.corpus_defaults || {})
        setSeededNow(!!r.seeded_now)
        setVoiceSources(r.voice_sources || [])
        setVoiceSource(p.voice_source || { mode: 'corpus', novels: [] })
      })
      .catch(e => setMsg(e.message || 'Could not load profile'))
    return () => { dead = true }
  }, [projectId])

  async function applyVoiceSource() {
    setBusy(true); setMsg('')
    try {
      // Style DNA only — intent, protagonist rules and everything else on this tab are kept.
      const r = await api.saveAuthorProfile(projectId, profile, false, voiceSource, true)
      setProfile(r.profile)
      setSeededNow(false)
      setVoiceFallback(false)
      setMsg('✓ Style DNA re-averaged from ' + voiceSourceLabel(voiceSource))
    } catch (e) {
      setMsg(e.message || 'Could not apply voice source')
    } finally {
      setBusy(false)
      setTimeout(() => setMsg(''), 3500)
    }
  }

  function voiceSourceLabel(vs) {
    if (vs.mode === 'corpus' || !vs.novels?.length) return 'the whole corpus'
    const names = vs.novels.map(id => voiceSources.find(s => s.id === id)?.title || id)
    return vs.mode === 'mix' ? `a mix of ${names.join(', ')}` : names[0]
  }

  async function save(next, reseed = false) {
    setBusy(true); setMsg('')
    try {
      const r = await api.saveAuthorProfile(projectId, reseed ? null : next, reseed, reseed ? voiceSource : null)
      setProfile(r.profile)
      setSeededNow(false)
      setVoiceFallback(false)
      setMsg(reseed ? `✓ Re-seeded from ${voiceSourceLabel(voiceSource)}` : '✓ Saved')
    } catch (e) {
      setMsg(e.message || 'Save failed')
    } finally {
      setBusy(false)
      setTimeout(() => setMsg(''), 3500)
    }
  }

  if (!profile) {
    return <div style={{ padding: 30, fontSize: 12, color: 'var(--text-muted)' }}>
      {msg || 'Loading author profile…'}
    </div>
  }

  const sd = profile.style_dna || {}
  const rp = profile.reader_psychology || {}
  const nv = profile.narrative_voice || {}
  const ai = profile.author_intent || {}
  const contracts = profile.genre_contracts || []
  const pdna = profile.protagonist_dna || {}
  const consistencyNotes = defaults?.protagonist_consistency_notes || []

  const setPath = (path, value) => {
    const next = JSON.parse(JSON.stringify(profile))
    let node = next
    for (let i = 0; i < path.length - 1; i++) {
      node[path[i]] = node[path[i]] || {}
      node = node[path[i]]
    }
    node[path[path.length - 1]] = value
    setProfile(next)
  }

  const Dist = ({ title, obj, path }) => {
    const entries = Object.entries(obj || {})
    if (!entries.length) return null
    return (
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>{title}</div>
        {entries.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', width: 150 }}>
              {k.replace(/_/g, ' ')}
            </span>
            <input type="range" min={0} max={1} step={0.01} value={v ?? 0}
              onChange={e => setPath([...path, k], Number(e.target.value))}
              style={{ flex: 1, maxWidth: 200 }} />
            <span style={{ fontSize: 10.5, width: 38, textAlign: 'right', color: 'var(--accent)' }}>
              {Math.round((v ?? 0) * 100)}%
            </span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
      <Panel>
        <PanelTitle action={
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {msg && <span style={{ fontSize: 10, color: msg.startsWith('✓') ? 'var(--green)' : 'var(--red)' }}>{msg}</span>}
            <button onClick={() => save(null, true)} disabled={busy}
              title="Discard ALL edits on this tab and re-average everything from the selected voice source (to re-average only the style targets, use Apply above)"
              style={{
                fontSize: 10, padding: '3px 10px', background: 'var(--bg-elevated)',
                border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                color: 'var(--text-secondary)',
              }}>↻ Re-seed</button>
            <button onClick={() => save(profile)} disabled={busy}
              className="btn-primary" style={{ fontSize: 10, padding: '3px 12px' }}>
              {busy ? <Spinner size={10} /> : 'Save'}
            </button>
          </div>
        }>Author DNA</PanelTitle>

        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55, marginBottom: 12 }}>
          This book's writing profile. It is injected into every arc and chapter
          plan, so changes here steer what gets generated.
          {profile.seeded_from && (
            <> Seeded from <b>{profile.seeded_from.deltas}</b> extracted chapters
            ({profile.seeded_from.genre}).</>
          )}
          {seededNow && <b style={{ color: 'var(--amber)' }}> Not saved yet — press Save to lock it in.</b>}
        </div>

        <VoiceSourcePicker sources={voiceSources} value={voiceSource} onChange={setVoiceSource}
          applied={profile.voice_source || { mode: 'corpus', novels: [] }}
          onApply={applyVoiceSource} busy={busy} />

        {/* The chosen novel as a construction reference at every level (routers/reference_mechanics.py) */}
        {(() => {
          const applied = profile.voice_source || { mode: 'corpus', novels: [] }
          const one = applied.mode !== 'corpus' && (applied.novels || []).length > 0
          return (
            <div style={{ marginBottom: 14, padding: '10px 12px', background: 'var(--bg-elevated)', border: `1px solid ${profile.reference_plans && one ? 'var(--accent)' : 'var(--border-soft)'}`, borderRadius: 'var(--radius-sm)' }}>
              {(() => {
                const wholeCorpus = profile.reference_scope === 'corpus'
                const usable = one || wholeCorpus
                return (<>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700, cursor: usable ? 'pointer' : 'default', opacity: usable ? 1 : 0.55 }}>
                    <input type="checkbox" checked={!!profile.reference_plans && usable} disabled={busy || !usable}
                      onChange={e => save({ ...profile, reference_plans: e.target.checked })} />
                    Plan from corpus data and raws (how chapters are built)
                  </label>
                  <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', margin: '6px 0 2px 22px', fontSize: 11 }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
                      <input type="radio" name="refscope" checked={wholeCorpus} disabled={busy}
                        onChange={() => save({ ...profile, reference_scope: 'corpus' })} />
                      Whole corpus{one ? `, ${voiceSourceLabel(applied)} ranked first` : ''}
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: one ? 'pointer' : 'default', opacity: one ? 1 : 0.5 }}>
                      <input type="radio" name="refscope" checked={!wholeCorpus} disabled={busy || !one}
                        onChange={() => save({ ...profile, reference_scope: 'novel' })} />
                      {one ? `Only ${voiceSourceLabel(applied)}` : 'Only the chosen novel (pick one above and Apply)'}
                    </label>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, lineHeight: 1.5 }}>
                    Arcs follow the reference's rhythm of set pieces; chapter plans copy how its matching chapters are built (beat order, run-up against fight, scene joins, talk between blows, what each beat is for); the writer hears its real lines for those beats. {wholeCorpus ? 'Each plan draws on the best matches from all 18 novels, plus the best from your chosen novel.' : ''} Never names or events, and always below the Plot tree, Timeline and arcs.
                  </div>
                </>)
              })()}
            </div>
          )
        })()}

        <Dist title="Sentence length mix" obj={sd.sentence_length_distribution}
          path={['style_dna', 'sentence_length_distribution']} />
        <Dist title="Paragraph length mix" obj={sd.paragraph_length_distribution}
          path={['style_dna', 'paragraph_length_distribution']} />

        <VoiceTargetsEditor voice={sd.voice} fallback={voiceFallback}
          onChange={v => setPath(['style_dna', 'voice'], v)} />

        {profile.pacing_dna && (
          <div style={{ marginBottom: 12, paddingTop: 10, borderTop: '1px solid var(--border-soft)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 2 }}>Pacing DNA</div>
            <div style={{ fontSize: 10, color: voiceFallback ? 'var(--amber)' : 'var(--text-muted)', marginBottom: 8, lineHeight: 1.5 }}>
              How chapters are built and paced — steers arc and chapter-skeleton planning. Humor DNA has its own tab now.
              {voiceFallback && ' Measured from your voice source; press Save to lock it in.'}
            </div>
            {profile.pacing_dna && (<>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10.5, color: 'var(--text-muted)', width: 150 }}>Scenes per chapter</span>
                <input type="number" min={1} max={12} value={profile.pacing_dna.scenes_per_chapter ?? ''}
                  onChange={e => setPath(['pacing_dna', 'scenes_per_chapter'], Number(e.target.value) || null)}
                  style={{ width: 56, padding: '3px 6px', fontSize: 11, borderRadius: 4 }} />
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  ≈ {profile.pacing_dna.scenes_per_chapter ? Math.round(2000 / profile.pacing_dna.scenes_per_chapter) : '—'} words each at 2,000-word chapters
                </span>
              </div>
              <Dist title="Scene pacing mix" obj={profile.pacing_dna.scene_pacing_mix} path={['pacing_dna', 'scene_pacing_mix']} />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10.5, color: 'var(--text-muted)', width: 150 }}>Payoff cadence</span>
                <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>a payoff or climax chapter every</span>
                <input type="number" min={1} max={10} value={profile.pacing_dna.payoff_every_n_chapters ?? ''}
                  onChange={e => setPath(['pacing_dna', 'payoff_every_n_chapters'], Number(e.target.value) || null)}
                  style={{ width: 48, padding: '3px 6px', fontSize: 11, borderRadius: 4 }} />
                <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>chapters</span>
              </div>
              <Dist title="Payoff mix (the satisfaction a chapter delivers)" obj={profile.pacing_dna.payoff_mix} path={['pacing_dna', 'payoff_mix']} />
            </>)}
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>Transition vocabulary</div>
          <input value={(sd.favorite_transitions || []).join(', ')}
            onChange={e => setPath(['style_dna', 'favorite_transitions'],
              e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
            placeholder="However, suddenly, meanwhile…"
            style={{ width: '100%', padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>Target reader emotions (0–10)</div>
          {Object.entries(rp.reader_emotions || {}).map(([k, v]) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
              <span style={{ fontSize: 10.5, color: 'var(--text-muted)', width: 150 }}>{k}</span>
              <input type="range" min={0} max={10} step={0.1} value={v ?? 0}
                onChange={e => setPath(['reader_psychology', 'reader_emotions', k], Number(e.target.value))}
                style={{ flex: 1, maxWidth: 200 }} />
              <span style={{ fontSize: 10.5, width: 38, textAlign: 'right', color: 'var(--accent)' }}>{v}</span>
            </div>
          ))}
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>Default chapter tension curve</div>
          <div style={{ display: 'flex', gap: 10 }}>
            {['start', 'peak', 'end'].map(k => (
              <label key={k} style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                {k}&nbsp;
                <input type="number" min={0} max={100}
                  value={(rp.tension_curve || {})[k] ?? ''}
                  onChange={e => setPath(['reader_psychology', 'tension_curve', k], Number(e.target.value))}
                  style={{ width: 56, padding: '3px 6px', fontSize: 11, borderRadius: 4 }} />
              </label>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>Narrative POV</div>
          <select value={nv.dominant_pov || 'close_third'}
            onChange={e => setPath(['narrative_voice', 'dominant_pov'], e.target.value)}
            style={{ padding: '4px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }}>
            {(nv.pov_options && nv.pov_options.length
              ? nv.pov_options
              : ['close_third', 'distant_third', 'omniscient', 'first_person']
            ).map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>
            Genre contracts <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>— promises every chapter should keep</span>
          </div>
          <textarea value={contracts.join('\n')} rows={4}
            onChange={e => setPath(['genre_contracts'],
              e.target.value.split('\n').map(s => s.trim()).filter(Boolean))}
            style={{ width: '100%', padding: '6px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>
            Protagonist consistency rules <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>— non-negotiable behaviors for THIS book's protagonist</span>
          </div>
          {consistencyNotes.length > 0 && (
            <div style={{
              fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 6,
              padding: '6px 8px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)',
            }}>
              <b>Corpus reference</b> — cross-novel findings on what keeps protagonists consistent (for inspiration, not injected as-is):
              <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
                {consistencyNotes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </div>
          )}
          <textarea value={(pdna.rules || []).join('\n')} rows={4}
            onChange={e => setPath(['protagonist_dna', 'rules'],
              e.target.value.split('\n').map(s => s.trim()).filter(Boolean))}
            placeholder="e.g. NEVER show mercy to someone who threatened an ally&#10;ALWAYS express anger as calm precision, not shouting"
            style={{ width: '100%', padding: '6px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
        </div>

        <div>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 5 }}>Author strategy notes</div>
          <textarea value={ai.strategy_notes || ''} rows={3}
            onChange={e => setPath(['author_intent', 'strategy_notes'], e.target.value)}
            placeholder="Standing instructions for how this book should be written…"
            style={{ width: '100%', padding: '6px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
        </div>
      </Panel>
    </div>
  )
}
