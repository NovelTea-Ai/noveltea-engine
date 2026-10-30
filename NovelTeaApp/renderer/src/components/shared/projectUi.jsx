import { useRef, useState } from 'react'
import useStore from '../../store/useStore'
import ElapsedTimer, { fmtElapsed, secsSince } from './ElapsedTimer'
import { API_BASE, api } from '../../api'
import useSpokenAudio, { interviewText, speechLabel, speechTitle } from '../../hooks/useSpokenAudio'
import { EngineConsoleMerged } from '../layout/EngineConsole'

/* ── tiny shared pieces ── */

export function Spinner({ size = 14 }) {
  return <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite', fontSize: size }}>⟳</span>
}

export function Panel({ children, style = {} }) {
  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border-soft)',
      borderRadius: 'var(--radius-lg)', padding: 16, ...style,
    }}>{children}</div>
  )
}

export function PanelTitle({ children, action }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
      <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.06em', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
        {children}
      </span>
      {action}
    </div>
  )
}

// Shared clipboard helper — every "Copy" button in this file used to call
// navigator.clipboard.writeText(...).then(...) directly, with NO .catch and
// no fallback. That API silently rejects (or is straight-up undefined,
// throwing a TypeError on the call itself) in any context the Clipboard API
// considers non-secure — most relevantly here, this app is a plain browser
// tab hitting a bare HTTP server (see launcher.py: it never opens its own
// window, "the app" IS whatever browser tab is pointed at localhost:7432 or
// a LAN IP from another device) — a LAN-IP tab is genuinely insecure-origin
// and got zero clipboard access with zero error shown, which is exactly
// "copy does nothing" with no clue why. Falls back to the older
// document.execCommand('copy') (works without the secure-context
// requirement) and, if BOTH fail, calls onFail so the caller can actually
// tell the user instead of failing silently.
export async function copyTextToClipboard(text, onFail) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
    throw new Error('Clipboard API unavailable in this context')
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (ok) return true
      throw new Error('execCommand copy returned false')
    } catch (e2) {
      if (onFail) onFail(e2)
      return false
    }
  }
}

/* ── Interactive survey generate button (arcs / chapter skeleton) ──
   Same A/B/other decision-popup pattern as Interactive Write: the LLM
   interviews the author with pivotal questions (one per arc, or 3 for a
   skeleton batch) BEFORE generating, each with a ★ Recommended option. */
export function FieldSurveyButton({ field, projectId, onDone, small = false, chapterNumber = null, label = null, fullWidth = false, disabled = false, critiqueText = null, forcePattern = false }) {
  const [survey, setSurvey] = useState(null)   // {session_id, question, options, recommended, progress, busy}
  const [other, setOther] = useState('')
  const [selected, setSelected] = useState(null)   // null | option index | 'other' — tap selects, Continue submits
  const [qHistory, setQHistory] = useState([])   // [{question}] indexed by "answered" position — breadcrumb
  const [submitting, setSubmitting] = useState(false)   // covers the silent auto-polish-then-submit round-trip
  const [evidenceIdx, setEvidenceIdx] = useState(null)   // which option's "🧬 source" popup is open
  const [abandoning, setAbandoning] = useState(false)
  const isNarrow = typeof window !== 'undefined' && window.innerWidth < 768
  const consoleOpen = useStore(s => s.consoleOpen)
  const { appendConsoleLine, openConsole } = useStore()

  function handleRes(res) {
    setSelected(null)
    setOther('')
    setEvidenceIdx(null)
    const t = stepStart.current ? ` in ${fmtElapsed(secsSince(stepStart.current))}` : ''
    appendConsoleLine(res.done ? `✓ Interactive ${field} complete${t}` : `✍ Interactive ${field}: next question ready${t}`, res.done ? 'success' : 'info')
    if (res.done) {
      setSurvey(null)
      setQHistory([])
      if (onDone) onDone(res)
    } else {
      const answered = res.answered ?? 0
      setQHistory(h => { const next = [...h]; next[answered] = { question: res.question }; return next.slice(0, answered + 1) })
      setSurvey({ session_id: res.session_id, question: res.question, options: res.options || [],
                  recommended: res.recommended ?? 0, progress: res.progress || '',
                  answered, busy: false })
      return res
    }
  }

  // Failures go to the global console ONLY (not a per-button inline line) —
  // one consistent place to look regardless of which button/tab/page failed,
  // instead of the error text living wherever the button happened to be.
  function reportErr(e) {
    appendConsoleLine(`✗ Interactive ${field} failed: ${e.message || 'failed'}`, 'error')
    openConsole()
  }

  // Before this existed, the ONLY way to actually clear an unwanted or stuck
  // interview was restarting the whole app — /api/generate/abandon only
  // clears an ACTIVELY RUNNING call's process/lock, it has nothing to say
  // about a session just sitting there with a pending question, and closing
  // this popup without answering left the session alive server-side to be
  // silently RESUMED (not restarted) the next time this button was clicked.
  // field-interactive-abandon actually deletes the session (memory + disk),
  // so the next click genuinely starts over.
  async function abandon() {
    if (abandoning) return
    setAbandoning(true)
    try {
      await api.interactiveFieldAbandon(projectId, field, survey?.session_id || null)
    } catch (e) { reportErr(e) } finally {
      setAbandoning(false)
      setSurvey(null)
      setQHistory([])
      setSelected(null)
      setOther('')
    }
  }

  const stepStart = useRef(0)
  const [sessionSince, setSessionSince] = useState(0)
  const beginStep = () => { stepStart.current = Date.now(); const t = stepStart.current; setSurvey(s => (s ? { ...s, busySince: t } : s)) }
  async function start() {
    stepStart.current = Date.now()
    setSessionSince(stepStart.current)
    setSurvey({ busy: true, starting: true, busySince: stepStart.current })
    try {
      handleRes(await api.interactiveField(projectId, field, null, null, null, false, chapterNumber, critiqueText, forcePattern))
    } catch (e) { reportErr(e); setSurvey(null) }
  }

  const chosenText = selected === 'other' ? other.trim()
    : (selected !== null && survey?.options?.[selected]) ? survey.options[selected].label : ''

  // Free-text answers get silently expanded before submitting — no separate
  // button/step, just a slightly longer "Thinking…" while it happens. Picked
  // options go straight through untouched (nothing to polish).
  async function confirmChoice() {
    if (!survey?.session_id || survey.busy || !chosenText) return
    setSurvey(s => ({ ...s, busy: true }))
    beginStep()
    setSubmitting(true)
    try {
      let finalText = chosenText
      if (selected === 'other') {
        try { finalText = (await api.polishAnswer(projectId, survey.question, chosenText, chapterNumber)).polished || chosenText }
        catch { /* polish is best-effort — submit the raw note if it fails */ }
      }
      handleRes(await api.interactiveField(projectId, field, survey.session_id, finalText, null, false, chapterNumber))
    } catch (e) { reportErr(e); setSurvey(null) } finally { setSubmitting(false) }
  }

  async function goBack(toIndex = true) {
    if (!survey?.session_id || survey.busy || !survey.answered) return
    setSurvey(s => ({ ...s, busy: true }))
    beginStep()
    try {
      handleRes(await api.interactiveField(projectId, field, survey.session_id, null, null, toIndex, chapterNumber))
    } catch (e) { reportErr(e); setSurvey(s => ({ ...s, busy: false })) }
  }

  // Skip: the backend has no "no answer" path (a choice is required to
  // advance), so this submits the recommended option's text — but PREFIXED
  // so the interview log and any downstream LLM read can tell this wasn't a
  // deliberate pick, just "move on, use your best judgment here."
  async function skip() {
    if (!survey?.session_id || survey.busy) return
    const rec = survey.options?.[survey.recommended]
    if (!rec) return
    setSurvey(s => ({ ...s, busy: true }))
    beginStep()
    try {
      handleRes(await api.interactiveField(projectId, field, survey.session_id, `[Skipped — use your best judgment] ${rec.label}`, null, false, chapterNumber))
    } catch (e) { reportErr(e); setSurvey(s => ({ ...s, busy: false })) }
  }

  // Read the question + options aloud (NVIDIA Magpie TTS, same voice as
  // chapter narration) — the flipped direction of "voice input": the app
  // speaks to you instead of you having to type/read everything.
  // Once the voice has arrived the Read button becomes a Play button that replays the saved audio (no new request).
  const speech = useSpokenAudio(interviewText(survey?.question, survey?.options), e => reportErr(e),
    { onReady: s => appendConsoleLine(`🔊 Question voiced in ${fmtElapsed(s)}`, 'info') })

  return (
    <div style={fullWidth ? { width: '100%' } : { display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
      <button onClick={start} disabled={!!survey || disabled}
        title="Interactive: answer a few pivotal A/B questions (with a recommended pick) before it generates"
        style={fullWidth ? {
          width: '100%', padding: '7px', fontSize: 11, fontWeight: 600, marginBottom: 6,
          background: survey ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#f59e0b,#ef4444)',
          color: survey ? 'var(--text-muted)' : '#fff',
          border: 'none', borderRadius: 'var(--radius-sm)', opacity: disabled ? 0.6 : 1,
        } : {
          display: 'flex', alignItems: 'center', gap: 5,
          padding: small ? '3px 10px' : '5px 13px',
          fontSize: small ? 10 : 11, fontWeight: 600,
          background: 'linear-gradient(135deg,#f59e0b,#ef4444)', color: '#fff',
          borderRadius: 'var(--radius-sm)', opacity: survey ? 0.7 : 1,
        }}>
        {survey ? <ElapsedTimer since={sessionSince} /> : (!fullWidth && <span style={{ fontSize: 10 }}>⚡</span>)}
        {survey ? 'Interviewing…' : (label || 'Interactive')}
      </button>
      {survey && !survey.starting && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 300, background: isNarrow ? 'var(--bg-card)' : 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: isNarrow ? 'stretch' : 'center', justifyContent: 'center',
        }}>
          <div className="fade-in" style={{
            width: isNarrow ? '100%' : 560, maxWidth: '100%',
            height: isNarrow ? '100%' : 'auto', maxHeight: isNarrow ? '100%' : '85vh', overflowY: 'auto',
            background: 'var(--bg-card)', border: isNarrow ? 'none' : '1px solid var(--border)',
            borderRadius: isNarrow ? 0 : 'var(--radius-lg)',
            padding: 18, display: 'flex', flexDirection: 'column', gap: 12, textAlign: 'left',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                ⚡ {survey.progress || 'Your call'}
              </div>
              <button onClick={abandon} disabled={abandoning}
                title="Cancel this interview entirely — clears the session so the next click starts fresh"
                style={{
                  fontSize: 10, padding: '3px 9px', borderRadius: 'var(--radius-sm)',
                  background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)',
                  display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0,
                }}>{abandoning ? <ElapsedTimer /> : '✕ Abandon'}</button>
            </div>
            {qHistory.length > 1 && (
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {qHistory.map((h, i) => (
                  <button key={i} onClick={() => i !== survey.answered && !survey.busy && goBack(i)}
                    disabled={survey.busy} title={h.question}
                    style={{
                      width: 22, height: 22, borderRadius: '50%', fontSize: 10, fontWeight: 700,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      background: i === survey.answered ? 'var(--accent)' : 'var(--bg-elevated)',
                      color: i === survey.answered ? '#fff' : 'var(--text-muted)',
                      border: `1px solid ${i === survey.answered ? 'var(--accent)' : 'var(--border)'}`,
                      cursor: i === survey.answered ? 'default' : 'pointer',
                    }}>{i + 1}</button>
                ))}
              </div>
            )}
            <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.4 }}>{survey.question}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {survey.options.map((opt, i) => (
                <div key={i} style={{ position: 'relative' }}>
                  <button onClick={() => setSelected(i)} disabled={survey.busy} style={{
                    width: '100%', textAlign: 'left', padding: '11px 13px', borderRadius: 'var(--radius)',
                    background: selected === i ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                    border: selected === i ? '2px solid var(--accent)' : '1px solid var(--border)',
                    opacity: survey.busy ? 0.5 : 1, minHeight: 44,
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      {selected === i && <span style={{ color: 'var(--accent-light)' }}>✓</span>}
                      {opt.label}
                      {i === survey.recommended && (
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
              <div style={{ display: 'flex', gap: 6 }}>
                <input value={other}
                  onChange={e => { setOther(e.target.value); setSelected(e.target.value.trim() ? 'other' : null) }}
                  onFocus={() => { if (other.trim()) setSelected('other') }}
                  onKeyDown={e => { if (e.key === 'Enter') confirmChoice() }}
                  placeholder="Or write your own answer…" disabled={survey.busy}
                  style={{
                    flex: 1, padding: '10px 12px', fontSize: 12, borderRadius: 'var(--radius-sm)', minHeight: 44,
                    border: selected === 'other' ? '2px solid var(--accent)' : undefined,
                  }} />
              </div>
            </div>
            {survey.busy
              ? <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-muted)' }}><ElapsedTimer since={survey.busySince} /> {submitting ? 'Polishing & submitting…' : 'Thinking…'}</div>
              : (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button onClick={() => setSurvey(null)}
                      style={{ fontSize: 10, color: 'var(--text-muted)' }}>Cancel</button>
                    {survey.answered > 0 && (
                      <button onClick={() => goBack(true)} title="Go back and change your answer to the previous question"
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
                    <button onClick={skip} title="Skip — go with the recommended answer without deciding yourself"
                      style={{
                        fontSize: 11, fontWeight: 600, padding: '6px 10px', borderRadius: 'var(--radius-sm)',
                        background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
                      }}>⏭ Skip</button>
                  </div>
                  <button onClick={confirmChoice} disabled={!chosenText} style={{
                    padding: '5px 18px', fontSize: 12, fontWeight: 700, minHeight: 30,
                    background: chosenText ? 'var(--accent)' : 'var(--bg-elevated)',
                    color: chosenText ? '#fff' : 'var(--text-muted)',
                    borderRadius: 'var(--radius-sm)', border: 'none',
                  }}>Continue →</button>
                </div>
              )}
            {/* Merges the global console into this card instead of a second overlay. */}
            {consoleOpen && <EngineConsoleMerged />}
          </div>
        </div>
      )}
    </div>
  )
}

// Resolves a project's cover image (if uploaded) to a full <img> src URL —
// cover_image is stored as a relative path (e.g. "/project-covers/{id}/cover.png?v=xxxx")
// so it needs the same origin-resolution API.js already does for every other call.
export function coverImageUrl(project) {
  return project?.cover_image ? `${API_BASE}${project.cover_image}` : null
}

/** Scene/beat detail that only sequential generation produces. */
export function SkeletonDetail({ ch }) {
  const scenes = Array.isArray(ch.scenes) ? ch.scenes : []
  const beats = Array.isArray(ch.beats) ? ch.beats : []
  // Two skeleton shapes exist: an older flatter one (this component was built for) and the
  // interactive interview's richer one (setting/purpose/key_beats per scene, top-level
  // tension_curve, ending_hook, reveals_delivered_this_chapter, ...). Real incident 2026-09-30:
  // a fully-populated interactive skeleton rendered as near-blank — the title matched (both
  // schemas call it "title"), but everything else used a different field name in each shape, so
  // this component silently found nothing to show under the names it was checking for. Every
  // field below now checks both shapes rather than assuming which one produced `ch`.
  const reveals = Array.isArray(ch.reveals) ? ch.reveals
    : Array.isArray(ch.reveals_delivered_this_chapter) ? ch.reveals_delivered_this_chapter : []
  const characters = Array.isArray(ch.characters_in_chapter) ? ch.characters_in_chapter : []
  const antiPatterns = Array.isArray(ch.anti_patterns) ? ch.anti_patterns : []
  const canonLock = ch.canon_lock && typeof ch.canon_lock === 'object' ? ch.canon_lock : null
  const hardConstraints = ch.hard_constraints?.description
  const hookWithholds = ch.hook_withholds
  const hook = (typeof ch.hook === 'string' ? ch.hook : ch.hook?.description) || ch.ending_hook
  const authorNotes = ch.author_notes
  const knowledgeState = Array.isArray(ch.knowledge_state) ? ch.knowledge_state : []
  const readerEmotions = ch.target_psychology?.reader_emotions
  const intent = ch.intent && typeof ch.intent === 'object' ? ch.intent : null
  const patternUsed = ch.pattern_used
  const patternEscalation = ch.pattern_escalation_note
  const tc = ch.target_psychology?.tension_curve || ch.tension_curve
  // Interactive-interview-only fields, no older-schema equivalent to fall back to.
  const mechanics = Array.isArray(ch.system_mechanics_established) ? ch.system_mechanics_established : []
  const threadsOpened = Array.isArray(ch.threads_opened_this_chapter) ? ch.threads_opened_this_chapter : []
  const threadsWithheld = Array.isArray(ch.threads_deliberately_not_resolved) ? ch.threads_deliberately_not_resolved : []
  const faceSlapping = typeof ch.face_slapping_setup_not_payoff === 'string' ? ch.face_slapping_setup_not_payoff : null
  const [expanded, setExpanded] = useState(false)
  if (!scenes.length && !beats.length && !reveals.length && !tc && !characters.length
      && !antiPatterns.length && !canonLock && !hardConstraints && !hookWithholds
      && !hook && !authorNotes && !knowledgeState.length && !readerEmotions && !intent
      && !patternUsed && !mechanics.length && !threadsOpened.length && !threadsWithheld.length
      && !faceSlapping) return null

  // Collapsed by default: the full structural-discipline schema (canon_lock,
  // characters_in_chapter, anti_patterns, hard_constraints, hook_withholds)
  // is a lot of text to show inline on every card in a list — expand on
  // demand instead of always rendering all of it.
  return (
    <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--border-soft)', fontSize: 10.5 }}
      onClick={e => e.stopPropagation()}>
      {tc && (
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: 'var(--text-muted)' }}>Tension: </span>
          {tc.start ?? '?'} → <b style={{ color: 'var(--amber)' }}>{tc.peak ?? '?'}</b> → {tc.end ?? '?'}
          {ch.chapter_function && <span style={{ color: 'var(--text-muted)' }}> · {typeof ch.chapter_function === 'string' ? ch.chapter_function : ch.chapter_function.primary}</span>}
        </div>
      )}
      {scenes.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <div style={{ color: 'var(--text-muted)' }}>{scenes.length} scenes:</div>
          {scenes.map((s, i) => {
            const label = s.scene_type || s.setting   // interactive schema has no scene_type; its "setting" fills the same slot
            const who = s.pov_character || (Array.isArray(s.characters) ? s.characters.join(', ') : null)
            const sceneReveals = Array.isArray(s.reveals) ? s.reveals : []
            return (
              <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8, marginBottom: expanded ? 3 : 0 }}>
                {s.scene_number ?? s.number ?? i + 1}{label ? `. [${label}]` : '.'} {who || '?'}
                {s.tension_level != null && ` · tension ${s.tension_level}`}
                {s.pacing && ` · ${s.pacing}`}
                {s.estimated_word_count ? ` · ~${s.estimated_word_count}w` : ''}
                {s.min_dialogue_lines ? ` · ${s.min_dialogue_lines}+ dialogue lines` : ''}
                {s.purpose && (
                  <div style={{ color: 'var(--text-muted)', paddingLeft: 12 }}>{s.purpose}</div>
                )}
                {expanded && s.structure_notes && (
                  <div style={{ color: 'var(--text-muted)', paddingLeft: 12 }}>{s.structure_notes}</div>
                )}
                {expanded && Array.isArray(s.key_beats) && s.key_beats.map((b, j) => (
                  <div key={j} style={{ color: 'var(--text-muted)', paddingLeft: 12 }}>• {b}</div>
                ))}
                {expanded && sceneReveals.map((r, j) => (
                  <div key={j} style={{ color: 'var(--amber)', paddingLeft: 12 }}>⚡ {r}</div>
                ))}
              </div>
            )
          })}
        </div>
      )}
      {beats.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <div style={{ color: 'var(--text-muted)' }}>Beats:</div>
          {beats.slice(0, expanded ? beats.length : 6).map((b, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>
              • {b.event}{b.stakes ? ` — ${b.stakes}` : ''}
            </div>
          ))}
        </div>
      )}
      {reveals.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <div style={{ color: 'var(--text-muted)' }}>Reveals:</div>
          {reveals.slice(0, expanded ? reveals.length : 4).map((r, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>• {r}</div>
          ))}
        </div>
      )}
      {hook && (
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: 'var(--text-muted)' }}>Hook: </span>
          <span style={{ color: 'var(--text-secondary)' }}>{hook}</span>
        </div>
      )}
      {hookWithholds && (
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: 'var(--text-muted)' }}>Withholds: </span>
          <span style={{ color: 'var(--text-secondary)' }}>{hookWithholds}</span>
        </div>
      )}
      {mechanics.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <div style={{ color: 'var(--text-muted)' }}>System mechanics established:</div>
          {mechanics.map((m, i) => <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>• {m}</div>)}
        </div>
      )}
      {threadsOpened.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <div style={{ color: 'var(--text-muted)' }}>Threads opened:</div>
          {threadsOpened.map((t, i) => <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>• {t}</div>)}
        </div>
      )}
      {threadsWithheld.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <div style={{ color: 'var(--text-muted)' }}>Deliberately not resolved:</div>
          {threadsWithheld.map((t, i) => <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>• {t}</div>)}
        </div>
      )}
      {faceSlapping && (
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: 'var(--text-muted)' }}>Face-slapping setup: </span>
          <span style={{ color: 'var(--text-secondary)' }}>{faceSlapping}</span>
        </div>
      )}
      {(characters.length > 0 || antiPatterns.length > 0 || canonLock || hardConstraints
        || authorNotes || knowledgeState.length > 0 || readerEmotions || intent || patternUsed) && (
        <button onClick={() => setExpanded(x => !x)} style={{
          fontSize: 10, padding: '2px 8px', marginTop: 2, marginBottom: expanded ? 4 : 0,
          background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 4,
          color: 'var(--accent-light)',
        }}>{expanded ? '▲ Less' : '▼ Full skeleton detail (canon lock, characters, constraints)'}</button>
      )}
      {expanded && authorNotes && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700, marginTop: 4 }}>Author notes:</div>
          <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>{authorNotes}</div>
        </div>
      )}
      {expanded && characters.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700, marginTop: 4 }}>Characters in chapter:</div>
          {characters.map((c, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8, marginBottom: 3 }}>
              <b>{c.name}</b>
              {c.enters_believing && <div style={{ paddingLeft: 8 }}>enters believing: {c.enters_believing}</div>}
              {c.true_intention && <div style={{ paddingLeft: 8 }}>intention: {c.true_intention}</div>}
              {c.knowledge_state && <div style={{ paddingLeft: 8 }}>knows: {c.knowledge_state}</div>}
              {c.arc_within_chapter && <div style={{ paddingLeft: 8 }}>arc: {c.arc_within_chapter}</div>}
            </div>
          ))}
        </div>
      )}
      {expanded && canonLock && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700 }}>Canon lock:</div>
          {canonLock.staging_rule && <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>staging: {canonLock.staging_rule}</div>}
          {canonLock.numeric_canon && <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>canon: {canonLock.numeric_canon}</div>}
        </div>
      )}
      {expanded && knowledgeState.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700 }}>Knowledge state:</div>
          {knowledgeState.map((k, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>
              • {k.fact}{k.known_to?.length ? ` — known to: ${k.known_to.join(', ')}` : ''}{k.hidden_from?.length ? ` · hidden from: ${k.hidden_from.join(', ')}` : ''}
            </div>
          ))}
        </div>
      )}
      {expanded && (readerEmotions || intent) && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700 }}>Target psychology:</div>
          {readerEmotions && (
            <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>
              reader emotions: {Object.entries(readerEmotions).map(([k, v]) => `${k} ${v}`).join(', ')}
            </div>
          )}
          {intent?.author_goal && <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>author goal: {intent.author_goal}</div>}
          {intent?.reader_effect && <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>reader effect: {intent.reader_effect}</div>}
          {intent?.theme_reinforced && <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>theme reinforced: {intent.theme_reinforced}</div>}
        </div>
      )}
      {expanded && patternUsed && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700 }}>Pattern:</div>
          <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>{patternUsed}</div>
          {patternEscalation && <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>escalation: {patternEscalation}</div>}
        </div>
      )}
      {expanded && antiPatterns.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700 }}>Anti-patterns (do NOT):</div>
          {antiPatterns.map((a, i) => (
            <div key={i} style={{ color: 'var(--red)', paddingLeft: 8 }}>✕ {a}</div>
          ))}
        </div>
      )}
      {expanded && hardConstraints && (
        <div>
          <div style={{ color: 'var(--text-muted)', fontWeight: 700 }}>Hard constraints:</div>
          <div style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>{hardConstraints}</div>
        </div>
      )}
    </div>
  )
}
