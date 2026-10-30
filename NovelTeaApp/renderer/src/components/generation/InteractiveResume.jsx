import { useState, useEffect, useRef } from 'react'
import useStore from '../../store/useStore'
import useSpokenAudio, { interviewText, speechLabel, speechTitle } from '../../hooks/useSpokenAudio'
import { api } from '../../api'
import { EngineConsoleMerged } from '../layout/EngineConsole'
import GateFailureDetails from './GateFailureDetails'
import ElapsedTimer, { fmtElapsed, secsSince } from '../shared/ElapsedTimer'

function Spinner({ size = 14 }) {
  return <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite', fontSize: size }}>⟳</span>
}

function trim(s, limit) {
  s = String(s || '')
  return s.length > limit ? s.slice(0, limit - 1) + '…' : s
}

// Mounted once at the App root (alongside EngineConsole/TitleBar), NOT inside
// any page/tab — this is what makes "Continue Session" actually work
// regardless of which page is on screen: the popup lives here, independent
// of whichever tab originally started the survey/chapter session.
export default function InteractiveResume() {
  const { interactiveResumeOpen, interactiveResumeStatus, closeInteractiveResume,
          activeProjectId, consoleOpen, appendConsoleLine, openConsole, setConsoleRunning, clearConsoleRunning,
          loadProjects } = useStore()
  const [state, setState] = useState(null)   // {sessionId, kind, field, chapterNumber, question, options, recommended, segment} | null
  const [selected, setSelected] = useState(null)
  const [other, setOther] = useState('')
  const [busy, setBusy] = useState(false)
  const [waiting, setWaiting] = useState(false)   // server said "still working, try again shortly"
  const [qHistory, setQHistory] = useState([])    // [{question}] indexed by "answered"/"partsCount-1" position — breadcrumb
  const [submitting, setSubmitting] = useState(false)
  const [evidenceIdx, setEvidenceIdx] = useState(null)
  const [abandoning, setAbandoning] = useState(false)
  const [busySince, setBusySince] = useState(0)    // when the step being written now was asked for (for the timers)
  const stepStart = useRef(0)
  const beginStep = () => { const t = Date.now(); stepStart.current = t; setBusySince(t) }
  const took = () => (stepStart.current ? ` in ${fmtElapsed(secsSince(stepStart.current))}` : '')
  const isNarrow = typeof window !== 'undefined' && window.innerWidth < 768

  function applyRes(res, projectId) {
    setBusy(false)
    setSelected(null)
    setOther('')
    setEvidenceIdx(null)
    if (res.in_flight) {
      setWaiting(true)
      return
    }
    setWaiting(false)
    if (res.done) {
      appendConsoleLine(`✓ Interactive ${res.field || 'chapter'} complete${took()} — check the project for the result.`, 'success')
      clearConsoleRunning()
      closeInteractiveResume()
      setState(null)
      setQHistory([])
      if (projectId) loadProjects()   // picks up registry-visible changes (planning_progress etc.)
      return
    }
    const step = state?.kind === 'field' ? (res.answered ?? 0) : (res.parts_so_far ?? 1) - 1
    appendConsoleLine(state?.kind === 'field'
      ? `✍ Next question ready${took()}`
      : `✍ Part ${res.parts_so_far ?? step + 1} written${took()} — decision needed`, 'info')
    setQHistory(h => { const next = [...h]; next[step] = { question: res.question }; return next.slice(0, step + 1) })
    setState(s => ({
      ...s,
      sessionId: res.session_id,
      question: res.question,
      options: res.options || [],
      recommended: res.recommended ?? 0,
      segment: res.segment,
      answered: res.answered ?? 0,
      partsCount: res.parts_so_far ?? 0,
      gateReasons: res.gate_reasons || null,
      gatePreview: res.gate_preview || null,
    }))
  }

  useEffect(() => {
    if (!interactiveResumeOpen || !interactiveResumeStatus || !activeProjectId) return
    const { kind, field, chapter_number } = interactiveResumeStatus
    setState({ kind, field, chapterNumber: chapter_number, question: null, options: [], segment: null })
    setQHistory([])
    setBusy(true)
    beginStep()
    setConsoleRunning(kind === 'field' ? field : 'interactive', kind === 'field' ? field : 'interactive')
    const call = kind === 'field'
      ? api.interactiveField(activeProjectId, field)
      : api.interactiveChapter(activeProjectId, chapter_number)
    call.then(res => applyRes(res, activeProjectId))
        .catch(e => {
          appendConsoleLine(`✗ Interactive ${field || 'chapter'} failed: ${e.message || 'failed'}`, 'error')
          openConsole()
          setBusy(false)
        })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interactiveResumeOpen])

  // Once the voice has arrived the Read button becomes a Play button that replays the saved audio (no new request).
  const speech = useSpokenAudio(interviewText(state?.question, state?.options),
    e => appendConsoleLine(`✗ Read-aloud failed: ${e.message || 'failed'}`, 'error'),
    { onReady: s => appendConsoleLine(`🔊 Question voiced in ${fmtElapsed(s)}`, 'info') })

  if (!interactiveResumeOpen || !state) return null

  const chosenText = selected === 'other' ? other.trim()
    : (selected !== null && state.options?.[selected]) ? state.options[selected].label : ''

  async function submit() {
    if (!state.sessionId || busy || !chosenText) return
    setBusy(true)
    beginStep()
    setSubmitting(true)
    try {
      let finalText = chosenText
      if (selected === 'other') {
        try { finalText = (await api.polishAnswer(activeProjectId, state.question, chosenText, state.kind !== 'field' ? state.chapterNumber : null)).polished || chosenText }
        catch { /* best-effort — submit the raw note if polish fails */ }
      }
      const res = state.kind === 'field'
        ? await api.interactiveField(activeProjectId, state.field, state.sessionId, finalText)
        : await api.interactiveChapter(activeProjectId, state.chapterNumber, state.sessionId, finalText)
      applyRes(res, activeProjectId)
    } catch (e) {
      appendConsoleLine(`✗ Interactive ${state.field || 'chapter'} failed: ${e.message || 'failed'}`, 'error')
      openConsole()
      setBusy(false)
    } finally { setSubmitting(false) }
  }

  const canGoBack = state.kind === 'field' ? (state.answered || 0) > 0 : (state.partsCount || 0) > 1

  async function goBack(toIndex = true) {
    if (!state.sessionId || busy || !canGoBack) return
    setBusy(true)
    beginStep()
    try {
      const res = state.kind === 'field'
        ? await api.interactiveField(activeProjectId, state.field, state.sessionId, null, null, toIndex)
        : await api.interactiveChapter(activeProjectId, state.chapterNumber, state.sessionId, null, null, toIndex)
      applyRes(res, activeProjectId)
    } catch (e) {
      appendConsoleLine(`✗ Interactive ${state.field || 'chapter'} failed: ${e.message || 'failed'}`, 'error')
      openConsole()
      setBusy(false)
    }
  }

  function retryCheck() {
    if (!activeProjectId || !state) return
    setBusy(true)
    beginStep()
    const call = state.kind === 'field'
      ? api.interactiveField(activeProjectId, state.field)
      : api.interactiveChapter(activeProjectId, state.chapterNumber)
    call.then(res => applyRes(res, activeProjectId))
        .catch(e => {
          appendConsoleLine(`✗ Interactive ${state.field || 'chapter'} failed: ${e.message || 'failed'}`, 'error')
          openConsole()
          setBusy(false)
        })
  }

  function close() {
    clearConsoleRunning()
    closeInteractiveResume()
    setState(null)
    setQHistory([])
  }

  // Real abandon — this dialog's own ✕ only ever dismissed the popup locally;
  // the server-side session (and, for a chapter session, its own possibly-stale
  // base_prompt) stayed alive and would resume again next time. Covers both
  // session kinds this dialog can show.
  async function abandon() {
    if (abandoning || !state) return
    setAbandoning(true)
    try {
      if (state.kind === 'field') {
        await api.interactiveFieldAbandon(activeProjectId, state.field, state.sessionId || null)
      } else {
        await api.interactiveChapterAbandon(activeProjectId, state.chapterNumber, state.sessionId || null)
      }
    } catch (e) {
      appendConsoleLine(`✗ Abandon failed: ${e.message || 'failed'}`, 'error')
      openConsole()
    } finally {
      setAbandoning(false)
      close()
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 400, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: isNarrow ? 'flex-end' : 'center', justifyContent: 'center',
    }} onClick={close}>
      <div className="fade-in" onClick={e => e.stopPropagation()} style={{
        width: isNarrow ? '100%' : 560, maxWidth: '100%', maxHeight: '85vh', overflowY: 'auto',
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: isNarrow ? 'var(--radius-lg) var(--radius-lg) 0 0' : 'var(--radius-lg)',
        padding: 18, display: 'flex', flexDirection: 'column', gap: 12, textAlign: 'left',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            ▶ Continue Session — {state.field || `Chapter ${state.chapterNumber}`}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            <button onClick={abandon} disabled={abandoning}
              title="Abandon this session entirely — deletes it so it won't resume again"
              style={{
                fontSize: 10, padding: '3px 9px', borderRadius: 'var(--radius-sm)',
                background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)',
                display: 'flex', alignItems: 'center', gap: 4,
              }}>{abandoning ? <ElapsedTimer /> : '✕ Abandon'}</button>
            <button onClick={close} title="Dismiss — the session stays alive and will resume later" style={{ fontSize: 10, color: 'var(--text-muted)' }}>✕</button>
          </div>
        </div>

        {waiting && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-start' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
              <ElapsedTimer since={busySince} /> Still working on the last step — this can take a few minutes for a full
              generation. Your answers are safe.
            </div>
            <button onClick={retryCheck} disabled={busy} className="btn-ghost" style={{ fontSize: 11, padding: '6px 12px' }}>
              {busy ? <ElapsedTimer since={busySince} /> : 'Check again'}
            </button>
          </div>
        )}

        {!waiting && busy && !state.question && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
            <ElapsedTimer since={busySince} /> Loading…
          </div>
        )}

        {!waiting && state.segment && (
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', maxHeight: 140, overflowY: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.5, background: 'var(--bg-elevated)', padding: 10, borderRadius: 'var(--radius-sm)' }}>
            {trim(state.segment, 600)}
          </div>
        )}

        {!waiting && <GateFailureDetails reasons={state.gateReasons} preview={state.gatePreview} />}

        {!waiting && state.question && (
          <>
            {qHistory.length > 1 && (
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {qHistory.map((h, i) => {
                  const cur = state.kind === 'field' ? state.answered : (state.partsCount || 1) - 1
                  return (
                    <button key={i} onClick={() => i !== cur && !busy && goBack(i)}
                      disabled={busy} title={h.question}
                      style={{
                        width: 22, height: 22, borderRadius: '50%', fontSize: 10, fontWeight: 700,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: i === cur ? 'var(--accent)' : 'var(--bg-elevated)',
                        color: i === cur ? '#fff' : 'var(--text-muted)',
                        border: `1px solid ${i === cur ? 'var(--accent)' : 'var(--border)'}`,
                        cursor: i === cur ? 'default' : 'pointer',
                      }}>{i + 1}</button>
                  )
                })}
              </div>
            )}
            <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.4 }}>{state.question}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {state.options.map((opt, i) => (
                <div key={i} style={{ position: 'relative' }}>
                  <button onClick={() => setSelected(i)} disabled={busy} style={{
                    width: '100%', textAlign: 'left', padding: '11px 13px', borderRadius: 'var(--radius)',
                    background: selected === i ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                    border: selected === i ? '2px solid var(--accent)' : '1px solid var(--border)',
                    opacity: busy ? 0.5 : 1, minHeight: 44,
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      {selected === i && <span style={{ color: 'var(--accent-light)' }}>✓</span>}
                      {opt.label}
                      {i === state.recommended && (
                        <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent-light)', background: 'var(--accent-dim)', padding: '1px 7px', borderRadius: 10 }}>★ Recommended</span>
                      )}
                      {opt.evidence && (
                        <span onClick={e => { e.stopPropagation(); setEvidenceIdx(v => v === i ? null : i) }}
                          title="Why this option — corpus source" role="button"
                          style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 10, padding: '1px 6px', cursor: 'pointer' }}>
                          🧬 source
                        </span>
                      )}
                    </div>
                    {opt.description && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{opt.description}</div>}
                  </button>
                  {evidenceIdx === i && opt.evidence && (
                    <div style={{
                      position: 'absolute', top: '100%', left: 8, right: 8, zIndex: 10, marginTop: 2,
                      background: 'var(--bg-card)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
                      padding: '8px 10px', fontSize: 11, color: 'var(--text-secondary)', boxShadow: '0 4px 14px rgba(0,0,0,0.35)',
                    }}>
                      🧬 <b style={{ color: 'var(--text-primary)' }}>Source:</b> {opt.evidence}
                    </div>
                  )}
                </div>
              ))}
              <input value={other}
                onChange={e => { setOther(e.target.value); setSelected(e.target.value.trim() ? 'other' : null) }}
                onFocus={() => { if (other.trim()) setSelected('other') }}
                onKeyDown={e => { if (e.key === 'Enter') submit() }}
                placeholder="Or write your own answer…" disabled={busy}
                style={{
                  padding: '10px 12px', fontSize: 12, borderRadius: 'var(--radius-sm)', minHeight: 44,
                  border: selected === 'other' ? '2px solid var(--accent)' : undefined,
                }} />
            </div>
            {busy
              ? <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-muted)' }}><ElapsedTimer since={busySince} /> {submitting ? 'Polishing & submitting…' : 'Thinking…'}</div>
              : (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button onClick={close} style={{ fontSize: 10, color: 'var(--text-muted)' }}>Close</button>
                    {canGoBack && (
                      <button onClick={() => goBack(true)} title="Go back and change your previous answer"
                        style={{
                          fontSize: 11, fontWeight: 600, padding: '6px 10px', borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
                        }}>← Back</button>
                    )}
                    <button onClick={speech.toggle} disabled={speech.status === 'loading'} title={speechTitle(speech.status)}
                      style={{
                        fontSize: 11, fontWeight: 600, padding: '6px 10px', borderRadius: 'var(--radius-sm)',
                        background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
                      }}>{speech.status === 'loading' ? <ElapsedTimer since={speech.since} /> : speechLabel(speech.status)}</button>
                  </div>
                  <button onClick={submit} disabled={!chosenText} style={{
                    padding: '5px 18px', fontSize: 12, fontWeight: 700, minHeight: 30,
                    background: chosenText ? 'var(--accent)' : 'var(--bg-elevated)',
                    color: chosenText ? '#fff' : 'var(--text-muted)',
                    borderRadius: 'var(--radius-sm)', border: 'none',
                  }}>Continue →</button>
                </div>
              )}
          </>
        )}

        {consoleOpen && <EngineConsoleMerged />}
      </div>
    </div>
  )
}
