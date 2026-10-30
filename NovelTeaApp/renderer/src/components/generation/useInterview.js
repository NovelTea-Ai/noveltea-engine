import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import useStore from '../../store/useStore'
import useSpokenAudio, { interviewText } from '../../hooks/useSpokenAudio'
import { fmtElapsed, secsSince } from '../shared/ElapsedTimer'
import { isConnectionDrop, waitOrReturn } from '../../hooks/connection'

// The interactive ("interview") chapter engine for the Generate workspace: the same API calls and
// flow as GenerateTab's interactive mode, but it also keeps ALL the parts written so far (the
// backend now sends them) so the workspace can show them on a page, and it can reload a
// half-finished interview from the server (so the page survives a reload or a restart).
//
// This hook is the chapter interview: the old tab-based Generate screen no longer exists.
export default function useInterview({ projectId, chapterNum, modelOverride }) {
  const { appendConsoleLine, setConsoleRunning, clearConsoleRunning } = useStore()
  const [parts, setParts] = useState([])            // every part written so far, in order
  const [source, setSource] = useState('none')      // none | session | sidecar | file
  const [interactive, setInteractive] = useState(null)   // the pending question, or null
  const [qHistory, setQHistory] = useState([])      // [{question}] — the breadcrumb
  const [sel, setSel] = useState(null)              // null | option index | 'other'
  const [other, setOther] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [evidenceIdx, setEvidenceIdx] = useState(null)
  const [abandoning, setAbandoning] = useState(false)
  const [starting, setStarting] = useState(false)   // the opening part is being written
  const [inFlight, setInFlight] = useState(false)   // a part is being written on the server right now
  const [loading, setLoading] = useState(false)
  const [loadedFor, setLoadedFor] = useState(0)     // the chapter whose text has finished loading onto the page (0 = none yet)
  const [stored, setStored] = useState(null)        // a saved interview that can be restored (none live): { parts, decisions }
  const [waiting, setWaiting] = useState(null)      // Continue found a part that may still be writing: { retry_after }
  const [recovering, setRecovering] = useState(false)
  const [busySince, setBusySince] = useState(0)     // when the part being written now was asked for (for the button timers)
  const stepStart = useRef(0)
  const beginStep = () => { const t = Date.now(); stepStart.current = t; setBusySince(t) }
  const took = () => (stepStart.current ? ` in ${fmtElapsed(secsSince(stepStart.current))}` : '')
  // Bumped whenever something newer than a page reload happens (the chapter changes, an interview starts). A reload
  // that was already in flight then discards its answer instead of overwriting the newer state with a stale one.
  const epoch = useRef(0)
  // Chapter generation keeps the console hidden: lines are still logged (open it with the Console button, top right), it just never pops up.
  const addLog = useCallback((msg, type = 'info') => { appendConsoleLine(msg, type); useStore.getState().closeConsole() }, [appendConsoleLine])

  // Show a question: shared by a live response and by a question reloaded from the server.
  const showQuestion = useCallback((res) => {
    const step = (res.parts_so_far || 1) - 1
    // always a complete array: resuming a session at part 3 has no record of questions 1-2, and a hole here
    // used to become an `undefined` entry on the next update and crash the breadcrumb
    setQHistory(h => {
      const next = Array.from({ length: step + 1 }, (_, i) => h[i] || { question: `Part ${i + 1}` })
      next[step] = { question: res.question }
      return next
    })
    setInteractive({
      session_id: res.session_id, question: res.question,
      options: res.options || [], recommended: res.recommended ?? 0,
      partsCount: res.parts_so_far, segment: res.segment, busy: false,
      gateReasons: res.gate_reasons || null, gatePreview: res.gate_preview || null, sceneWords: res.scene_words || null,
    })
  }, [])

  // Pull this chapter's page from the server: the live interview's parts (and its pending question),
  // or the saved chapter split into the parts it was written in.
  const loadDraft = useCallback(async () => {
    const mine = epoch.current
    setLoading(true)
    try {
      const d = await api.interactiveDraft(projectId, chapterNum)
      if (mine !== epoch.current) return d      // superseded while it was loading
      setParts(d.parts || [])
      setLoadedFor(chapterNum)
      setSource(d.source || 'none')
      setInFlight(!!d.in_flight)
      setStored(d.stored || null)
      if (d.pending) {
        showQuestion({ ...d.pending, session_id: d.session_id || d.pending.session_id,
                       parts_so_far: d.pending.parts_so_far ?? (d.parts || []).length })
      } else {
        setInteractive(null)
        setQHistory([])
      }
      return d
    } catch (e) {
      addLog(`✗ Couldn't load chapter ${chapterNum}: ${e.message}`, 'error')
      return null
    } finally { setLoading(false) }
  }, [projectId, chapterNum, showQuestion, addLog])

  // reload whenever the chapter changes (also resets the per-question UI state)
  useEffect(() => {
    setSel(null); setOther(''); setEvidenceIdx(null)
    setParts([]); setInteractive(null); setQHistory([]); setLoadedFor(0)
    epoch.current++      // anything still loading the previous chapter is now stale
    loadDraft()
  }, [projectId, chapterNum]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleResponse = useCallback((res) => {
    setSel(null); setOther(''); setEvidenceIdx(null)
    if (res.in_flight) {
      setInFlight(true)
      addLog('⚡ Still writing a part on the server — check again shortly. What is written so far is safe.', 'info')
      return
    }
    setInFlight(false)
    if (res.done) {
      addLog(`✓ Chapter ${chapterNum} complete${took()} (~${res.word_count} words) — steered by ${res.decisions?.length || 0} of your choices.`, 'success')
      setInteractive(null); setQHistory([])
      clearConsoleRunning()
      loadDraft()            // the saved (polished) chapter replaces the draft parts on the page
      return
    }
    if (res.parts) { setParts(res.parts); setSource('session') }
    addLog(res.resumed
      ? `⚡ Resumed your in-progress session — part ${res.parts_so_far} is awaiting your choice`
      : `✍ Part ${res.parts_so_far} written${took()} — decision needed: ${res.question}`, 'info')
    showQuestion(res)
  }, [chapterNum, addLog, clearConsoleRunning, loadDraft, showQuestion])

  // The phone dropped the request (you switched apps) but the server is still writing the part. Wait for it and put it
  // on the page when it lands, instead of reporting a failure. Checks every 10 s, and at once when you come back.
  const pickUpAfterDrop = useCallback(async (partsBefore) => {
    addLog('📱 The connection dropped (the phone left the app). The part is still being written on the server; it will appear here when it is ready.', 'info')
    for (let i = 0; i < 180; i++) {            // up to about half an hour
      await waitOrReturn(10000)
      let d
      try { d = await api.interactiveDraft(projectId, chapterNum) } catch { continue }   // still offline
      if (d.in_flight) continue
      setParts(d.parts || []); setLoadedFor(chapterNum); setSource(d.source || 'none'); setInFlight(false); setStored(d.stored || null)
      if (d.pending) {
        const n = d.pending.parts_so_far ?? (d.parts || []).length
        addLog(`✍ Part ${n} written${took()} — picked up after the connection dropped. Decision needed: ${d.pending.question}`, 'info')
        showQuestion({ ...d.pending, session_id: d.session_id || d.pending.session_id, parts_so_far: n })
      } else {
        setInteractive(null); setQHistory([])
        clearConsoleRunning()
        addLog((d.parts || []).length > partsBefore ? `✓ Chapter ${chapterNum} finished${took()} while the phone was away.` : '⚡ Picked the interview back up.', 'success')
      }
      return true
    }
    addLog('✗ Still no answer from the server after a long wait. Press Continue to look again.', 'error')
    return false
  }, [projectId, chapterNum, addLog, showQuestion, clearConsoleRunning]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(async () => {
    epoch.current++      // a reload that is still in flight must not wipe what this interview writes
    setConsoleRunning('interactive')
    useStore.getState().closeConsole()
    setQHistory([])
    setStarting(true)
    beginStep()
    addLog(`⚡ Interactive: writing chapter ${chapterNum} opening — you'll choose the direction at each pivotal moment…`)
    try {
      handleResponse(await api.interactiveChapter(projectId, chapterNum, null, null, null, false, modelOverride || null))
    } catch (e) {
      if (isConnectionDrop(e)) { await pickUpAfterDrop(0); return }
      addLog(`✗ ${e.message}`, 'error')
      clearConsoleRunning()
    } finally { setStarting(false) }
  }, [projectId, chapterNum, modelOverride, setConsoleRunning, clearConsoleRunning, addLog, handleResponse, pickUpAfterDrop])

  const chosenText = sel === 'other' ? other.trim()
    : (sel !== null && interactive?.options?.[sel]) ? interactive.options[sel].label : ''

  const confirm = useCallback(async () => {
    if (!interactive?.session_id || interactive.busy || !chosenText) return
    let choiceText = chosenText
    setInteractive(i => ({ ...i, busy: true }))
    setSubmitting(true)
    beginStep()
    if (sel === 'other') {   // free-text directions get silently expanded, like the planning wizards
      try { choiceText = (await api.polishAnswer(projectId, interactive.question, choiceText, chapterNum)).polished || choiceText }
      catch { /* best-effort */ }
    }
    addLog(`⚡ You chose: ${choiceText.slice(0, 80)} — continuing…`)
    try {
      handleResponse(await api.interactiveChapter(projectId, chapterNum, interactive.session_id, choiceText, null, false, modelOverride || null))
    } catch (e) {
      if (isConnectionDrop(e)) { setSubmitting(false); await pickUpAfterDrop(parts.length); return }
      addLog(`✗ ${e.message}`, 'error')
      setInteractive(null)
      clearConsoleRunning()
      loadDraft()
    } finally { setSubmitting(false) }
  }, [interactive, chosenText, sel, projectId, chapterNum, modelOverride, addLog, handleResponse, clearConsoleRunning, loadDraft, pickUpAfterDrop, parts.length])

  const goBack = useCallback(async (toIndex = true) => {
    if (!interactive?.session_id || interactive.busy || (interactive.partsCount || 0) <= 1) return
    setInteractive(i => ({ ...i, busy: true }))
    beginStep()
    addLog('⚡ Going back to reconsider an earlier part…')
    try {
      handleResponse(await api.interactiveChapter(projectId, chapterNum, interactive.session_id, null, null, toIndex, modelOverride || null))
    } catch (e) {
      if (isConnectionDrop(e)) { await pickUpAfterDrop(parts.length); return }
      addLog(`✗ ${e.message}`, 'error')
      setInteractive(i => ({ ...i, busy: false }))
    }
  }, [interactive, projectId, chapterNum, modelOverride, addLog, handleResponse, pickUpAfterDrop, parts.length])

  // Continue: ask the server to find this chapter's stored interview and put it back on the question it was on.
  // `force` takes over a part the server thinks may still be writing (second press).
  const resume = useCallback(async (force = false) => {
    if (recovering) return null
    epoch.current++
    setRecovering(true)
    try {
      const r = await api.interactiveRecover(projectId, chapterNum, force)
      if (r.waiting) {
        setWaiting(r)
        if (r.parts) { setParts(r.parts); setSource('session') }
        return r
      }
      setWaiting(null); setInFlight(false); setStored(null)
      if (r.parts) { setParts(r.parts); setSource('session') }
      addLog(r.restored ? `⚡ Restored your saved interview — part ${r.parts_so_far} is awaiting your choice`
        : `⚡ Continuing — part ${r.parts_so_far} is awaiting your choice`, 'info')
      showQuestion(r)
      return r
    } catch (e) {
      addLog(`✗ Couldn't continue: ${e.message}`, 'error')
      return null
    } finally { setRecovering(false) }
  }, [recovering, projectId, chapterNum, addLog, showQuestion])

  // Back to a part: the interview returns to the question that followed it; later parts are dropped (backed up first).
  const rewind = useCallback(async (part) => {
    epoch.current++
    try {
      if (inFlight) { const r0 = await resume(true); if (!r0 || r0.waiting) return null }
      const r = await api.interactiveRewind(projectId, chapterNum, part)
      setWaiting(null); setInFlight(false)
      if (r.parts) { setParts(r.parts); setSource('session') }
      addLog(`⚡ Back at part ${part} — pick a different direction`, 'info')
      showQuestion(r)
      return r
    } catch (e) {
      addLog(`✗ Couldn't go back to part ${part}: ${e.message}`, 'error')
      return null
    }
  }, [inFlight, resume, projectId, chapterNum, addLog, showQuestion])

  // Regenerate from a part: parts after it are deleted and its question is asked again. A live interview is rewound; a
  // finished chapter has its stored interview restored first. Returns { error } instead of throwing, for the page to show.
  const regenerate = useCallback(async (part) => {
    if (source === 'session') {
      const r = await rewind(part)
      return r || { error: "Couldn't go back to that part" }
    }
    epoch.current++
    try {
      const r = await api.interactiveRegenerate(projectId, chapterNum, part, parts[part - 1] || '')
      setWaiting(null); setInFlight(false); setStored(null)
      if (r.parts) { setParts(r.parts); setSource('session') }
      addLog(`⚡ Back at part ${part} — later parts deleted; pick a direction to redo from here`, 'info')
      showQuestion(r)
      return r
    } catch (e) {
      addLog(`✗ Couldn't regenerate from part ${part}: ${e.message}`, 'error')
      return { error: e.message }
    }
  }, [source, rewind, projectId, chapterNum, parts, addLog, showQuestion])

  const abandon = useCallback(async () => {
    if (abandoning) return
    setAbandoning(true)
    try {
      await api.interactiveChapterAbandon(projectId, chapterNum, interactive?.session_id || null)
      addLog('⚡ Interactive session abandoned.', 'info')
    } catch (e) {
      addLog(`✗ Abandon failed: ${e.message}`, 'error')
    } finally {
      setAbandoning(false)
      setInteractive(null); setQHistory([])
      clearConsoleRunning()
      loadDraft()
    }
  }, [abandoning, projectId, chapterNum, interactive, addLog, clearConsoleRunning, loadDraft])

  // Once the voice has arrived the Read button becomes a Play button that replays the saved audio (no new request).
  const speech = useSpokenAudio(interviewText(interactive?.question, interactive?.options), e => addLog(`✗ Read-aloud failed: ${e.message}`, 'error'),
    { onReady: s => addLog(`🔊 Question voiced in ${fmtElapsed(s)}`, 'info') })

  return {
    parts, setParts, source, interactive, qHistory, sel, setSel, other, setOther, chosenText,
    submitting, speech, evidenceIdx, setEvidenceIdx, abandoning, starting, inFlight, loading, busySince,
    start, confirm, goBack, abandon, loadDraft, loadedFor, resume, rewind, regenerate, stored, waiting, recovering,
  }
}
