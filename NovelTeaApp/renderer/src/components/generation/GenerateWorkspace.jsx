import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import useStore from '../../store/useStore'
import useIsMobile from '../../hooks/useIsMobile'
import { MODELS_BY_PROVIDER } from '../../constants/agentModels'
import useInterview from './useInterview'
import InterviewDock from './InterviewDock'
import PartView, { useGateReport, paragraphsOf } from './GateMarks'
import ReferenceGauge from './ReferenceGauge'
import ElapsedTimer, { fmtElapsed, secsSince } from '../shared/ElapsedTimer'

function Spinner({ size = 12 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, flexShrink: 0,
      border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    }} />
  )
}

const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v } catch { return d } }
const lsSet = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

const PAGE_CSS = `
.ws-scroll {
  background:
    radial-gradient(ellipse 75% 38% at 50% 0%, rgba(124,58,237,0.17), transparent 72%),
    radial-gradient(ellipse 60% 30% at 50% 100%, rgba(236,72,153,0.08), transparent 70%),
    var(--bg-base);
}
.ws-page { position: relative; animation: ws-rise 0.6s cubic-bezier(0.2, 0.8, 0.2, 1) both; }
.ws-page::before {            /* a hairline edge and a soft top highlight, so the sheet reads as paper */
  content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.95), inset 0 0 0 1px rgba(17,24,39,0.07);
}
.ws-page ::selection { background: rgba(124, 58, 237, 0.22); }
.ws-ribbon::-webkit-scrollbar { display: none; }   /* a slim row that scrolls sideways, without a scrollbar eating height */
.ws-dropcap::first-letter {
  float: left; font-size: 3.6em; line-height: 0.82; padding: 0.06em 0.1em 0 0; font-weight: 700; color: #5b21b6;
}
.ws-anim { animation: ws-fade 0.6s ease both; }
@keyframes ws-rise { from { opacity: 0; transform: translateY(16px) scale(0.985); } to { opacity: 1; transform: none; } }
@keyframes ws-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .ws-page, .ws-anim { animation: none; } }
`

const ribbonBtnBase = {
  fontSize: 12, fontWeight: 600, padding: '3px 11px', minHeight: 28, borderRadius: 'var(--radius-sm)',
  background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)', whiteSpace: 'nowrap',
}

// The Generate tab as a Word-style workspace: a page in the middle that shows the chapter — every part the
// interview writes lands on it as it arrives and is stored on the server, so it is still there after a
// reload — with the interview docked beside it (minimisable) and any paragraph the house-style gate
// flagged drawn in orange; click one to send just that paragraph back through the gate.
export default function GenerateWorkspace({ projectId, chapterNum: chapterProp, setChapterNum: setChapterProp,
                                           ribbonLeft = null, ribbonRight = null, refreshToken = 0, renderPlan }) {
  const isMobile = useIsMobile()
  // slim buttons on a phone so the bars above the page stay thin
  const ribbonBtn = isMobile ? { ...ribbonBtnBase, minHeight: 28, fontSize: 11, padding: '2px 9px', flexShrink: 0 } : ribbonBtnBase
  const running = useStore(s => s.consoleRunning)
  const resumeStatus = useStore(s => s.interactiveResumeStatus)
  const genEngine = useStore(s => s.agentEngines?.current)
  const modelChoices = MODELS_BY_PROVIDER[genEngine] || null

  // The chapter is owned by ProjectWorkspace when the slide-out tools need it too; standalone it keeps its own.
  const [chapterInner, setChapterInner] = useState(0)   // 0 = not chosen yet, decided once the chapter list loads
  const controlled = chapterProp !== undefined
  const chapterNum = controlled ? chapterProp : chapterInner
  const setChapterNum = controlled ? setChapterProp : setChapterInner
  const [chapters, setChapters] = useState([])          // chapters already written to disk
  const [modelOverride, setModelOverride] = useState('')
  useEffect(() => { setModelOverride('') }, [genEngine])
  const [marksOn, setMarksOn] = useState(() => lsGet('nm-gate-marks', '1') !== '0')
  const [minimized, setMinimizedState] = useState(false)
  const [fixingKey, setFixingKey] = useState(null)
  const [fixMessage, setFixMessage] = useState(null)
  const pageRef = useRef(null)
  // with a tool panel on each side the page can be narrow: below 760px it uses the phone's tighter paddings
  const [pageW, setPageW] = useState(0)
  useEffect(() => {
    const el = pageRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(entries => setPageW(Math.round(entries[0].contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const compact = isMobile || (pageW > 0 && pageW < 760)

  const writtenNums = useMemo(() => chapters.map(c => c.number).filter(Number.isInteger), [chapters])
  const refreshChapters = useCallback(async () => {
    try {
      const r = await api.listGenerated(projectId)
      setChapters(r.chapters || [])
      return (r.chapters || []).map(c => c.number).filter(Number.isInteger)
    } catch { return [] }
  }, [projectId])

  // Loading a project opens its LATEST chapter on the page: the chapter being interviewed if there is one, else the
  // newest written chapter (a blank page 1 for a project with none yet). It does not restore the chapter last viewed.
  useEffect(() => {
    let alive = true
    refreshChapters().then(nums => {
      if (!alive) return
      const active = resumeStatus?.active && resumeStatus.kind !== 'field' ? resumeStatus.chapter_number : null
      setChapterNum(active || (nums.length ? Math.max(...nums) : 1))
    })
    return () => { alive = false }
  }, [projectId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (chapterNum) lsSet(`nm-ws-ch:${projectId}`, String(chapterNum)) }, [projectId, chapterNum])

  const iv = useInterview({ projectId, chapterNum: chapterNum || 1, modelOverride })
  // a tool panel (reader, editor, revision…) was closed: it may have changed the chapter, so reload the page
  const firstRefresh = useRef(true)
  useEffect(() => {
    if (firstRefresh.current) { firstRefresh.current = false; return }
    iv.loadDraft()
  }, [refreshToken]) // eslint-disable-line react-hooks/exhaustive-deps
  // the list of written chapters changes when an interview finishes
  useEffect(() => { refreshChapters() }, [iv.source, iv.parts.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // the dock's minimised state is remembered per chapter; a freshly started interview opens it
  useEffect(() => { setMinimizedState(lsGet(`nm-dock-min:${projectId}:${chapterNum}`, '0') === '1') }, [projectId, chapterNum])
  const setMinimized = v => { setMinimizedState(v); lsSet(`nm-dock-min:${projectId}:${chapterNum}`, v ? '1' : '0') }
  useEffect(() => { if (iv.starting) setMinimized(false) }, [iv.starting]) // eslint-disable-line react-hooks/exhaustive-deps

  // gate marks: the saved parts, and the draft awaiting Keep / Try again (not saved yet)
  const pendingDraft = iv.interactive?.gatePreview || null
  const reportIds = useMemo(() => ({ projectId, chapterNum }), [projectId, chapterNum])
  const report = useGateReport(iv.parts, marksOn, [], reportIds)
  // paragraphs of the waiting draft that the repeat gate's AI judge says re-tell earlier text
  const judgedRepeats = useMemo(() => {
    const r = (iv.interactive?.gateReasons || []).find(x => Array.isArray(x.paragraphs) && /re-tell/i.test(x.rule || ''))
    return r ? r.paragraphs : []
  }, [iv.interactive?.gateReasons])
  const pendingReport = useGateReport(pendingDraft ? [pendingDraft] : [], marksOn, pendingDraft ? iv.parts : [], null, judgedRepeats)

  // Opening a project or switching chapter shows the page from the TOP, once its text has loaded.
  const needTop = useRef(true)
  const prevLen = useRef(0)
  const prevPending = useRef(false)
  useEffect(() => { needTop.current = true }, [projectId, chapterNum])
  useEffect(() => {
    if (!needTop.current || iv.loading || !chapterNum || iv.loadedFor !== chapterNum) return
    needTop.current = false
    prevLen.current = iv.parts.length
    prevPending.current = !!pendingDraft
    const el = pageRef.current
    if (el) el.scrollTo({ top: 0, behavior: 'auto' })
  }, [iv.loading, iv.parts.length, chapterNum, iv.loadedFor]) // eslint-disable-line react-hooks/exhaustive-deps
  // ...and while an interview is writing, keep the newest part (or the draft awaiting a decision) in view
  useEffect(() => {
    if (needTop.current || iv.loading || iv.loadedFor !== chapterNum) return
    const grew = iv.parts.length > prevLen.current || (!!pendingDraft && !prevPending.current)
    prevLen.current = iv.parts.length
    prevPending.current = !!pendingDraft
    const el = pageRef.current
    if (grew && el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [iv.parts.length, !!pendingDraft]) // eslint-disable-line react-hooks/exhaustive-deps

  async function fixParagraph(part, index, text) {
    const key = `${part}:${index}`
    const t0 = Date.now()
    setFixingKey(key)
    setFixMessage(null)
    try {
      const r = await api.gateFixParagraph({
        project_id: projectId, chapter_number: chapterNum, part, paragraph_index: index, paragraph_text: text,
      })
      if (r.draft?.parts) iv.setParts(r.draft.parts)
      setFixMessage({ key, passed: !!r.passed, failures: r.failures || [], attempts: r.attempts })
      useStore.getState().appendConsoleLine(`${r.passed ? '✓' : '✗'} Part ${part}, paragraph ${index + 1}: gate fix ${r.passed ? 'passed' : 'did not pass'} in ${fmtElapsed(secsSince(t0))}`, r.passed ? 'success' : 'info')
    } catch (e) {
      setFixMessage({ key, passed: false, error: e.message })
    } finally { setFixingKey(null) }
  }

  // "Generate" is how a chapter is started: it goes to the next chapter that has nothing yet (or stays on this
  // one if it is still a blank page) and opens the interview straight away.
  const [autoStart, setAutoStart] = useState(false)
  const blankPage = iv.parts.length === 0 && !iv.interactive && !iv.starting && !iv.inFlight && iv.source === 'none'
  // View Plan: the chapter's plan (arc, skeleton goal, characters, themes) in a card over the page
  const [plan, setPlan] = useState(null)
  const [planOpen, setPlanOpen] = useState(false)
  const [planBusy, setPlanBusy] = useState(false)
  useEffect(() => { setPlanOpen(false); setPlan(null) }, [chapterNum])
  async function viewPlan() {
    if (!chapterNum || planBusy) return
    setPlanBusy(true)
    try { setPlan(await api.getChapterPlan(projectId, chapterNum)) }
    catch (e) { setPlan({ error: e.message || 'Could not load the plan' }) }
    finally { setPlanBusy(false); setPlanOpen(true) }
  }

  // A paragraph edited by hand: saved as written, then the gate checks it. The page redraws from the server, so the
  // orange goes only if the gate agrees; the notice says which way it went.
  const [notice, setNotice] = useState(null)
  useEffect(() => {
    if (!notice) return
    const t = setTimeout(() => setNotice(null), 8000)
    return () => clearTimeout(t)
  }, [notice])
  async function saveParagraph(part, index, original, edited) {
    const r = await api.gateSaveParagraph({
      project_id: projectId, chapter_number: chapterNum, part, paragraph_index: index,
      paragraph_text: original, new_text: edited,
    })
    if (r.draft?.parts) iv.setParts(r.draft.parts)
    setNotice(r.unchanged ? { ok: false, msg: 'Nothing changed.' }
      : r.passed ? { ok: true, msg: 'Saved — your edit passes the gate.' }
      : { ok: false, msg: `Saved — still flagged (${r.failures.map(f => f.rule.split(' — ')[0]).join('; ')}). Click it to see why.` })
    return r
  }

  // ── Read aloud: the page, top to bottom, with the browser's own speech (instant, free, works offline). Pause / Stop,
  //    and the paragraph being read is highlighted and kept in view.
  const speechOk = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [speech, setSpeech] = useState('idle')          // idle | reading | paused
  const [readingAt, setReadingAt] = useState(null)      // { part, para } of the paragraph being read
  const speechRun = useRef(0)                           // bumped on every start / stop, so a cancelled run's callbacks are ignored
  function speechQueue() {
    // Short chunks (about a sentence or two): some browsers cut a long utterance off partway through
    const chunks = text => {
      const sentences = text.match(/[^.!?…]+[.!?…]*["”’)]*\s*/g) || [text]
      const out = []
      let cur = ''
      for (const s of sentences) {
        if (cur && (cur + s).length > 220) { out.push(cur.trim()); cur = '' }
        cur += s
      }
      if (cur.trim()) out.push(cur.trim())
      return out
    }
    const q = [{ part: -1, para: -1, text: `Chapter ${chapterNum}.` }]
    iv.parts.forEach((t, pi) => paragraphsOf(t).forEach((p, qi) => chunks(p).forEach(c => q.push({ part: pi, para: qi, text: c }))))
    return q
  }
  function stopReading() {
    speechRun.current += 1
    try { window.speechSynthesis.cancel() } catch { /* nothing speaking */ }
    setSpeech('idle'); setReadingAt(null)
  }
  function startReading() {
    if (!speechOk || !iv.parts.length) return
    try { window.speechSynthesis.cancel() } catch { /* nothing speaking */ }
    const run = ++speechRun.current
    const queue = speechQueue()
    const voices = window.speechSynthesis.getVoices ? window.speechSynthesis.getVoices() : []
    const voice = voices.find(v => v.lang && v.lang.toLowerCase().startsWith((navigator.language || 'en').slice(0, 2).toLowerCase())) || null
    let i = 0
    const next = () => {
      if (run !== speechRun.current) return
      const item = queue[i]
      if (!item) { setSpeech('idle'); setReadingAt(null); return }
      const u = new SpeechSynthesisUtterance(item.text)
      if (voice) u.voice = voice
      u.onstart = () => { if (run === speechRun.current) setReadingAt(item.part >= 0 ? { part: item.part, para: item.para } : null) }
      u.onend = () => { if (run === speechRun.current) { i += 1; next() } }
      u.onerror = e => { if (run === speechRun.current && e.error !== 'interrupted' && e.error !== 'canceled') { i += 1; next() } }
      window.speechSynthesis.speak(u)
    }
    setSpeech('reading')
    next()
  }
  function pauseReading() { try { window.speechSynthesis.pause() } catch { /* ignore */ } setSpeech('paused') }
  function resumeReading() { try { window.speechSynthesis.resume() } catch { /* ignore */ } setSpeech('reading') }
  // a different chapter (or leaving the page) stops it; keep the paragraph being read in view
  useEffect(() => { stopReading() }, [chapterNum]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { speechRun.current += 1; try { window.speechSynthesis.cancel() } catch { /* ignore */ } }, [])
  useEffect(() => {
    if (!readingAt) return
    const el = pageRef.current && pageRef.current.querySelector('[data-reading="true"]')
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [readingAt])

  // ── Swipe the page left / right to flip to the next / previous chapter, Tinder-style: the card follows the finger,
  //    tilts a little, and flies off once it's dragged far enough. Touch and pen only (a mouse keeps selecting text);
  //    buttons, fields and the gate popover are left alone, and vertical scrolling is untouched.
  const cardRef = useRef(null)
  const swipe = useRef(null)
  const flipTo = useRef(null)
  flipTo.current = dir => {
    const i = pickerNums.indexOf(chapterNum)
    const n = i < 0 ? undefined : pickerNums[i + dir]
    return n
  }
  const cardStyle = (x, y, anim) => {
    const el = cardRef.current
    if (!el) return
    el.style.transition = anim ? 'transform 0.26s ease-out, opacity 0.26s ease-out' : 'none'
    el.style.transform = x || y ? `translateX(${x}px) rotate(${x / 40}deg)` : ''
    el.style.opacity = y ?? ''
  }
  const swipeDown = e => {
    if (e.pointerType === 'mouse' || !e.isPrimary) return
    if (e.target.closest && e.target.closest('button, input, textarea, select, a')) return
    swipe.current = { x: e.clientX, y: e.clientY, dx: 0, live: false }
  }
  const swipeMove = e => {
    const s = swipe.current
    if (!s) return
    const dx = e.clientX - s.x, dy = e.clientY - s.y
    if (!s.live) {
      if (Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx)) { swipe.current = null; return }   // it's a scroll
      if (Math.abs(dx) < 14) return
      s.live = true
      try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* ignore */ }
    }
    const dir = dx < 0 ? 1 : -1
    const has = flipTo.current(dir) !== undefined
    s.dx = has ? dx : dx / 4                       // nothing that way: rubber-band
    cardStyle(s.dx, String(Math.max(0.55, 1 - Math.abs(s.dx) / 700)), false)
  }
  const swipeEnd = () => {
    const s = swipe.current
    swipe.current = null
    if (!s || !s.live) return
    const dir = s.dx < 0 ? 1 : -1
    const next = flipTo.current(dir)
    if (next === undefined || Math.abs(s.dx) < 90) { cardStyle(0, '', true); return }
    cardStyle(-dir * (window.innerWidth + 200), '0', true)          // fly off
    setTimeout(() => {
      setChapterNum(next)
      cardStyle(dir * 60, '0', false)                                // the next card arrives from the other side
      requestAnimationFrame(() => requestAnimationFrame(() => cardStyle(0, '', true)))
    }, 230)
  }

  // ── Regenerate: a slim button over the page's top-right corner. It lists the parts; picking one keeps it, deletes
  //    every part after it, and asks that part's question again — so the chapter can be redone from any part.
  const [regen, setRegen] = useState(null)          // null (closed) | { pick, busy, err }
  async function doRegen(part) {
    setRegen({ pick: part, busy: true, err: '' })
    const r = await iv.regenerate(part)
    if (r && !r.error) { setRegen(null); setMinimized(false) } else setRegen({ pick: part, busy: false, err: (r && r.error) || 'Could not go back to that part.' })
  }
  useEffect(() => { setRegen(null) }, [chapterNum])

  const newChapter = () => {
    if (running || iv.loading) return
    const active = resumeStatus?.active && resumeStatus.kind !== 'field' ? resumeStatus.chapter_number : 0
    const next = Math.max(0, ...writtenNums, chapterNum || 0, active || 0) + 1
    const target = blankPage && chapterNum ? chapterNum : next
    setMinimized(false)
    setAutoStart(true)
    if (target !== chapterNum) setChapterNum(target)
  }
  // start once the page is on the new chapter (the hook reloads it when the number changes)
  useEffect(() => {
    if (!autoStart || !chapterNum || iv.loading) return
    setAutoStart(false)
    iv.start()
  }, [autoStart, chapterNum, iv.loading]) // eslint-disable-line react-hooks/exhaustive-deps
  const pickerNums = useMemo(() => {
    const set = new Set(writtenNums)
    if (chapterNum) set.add(chapterNum)
    set.add(Math.max(0, ...writtenNums) + 1)
    return [...set].sort((a, b) => a - b)
  }, [writtenNums, chapterNum])

  const words = useMemo(() => iv.parts.join(' ').split(/\s+/).filter(Boolean).length, [iv.parts])
  const live = iv.source === 'session'
  const dockVisible = !!(iv.interactive || iv.starting)
  const blank = !iv.loading && iv.parts.length === 0 && !pendingDraft && !iv.starting

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
      {/* ── ribbon: chapter + the processing action ── */}
      <div className="ws-ribbon" style={{
        whiteSpace: isMobile ? 'nowrap' : undefined,   // nothing in a slim phone row may wrap onto a second line
        display: 'flex', alignItems: 'center', flexWrap: isMobile ? 'nowrap' : 'wrap', gap: isMobile ? 6 : '6px 8px', flexShrink: 0,
        overflowX: isMobile ? 'auto' : 'visible', scrollbarWidth: 'none',
        padding: isMobile ? '4px 8px' : '8px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-soft)',
      }}>
        {ribbonLeft}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-secondary)', flexShrink: 0 }}>
          {!isMobile && 'Chapter'}
          <select aria-label="Chapter" value={chapterNum || ''} onChange={e => setChapterNum(Number(e.target.value))}
            style={{ ...ribbonBtn, padding: '4px 8px', color: 'var(--text-primary)', cursor: 'pointer' }}>
            {pickerNums.map(n => {
              const written = writtenNums.includes(n)
              const inProgress = resumeStatus?.active && resumeStatus.kind !== 'field' && resumeStatus.chapter_number === n
              return <option key={n} value={n}>{n}{inProgress ? ' · in progress' : written ? '' : ' · new'}</option>
            })}
          </select>
        </label>
        <button onClick={newChapter} disabled={!!running || iv.loading}
          title="Generate: start the next chapter — the interview opens over the page and each part is written onto it"
          style={{
            ...ribbonBtn, fontWeight: 700, border: 'none',
            background: running ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#f59e0b,#ef4444)',
            color: running ? 'var(--text-muted)' : '#fff',
          }}>{running === 'interactive' ? <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><ElapsedTimer since={iv.busySince} /> Writing…</span>
            : 'Generate'}</button>
        {/* (on a phone the pill floating at the bottom of the screen does this job) */}
        {dockVisible && minimized && !isMobile && (
          <button onClick={() => setMinimized(false)} style={ribbonBtn}>▲ Show interview</button>
        )}
        {speechOk && (speech === 'idle' ? (
          <button onClick={startReading} disabled={!iv.parts.length} style={ribbonBtn}
            title="Read this page aloud, from the top" aria-label="Read aloud">{isMobile ? '🔊' : '🔊 Read aloud'}</button>
        ) : (
          <>
            <button onClick={speech === 'reading' ? pauseReading : resumeReading} style={{ ...ribbonBtn, borderColor: 'var(--accent)', color: 'var(--accent-light)' }}
              title={speech === 'reading' ? 'Pause reading' : 'Carry on reading'}>{speech === 'reading' ? '⏸ Pause' : '▶ Resume'}</button>
            <button onClick={stopReading} style={ribbonBtn} title="Stop reading">■ Stop</button>
          </>
        ))}
        <button onClick={viewPlan} disabled={planBusy || !chapterNum} style={ribbonBtn}
          title="Show this chapter's plan: its arc, skeleton goal, characters and themes">
          {planBusy ? <Spinner /> : (isMobile ? 'Plan' : 'View Plan')}
        </button>
        {modelChoices && (
          <select value={modelOverride} onChange={e => setModelOverride(e.target.value)} title="Model for writing chapters — nothing is saved"
            style={{ ...ribbonBtn, maxWidth: isMobile ? 150 : 220, color: modelOverride ? 'var(--accent-light)' : 'var(--text-primary)', cursor: 'pointer' }}>
            <option value="">Model: Settings default</option>
            {modelChoices.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        )}
        <span style={{ flex: 1 }} />
        {ribbonRight}
        <label title="Draw the paragraphs the house-style gate flags in orange. Chapters written outside the interview never went through the gate, so marks on them are best-effort."
          style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-secondary)', cursor: 'pointer', minHeight: isMobile ? 28 : 36, flexShrink: 0, whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={marksOn}
            onChange={e => { setMarksOn(e.target.checked); lsSet('nm-gate-marks', e.target.checked ? '1' : '0') }} />
          Gate marks
        </label>
        {words > 0 && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{words.toLocaleString()} words · {iv.parts.length} part{iv.parts.length === 1 ? '' : 's'}</span>}
        <button onClick={() => { const st = useStore.getState(); st.consoleOpen ? st.closeConsole() : st.openConsole() }}
          title="Show or hide the engine console (hidden automatically while a chapter is written)"
          style={{ ...ribbonBtn, marginLeft: 'auto', flexShrink: 0 }}>▤ Console</button>
      </div>

      {/* ── the page, with the interview docked beside it ── */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, minWidth: 0, position: 'relative' }}>
        <style>{PAGE_CSS}</style>
        <div ref={pageRef} className="ws-scroll" style={{
          flex: 1, minWidth: 0, overflowY: 'auto', background: 'var(--bg-base)',
          padding: compact ? `14px 10px ${dockVisible && minimized ? 84 : 34}px` : `32px 28px ${dockVisible && minimized ? 92 : 48}px`,   // extra room only while the minimised interview pill is floating over the bottom   // just room under the sheet for its shadow and the sheets peeking out beneath
        }}>
          <article className="ws-page" ref={cardRef}
            onPointerDown={swipeDown} onPointerMove={swipeMove} onPointerUp={swipeEnd} onPointerCancel={swipeEnd}
            style={{
            touchAction: 'pan-y', position: 'relative',
            // The page is white, like a Word document, in both themes. Everything drawn on it (text, the
            // grey labels, the red gate marks, the fix popover) reads these colours instead of the app
            // theme's, which are pale on a dark theme and would vanish on white.
            '--text-primary': '#1f2937', '--text-secondary': '#4b5563', '--text-muted': '#6b7280',
            '--border': '#d1d5db', '--border-soft': '#e5e7eb', '--bg-elevated': '#f3f4f6', '--bg-base': '#ffffff',
            '--flag': '#ea580c', '--flag-text': '#c2410c', '--red': '#dc2626', '--amber': '#b45309', '--green': '#15803d',
            // minHeight 100%: the sheet runs down to near the bottom of the screen
            maxWidth: 820, margin: '0 auto', minHeight: '100%', background: 'linear-gradient(180deg, #ffffff 0%, #fffefd 100%)',
            borderRadius: isMobile ? 16 : 22,
            // two more sheets peeking out underneath, then a ladder of soft shadows, ending in a faint violet glow
            boxShadow: isMobile
              ? '0 8px 0 -4px #ececf2, 0 16px 0 -8px #dcdce6, 0 2px 4px rgba(0,0,0,0.12), 0 12px 28px rgba(0,0,0,0.30), 0 24px 50px -12px rgba(76,29,149,0.38)'
              : '0 12px 0 -7px #ececf2, 0 24px 0 -14px #dcdce6, 0 1px 2px rgba(0,0,0,0.10), 0 4px 8px rgba(0,0,0,0.12), 0 14px 28px rgba(0,0,0,0.20), 0 34px 64px rgba(0,0,0,0.32), 0 60px 110px -18px rgba(76,29,149,0.42)',
            padding: compact ? '28px 20px 30px' : '60px 72px 64px', color: '#1f2937',
            fontFamily: 'Georgia, "Times New Roman", serif', fontSize: compact ? 15 : 16.5, lineHeight: 1.8,
          }}>
            {/* Regenerate — slim, over the card's top-right corner */}
            {iv.parts.length > 0 && !pendingDraft && !iv.starting && !iv.interactive?.busy && (
              <div style={{ position: 'absolute', top: isMobile ? 8 : 12, right: isMobile ? 10 : 14, zIndex: 25, fontFamily: 'var(--font-ui, system-ui, sans-serif)' }}>
                {!regen ? (
                  <button onClick={() => setRegen({ pick: null, busy: false, err: '' })}
                    title="Go back to a part and redo the chapter from there"
                    style={{
                      fontSize: 10, fontWeight: 600, lineHeight: 1, padding: '3px 9px', minHeight: 22, borderRadius: 999, cursor: 'pointer',
                      background: 'rgba(255,255,255,0.92)', color: '#6d28d9', border: '1px solid #ddd6fe',
                    }}>↻ Regenerate</button>
                ) : (
                  <div role="dialog" aria-label="Regenerate from a part" style={{
                    width: 'min(260px, calc(100vw - 48px))', padding: '9px 10px', borderRadius: 12, background: '#fff',
                    border: '1px solid #ddd6fe', boxShadow: '0 10px 30px rgba(76,29,149,0.25)', fontSize: 11, color: '#374151',
                  }}>
                    {regen.pick === null ? (
                      <>
                        <div style={{ fontWeight: 700, marginBottom: 6 }}>Go back to which part?</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 8 }}>
                          {iv.parts.map((_, i) => (
                            <button key={i} onClick={() => setRegen({ pick: i + 1, busy: false, err: '' })}
                              style={{ minWidth: 30, fontSize: 11, fontWeight: 700, padding: '3px 8px', minHeight: 26, borderRadius: 8, cursor: 'pointer',
                                       background: '#f5f3ff', color: '#6d28d9', border: '1px solid #ddd6fe' }}>Part {i + 1}</button>
                          ))}
                        </div>
                        <button onClick={() => setRegen(null)} style={{ fontSize: 11, color: '#6b7280', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>Close</button>
                      </>
                    ) : (
                      <>
                        <div style={{ marginBottom: 8, lineHeight: 1.45 }}>
                          Keep part{regen.pick > 1 ? `s 1–${regen.pick}` : ' 1'}
                          {iv.parts.length > regen.pick ? <> and <b style={{ color: '#c2410c' }}>delete the {iv.parts.length - regen.pick} later part{iv.parts.length - regen.pick === 1 ? '' : 's'}</b></> : ' (nothing after it to delete)'}
                          , then redo the chapter from there?
                        </div>
                        {regen.err && <div style={{ color: '#c2410c', marginBottom: 8, lineHeight: 1.4 }}>{regen.err}</div>}
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                          <button onClick={() => doRegen(regen.pick)} disabled={regen.busy}
                            style={{ fontSize: 11, fontWeight: 700, padding: '3px 12px', minHeight: 26, borderRadius: 8, background: '#7c3aed', color: '#fff', border: 'none', cursor: 'pointer' }}>
                            {regen.busy ? <ElapsedTimer /> : 'Redo from here'}</button>
                          <button onClick={() => setRegen({ pick: null, busy: false, err: '' })} disabled={regen.busy}
                            style={{ fontSize: 11, padding: '3px 10px', minHeight: 26, borderRadius: 8, background: 'transparent', color: '#4b5563', border: '1px solid #d1d5db', cursor: 'pointer' }}>Back</button>
                          {regen.err && iv.source !== 'session' && (
                            <button onClick={() => { setRegen(null); setMinimized(false); iv.start() }}
                              title="No saved interview can be rewound, so write the chapter again from the opening (the saved chapter is archived when the new one finishes)"
                              style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', minHeight: 26, borderRadius: 8, background: '#fff7ed', color: '#c2410c', border: '1px solid #fdba74', cursor: 'pointer' }}>Start over</button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            <header style={{ textAlign: 'center', margin: isMobile ? '0 0 22px' : '0 0 34px' }}>
              <h2 style={{ margin: 0, fontWeight: 400 }} aria-label={`Chapter ${chapterNum || ''}`}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14 }}>
                  <span style={{ flex: '0 1 90px', height: 1, background: 'linear-gradient(90deg, transparent, #c4b5fd)' }} />
                  <span style={{ fontFamily: 'var(--font-ui, system-ui, sans-serif)', fontSize: 11, fontWeight: 700, letterSpacing: '0.34em', textTransform: 'uppercase', color: '#6b7280', paddingLeft: '0.34em' }}>Chapter</span>
                  <span style={{ flex: '0 1 90px', height: 1, background: 'linear-gradient(270deg, transparent, #c4b5fd)' }} />
                </div>
                <div style={{ fontSize: isMobile ? 48 : 68, lineHeight: 1.05, color: '#4c1d95', margin: '8px 0 2px', fontWeight: 400 }}>{chapterNum || '…'}</div>
              </h2>
              <div style={{ fontSize: 15, color: '#a78bfa', lineHeight: 1 }}>❦</div>
              {live && <div style={{ marginTop: 8, fontFamily: 'var(--font-ui, system-ui, sans-serif)', fontSize: 10, fontWeight: 700, letterSpacing: '0.22em', textTransform: 'uppercase', color: '#b45309' }}>draft in progress</div>}
            </header>

            {iv.loading && <div style={{ display: 'flex', justifyContent: 'center', padding: 30 }}><Spinner size={18} /></div>}

            {blank && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: isMobile ? '50px 8px' : '90px 20px', fontFamily: 'var(--font-ui, system-ui, sans-serif)', fontSize: 14, lineHeight: 1.7 }}>
                <div style={{ fontSize: 34, opacity: 0.5, marginBottom: 6 }}>¶</div>
                A blank page.<br />
                Press <b style={{ color: 'var(--text-secondary)' }}>Generate</b> — every part you write appears here and is kept,
                and a paragraph that fails the house-style gate turns orange so you can fix just that paragraph.
              </div>
            )}

            {iv.inFlight && !iv.starting && !iv.interactive && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: 'var(--amber)', marginBottom: 18,
                fontFamily: 'var(--font-ui, system-ui, sans-serif)',
              }}>
                <ElapsedTimer /> A part is still being written on the server.
                <button onClick={iv.loadDraft} style={{ ...ribbonBtn, padding: '3px 10px', minHeight: 28, fontSize: 11 }}>Check again</button>
              </div>
            )}

            {iv.parts.map((text, i) => (
              <PartView key={i} index={i}
                label={iv.source === 'file' ? 'Chapter text' : `Part ${i + 1}`}
                text={text} mark={report ? report[i] : null} fixable onEdit={saveParagraph}
                dropCap={i === 0}
                reading={readingAt && readingAt.part === i ? readingAt.para : -1}
                latest={live && i === iv.parts.length - 1 && !pendingDraft}
                onRewind={live && i < iv.parts.length - 1 ? iv.rewind : undefined} laterParts={iv.parts.length - 1 - i}
                fixingKey={fixingKey} fixMessage={fixMessage} onFix={fixParagraph} />
            ))}

            {pendingDraft && (
              <PartView index={iv.parts.length} pending label="Draft awaiting your decision — failed the gate"
                text={pendingDraft} mark={pendingReport ? pendingReport[0] : null} fixable={false}
                fixingKey={null} fixMessage={null} onFix={() => {}} />
            )}

            {iv.parts.length > 0 && !pendingDraft && (
              <div aria-hidden style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, margin: '26px 0 0', color: '#c4b5fd' }}>
                <span style={{ flex: '0 1 70px', height: 1, background: 'linear-gradient(90deg, transparent, #ddd6fe)' }} />
                <span style={{ fontSize: 13 }}>◆</span>
                <span style={{ flex: '0 1 70px', height: 1, background: 'linear-gradient(270deg, transparent, #ddd6fe)' }} />
              </div>
            )}

            {iv.starting && !iv.interactive && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-muted)', fontSize: 13, fontFamily: 'var(--font-ui, system-ui, sans-serif)' }}>
                <ElapsedTimer since={iv.busySince} /> Writing the opening part…
              </div>
            )}
            {iv.interactive?.busy && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-muted)', fontSize: 13, fontFamily: 'var(--font-ui, system-ui, sans-serif)' }}>
                <ElapsedTimer since={iv.busySince} /> Writing the next part…
              </div>
            )}
          </article>

          {/* Continue — always on the page while this chapter has an interview (live, cut off, or stored): it finds the
              stored session and puts the interview back on the question it was on, whatever state it was left in. */}
          {(live || (iv.stored && iv.source === 'none')) && (
            <div style={{
              position: 'sticky', bottom: isMobile ? (dockVisible && minimized ? 74 : 10) : 14, zIndex: 20, marginTop: 14,
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, pointerEvents: 'none',
            }}>
              {iv.waiting && (
                <div role="status" style={{
                  pointerEvents: 'auto', maxWidth: 340, textAlign: 'center', fontSize: 11, padding: '6px 12px', borderRadius: 10,
                  background: 'var(--bg-card)', color: 'var(--amber)', border: '1px solid var(--amber)', boxShadow: '0 6px 20px rgba(0,0,0,0.4)',
                  fontFamily: 'var(--font-ui, system-ui, sans-serif)',
                }}>A part may still be writing on the server (about {Math.max(1, Math.ceil(iv.waiting.retry_after / 60))} min until it is treated as cut off). If it's stuck, force it.</div>
              )}
              <button onClick={async () => {
                  const r = await iv.resume(!!iv.waiting)
                  if (r && !r.waiting) setMinimized(false)
                }}
                disabled={iv.recovering || iv.starting}
                title="Find this chapter's stored interview and continue from the question it was on"
                style={{
                  pointerEvents: 'auto', padding: '5px 20px', minHeight: 32, fontSize: 13, fontWeight: 700, borderRadius: 999,
                  cursor: iv.recovering ? 'default' : 'pointer', background: iv.waiting ? 'var(--amber)' : 'var(--accent)', color: '#fff', border: 'none',
                  fontFamily: 'var(--font-ui, system-ui, sans-serif)', boxShadow: '0 8px 22px rgba(76,29,149,0.45)', opacity: iv.recovering ? 0.7 : 1,
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                }}>{iv.recovering ? <><ElapsedTimer /> Finding it…</> : iv.waiting ? '⚠ Force continue'
                  : iv.stored && !live ? `▶ Continue — restore saved interview (${iv.stored.parts} parts)` : '▶ Continue'}</button>
            </div>
          )}
        </div>

        {notice && (
          <div role="status" onClick={() => setNotice(null)} style={{
            position: 'absolute', zIndex: 135, top: 12, left: '50%', transform: 'translateX(-50%)', maxWidth: 'calc(100% - 24px)',
            padding: '9px 16px', borderRadius: 999, fontSize: 12, fontWeight: 600, cursor: 'pointer',
            background: 'var(--bg-card)', color: notice.ok ? 'var(--green)' : 'var(--amber)',
            border: `1px solid ${notice.ok ? 'var(--green)' : 'var(--amber)'}`, boxShadow: '0 8px 28px rgba(0,0,0,0.5)',
          }}>{notice.ok ? '✓ ' : ''}{notice.msg}</div>
        )}
        {planOpen && (
          <div role="dialog" aria-label={`Chapter ${chapterNum} plan`} style={{
            position: 'absolute', zIndex: 130, top: 10, left: isMobile ? 8 : 16, right: isMobile ? 8 : 'auto',
            width: isMobile ? 'auto' : 480, maxHeight: 'calc(100% - 20px)', overflowY: 'auto',
            background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14,
            boxShadow: '0 14px 44px rgba(0,0,0,0.55)', padding: 14,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Chapter {chapterNum} plan
              </div>
              <button onClick={() => setPlanOpen(false)} aria-label="Close the plan" style={{ ...ribbonBtn, padding: '2px 10px', minHeight: 30 }}>✕</button>
            </div>
            {/* the reference gauge first, so its suggested budgets and Apply button are in view without scrolling */}
            <ReferenceGauge projectId={projectId} chapterNum={chapterNum}
              onApplied={() => api.getChapterPlan(projectId, chapterNum).then(setPlan).catch(() => {})} />
            <div style={{ height: 12 }} />
            {plan?.error
              ? <div style={{ fontSize: 12, color: 'var(--red)' }}>{plan.error}</div>
              : (renderPlan ? renderPlan(plan) : <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{JSON.stringify(plan, null, 2)}</pre>)}
          </div>
        )}
        {dockVisible && <InterviewDock iv={iv} minimized={minimized} setMinimized={setMinimized} isMobile={isMobile} />}
      </div>
    </div>
  )
}
