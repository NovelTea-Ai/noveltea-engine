import { useEffect, useState } from 'react'
import { api } from '../../api'

// Reader panel: how closely this chapter matches the corpus voice — every style
// DNA target in the Author Profile (sentence mix, paragraph mix, transitions,
// punctuation habits, dialogue share), measured on the current draft. Free and
// deterministic (no AI call), so it can be re-checked after every edit. The humor
// count is different: an AI call made once at the end of generation, shown as
// saved and not re-counted here.
export default function VoiceMatchPanel({ projectId, chapterNumber, draft }) {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function check() {
    setBusy(true); setErr('')
    try { setRes(await api.voiceMatch(projectId, chapterNumber, draft)) }
    catch (e) { setErr(e.message || 'Voice match failed') }
    finally { setBusy(false) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (chapterNumber) check() }, [projectId, chapterNumber])

  const groups = [['rhythm', 'Rhythm'], ['voice', 'Punctuation & dialogue']]
  return (
    <div style={{
      padding: '10px 12px', borderBottom: '1px solid var(--border-soft)',
      flexShrink: 0, background: 'var(--bg-elevated)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: res?.total ? 8 : 0 }}>
        <span style={{ fontSize: 12, fontWeight: 700 }}>
          Corpus voice match{res?.total ? `: ${res.score}/${res.total}` : ''}
        </span>
        {res?.before_polish?.total ? (
          <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
            before end-of-chapter polish: {res.before_polish.score}/{res.before_polish.total}
          </span>
        ) : null}
        <button onClick={check} disabled={busy} style={{
          fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)', marginLeft: 'auto',
          background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
        }}>{busy ? '…' : '↻ Re-check'}</button>
      </div>
      {err && <div style={{ fontSize: 11, color: 'var(--red)' }}>{err}</div>}
      {res && !res.total && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          This project has no Author DNA yet — set it up in the Author DNA tab to get voice targets.
        </div>
      )}
      {res?.total > 0 && groups.map(([g, title]) => {
        const rows = res.signals.filter(s => s.group === g)
        if (!rows.length) return null
        return (
          <div key={g} style={{ marginBottom: 6 }}>
            <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>
              {title}
            </div>
            {rows.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 11, lineHeight: 1.6 }}>
                <span style={{ width: 14, color: s.ok ? 'var(--green)' : 'var(--amber)', fontWeight: 700 }}>{s.ok ? '✓' : '✗'}</span>
                <span style={{ flex: '0 0 210px', color: 'var(--text-secondary)' }}>{s.label}</span>
                <span style={{ flex: '0 0 110px', color: s.ok ? 'var(--text-primary)' : 'var(--amber)', fontWeight: 600 }}>{s.value}</span>
                <span style={{ color: 'var(--text-muted)' }}>target {s.target}{s.note ? ` — ${s.note}` : ''}</span>
              </div>
            ))}
          </div>
        )
      })}
      {res?.humor && <HumorRow h={res.humor} />}
      {res?.combat?.signals?.length > 0 && <CombatRows c={res.combat} />}
    </div>
  )
}

// The chapter's fights against Combat DNA: measured live like the voice signals,
// but not part of the voice score.
function CombatRows({ c }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>
        Combat (fight check{c.missing?.length ? ` · missing: ${c.missing.join(', ')}` : ''})
      </div>
      {c.signals.map((s, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 11, lineHeight: 1.6 }}>
          <span style={{ width: 14, color: s.ok ? 'var(--green)' : 'var(--amber)', fontWeight: 700 }}>{s.ok ? '✓' : '✗'}</span>
          <span style={{ flex: '0 0 210px', color: 'var(--text-secondary)' }}>{s.label}</span>
          <span style={{ flex: '0 0 110px', color: s.ok ? 'var(--text-primary)' : 'var(--amber)', fontWeight: 600 }}>{s.value}</span>
          <span style={{ color: 'var(--text-muted)' }}>{s.target}</span>
        </div>
      ))}
    </div>
  )
}

function HumorRow({ h }) {
  const found = Object.entries(h.by_type || {})
    .map(([t, n]) => `${n} ${t.replace(/_/g, ' ')}`).join(', ')
  const added = h.added || []
  const gags = [
    h.gags?.called_back?.length ? `called back ${h.gags.called_back.join('; ')}` : '',
    h.gags?.promoted?.length ? `now running gags: ${h.gags.promoted.join('; ')}` : '',
    h.gags?.new?.length ? `new candidate ${h.gags.new.join('; ')}` : '',
  ].filter(Boolean).join(' · ')
  return (
    <div style={{ marginBottom: 2 }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>
        Humor (end-of-chapter check)
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 11, lineHeight: 1.6 }}>
        <span style={{ width: 14, color: h.ok ? 'var(--green)' : 'var(--amber)', fontWeight: 700 }}>{h.ok ? '✓' : '✗'}</span>
        <span style={{ flex: '0 0 210px', color: 'var(--text-secondary)' }}>Humor beats</span>
        <span style={{ flex: '0 0 110px', color: h.ok ? 'var(--text-primary)' : 'var(--amber)', fontWeight: 600 }}>{h.after}</span>
        <span style={{ color: 'var(--text-muted)' }}>
          target about {h.average} per chapter
          {added.length ? ` — ${h.before} before the polish, ${added.length} added` : ''}
          {' '}· counted when the chapter was generated
        </span>
      </div>
      {(found || added.length > 0 || gags) && (
        <div style={{ paddingLeft: 22, fontSize: 10.5, lineHeight: 1.6, color: 'var(--text-muted)' }}>
          {found && <div>Found: {found}</div>}
          {added.map((q, i) => <div key={i}>Added: “{q}”</div>)}
          {gags && <div>Running gags: {gags}</div>}
        </div>
      )}
    </div>
  )
}
