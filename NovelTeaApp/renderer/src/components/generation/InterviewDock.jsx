import GateFailureDetails from './GateFailureDetails'
import { EngineConsoleMerged } from '../layout/EngineConsole'
import useStore from '../../store/useStore'

import { speechLabel, speechTitle } from '../../hooks/useSpokenAudio'
import ElapsedTimer from '../shared/ElapsedTimer'
function Spinner({ size = 12 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, flexShrink: 0,
      border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    }} />
  )
}

const ghostBtn = {
  fontSize: 11, fontWeight: 600, padding: '3px 9px', borderRadius: 'var(--radius-sm)', minHeight: 26,
  background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
}

// The interview card takes the whole space under the top bars (title bar and the page's ribbon), on desktop and
// phone alike, and is minimisable: minimised, it is a pill you tap to reopen, and the page is back in view.
export default function InterviewDock({ iv, minimized, setMinimized, isMobile }) {
  const consoleOpen = useStore(s => s.consoleOpen)
  const q = iv.interactive
  if (!q && !iv.starting) return null
  const writing = iv.starting && !q   // the opening part is being written

  if (minimized) {
    return (
      <button onClick={() => setMinimized(false)} title="Reopen the interview"
        style={{
          // bottom-left on desktop: the floating Engine Console sits bottom-right and would hide it
          position: 'absolute', zIndex: 150, bottom: 12, left: isMobile ? 12 : 16, right: isMobile ? 12 : 'auto',
          maxWidth: isMobile ? 'none' : 420, display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 14px', minHeight: 34, borderRadius: 999, textAlign: 'left',
          background: 'var(--bg-card)', border: '1px solid var(--amber)', color: 'var(--text-primary)',
          boxShadow: '0 6px 22px rgba(0,0,0,0.4)', fontSize: 12,
        }}>
        {(writing || q?.busy) ? <ElapsedTimer since={iv.busySince} style={{ color: 'var(--amber)', fontWeight: 700 }} /> : <span style={{ color: 'var(--amber)' }}>⚡</span>}
        <span style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
          Interview{q ? ` · Part ${q.partsCount}` : ''}
        </span>
        <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
          {writing ? 'writing the opening…' : q.busy ? 'writing the next part…' : q.question}
        </span>
        <span style={{ color: 'var(--accent-light)', fontWeight: 700, flexShrink: 0 }}>▲</span>
      </button>
    )
  }

  // fills the area under the top bars; on a wide screen the content keeps a readable column in the middle
  const shell = { position: 'absolute', zIndex: 150, inset: 0 }
  const pad = isMobile ? '14px 14px 18px' : '22px max(28px, calc((100% - 820px) / 2)) 28px'

  return (
    <aside role="complementary" aria-label="Interview" className="fade-in" style={{
      ...shell, background: 'var(--bg-card)', overflowY: 'auto', padding: pad,
      display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          {writing ? '⚡ Writing the opening…' : `⚡ Part ${q.partsCount} written — your call`}
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button onClick={() => setMinimized(true)} title="Minimise — the interview stays open, tap the pill to bring it back"
            style={{ ...ghostBtn, padding: '3px 9px', minHeight: 24 }}>▼ Minimise</button>
          {q && (
            <button onClick={iv.abandon} disabled={iv.abandoning}
              title="Abandon this interview entirely — deletes the session so the next click starts fresh"
              style={{ ...ghostBtn, padding: '3px 8px', minHeight: 24, color: 'var(--text-muted)', fontSize: 10 }}>
              {iv.abandoning ? <ElapsedTimer /> : '✕ Abandon'}
            </button>
          )}
        </div>
      </div>

      {writing && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
          <ElapsedTimer since={iv.busySince} style={{ color: 'var(--amber)', fontWeight: 700 }} /> Writing the opening part — it will appear on the page, then you choose the direction.
        </div>
      )}

      {q && (
        <>
          {iv.qHistory.length > 1 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {iv.qHistory.map((h, i) => {
                const here = i === q.partsCount - 1
                return (
                  <button key={i} onClick={() => !here && !q.busy && iv.goBack(i)} disabled={q.busy} title={h.question}
                    style={{
                      width: 26, height: 26, borderRadius: '50%', fontSize: 10, fontWeight: 700,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: here ? 'var(--accent)' : 'var(--bg-elevated)', color: here ? '#fff' : 'var(--text-muted)',
                      border: `1px solid ${here ? 'var(--accent)' : 'var(--border)'}`, cursor: here ? 'default' : 'pointer',
                    }}>{i + 1}</button>
                )
              })}
            </div>
          )}

          {/* the failing draft itself is on the page, in orange — here are the rules it broke */}
          <GateFailureDetails reasons={q.gateReasons} />
          {q.gatePreview && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              The draft that failed is on the page below the saved parts, in orange — minimise this card to see it.
            </div>
          )}

          <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.4 }}>{q.question}</div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {q.options.map((opt, i) => (
              <div key={i} style={{ position: 'relative' }}>
                <button onClick={() => iv.setSel(i)} disabled={q.busy} style={{
                  width: '100%', textAlign: 'left', padding: '11px 13px', borderRadius: 'var(--radius)',
                  background: iv.sel === i ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: iv.sel === i ? '2px solid var(--accent)' : '1px solid var(--border)',
                  opacity: q.busy ? 0.5 : 1, minHeight: 44,
                }}>
                  <div style={{ fontSize: 12, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    {iv.sel === i && <span style={{ color: 'var(--accent-light)' }}>✓</span>}
                    {opt.label}
                    {i === q.recommended && (
                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent-light)', background: 'var(--accent-dim)', padding: '1px 7px', borderRadius: 10 }}>★ Recommended</span>
                    )}
                    {opt.evidence && (
                      <span onClick={e => { e.stopPropagation(); iv.setEvidenceIdx(v => v === i ? null : i) }}
                        title="Why this option — corpus source" role="button"
                        style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 10, padding: '1px 6px', cursor: 'pointer' }}>
                        🧬 source
                      </span>
                    )}
                  </div>
                  {opt.description && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{opt.description}</div>}
                </button>
                {iv.evidenceIdx === i && opt.evidence && (
                  <div style={{
                    margin: '4px 0 0', padding: '8px 10px', fontSize: 11, color: 'var(--text-secondary)',
                    background: 'var(--bg-base)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
                  }}>
                    🧬 <b style={{ color: 'var(--text-primary)' }}>Source:</b> {opt.evidence}
                  </div>
                )}
              </div>
            ))}
            <input value={iv.other}
              onChange={e => { iv.setOther(e.target.value); iv.setSel(e.target.value.trim() ? 'other' : null) }}
              onFocus={() => { if (iv.other.trim()) iv.setSel('other') }}
              onKeyDown={e => { if (e.key === 'Enter') iv.confirm() }}
              placeholder="Or write your own direction…" disabled={q.busy}
              style={{
                padding: '10px 12px', fontSize: 12, borderRadius: 'var(--radius-sm)', minHeight: 44,
                border: iv.sel === 'other' ? '2px solid var(--accent)' : undefined,
              }} />
          </div>

          {q.busy ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-muted)' }}>
              <ElapsedTimer since={iv.busySince} style={{ color: 'var(--amber)', fontWeight: 700 }} /> {iv.submitting ? 'Polishing & continuing…' : 'Writing the next part with your choice…'}
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {(q.partsCount || 0) > 1 && (
                  <button onClick={() => iv.goBack(true)} style={ghostBtn}
                    title="Go back and choose a different direction at the previous decision point">← Back</button>
                )}
                <button onClick={iv.speech.toggle} disabled={iv.speech.status === 'loading'} style={ghostBtn}
                  title={speechTitle(iv.speech.status)}>{iv.speech.status === 'loading' ? <ElapsedTimer since={iv.speech.since} /> : speechLabel(iv.speech.status)}</button>
              </div>
              <button onClick={iv.confirm} disabled={!iv.chosenText} style={{
                padding: '5px 18px', fontSize: 12, fontWeight: 700, minHeight: 30,
                background: iv.chosenText ? 'var(--accent)' : 'var(--bg-elevated)',
                color: iv.chosenText ? '#fff' : 'var(--text-muted)', borderRadius: 'var(--radius-sm)', border: 'none',
              }}>Continue →</button>
            </div>
          )}

          {/* the scene's word budget: words written / words planned (this scene, both question rounds together) */}
          {q.sceneWords && (
            <div title={`Scene ${q.sceneWords.scene} of ${q.sceneWords.scenes}: ${q.sceneWords.used} words written of ${q.sceneWords.budget} planned`
              + (q.sceneWords.of > 1 ? ` (question ${q.sceneWords.question} of ${q.sceneWords.of})` : '')}
              style={{ textAlign: 'right', fontSize: 10, lineHeight: 1, color: q.sceneWords.left < 0 ? 'var(--amber)' : 'var(--text-muted)', opacity: 0.85 }}>
              {q.sceneWords.used}w/{q.sceneWords.budget}w
            </div>
          )}
        </>
      )}

      {/* the Engine Console merges into this card instead of floating over its buttons */}
      {consoleOpen && <EngineConsoleMerged />}
    </aside>
  )
}
