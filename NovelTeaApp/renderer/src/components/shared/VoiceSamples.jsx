import { useEffect, useMemo, useRef, useState } from 'react'
import { api, API_BASE } from '../../api'
import useStore from '../../store/useStore'
import ElapsedTimer, { fmtElapsed, secsSince } from './ElapsedTimer'
import { TTS_VOICES, TTS_GROUPS } from '../../constants/ttsVoices'

// Settings → Voice Samples: each narration voice the app offers (constants/ttsVoices.js) saying the same line.
// A sample is made the first time its ▶ is pressed, then saved on the server and replayed from there.
export default function VoiceSamples() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState({})          // voice id -> Date.now() while its sample is being made
  const [done, setDone] = useState({})          // voice id -> true once a sample exists
  const [playing, setPlaying] = useState(null)
  const audio = useRef(null)
  const { appendConsoleLine } = useStore()

  useEffect(() => {
    api.ttsVoices()
      .then(d => { setData(d); setDone(Object.fromEntries([...d.nvidia, ...d.kokoro].filter(v => v.sampled).map(v => [v.id, true]))) })
      .catch(() => setData({ text: 'Welcome to NovelTea Engine.', nvidia: [], kokoro: [] }))
      .catch(e => setError(e.message || 'Could not load the voice list'))
    return () => { if (audio.current) audio.current.pause() }
  }, [])

  async function play(v) {
    if (busy[v.id]) return
    if (playing === v.id && audio.current) { audio.current.pause(); setPlaying(null); return }
    if (audio.current) audio.current.pause()
    const t0 = Date.now()
    const fresh = !done[v.id]
    if (fresh) setBusy(b => ({ ...b, [v.id]: t0 }))
    try {
      const r = await fetch(`${API_BASE}/api/generate/voice-sample?voice=${encodeURIComponent(v.id)}`)
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
      const url = URL.createObjectURL(await r.blob())
      if (fresh) appendConsoleLine(`🔊 Voice sample ${v.label}: made in ${fmtElapsed(secsSince(t0))}`, 'success')
      setDone(d => ({ ...d, [v.id]: true }))
      const a = new Audio(url)
      a.onended = () => { setPlaying(p => (p === v.id ? null : p)); URL.revokeObjectURL(url) }
      audio.current = a
      setPlaying(v.id)
      await a.play().catch(() => setPlaying(null))
    } catch (e) {
      appendConsoleLine(`✗ Voice sample ${v.label}: ${e.message}`, 'error')
    } finally {
      if (fresh) setBusy(b => { const n = { ...b }; delete n[v.id]; return n })
    }
  }

  // only the voices the app offers, in the same groups as the Reader's voice menu
  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return TTS_GROUPS.map(g => [g, TTS_VOICES.filter(v => v.group === g)
      .filter(v => !q || v.label.toLowerCase().includes(q) || g.toLowerCase().includes(q))])
      .filter(([, vs]) => vs.length)
  }, [filter])

  const total = TTS_VOICES.length
  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Voice Samples</h2>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Every narration voice{total ? ` (${total})` : ''} saying “{data?.text || 'Welcome to NovelTea Engine.'}”.
          A sample is made the first time you press ▶ (Kokoro runs on this computer and is free; NVIDIA uses your API key),
          then it is saved and replays instantly.
        </div>
      </div>
      <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter voices (e.g. British, Sofia)…"
        style={{ width: '100%', marginBottom: 14, padding: '8px 10px', fontSize: 13, background: 'var(--bg-elevated)',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)' }} />
      {error && <div style={{ color: 'var(--red)', fontSize: 12 }}>{error}</div>}
      {!data && !error && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}><ElapsedTimer /> Loading the voice list…</div>}
      {groups.map(([g, voices]) => (
        <details key={g} open style={{ marginBottom: 10 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', padding: '4px 0' }}>
            {g} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({voices.length})</span>
          </summary>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 6, marginTop: 6 }}>
            {voices.map(v => (
              <button key={v.id} onClick={() => play(v)} title={v.id}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
                  padding: '8px 10px', minHeight: 40, fontSize: 12, textAlign: 'left',
                  background: playing === v.id ? 'var(--accent-dim, rgba(124,58,237,0.15))' : 'var(--bg-elevated)',
                  border: `1px solid ${playing === v.id ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
                }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.label}</span>
                <span style={{ flexShrink: 0, fontSize: 11, color: done[v.id] ? 'var(--green)' : 'var(--text-muted)' }}>
                  {busy[v.id] ? <ElapsedTimer since={busy[v.id]} /> : playing === v.id ? '⏸' : '▶'}
                </span>
              </button>
            ))}
          </div>
        </details>
      ))}
    </>
  )
}
