import { useEffect, useState } from 'react'
import { API_BASE, api } from '../../api'
import { TTS_GROUPS, TTS_VOICES, savedTtsVoice } from '../../constants/ttsVoices'
import useStore from '../../store/useStore'
import { fmtElapsed, secsSince } from '../shared/ElapsedTimer'
import { isConnectionDrop, waitOrReturn } from '../../hooks/connection'
import { ExportMenu } from '../shared/ProjectIO'
import { Spinner, copyTextToClipboard } from '../shared/projectUi'

/* ══════════════════════════════════════
   READER TAB
══════════════════════════════════════ */
export function InfluenceCard({ inf, onClose }) {
  const novelName = inf.novel?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || '?'
  const tones = (inf.tone || []).slice(0, 4).map(t => t.replace(/_/g, ' '))
  return (
    <div style={{
      position: 'fixed', zIndex: 9999,
      background: 'var(--bg-surface)', border: '1px solid var(--accent)',
      borderRadius: 'var(--radius-lg)', padding: 14, maxWidth: 340,
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--accent-light)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Corpus Influence
          </div>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', marginTop: 2 }}>{novelName}</div>
        </div>
        <button onClick={onClose} style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1 }}>✕</button>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>
        TYPE: <span style={{ color: 'var(--text-secondary)' }}>{inf.humor_type?.replace(/_/g, ' ') || inf.type || '?'}</span>
      </div>
      {tones.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
          {tones.map(t => (
            <span key={t} style={{
              fontSize: 9, padding: '2px 6px', borderRadius: 10,
              background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              color: 'var(--text-muted)',
            }}>{t}</span>
          ))}
        </div>
      )}
      {inf.excerpt && (
        <div style={{
          fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.6,
          fontStyle: 'italic', borderLeft: '2px solid var(--accent)',
          paddingLeft: 8,
        }}>
          "{inf.excerpt}"
        </div>
      )}
    </div>
  )
}

// Render chapter prose: *asterisk-wrapped* spans (inner monologue / emphasis)
// become real italics in a distinct tint, so thoughts never read as dialogue.
// `marks` = {word: how narration says it}. Those words show in blue; clicking
// one calls onMark(word, say, event). The text itself is shown exactly as written.
export function markWords(s, marks, onMark, keyBase) {
  const words = Object.keys(marks || {})
  if (!words.length) return s
  const re = new RegExp(`\\b(${words.sort((a, b) => b.length - a.length).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`, 'g')
  return s.split(re).map((p, i) => (i % 2 === 1
    ? <span key={`${keyBase}-${i}`} onClick={e => onMark && onMark(p, marks[p], e)}
        title={`Spoken as “${marks[p]}”`}
        style={{ color: '#4a90e2', cursor: 'pointer', borderBottom: '1px dotted #4a90e2' }}>{p}</span>
    : p))
}

export function renderProse(t, marks = null, onMark = null) {
  const parts = String(t).split(/(\*[^*\n]+\*)/g)
  return parts.map((p, i) =>
    p.length > 2 && p.startsWith('*') && p.endsWith('*')
      ? <em key={i} style={{ fontStyle: 'italic', color: 'var(--accent-light)' }}>{markWords(p.slice(1, -1), marks, onMark, i)}</em>
      : <span key={i}>{markWords(p, marks, onMark, i)}</span>)
}

// The card shown when a blue word is clicked: the spoken form, and a button to hear it.
export function PronCard({ pop, voice, projectId, onClose }) {
  const [busy, setBusy] = useState(false)
  async function hear() {
    setBusy(true)
    try {
      const r = await api.speak(pop.say, voice, projectId)
      const bin = atob(r.audio_b64)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
      const a = new Audio(url)
      a.onended = () => URL.revokeObjectURL(url)
      await a.play()
    } catch { /* voice unavailable: the spelling is still shown */ }
    setBusy(false)
  }
  return (
    <div onClick={e => e.stopPropagation()} style={{
      position: 'fixed', left: Math.min(pop.x, window.innerWidth - 230), top: pop.y + 14, zIndex: 400,
      width: 214, padding: '10px 12px', borderRadius: 'var(--radius-sm)',
      background: 'var(--bg-elevated)', border: '1px solid #4a90e2', boxShadow: '0 6px 20px rgba(0,0,0,0.25)',
      fontFamily: 'system-ui, sans-serif', fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'normal',
    }}>
      <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: 13 }}>{pop.word}</div>
      <div style={{ margin: '4px 0 8px' }}>Spoken as <b style={{ color: '#4a90e2' }}>{pop.say}</b></div>
      <div style={{ display: 'flex', gap: 6 }}>
        <button onClick={hear} disabled={busy} style={{
          fontSize: 11, padding: '4px 10px', fontWeight: 600, background: 'var(--bg-elevated)',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
        }}>{busy ? <Spinner size={11} /> : '▶ Hear it'}</button>
        <button onClick={onClose} style={{
          fontSize: 11, padding: '4px 10px', background: 'transparent', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
        }}>Close</button>
      </div>
    </div>
  )
}

export function ReaderTab({ projectId, onEdit }) {
  const [chapters, setChapters] = useState([])
  const [selected, setSelected] = useState(null)
  const [text, setText] = useState('')
  const [influences, setInfluences] = useState([])
  const [showInfluences, setShowInfluences] = useState(false)
  const [activeInf, setActiveInf] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revising, setRevising] = useState(false)
  const [reviseResult, setReviseResult] = useState(null)
  const [showRevise, setShowRevise] = useState(false)
  const [reviseNote, setReviseNote] = useState('')
  // chapter versions: regenerating archives the old text; the reader can view/restore
  const [versions, setVersions] = useState([])
  const [viewingV, setViewingV] = useState(null)      // null = current
  const [versionText, setVersionText] = useState('')
  // narration (NVIDIA Magpie TTS) — keyed per chapter so switching chapters
  // doesn't show stale audio for the wrong one. Voice choice persists across
  // sessions/chapters (a reader picks a narrator once, not per chapter).
  const [narrating, setNarrating] = useState(false)
  const [audioUrl, setAudioUrl] = useState(null)
  const [voice, setVoice] = useState(savedTtsVoice)
  const { appendConsoleLine, openConsole, setConsoleRunning, clearConsoleRunning } = useStore()
  // Words narration respells (names, qi, sound words): shown blue, click for the spoken form.
  const [pronMarks, setPronMarks] = useState({})
  const [pronPop, setPronPop] = useState(null)
  const shownText = viewingV != null ? versionText : text
  useEffect(() => {
    setPronPop(null)
    if (!shownText) { setPronMarks({}); return }
    let live = true
    api.pronMarks(projectId, shownText).then(r => { if (live) setPronMarks(r.marks || {}) }).catch(() => {})
    return () => { live = false }
  }, [projectId, shownText])

  // Picking a voice loads that voice's saved narration for this chapter, if it
  // was made from the current text; otherwise the player clears until Narrate.
  function changeVoice(v) {
    setVoice(v)
    try { localStorage.setItem('nm-tts-voice', v) } catch {}
    setAudioUrl(null)
    if (!selected) return
    const ch = selected
    api.narrateStatus(projectId, ch, v)
      .then(r => { if (r.exists) setAudioUrl(`${API_BASE}${r.audio_url}`) })
      .catch(() => {})
  }

  // Narrate shows a running timer on the button, and the console gets the time taken when it finishes.
  const [narrateSecs, setNarrateSecs] = useState(0)
  async function narrate() {
    if (!selected || narrating) return
    const started = Date.now()
    const ch = selected
    const voiceLabel = TTS_VOICES.find(v => v.id === voice)?.label || voice
    setNarrateSecs(0)
    const tick = setInterval(() => setNarrateSecs(Math.floor((Date.now() - started) / 1000)), 1000)
    setNarrating(true)
    setAudioUrl(null)
    setConsoleRunning('narrate', 'narrate')
    try {
      const res = await api.narrateChapter(projectId, ch, voice)
      setAudioUrl(`${API_BASE}${res.audio_url}`)
      const took = fmtElapsed(Math.round((Date.now() - started) / 1000))
      const len = res.duration_sec ? ` · ${fmtElapsed(Math.round(res.duration_sec))} of audio` : ''
      appendConsoleLine(res.reused
        ? `🔊 Chapter ${ch} (${voiceLabel}): saved narration loaded in ${took}${len}`
        : `🔊 Chapter ${ch} (${voiceLabel}): narrated in ${took}${len}`, 'success')
    } catch (e) {
      let picked = false
      if (isConnectionDrop(e)) {   // the phone left the app: the server is still narrating and will save it
        appendConsoleLine(`📱 Chapter ${ch}: the connection dropped while narrating; the audio will load here when the server finishes.`, 'info')
        for (let i = 0; i < 120 && !picked; i++) {
          await waitOrReturn(10000)
          try {
            const s = await api.narrateStatus(projectId, ch, voice)
            if (s.exists) {
              setAudioUrl(`${API_BASE}${s.audio_url}`)
              appendConsoleLine(`🔊 Chapter ${ch} (${voiceLabel}): narrated in ${fmtElapsed(secsSince(started))} (picked up after the connection dropped)`, 'success')
              picked = true
            }
          } catch { /* still offline */ }
        }
      }
      if (!picked) {
        appendConsoleLine(`✗ Narration failed after ${fmtElapsed(Math.round((Date.now() - started) / 1000))}: ${e.message || 'failed'}`, 'error')
        openConsole()
      }
    } finally {
      clearInterval(tick)
      setNarrating(false)
      clearConsoleRunning()
    }
  }

  useEffect(() => {
    api.listGenerated(projectId)
      .then(r => {
        setChapters(r.chapters || [])
        if (r.chapters?.length > 0 && !selected) {
          // Restore the chapter that was open before a refresh (F5 / Safari
          // pull-to-refresh on iPhone) — fall back to the first chapter.
          let restore = null
          try { restore = Number(localStorage.getItem(`nm-reader-ch:${projectId}`)) || null } catch {}
          const nums = r.chapters.map(c => c.number)
          loadChapter(restore && nums.includes(restore) ? restore : r.chapters[0].number)
        }
      })
      .catch(() => setChapters([]))
  }, [projectId])

  async function loadChapter(num) {
    setSelected(num)
    try { localStorage.setItem(`nm-reader-ch:${projectId}`, String(num)) } catch {}
    setLoading(true)
    setError('')
    setInfluences([])
    setShowInfluences(false)
    setActiveInf(null)
    setViewingV(null)
    setVersionText('')
    setAudioUrl(null)
    try {
      const [chRes, infRes, verRes, narRes] = await Promise.all([
        api.getGenerated(projectId, num),
        api.getInfluences(projectId, num).catch(() => ({ influences: [] })),
        api.chapterVersions(projectId, num).catch(() => ({ versions: [] })),
        // Already-narrated chapters keep their audio saved on disk — restore
        // it here instead of showing nothing until Narrate is clicked again.
        api.narrateStatus(projectId, num, voice).catch(() => ({ exists: false })),
      ])
      setText(chRes.text || '')
      setInfluences(infRes.influences || [])
      setVersions(verRes.versions || [])
      if (narRes.exists) setAudioUrl(`${API_BASE}${narRes.audio_url}`)
    } catch (e) {
      setError(e.message)
      setText('')
      setVersions([])
    } finally {
      setLoading(false)
    }
  }

  // Permanently deletes this chapter's archived versions (the current text is kept).
  async function clearVersions() {
    if (!selected || !versions.length) return
    if (!window.confirm(`Delete all ${versions.length} older version${versions.length === 1 ? '' : 's'} of chapter ${selected}? The current text stays. This cannot be undone.`)) return
    try {
      const r = await api.clearChapterVersions(projectId, selected)
      setVersions([])
      setViewingV(null)
      setVersionText('')
      appendConsoleLine(`🗑 Chapter ${selected}: cleared ${r.removed} old version${r.removed === 1 ? '' : 's'}`, 'success')
    } catch (e) {
      appendConsoleLine(`✗ Could not clear versions: ${e.message || 'failed'}`, 'error')
      openConsole()
    }
  }

  async function viewVersion(v) {
    if (v === null || v === 'current') { setViewingV(null); setVersionText(''); return }
    try {
      const r = await api.chapterVersion(projectId, selected, v)
      setViewingV(v)
      setVersionText(r.text || '')
    } catch (e) { setError(e.message) }
  }

  async function restoreVersion() {
    if (viewingV == null) return
    try {
      await api.restoreChapterVersion(projectId, selected, viewingV)
      api.logMemory(projectId, `Chapter ${selected} version restored`,
        `Restored v${viewingV} as the current text (previous current archived).`).catch(() => {})
      await loadChapter(selected)   // reload current + refreshed version list
    } catch (e) { setError(e.message) }
  }

  async function applyPatch(patch, note = null) {
    if (!patch?.old_text || !patch?.new_text || !selected) return
    // record the applied edit (+ the chat's critique) in the project memory log
    const logEdit = (ch) => api.logMemory(
      projectId, `Chapter ${ch} edited via chapter chat`,
      (note ? `Critique/reason: ${String(note).slice(0, 400)}\n` : '') +
      `Replaced: “${patch.old_text.slice(0, 180)}”\nWith: “${patch.new_text.slice(0, 180)}”`,
    ).catch(() => {})

    // Build a map from collapsed-whitespace index → original index
    // so we can do whitespace-insensitive search and map back precisely
    function collapseWS(s) {
      // normalise \r\n, smart quotes, then collapse whitespace runs
      return s
        .replace(/\r\n/g, '\n')
        .replace(/[‘’]/g, "'")
        .replace(/[“”]/g, '"')
        .replace(/[^\S\n]+/g, ' ')
        .trim()
    }

    // Build index map: collapsedIdx → originalIdx
    function buildMap(s) {
      const map = []
      let prevWS = false
      for (let i = 0; i < s.length; i++) {
        const ch = s[i]
        const isWS = ch !== '\n' && /\s/.test(ch)
        if (isWS && prevWS) continue  // skip extra whitespace
        map.push(i)
        prevWS = isWS
      }
      return map
    }

    function fuzzyFind(haystack, needle) {
      const normH = collapseWS(haystack)
      const normN = collapseWS(needle)
      const pos = normH.indexOf(normN)
      if (pos === -1) return null
      const map = buildMap(haystack.replace(/\r\n/g, '\n').replace(/[‘’]/g, "'").replace(/[“”]/g, '"'))
      const start = map[pos]
      const end   = map[Math.min(pos + normN.length, map.length - 1)]
      // end should cover the full matched region — walk to end of last matched char
      const rawH = haystack.replace(/\r\n/g, '\n').replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
      // Find true end: advance from end until we've consumed normN.length non-collapsed chars
      let consumed = 0, ei = map[pos]
      let prevW = false
      while (consumed < normN.length && ei < rawH.length) {
        const ch = rawH[ei]
        const isWS = ch !== '\n' && /\s/.test(ch)
        if (!(isWS && prevW)) consumed++
        prevW = isWS
        ei++
      }
      return { start, end: ei }
    }

    const raw = text.replace(/\r\n/g, '\n')

    // 1. Exact match
    let start = raw.indexOf(patch.old_text.replace(/\r\n/g, '\n'))
    if (start !== -1) {
      const end = start + patch.old_text.replace(/\r\n/g, '\n').length
      const newText = raw.slice(0, start) + patch.new_text + raw.slice(end)
      setText(newText)
      await api.saveGenerated(projectId, selected, newText)
      logEdit(selected)
      return
    }

    // 2. Fuzzy whitespace + smart-quote normalised match
    const match = fuzzyFind(raw, patch.old_text)
    if (match) {
      const newText = raw.slice(0, match.start) + patch.new_text + raw.slice(match.end)
      setText(newText)
      await api.saveGenerated(projectId, selected, newText)
      logEdit(selected)
      return
    }

    // 3. First-sentence anchor — match just the first sentence of old_text in case AI added extra
    const firstSentence = patch.old_text.split(/(?<=[.!?])\s+/)[0]?.trim()
    if (firstSentence && firstSentence.length > 20) {
      const m2 = fuzzyFind(raw, firstSentence)
      if (m2) {
        const newText = raw.slice(0, m2.start) + patch.new_text + raw.slice(m2.end)
        setText(newText)
        await api.saveGenerated(projectId, selected, newText)
        logEdit(selected)
        return
      }
    }

    // 4. Fall back to backend — search ALL chapters on disk
    try {
      const res = await api.applyPatch(projectId, patch.old_text, patch.new_text, note)
      if (res.ok) {
        // If the patch landed in the currently open chapter, reload it
        if (res.chapter === selected) {
          const fresh = await api.getGenerated(projectId, selected)
          setText(fresh.text || '')
        }
        alert(`✓ Applied to Chapter ${res.chapter}`)
        return
      }
    } catch (e) {
      // 404 means not found anywhere
    }

    alert('Could not locate that passage in any chapter. Try asking the AI to quote a shorter, more specific sentence.')
  }

  async function runRevise() {
    setRevising(true)
    setReviseResult(null)
    setShowRevise(true)
    try {
      const res = await api.reviseChapters(projectId, null, reviseNote.trim() || null)
      setReviseResult(res)
      // Reload current chapter if it was patched
      if (selected && res.patches?.some(p => p.chapter === selected)) {
        await loadChapter(selected)
      }
      // Refresh chapter list
      const r = await api.listGenerated(projectId)
      setChapters(r.chapters || [])
    } catch (e) {
      setReviseResult({ error: e.message })
    } finally {
      setRevising(false)
    }
  }

  const [chapterPickerOpen, setChapterPickerOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const wordCount = text ? text.trim().split(/\s+/).filter(Boolean).length : 0
  const [copied, setCopied] = useState(false)

  async function handleDeleteChapter() {
    if (!selected) return
    setDeleting(true)
    try {
      await api.deleteGenerated(projectId, selected)
      // Refresh chapter list
      const r = await api.listGenerated(projectId)
      setChapters(r.chapters || [])
      setText('')
      setSelected(null)
    } catch (e) {
      console.error(e)
    } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  async function copyChapter() {
    if (!text) return
    const ok = await copyTextToClipboard(text, () => {
      appendConsoleLine('✗ Copy failed — your browser blocked clipboard access (common when accessing this app over LAN from a phone/other device rather than localhost). Try selecting the text manually.', 'error')
      openConsole()
    })
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  function openReaderWindow() {
    if (!text) return
    const wc = text.trim().split(/\s+/).filter(Boolean).length
    // chapter navigation data for the pop-out (prev/next + dropdown)
    const nums = chapters.map(c => c.number)
    const chapterOptions = nums.map(n =>
      `<option value="${n}"${n === selected ? ' selected' : ''}>Chapter ${n}</option>`).join('')
    const apiBase = (window.location.port === '5173' || window.location.port === '5175')
      ? `http://${window.location.hostname || 'localhost'}:7432`
      : window.location.origin
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Chapter ${selected}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #f5f0e8; color: #3d2b1f; font-family: Georgia, "Times New Roman", serif; }
  .toolbar {
    position: sticky; top: 0; z-index: 10;
    padding: 10px 20px; background: #f5f0e8;
    border-bottom: 1px solid #8b691422;
    display: flex; align-items: center; justify-content: space-between; gap: 12;
  }
  .toolbar-left { font-size: 13px; font-weight: 700; color: #8b6914; display: flex; align-items: center; gap: 8px; }
  .toolbar-left #wc-label { font-size: 11px; font-weight: 400; opacity: 0.75; white-space: nowrap; }
  .toolbar-right { display: flex; gap: 8px; align-items: center; }
  .btn:disabled { opacity: 0.35; cursor: default; }
  select.btn { appearance: auto; max-width: 150px; }
  .theme-dot {
    width: 22px; height: 22px; border-radius: 50%; cursor: pointer; border: 2px solid #ccc;
    flex-shrink: 0; appearance: none;
  }
  .theme-dot.active { border-color: currentColor; }
  .btn {
    padding: 5px 12px; font-size: 12px; font-weight: 600; border-radius: 6px;
    cursor: pointer; font-family: inherit;
    background: #8b691422; color: #8b6914; border: 1px solid #8b691444;
    transition: all 0.2s;
  }
  .btn:hover { filter: brightness(0.9); }
  body.white .btn { background: #55555522; color: #555; border-color: #55555544; }
  body.dark .btn { background: #9d6cf722; color: #9d6cf7; border-color: #9d6cf744; }

  /* ── Voice player bar ── */
  #player {
    position: sticky; top: 53px; z-index: 9;
    display: flex; flex-direction: column;
    background: #1c2333; border-bottom: 1px solid #2a3a50;
    font-family: system-ui, sans-serif;
  }
  #player-row1 { display: flex; align-items: center; gap: 10px; padding: 8px 16px; }
  #play-btn {
    width: 46px; height: 46px; border-radius: 50%; flex-shrink: 0;
    background: linear-gradient(135deg,#06b6d4,#3b82f6);
    border: none; color: #fff; font-size: 20px;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; box-shadow: 0 0 16px rgba(6,182,212,0.5);
    transition: all 0.2s;
  }
  #play-btn.playing { background: linear-gradient(135deg,#f59e0b,#ef4444); box-shadow: 0 0 16px rgba(239,68,68,0.5); }
  #stop-btn {
    width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
    background: transparent; border: 1px solid #2a3a50; color: #475569;
    font-size: 13px; display: flex; align-items: center; justify-content: center;
    cursor: pointer; transition: all 0.2s;
  }
  #stop-btn.active { background: #2a3a50; color: #94a3b8; border-color: #3a4a60; }
  #player-status { flex: 1; }
  #player-status-title { font-size: 13px; font-weight: 700; color: #e2e8f0; }
  #player-status-title.playing { color: #06b6d4; }
  #player-status-sub { font-size: 10px; color: #64748b; margin-top: 2px; }
  #voice-btn {
    flex-shrink: 0; padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600;
    background: #1e3347; border: 1px solid #2a3a50; color: #94a3b8; cursor: pointer;
  }
  #voice-btn.open { background: #0e4f6b; border-color: #06b6d4; color: #06b6d4; }
  #speed-row { display: flex; border-top: 1px solid #1e2d40; }
  #speed-label { display:flex; align-items:center; padding: 0 10px; font-size: 9px; color: #475569; font-weight: 700; letter-spacing: 0.1em; flex-shrink:0; }
  .spd {
    flex: 1; padding: 6px 0; font-size: 12px; font-weight: 400;
    background: transparent; border: none; border-left: 1px solid #1e2d40;
    color: #64748b; cursor: pointer; transition: all 0.15s;
  }
  .spd.active { background: #0e4f6b; color: #06b6d4; font-weight: 700; }
  #voice-panel { display: none; padding: 10px 16px 12px; border-top: 1px solid #1e2d40; }
  #voice-panel.open { display: block; }
  #voice-panel-label { font-size: 9px; color: #64748b; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
  #voice-list { display: flex; flex-wrap: wrap; gap: 6px; }
  .vbtn {
    padding: 4px 10px; border-radius: 6px; font-size: 11px;
    background: #1e3347; border: 1px solid #2a3a50; color: #94a3b8; cursor: pointer;
  }
  .vbtn.active { background: #0e4f6b; border-color: #06b6d4; color: #06b6d4; }

  /* Sentence highlight during reading */
  .reading-hl { background: rgba(6,182,212,0.22); border-radius: 3px; outline: 1px solid rgba(6,182,212,0.4); }

  .content {
    max-width: 680px; margin: 0 auto; padding: 32px 24px 80px;
    font-size: 17px; line-height: 1.9; white-space: pre-wrap;
  }
  /* inner monologue (*...*) rendered as tinted italics per theme */
  em.inner { font-style: italic; }
  body.sepia em.inner { color: #7a5c10; }
  body.white em.inner { color: #4a4a8a; }
  body.dark  em.inner { color: #b79df7; }
  .chapter-title { font-size: 22px; font-weight: 700; margin-bottom: 28px; color: #8b6914; }
  body.white { background: #fff; color: #1a1a1a; }
  body.white .toolbar { background: #fff; border-color: #55555522; }
  body.white .toolbar-left { color: #555; }
  body.white .chapter-title { color: #555; }
  body.dark { background: #1a1a2e; color: #d4d0c8; }
  body.dark .toolbar { background: #1a1a2e; border-color: #9d6cf722; }
  body.dark .toolbar-left { color: #9d6cf7; }
  body.dark .chapter-title { color: #9d6cf7; }
  @media (max-width: 600px) { .content { font-size: 16px; padding: 20px 14px 60px; } }
</style>
</head>
<body class="sepia">
<div class="toolbar">
  <div class="toolbar-left">
    <button class="btn" id="prev-btn" onclick="nav(-1)" title="Previous chapter">‹ Prev</button>
    <select id="ch-select" class="btn" onchange="loadChapterN(Number(this.value))">${chapterOptions}</select>
    <button class="btn" id="next-btn" onclick="nav(1)" title="Next chapter">Next ›</button>
    <span id="wc-label">${wc.toLocaleString()} words</span>
  </div>
  <div class="toolbar-right">
    <button class="theme-dot active" style="background:#f5f0e8" title="Sepia" onclick="setTheme('sepia',this)"></button>
    <button class="theme-dot" style="background:#ffffff" title="White" onclick="setTheme('white',this)"></button>
    <button class="theme-dot" style="background:#1a1a2e" title="Dark" onclick="setTheme('dark',this)"></button>
    <button class="btn" onclick="copyText()">⎘ Copy</button>
    <button class="btn" onclick="window.close()">✕ Close</button>
  </div>
</div>

<!-- Voice player bar -->
<div id="player">
  <div id="player-row1">
    <button id="play-btn" onclick="togglePlay()">▶</button>
    <button id="stop-btn" onclick="stopReading()">■</button>
    <div id="player-status">
      <div id="player-status-title">🔊 Voice Reader</div>
      <div id="player-status-sub">Press ▶ to listen to this chapter</div>
    </div>
    <button id="voice-btn" onclick="toggleVoicePanel()">🎙 Voice</button>
  </div>
  <div id="speed-row">
    <div id="speed-label">SPEED</div>
    <button class="spd" onclick="setSpeed(0.75)">0.75×</button>
    <button class="spd active" onclick="setSpeed(1)">1×</button>
    <button class="spd" onclick="setSpeed(1.25)">1.25×</button>
    <button class="spd" onclick="setSpeed(1.5)">1.5×</button>
    <button class="spd" onclick="setSpeed(2)">2×</button>
  </div>
  <div id="voice-panel">
    <div id="voice-panel-label">Select Voice</div>
    <div id="voice-list"></div>
  </div>
</div>

<div class="content">
  <div class="chapter-title" id="ch-title">Chapter ${selected}</div>
  <div id="body-text"></div>
</div>
<script>
  // ── Text ──
  let FULL_TEXT = ${JSON.stringify(text)};
  // *asterisk spans* (inner monologue / emphasis) render as tinted italics
  function renderBody(t) {
    const esc = t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return esc.replace(/\\*([^*\\n]+)\\*/g, '<em class="inner">$1</em>');
  }
  document.getElementById('body-text').innerHTML = renderBody(FULL_TEXT);

  // ── Chapter navigation (prev / next / dropdown, ← → keys) ──
  const CHAPTERS = ${JSON.stringify(nums)};
  const PROJECT = ${JSON.stringify(projectId)};
  const API = ${JSON.stringify(apiBase)};
  let CURRENT = ${JSON.stringify(selected)};
  function updateNavBtns() {
    const i = CHAPTERS.indexOf(CURRENT);
    document.getElementById('prev-btn').disabled = i <= 0;
    document.getElementById('next-btn').disabled = i >= CHAPTERS.length - 1;
  }
  async function loadChapterN(n) {
    if (CHAPTERS.indexOf(n) === -1 || n === CURRENT) return;
    stopReading();
    let d = null;
    try {
      const r = await fetch(API + '/api/engines/generated/' + PROJECT + '/' + n);
      d = await r.json();
    } catch (e) {}
    if (!d || typeof d.text !== 'string') { alert('Could not load chapter ' + n); return; }
    CURRENT = n;
    FULL_TEXT = d.text;
    sentences = []; sentIdx = 0;
    document.getElementById('body-text').innerHTML = renderBody(FULL_TEXT);
    document.getElementById('ch-title').textContent = 'Chapter ' + n;
    document.title = 'Chapter ' + n;
    const wcn = FULL_TEXT.trim().split(/\\s+/).filter(Boolean).length;
    document.getElementById('wc-label').textContent = wcn.toLocaleString() + ' words';
    document.getElementById('ch-select').value = String(n);
    updateNavBtns();
    window.scrollTo(0, 0);
  }
  function nav(d) {
    const i = CHAPTERS.indexOf(CURRENT);
    const n = CHAPTERS[i + d];
    if (n !== undefined) loadChapterN(n);
  }
  document.addEventListener('keydown', (e) => {
    if (e.target && (e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT')) return;
    if (e.key === 'ArrowRight') nav(1);
    if (e.key === 'ArrowLeft') nav(-1);
  });
  updateNavBtns();

  // ── Theme ──
  function setTheme(t, el) {
    document.body.className = t;
    document.querySelectorAll('.theme-dot').forEach(d => d.classList.remove('active'));
    el.classList.add('active');
  }
  function copyText() {
    const btn = event.target;
    function ok() { btn.textContent = '✓ Copied'; setTimeout(() => btn.textContent = '⎘ Copy', 2000); }
    function fallback() {
      // Same reasoning as the parent app's copyTextToClipboard helper — this
      // popped-out reader window shares the parent tab's origin/security
      // context, so navigator.clipboard is just as unavailable here when
      // accessed over LAN from another device rather than localhost.
      try {
        const ta = document.createElement('textarea');
        ta.value = FULL_TEXT; ta.style.position = 'fixed'; ta.style.opacity = '0'; ta.style.left = '-9999px';
        document.body.appendChild(ta); ta.focus(); ta.select();
        const success = document.execCommand('copy');
        document.body.removeChild(ta);
        if (success) { ok(); return; }
      } catch (e) {}
      btn.textContent = '✗ Copy blocked'; setTimeout(() => btn.textContent = '⎘ Copy', 2500);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(FULL_TEXT).then(ok).catch(fallback);
    } else {
      fallback();
    }
  }

  // ── Voice Reader ──
  let voices = [], voiceIdx = 0, speed = 1, isPlaying = false, sentences = [], sentIdx = 0;
  const synth = window.speechSynthesis;

  function loadVoices() {
    const all = synth.getVoices();
    if (!all.length) return;
    // Human names only — Neural/natural sounding voices
    const humanNames = ['Aria','Jenny','Guy','Ana','Christopher','Eric','Michelle','Roger','Steffan',
      'Sonia','Ryan','Libby','Mia','Natasha','William','James','Julia','Davis',
      'Samantha','Karen','Daniel','Moira','Kate','Serena','Rishi','Veena',
      'Alex','Allison','Ava','Joanna','Matthew','Brian','Amy','Emma','Ivy'];
    const badKeywords = ['eSpeak','Compact','Fred','Whisper','Trinoids','Hysterical','Bahh','Boing',
      'Bubbles','Cellos','Deranged','Good News','Jester','Organ','Ralph','Bells',
      'Wobble','Zarvox','Pipe Organ','Bad News','Kathy','Princess','Vicki'];
    const en = all.filter(v => {
      if (!v.lang.startsWith('en')) return false;
      if (badKeywords.some(k => v.name.includes(k))) return false;
      // Accept any voice with a human name OR any Microsoft/Apple voice not in bad list
      return humanNames.some(n => v.name.includes(n)) || v.name.startsWith('Microsoft') || v.name.startsWith('Apple');
    });
    // Sort: Online Natural/Neural first, Desktop second
    en.sort((a,b) => {
      const score = v => v.name.includes('Natural') ? 0 : v.name.includes('Neural') ? 1 : v.name.includes('Online') ? 2 : 3;
      return score(a) - score(b);
    });
    voices = en.length ? en : all.filter(v => v.lang.startsWith('en'));
    buildVoiceList();
  }
  synth.onvoiceschanged = loadVoices;
  loadVoices();

  function buildVoiceList() {
    const list = document.getElementById('voice-list');
    list.innerHTML = '';
    voices.forEach((v,i) => {
      const b = document.createElement('button');
      b.className = 'vbtn' + (i===voiceIdx?' active':'');
      b.textContent = v.name.replace('Microsoft ','').replace(' Online (Natural)',' ✦').replace(' Desktop','');
      b.onclick = () => { voiceIdx=i; buildVoiceList(); };
      list.appendChild(b);
    });
  }

  function splitSentences(t) {
    return t.match(/[^.!?…]+[.!?…]+['"»]?|[^.!?…]+$/g)?.map(s=>s.trim()).filter(Boolean) || [t];
  }

  function highlightSentence(idx) {
    const el = document.getElementById('body-text');
    if (idx < 0 || idx >= sentences.length) { el.innerHTML = renderBody(FULL_TEXT); return; }
    el.innerHTML = '';
    sentences.forEach((s,i) => {
      const span = document.createElement('span');
      span.textContent = s + ' ';
      if (i===idx) span.className = 'reading-hl';
      el.appendChild(span);
    });
  }

  function speakFrom(idx) {
    if (idx >= sentences.length) { stopReading(); return; }
    sentIdx = idx;
    const utt = new SpeechSynthesisUtterance(sentences[idx]);
    utt.rate = speed; utt.pitch = 1.05;
    if (voices[voiceIdx]) utt.voice = voices[voiceIdx];
    utt.onstart = () => highlightSentence(idx);
    utt.onend = () => { if (isPlaying) speakFrom(idx+1); };
    utt.onerror = e => { if (e.error!=='interrupted' && isPlaying) speakFrom(idx+1); };
    synth.speak(utt);
  }

  function togglePlay() {
    if (isPlaying) {
      synth.pause(); isPlaying = false;
      document.getElementById('play-btn').textContent = '▶';
      document.getElementById('play-btn').classList.remove('playing');
      document.getElementById('player-status-title').textContent = '⏸ Paused';
      document.getElementById('player-status-title').classList.remove('playing');
      document.getElementById('stop-btn').classList.add('active');
    } else if (synth.paused) {
      synth.resume(); isPlaying = true;
      document.getElementById('play-btn').textContent = '⏸';
      document.getElementById('play-btn').classList.add('playing');
      document.getElementById('player-status-title').textContent = '▸ Reading aloud…';
      document.getElementById('player-status-title').classList.add('playing');
    } else {
      synth.cancel();
      sentences = splitSentences(FULL_TEXT);
      isPlaying = true;
      document.getElementById('play-btn').textContent = '⏸';
      document.getElementById('play-btn').classList.add('playing');
      document.getElementById('player-status-title').textContent = '▸ Reading aloud…';
      document.getElementById('player-status-title').classList.add('playing');
      document.getElementById('player-status-sub').textContent = '';
      document.getElementById('stop-btn').classList.add('active');
      speakFrom(0);
    }
  }

  function stopReading() {
    synth.cancel(); isPlaying = false; sentIdx = 0;
    document.getElementById('play-btn').textContent = '▶';
    document.getElementById('play-btn').classList.remove('playing');
    document.getElementById('player-status-title').textContent = '🔊 Voice Reader';
    document.getElementById('player-status-title').classList.remove('playing');
    document.getElementById('player-status-sub').textContent = 'Press ▶ to listen to this chapter';
    document.getElementById('stop-btn').classList.remove('active');
    document.getElementById('body-text').innerHTML = renderBody(FULL_TEXT);
  }

  function setSpeed(s) {
    speed = s;
    document.querySelectorAll('.spd').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
  }

  function toggleVoicePanel() {
    const p = document.getElementById('voice-panel');
    const b = document.getElementById('voice-btn');
    p.classList.toggle('open'); b.classList.toggle('open');
  }

  window.addEventListener('beforeunload', () => synth.cancel());
</script>
</body>
</html>`
    const win = window.open('', '_blank', 'width=900,height=700,scrollbars=yes,resizable=yes')
    if (win) {
      win.document.open()
      win.document.write(html)
      win.document.close()
    }
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {activeInf && <InfluenceCard inf={activeInf} onClose={() => setActiveInf(null)} />}

      {/* Mobile chapter picker bar */}
      <div className="mobile-only" style={{
        padding: '8px 12px', borderBottom: '1px solid var(--border-soft)',
        background: 'var(--bg-surface)', flexShrink: 0, position: 'relative',
      }}>
        <button onClick={() => setChapterPickerOpen(o => !o)} style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px', borderRadius: 'var(--radius-sm)',
          background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          fontSize: 12, color: 'var(--text-primary)',
        }}>
          <span>{selected ? `Chapter ${selected}` : 'Select a chapter…'}</span>
          <span style={{ color: 'var(--text-muted)' }}>{chapterPickerOpen ? '▲' : '▼'}</span>
        </button>
        {chapterPickerOpen && (
          <div style={{
            position: 'absolute', zIndex: 100, left: 12, right: 12, top: '100%', marginTop: 2,
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            maxHeight: 260, overflowY: 'auto',
          }}>
            {chapters.length === 0 && (
              <div style={{ padding: '12px 14px', fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                No chapters yet. Generate one in the Generate tab.
              </div>
            )}
            {chapters.map(ch => (
              <button key={ch.number} onClick={() => { loadChapter(ch.number); setChapterPickerOpen(false) }} style={{
                width: '100%', textAlign: 'left', padding: '10px 14px',
                borderBottom: '1px solid var(--border-soft)', fontSize: 12,
                color: selected === ch.number ? 'var(--accent-light)' : 'var(--text-primary)',
                background: selected === ch.number ? 'var(--accent-dim)' : 'transparent',
              }}>
                Chapter {ch.number}
                <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 8 }}>
                  ~{Math.round(ch.size / 5)} words
                  {ch.has_influences && <span style={{ color: 'var(--accent-light)', marginLeft: 4 }}>✦</span>}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Main layout: chapter list | reader | chat */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>

        {/* Desktop chapter list sidebar */}
        <div className="desktop-only" style={{
          width: 160, flexShrink: 0, borderRight: '1px solid var(--border-soft)',
          overflowY: 'auto', padding: '12px 8px',
          display: 'flex', flexDirection: 'column', gap: 4,
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '0 8px 8px' }}>
            Chapters
          </div>
          {chapters.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '8px', fontStyle: 'italic' }}>No chapters yet.</div>
          )}
          {chapters.map(ch => (
            <button key={ch.number} onClick={() => loadChapter(ch.number)} style={{
              textAlign: 'left', padding: '7px 10px', borderRadius: 'var(--radius-sm)',
              background: selected === ch.number ? 'var(--accent-dim)' : 'transparent',
              color: selected === ch.number ? 'var(--accent-light)' : 'var(--text-secondary)',
              border: selected === ch.number ? '1px solid var(--accent)' : '1px solid transparent',
              fontSize: 11, fontWeight: selected === ch.number ? 600 : 400,
            }}>
              Ch {ch.number}
              <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>
                ~{Math.round(ch.size / 5)}w
                {ch.has_influences && <span style={{ color: 'var(--accent-light)', marginLeft: 4 }}>✦</span>}
              </div>
            </button>
          ))}
        </div>

        {/* Reader pane — shrinks when chat is open on desktop */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 'clamp(10px, 3vw, 20px)', display: 'flex', flexDirection: 'column', minWidth: 0 }}>

          {/* toolbar */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
            {/* Row 1: title */}
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-secondary)' }}>
              {selected
                ? <>Chapter {selected} <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>~{wordCount.toLocaleString()} words</span></>
                : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Select a chapter</span>
              }
            </div>
            {/* Row 2: action buttons — always wrap so nothing hides */}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              {selected && text && (
                <>
                  <button onClick={openReaderWindow} style={{
                    fontSize: 11, padding: '4px 10px', fontWeight: 600,
                    background: 'linear-gradient(135deg,#f5f0e8,#e8dcc8)',
                    border: '1px solid #c8a96e', borderRadius: 'var(--radius-sm)',
                    color: '#6b4c11', whiteSpace: 'nowrap',
                  }}>☰ Reader</button>
                  <button onClick={copyChapter} style={{
                    fontSize: 11, padding: '4px 10px', fontWeight: 600,
                    background: copied ? 'var(--green-dim)' : 'var(--bg-elevated)',
                    border: `1px solid ${copied ? 'var(--green)' : 'var(--border)'}`,
                    borderRadius: 'var(--radius-sm)',
                    color: copied ? 'var(--green)' : 'var(--text-secondary)',
                    transition: 'all 0.2s', whiteSpace: 'nowrap',
                  }}>{copied ? '✓ Copied' : '⎘ Copy'}</button>
                  <ExportMenu projectId={projectId} manuscriptOnly label="⤓ Manuscript" />
                  {confirmDelete ? (
                    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Delete?</span>
                      <button onClick={handleDeleteChapter} disabled={deleting} style={{
                        fontSize: 11, padding: '3px 8px', fontWeight: 600, borderRadius: 'var(--radius-sm)',
                        background: 'var(--red)', color: '#fff', border: 'none',
                      }}>{deleting ? '…' : 'Delete'}</button>
                      <button onClick={() => setConfirmDelete(false)} style={{
                        fontSize: 11, padding: '3px 7px', borderRadius: 'var(--radius-sm)',
                        background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)',
                      }}>✕</button>
                    </div>
                  ) : (
                    <button onClick={() => setConfirmDelete(true)} style={{
                      fontSize: 11, padding: '4px 8px', fontWeight: 600,
                      background: 'var(--red-dim)', border: '1px solid var(--red)',
                      borderRadius: 'var(--radius-sm)', color: 'var(--red)',
                    }}>🗑</button>
                  )}
                </>
              )}
              {influences.length > 0 && (
                <button onClick={() => setShowInfluences(s => !s)} style={{
                  fontSize: 11, padding: '4px 8px', fontWeight: 600,
                  background: showInfluences ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: `1px solid ${showInfluences ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius-sm)',
                  color: showInfluences ? 'var(--accent-light)' : 'var(--text-secondary)',
                }}>✦ {influences.length}</button>
              )}
              {selected && (
                <button onClick={() => onEdit && onEdit(selected)} style={{
                  fontSize: 11, padding: '4px 10px', fontWeight: 600,
                  background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
                }}>✏ Edit</button>
              )}
              {selected && (
                <select value={voice} onChange={e => changeVoice(e.target.value)} disabled={narrating}
                  title="Narration voice"
                  style={{
                    fontSize: 11, padding: '4px 6px', fontWeight: 600,
                    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
                  }}>
                  {TTS_GROUPS.map(g => (
                    <optgroup key={g} label={g}>
                      {TTS_VOICES.filter(v => v.group === g).map(v => <option key={v.id} value={v.id}>{v.label}</option>)}
                    </optgroup>
                  ))}
                </select>
              )}
              {selected && !audioUrl && (
                <button onClick={narrate} disabled={narrating}
                  title={voice.startsWith('Kokoro.') ? 'Read this chapter aloud (local Kokoro voice, about 4 minutes per chapter)' : 'Read this chapter aloud (NVIDIA Magpie TTS)'}
                  style={{
                    fontSize: 11, padding: '4px 10px', fontWeight: 600,
                    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
                    opacity: narrating ? 0.6 : 1,
                  }}>{narrating ? `⏱ ${fmtElapsed(narrateSecs)}` : '🔊 Narrate'}</button>
              )}
              {selected && versions.length > 0 && (
                <select value={viewingV == null ? 'current' : String(viewingV)}
                  onChange={e => viewVersion(e.target.value === 'current' ? null : Number(e.target.value))}
                  title="Older versions of this chapter (archived on regenerate)"
                  style={{
                    fontSize: 11, padding: '4px 8px', fontWeight: 600,
                    background: viewingV != null ? 'var(--amber-dim, rgba(251,191,36,0.15))' : 'var(--bg-elevated)',
                    border: `1px solid ${viewingV != null ? 'var(--amber, #fbbf24)' : 'var(--border)'}`,
                    borderRadius: 'var(--radius-sm)',
                    color: viewingV != null ? 'var(--amber, #fbbf24)' : 'var(--text-secondary)',
                  }}>
                  <option value="current">Current (v{versions.length + 1})</option>
                  {versions.map(v => (
                    <option key={v.v} value={v.v}>v{v.v} · {v.modified} · ~{v.words.toLocaleString()}w</option>
                  ))}
                </select>
              )}
              {selected && versions.length > 0 && (
                <button onClick={clearVersions}
                  title="Permanently delete every older version of this chapter (the current text stays)"
                  style={{
                    fontSize: 11, padding: '4px 10px', fontWeight: 600,
                    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
                  }}>🗑 Clear old versions</button>
              )}
            </div>
            {audioUrl && (
              <div style={{ padding: '6px 0' }}>
                <audio controls src={audioUrl} style={{ width: '100%', height: 32 }} />
              </div>
            )}
            {/* viewing an archived version */}
            {viewingV != null && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                padding: '6px 10px', borderRadius: 'var(--radius-sm)',
                background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.5)',
                fontSize: 11, color: '#fbbf24',
              }}>
                <span>Viewing archived <b>v{viewingV}</b> — the current text is unchanged.</span>
                <button onClick={restoreVersion} style={{
                  fontSize: 11, padding: '3px 10px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                  background: '#fbbf24', color: '#1a1a1a', border: 'none',
                }}>↩ Restore this version</button>
                <button onClick={() => viewVersion(null)} style={{
                  fontSize: 11, padding: '3px 10px', borderRadius: 'var(--radius-sm)',
                  background: 'transparent', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.5)',
                }}>Back to current</button>
              </div>
            )}
          </div>

          {/* Influences panel */}
          {showInfluences && influences.length > 0 && (
            <div style={{
              marginBottom: 14, padding: 12, borderRadius: 'var(--radius-lg)',
              background: 'var(--bg-card)', border: '1px solid var(--accent)',
              display: 'flex', flexDirection: 'column', gap: 8,
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent-light)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Corpus Influences</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {influences.map((inf, i) => {
                  const novel = inf.novel?.replace(/_/g, ' ')?.replace(/\b\w/g, c => c.toUpperCase()) || '?'
                  const type = inf.humor_type?.replace(/_/g, ' ') || inf.type || '?'
                  return (
                    <button key={i} onClick={() => setActiveInf(inf)} style={{
                      fontSize: 10, padding: '4px 8px', borderRadius: 'var(--radius-sm)',
                      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                      color: 'var(--text-secondary)', textAlign: 'left',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--accent-light)' }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
                    >
                      <span style={{ fontWeight: 700 }}>{novel}</span>
                      <span style={{ color: 'var(--text-muted)', marginLeft: 5 }}>· {type}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {loading && <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>}
          {error && <div style={{ color: 'var(--red)', fontSize: 12 }}>{error}</div>}
          {!loading && !error && (viewingV != null ? versionText : text) && (
            <div style={{
              fontSize: 15, lineHeight: 1.85, color: 'var(--text-primary)',
              fontFamily: 'Georgia, "Times New Roman", serif',
              whiteSpace: 'pre-wrap',
              paddingBottom: 80,
              opacity: viewingV != null ? 0.92 : 1,
            }}>
              {renderProse(viewingV != null ? versionText : text, pronMarks,
                (word, say, e) => setPronPop({ word, say, x: e.clientX, y: e.clientY }))}
            </div>
          )}
          {pronPop && <PronCard pop={pronPop} voice={voice} projectId={projectId} onClose={() => setPronPop(null)} />}
          {!loading && !error && !text && selected && (
            <div style={{ color: 'var(--text-muted)', fontSize: 13, fontStyle: 'italic' }}>Chapter is empty.</div>
          )}
        </div>

      </div>
    </div>
  )
}
