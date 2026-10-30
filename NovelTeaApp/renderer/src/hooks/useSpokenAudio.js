import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { savedTtsVoice } from '../constants/ttsVoices'
import useStore from '../store/useStore'

// The text read aloud for an interview question: the question, then each option's label, description and source.
export function interviewText(question, options) {
  if (!question) return ''
  const opts = (options || []).map((o, i) => {
    const bits = [`Option ${i + 1}: ${o.label}.`]
    if (o.description) bits.push(o.description)
    if (o.evidence) bits.push(`Source: ${o.evidence}`)
    return bits.join(' ')
  }).join(' ')
  return `${question} ${opts}`
}

// One shared audio player for every interview. Phones (iOS Safari especially) only let a page play sound it
// starts without a tap if the same <audio> element was first played from a tap; the first tap anywhere plays a
// silent clip on it, after which new questions can read themselves.
const SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA='
let player = null
function getPlayer() {
  if (!player && typeof Audio !== 'undefined') player = new Audio()
  return player
}
if (typeof window !== 'undefined') {
  const unlock = () => {
    const a = getPlayer()
    if (a && !a.src) {
      a.src = SILENT
      a.play().catch(() => {}).finally(() => { try { a.pause() } catch { /* fine */ } })
    }
    window.removeEventListener('pointerdown', unlock)
    window.removeEventListener('keydown', unlock)
  }
  window.addEventListener('pointerdown', unlock)
  window.addEventListener('keydown', unlock)
}

// Reads `text` aloud with the chosen narration voice (NVIDIA or local Kokoro) as soon as a new question arrives,
// and keeps the audio. The button is then a Play / Pause button that replays the saved audio without calling
// the voice service again. The audio is dropped when the text changes (a new question).
// If the browser still refuses to start sound on its own, the status is 'ready' and the Play button starts it.
//   status: 'idle' (nothing yet) | 'loading' (waiting for the voice service) | 'ready' (received, Play) | 'playing' (Pause)
export default function useSpokenAudio(text, onError, { autoPlay = true, onReady = null } = {}) {
  const [status, setStatus] = useState('idle')
  const [since, setSince] = useState(0)            // when the current voice request started (for the timer)
  const ready = useRef(onReady)
  ready.current = onReady
  const saved = useRef({ text: null, url: null })
  const run = useRef(0)
  const forText = useRef(null)                      // the text the audio is being fetched for, or already saved for
  const onErr = useRef(onError)
  onErr.current = onError

  const mine = () => { const a = getPlayer(); return a && saved.current.url && a.src === saved.current.url }

  const release = useCallback(() => {
    run.current++                                   // an answer still on its way for the old text is ignored
    if (mine()) { try { getPlayer().pause() } catch { /* already stopped */ } }
    if (saved.current.url) URL.revokeObjectURL(saved.current.url)
    saved.current = { text: null, url: null }
    forText.current = null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const play = useCallback(async (url) => {
    const a = getPlayer()
    if (!a) return
    if (a.src !== url) { a.pause(); a.src = url }
    a.onended = () => { if (a.src === url) setStatus('ready') }
    a.onpause = () => { if (a.src === url && !a.ended) setStatus('ready') }
    if (a.ended) a.currentTime = 0
    try { await a.play(); setStatus('playing') } catch { setStatus('ready') }   // still blocked: the Play button starts it
  }, [])

  const fetchAndPlay = useCallback(async (forThis) => {
    const r0 = ++run.current
    forText.current = forThis
    const t0 = Date.now()
    setSince(t0)
    setStatus('loading')
    try {
      const r = await api.speak(forThis, savedTtsVoice(), useStore.getState().activeProjectId)
      if (r0 !== run.current) return
      const bin = atob(r.audio_b64)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
      saved.current = { text: forThis, url }
      if (ready.current) ready.current(Math.round((Date.now() - t0) / 1000))
      await play(url)
    } catch (e) {
      if (r0 === run.current) { setStatus('idle'); if (onErr.current) onErr.current(e) }
    }
  }, [play])

  // A new question: drop the old audio, and read the new one straight away.
  useEffect(() => {
    if (forText.current !== null && forText.current !== text) { release(); setStatus('idle') }
    if (autoPlay && text && forText.current !== text) fetchAndPlay(text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, autoPlay])
  useEffect(() => () => release(), [release])

  const toggle = useCallback(async () => {
    if (!text || status === 'loading') return
    if (status === 'playing') { if (mine()) getPlayer().pause(); setStatus('ready'); return }
    if (saved.current.text === text && saved.current.url) { await play(saved.current.url); return }
    await fetchAndPlay(text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, status, play, fetchAndPlay])

  return { status, toggle, since }
}

export function speechLabel(status) {
  return status === 'playing' ? '⏸ Pause' : status === 'ready' ? '▶ Play' : status === 'loading' ? '🔊 Reading…' : '🔊 Read'
}

export function speechTitle(status) {
  return status === 'playing' ? 'Pause the reading'
    : status === 'ready' ? 'Play the saved reading again (no new voice request)'
    : status === 'loading' ? 'Getting the voice…' : 'Read this question and its options aloud'
}
