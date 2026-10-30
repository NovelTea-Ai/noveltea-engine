import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api'
import { TTS_VOICES, TTS_GROUPS, savedTtsVoice } from '../../constants/ttsVoices'

// Corpus Reader: a library of the corpus novels (three cards across) and a chapter reading page. Everything loads from the app's own
// address with relative URLs, so over the Tailscale https address it is https end to end.
//
// The reading page uses a plain reader layout: an "ink" shell, one paper card
// (960px max, 16px corners, full width on a phone), a header with the title and the size / font pills, the story in a 180% line-height
// column, a floating icon rail on the right, a prev / title / next pill top right, and a bottom bar on phones. Tapping the text shows or
// hides the floating controls. Colours and sizes are the site's own values; the web fonts it loads are not bundled, so each font falls
// back to the next one in its stack.

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v) } catch { return d } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} },
}

function hue(s) { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 360; return h }
const initials = t => String(t).split(/\s+/).filter(Boolean).slice(0, 3).map(w => w[0]).join('').toUpperCase()

// the site's reader fonts, in its order
const FONTS = [
  ['Inter', 'Inter, sans-serif'], ['Source Sans', '"Source Sans 3", "Source Sans Pro", sans-serif'], ['Segoe UI', '"Segoe UI", sans-serif'],
  ['Roboto', '"Roboto", sans-serif'], ['Nunito Sans', '"Nunito Sans", sans-serif'], ['Verdana', 'Verdana, sans-serif'],
  ['Tahoma', 'Tahoma, sans-serif'], ['Arial', 'Arial, sans-serif'], ['Palatino Linotype', '"Palatino Linotype", Palatino, serif'],
  ['Noticia Text', '"Noticia Text", Georgia, serif'], ['Times New Roman', '"Times New Roman", serif'], ['Patrick Hand', '"Patrick Hand", cursive'],
]
const SIZES = [['A', 12, 16], ['A', 13, 18], ['A', 14, 21]]     // pill label size, reading size

// "ink" palette + the paper colours of the site's dark reader
const INK = {
  '--color-bg': '#14120e', '--color-bg1': '#1a1712', '--color-bg-elevated': '#201c15', '--color-bg-subtle': '#262019',
  '--color-bg-strong': '#332b1f', '--color-border': '#2b2820', '--color-border-strong': '#5d9c8840', '--color-fg': '#e9e5da',
  '--color-fg-muted': '#9c968a', '--color-fg-subtle': '#6f6a5d', '--color-accent': '#5d9c88', '--color-accent-hover': '#6fb09b',
  '--color-accent-soft': '#5d9c881f', '--reader-paper-bg': '#0f1421', '--reader-paper-text': '#d6d8e0',
  '--font-display': '"Outfit", "Plus Jakarta Sans", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
}

const CSS = `
.cr-shell{background:var(--color-bg);color:var(--color-fg);font-family:var(--font-display);flex:1;min-height:0;position:relative;display:flex;flex-direction:column}
.cr-scroll{flex:1;min-height:0;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--color-border-strong) transparent;padding:0 0 112px}
.cr-scroll::-webkit-scrollbar{width:8px;height:8px}.cr-scroll::-webkit-scrollbar-thumb{background:var(--color-border-strong);border-radius:999px}.cr-scroll::-webkit-scrollbar-track{background:transparent}
.cr-hint{margin:12px 12px 0;display:flex;align-items:center;gap:12px;padding:16px 20px;border-radius:16px;background:#1f1b12;color:var(--color-fg-muted);font-size:17px}
.cr-hint b{color:#fff;font-weight:600}
.cr-article{background:var(--reader-paper-bg);color:var(--reader-paper-text);width:100%;max-width:960px;margin:16px auto 0;overflow:hidden;transition:background-color .2s,color .2s}
.cr-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:28px 28px 20px}
.cr-title{font-family:var(--font-display);font-weight:700;letter-spacing:-.025em;font-size:24px;line-height:1.25;margin:0;color:var(--reader-paper-text)}
.cr-sub{font-size:12px;opacity:.55;margin-top:6px}
.cr-tools{display:none;align-items:center;gap:8px;flex-shrink:0}
.cr-pills{display:inline-flex;padding:2px;border-radius:999px;background:#d6d8e00d}
.cr-pill{height:28px;padding:0 10px;border-radius:999px;border:none;background:transparent;color:var(--reader-paper-text);cursor:pointer;font-family:inherit;font-weight:500}
.cr-pill:hover,.cr-pill.on{background:#d6d8e01a}
.cr-select{height:32px;padding:0 12px;border-radius:999px;border:none;background:#d6d8e00d;color:var(--reader-paper-text);font-size:12.5px;cursor:pointer;color-scheme:dark;font-family:inherit}
.cr-body{padding:24px 28px;text-align:left;overflow-wrap:anywhere;word-break:break-word;min-width:0;max-width:100%}
.cr-body p{margin:0 0 var(--p-gap,1.2em)}
.cr-summary{margin:0 28px 4px;padding:12px 14px;border-radius:12px;background:#d6d8e00d;font-size:14px;line-height:1.55}
.cr-pager{position:fixed;top:12px;right:12px;z-index:40;display:none;align-items:center;gap:2px;height:40px;padding:0 4px;border-radius:999px;background:rgba(32,28,21,.95);backdrop-filter:blur(8px);transition:transform .2s ease-out}
.cr-ico{display:inline-flex;align-items:center;justify-content:center;border:none;background:transparent;color:var(--color-fg-muted);cursor:pointer;transition:color .15s,background .15s}
.cr-ico:hover{color:var(--color-fg);background:var(--color-bg-subtle)}.cr-ico:disabled{opacity:.3;pointer-events:none}
.cr-pager .cr-ico{height:32px;width:32px;border-radius:999px}
.cr-pager .cr-chap{display:inline-flex;align-items:center;gap:8px;height:28px;padding:0 8px;border-radius:999px;border:none;background:transparent;color:var(--color-fg);font:600 13px var(--font-display);cursor:pointer;max-width:200px}
.cr-pager .cr-chap:hover{background:var(--color-bg-subtle)}
.cr-chap span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cr-rail{position:fixed;top:50%;right:12px;transform:translateY(-50%);z-index:40;display:none;flex-direction:column;align-items:center;gap:4px;padding:6px;border-radius:16px;background:rgba(32,28,21,.95);backdrop-filter:blur(8px);transition:transform .2s ease-out}
.cr-rail .cr-ico{height:36px;width:36px;border-radius:12px}.cr-rail .cr-ico.on{color:var(--color-accent)}
.cr-rail hr{width:24px;height:1px;border:none;background:var(--color-bg-subtle);margin:2px 0}
.cr-bottom{position:fixed;left:0;right:0;bottom:0;z-index:40;background:var(--color-bg-elevated);display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 12px;transition:transform .2s ease-out}
.cr-bottom .cr-grp{display:flex;align-items:center;gap:2px;height:40px;padding:0 4px;border-radius:999px;background:var(--color-bg-subtle);min-width:0}
.cr-bottom .cr-ico{height:28px;width:28px;border-radius:999px}
.cr-bottom .cr-ico.big{height:40px;width:40px;border-radius:12px}
.cr-bottom .cr-chap{font:600 13px var(--font-display);color:var(--color-fg);background:transparent;border:none;padding:0 6px;max-width:42vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cr-drawer{position:fixed;inset:0;z-index:60;background:rgba(0,0,0,.5);display:flex;justify-content:flex-end}
.cr-drawer>div{width:min(420px,92vw);height:100%;background:var(--color-bg-elevated);border-left:1px solid var(--color-border);display:flex;flex-direction:column}
.cr-drawer header{padding:16px 18px;border-bottom:1px solid var(--color-border);display:flex;align-items:center;justify-content:space-between;font-weight:600}
.cr-list{overflow-y:auto;flex:1}
.cr-list button{display:block;width:100%;text-align:left;padding:10px 18px;border:none;border-bottom:1px solid var(--color-border);background:transparent;color:var(--color-fg);font:400 13.5px var(--font-display);cursor:pointer}
.cr-list button:hover{background:var(--color-bg-subtle)}.cr-list button.cur{color:var(--color-accent);font-weight:600;background:var(--color-accent-soft)}
.cr-panel{position:fixed;right:64px;top:50%;transform:translateY(-50%);z-index:50;width:min(300px,86vw);padding:16px;border-radius:16px;background:var(--color-bg-elevated);border:1px solid var(--color-border);display:flex;flex-direction:column;gap:14px;font-size:13px}
.cr-panel label{display:flex;flex-direction:column;gap:6px;color:var(--color-fg-muted);font-size:12px}
.cr-panel input[type=range]{accent-color:var(--color-accent)}
.cr-panel .cr-select{background:var(--color-bg-subtle);color:var(--color-fg);width:100%}
.cr-hide-r{transform:translateX(calc(100% + 24px))}.cr-hide-rail{transform:translate(calc(100% + 24px),-50%)}.cr-hide-b{transform:translateY(100%)}
@media (min-width:640px){.cr-title{font-size:30px}.cr-tools{display:flex}}
.cr-story{position:fixed;inset:0;z-index:70;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;padding:16px}
.cr-story>div{width:min(640px,100%);max-height:88vh;display:flex;flex-direction:column;border-radius:16px;background:var(--color-bg-elevated);border:1px solid var(--color-border);overflow:hidden}
.cr-story header{padding:14px 16px;border-bottom:1px solid var(--color-border);display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.cr-story h3{margin:0;font:700 16px var(--font-display);color:var(--color-fg)}
.cr-story .cr-meta{font-size:12px;color:var(--color-fg-muted);margin-top:2px}
.cr-story .cr-text{padding:14px 18px;overflow-y:auto;font-size:15px;line-height:1.65;color:var(--color-fg)}
.cr-story .cr-text p{margin:0 0 .9em}
.cr-story .cr-text p.on{background:#d6d8e014;border-radius:8px;box-shadow:-10px 0 0 #d6d8e014,10px 0 0 #d6d8e014}
.cr-story footer{padding:10px 14px 12px;border-top:1px solid var(--color-border);display:flex;flex-direction:column;gap:8px}
.cr-story .cr-seek{display:flex;align-items:center;gap:10px}
.cr-story .cr-seek input{flex:1;min-width:0;accent-color:var(--color-accent)}
.cr-story .cr-seek span{font-size:12px;color:var(--color-fg-muted);white-space:nowrap}
.cr-story .cr-ctl{display:flex;align-items:center;gap:6px}
.cr-story .cr-pbtn{height:38px;width:38px;border-radius:999px;border:none;background:var(--color-bg-subtle);color:var(--color-fg);font-size:15px;cursor:pointer}
.cr-story .cr-pbtn:disabled{opacity:.4;cursor:default}
.cr-story .cr-go{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:38px;min-width:128px;padding:0 16px;border-radius:999px;border:none;background:var(--color-accent);color:#10131c;font:700 13px var(--font-display);cursor:pointer}
.cr-story .cr-go:disabled{opacity:.6;cursor:default}
.cr-story .cr-spd{width:74px;height:38px;margin-left:auto}
.cr-story .cr-voice{width:100%;height:38px}
.cr-story .cr-prog{font-size:12px;color:var(--color-fg-muted)}
@media (max-width:639px){.cr-story{align-items:flex-end;padding:0}.cr-story>div{width:100%;max-height:82vh;border-radius:16px 16px 0 0}}
@media (max-width:420px){.cr-bottom .cr-ico.big{height:36px;width:36px}}
@media (min-width:1024px){
  .cr-article{border-radius:16px;margin-top:16px}.cr-scroll{padding:16px 64px 96px 16px}
  .cr-pager,.cr-rail{display:inline-flex}.cr-rail{display:flex}.cr-bottom{display:none}
}
@media (max-width:1023px){.cr-article{margin-top:12px}.cr-head,.cr-body{padding-left:16px;padding-right:16px}.cr-summary{margin-left:16px;margin-right:16px}}
`

function Icon({ d, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {[].concat(d).map((p, i) => <path key={i} d={p} />)}
    </svg>
  )
}
const IC = {
  prev: 'M15 18l-6-6 6-6', next: 'M9 18l6-6-6-6', down: 'M6 9l6 6 6-6',
  home: ['M3 11l9-8 9 8', 'M5 10v10h14V10'],
  book: ['M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2z', 'M4 21V5'],
  list: ['M8 6h13', 'M8 12h13', 'M8 18h13', 'M3 6h.01', 'M3 12h.01', 'M3 18h.01'],
  summary: ['M5 4h14v16H5z', 'M9 9h6', 'M9 13h6', 'M9 17h4'],
  settings: ['M4 6h10', 'M18 6h2', 'M4 12h4', 'M12 12h8', 'M4 18h12', 'M20 18h0', 'M14 4v4', 'M8 10v4', 'M16 16v4'],
  full: ['M4 9V4h5', 'M20 9V4h-5', 'M4 15v5h5', 'M20 15v5h-5'],
  hand: ['M8 13V5a1.5 1.5 0 013 0v6', 'M11 11V4.5a1.5 1.5 0 013 0V11', 'M14 11V6a1.5 1.5 0 013 0v7a6 6 0 01-6 6h-1a6 6 0 01-5-3l-2-3a1.5 1.5 0 012-2l2 2'],
}

const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2]

// Each paragraph cut into sentences grouped to at most ~500 characters, so the voice starts quickly and each request stays small.
// Every piece remembers its paragraph, which is the one lit up while it is spoken.
function speechChunks(paragraphs) {
  const out = []
  paragraphs.forEach((para, pi) => {
    const sentences = String(para).replace(/\s+/g, ' ').trim().match(/[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g) || []
    let cur = ''
    for (const s of sentences) {
      if (cur && (cur + s).length > 500) { out.push({ text: cur.trim(), para: pi }); cur = '' }
      cur += s
    }
    if (cur.trim()) out.push({ text: cur.trim(), para: pi })
  })
  return out
}

// "Story so far": the novel's rolling summary in a pop-up with a player that reads it aloud in the saved Kokoro voice (local, no key):
// play / pause, previous / next part, a seek bar, and speed. Audio comes one piece at a time and is kept, so going back replays at once.
function StoryPopup({ novel, title, onClose }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [voice, setVoice] = useState(() => savedTtsVoice())
  const [rate, setRate] = useState(() => { try { return Number(localStorage.getItem('nm-tts-rate')) || 1 } catch { return 1 } })
  const [state, setState] = useState('idle')          // idle · loading · playing · paused
  const [pos, setPos] = useState(0)                   // the piece being spoken (or next to speak)
  const [frac, setFrac] = useState(0)                 // how far through that piece
  const [scrub, setScrub] = useState(null)            // seek-bar value while it is being dragged
  const audioRef = useRef(null)
  const token = useRef(0)
  const wake = useRef(null)
  const clips = useRef(new Map())                     // piece index -> Promise of its audio url
  const paraRefs = useRef([])

  useEffect(() => {
    let alive = true
    api.crRollingSummary(novel).then(r => { if (alive) setData(r) }).catch(e => { if (alive) setErr(e.message || String(e)) })
    return () => { alive = false }
  }, [novel])
  useEffect(() => () => { halt(); dropClips() }, [])      // eslint-disable-line react-hooks/exhaustive-deps

  const paragraphs = useMemo(() => (data ? data.summary.split(/\n+/).map(x => x.trim()).filter(Boolean) : []), [data])
  const chunks = useMemo(() => speechChunks(paragraphs), [paragraphs])
  const N = chunks.length
  const curPara = state === 'idle' ? -1 : chunks[pos]?.para

  useEffect(() => {      // keep the spoken paragraph in view
    if (curPara >= 0) paraRefs.current[curPara]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [curPara])

  function player() {
    if (!audioRef.current) audioRef.current = new Audio()
    return audioRef.current
  }
  function halt() {
    token.current += 1
    try { audioRef.current?.pause() } catch { /* no player yet */ }
    if (wake.current) { wake.current(); wake.current = null }
  }
  function dropClips() {
    clips.current.forEach(p => p.then(u => URL.revokeObjectURL(u)).catch(() => {}))
    clips.current.clear()
  }
  function clipFor(i) {
    if (!clips.current.has(i)) {
      const pr = api.speak(chunks[i].text, voice).then(r => {
        const bin = atob(r.audio_b64)
        const bytes = new Uint8Array(bin.length)
        for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k)
        return URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
      })
      pr.catch(() => clips.current.delete(i))
      clips.current.set(i, pr)
    }
    return clips.current.get(i)
  }
  async function runFrom(i0) {
    if (!N) return
    const a = player()
    // started inside the tap, so a phone browser lets the later pieces play without another tap
    a.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA='
    a.play().catch(() => {})
    halt()
    const me = ++token.current
    setErr('')
    for (let i = Math.max(0, Math.min(i0, N - 1)); i < N; i++) {
      setPos(i); setFrac(0); setState('loading')
      let url
      try { url = await clipFor(i) } catch (e) { if (token.current === me) { setErr('Read-aloud failed: ' + (e.message || e)); setState('idle') } return }
      if (token.current !== me) return
      if (i + 1 < N) clipFor(i + 1).catch(() => {})
      await new Promise(res => {
        wake.current = res
        a.onended = a.onerror = () => { wake.current = null; res() }
        a.ontimeupdate = () => setFrac(a.duration ? Math.min(1, a.currentTime / a.duration) : 0)
        a.src = url
        a.defaultPlaybackRate = rate
        a.playbackRate = rate
        a.play().then(() => { if (token.current === me) setState('playing') }).catch(res)
      })
      if (token.current !== me) return
    }
    setState('idle'); setPos(0); setFrac(0)
  }
  function toggle() {
    const a = audioRef.current
    if (state === 'playing') { a.pause(); setState('paused') }
    else if (state === 'paused') { a.play().then(() => setState('playing')).catch(() => {}) }
    else if (state === 'idle') runFrom(pos)
  }
  function stop() { halt(); setState('idle'); setPos(0); setFrac(0) }
  function prev() { runFrom(state !== 'idle' && frac > 0.15 ? pos : Math.max(0, pos - 1)) }
  function next() { if (pos + 1 < N) runFrom(pos + 1); else stop() }
  function commitScrub() {
    if (scrub == null) return
    const i = Math.min(N - 1, Math.floor(scrub / 1000 * N))
    setScrub(null)
    runFrom(i)
  }
  function pickSpeed(r) {
    setRate(r)
    try { localStorage.setItem('nm-tts-rate', String(r)) } catch { /* storage blocked */ }
    if (audioRef.current) { audioRef.current.defaultPlaybackRate = r; audioRef.current.playbackRate = r }
  }
  function pickVoice(v) {
    halt(); dropClips(); setState('idle'); setPos(0); setFrac(0); setVoice(v)
    try { localStorage.setItem('nm-tts-voice', v) } catch { /* storage blocked */ }
  }
  function close() { halt(); onClose() }

  const seekVal = scrub != null ? scrub : N ? Math.round(((state === 'idle' ? 0 : pos) + (state === 'idle' ? 0 : frac)) / N * 1000) : 0
  const busy = state === 'loading'

  return (
    <div className="cr-story" onClick={close}>
      <div onClick={e => e.stopPropagation()} role="dialog" aria-label="Story so far">
        <header>
          <div style={{ minWidth: 0 }}>
            <h3>Story so far · {title}</h3>
            <div className="cr-meta">
              {data ? `Covers chapters 1–${data.through ?? '?'}${data.updated_at ? ` · updated ${String(data.updated_at).slice(0, 10)}` : ''}` : err ? '' : 'Loading…'}
            </div>
          </div>
          <button className="cr-ico" style={{ width: 32, height: 32, borderRadius: 10, flex: 'none' }} onClick={close} aria-label="Close">✕</button>
        </header>
        <div className="cr-text">
          {err && !data && <div style={{ color: '#f87171' }}>{err}</div>}
          {paragraphs.map((p, i) => <p key={i} ref={el => { paraRefs.current[i] = el }} className={i === curPara ? 'on' : ''}>{p}</p>)}
        </div>
        <footer>
          <div className="cr-seek">
            <input type="range" min="0" max="1000" value={seekVal} disabled={!N}
              onChange={e => setScrub(Number(e.target.value))} onPointerUp={commitScrub} onKeyUp={commitScrub} aria-label="Seek" />
            <span>{state === 'idle' ? `${N} parts` : `Part ${Math.min(pos + 1, N)} of ${N}`}</span>
          </div>
          <div className="cr-ctl">
            <button className="cr-pbtn" disabled={!N || state === 'idle'} onClick={prev} aria-label="Previous part">⏮</button>
            <button className="cr-go" disabled={!N} onClick={toggle} aria-label={state === 'playing' ? 'Pause' : 'Play'}>
              {busy ? 'Loading…' : state === 'playing' ? '❚❚ Pause' : state === 'paused' ? '▶ Resume' : '▶ Read aloud'}
            </button>
            <button className="cr-pbtn" disabled={!N || state === 'idle'} onClick={next} aria-label="Next part">⏭</button>
            <button className="cr-pbtn" disabled={state === 'idle'} onClick={stop} aria-label="Stop">■</button>
            <select className="cr-select cr-spd" value={rate} onChange={e => pickSpeed(Number(e.target.value))} aria-label="Speed">
              {SPEEDS.map(r => <option key={r} value={r}>{r}×</option>)}
            </select>
          </div>
          <select className="cr-select cr-voice" value={voice} onChange={e => pickVoice(e.target.value)} aria-label="Voice">
            {TTS_GROUPS.map(g => (
              <optgroup key={g} label={g}>
                {TTS_VOICES.filter(v => v.group === g).map(v => <option key={v.id} value={v.id}>{v.label}</option>)}
              </optgroup>
            ))}
          </select>
          {err && data && <div className="cr-prog" style={{ color: '#f87171' }}>{err}</div>}
        </footer>
      </div>
    </div>
  )
}

function NovelCard({ n, last, onOpen }) {
  const h = hue(n.id)
  return (
    <button onClick={onOpen} style={{
      textAlign: 'left', background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', color: 'inherit', minWidth: 0,
    }}>
      <div style={{
        position: 'relative', aspectRatio: '3 / 4', borderRadius: 12, overflow: 'hidden',
        background: `linear-gradient(155deg, hsl(${h} 55% 30%), hsl(${(h + 50) % 360} 60% 14%))`,
        border: '1px solid rgba(255,255,255,0.08)', boxShadow: '0 4px 14px rgba(0,0,0,0.35)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <span style={{ fontSize: 'clamp(26px, 9vw, 54px)', fontWeight: 800, letterSpacing: 2, color: `hsl(${h} 80% 82%)`, opacity: 0.9 }}>
          {initials(n.title)}
        </span>
        <span style={{
          position: 'absolute', left: 6, bottom: 6, fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 8,
          background: 'rgba(0,0,0,0.55)', color: '#e6edf7',
        }}>{n.chapters.toLocaleString()} ch</span>
        {last ? (
          <span style={{
            position: 'absolute', right: 6, top: 6, fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 8,
            background: 'rgba(52,211,153,0.9)', color: '#04210f',
          }}>ch {last}</span>
        ) : null}
      </div>
      <div style={{ marginTop: 7, fontSize: 12.5, fontWeight: 700, lineHeight: 1.25, color: 'var(--text-primary)',
        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{n.title}</div>
      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 2 }}>
        {n.extracted ? `${n.extracted} extracted` : 'not extracted'}
      </div>
    </button>
  )
}

export default function CorpusReaderPage() {
  const [novels, setNovels] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(() => store.get('nm-cr-novel', null))      // novel id being read
  const [chapters, setChapters] = useState([])
  const [ch, setCh] = useState(null)                                           // the loaded chapter
  const [n, setN] = useState(() => store.get('nm-cr-ch', {}))                  // last chapter read per novel
  const [fontIdx, setFontIdx] = useState(() => store.get('nm-cr-font', 3))     // Roboto, the site's default
  const [size, setSize] = useState(() => store.get('nm-cr-size', 18))
  const [lh, setLh] = useState(() => store.get('nm-cr-lh', 180))               // line height in %, the site's default
  const [controls, setControls] = useState(true)
  const [hint, setHint] = useState(() => !store.get('nm-cr-hint-seen', false))
  const [showList, setShowList] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showSummary, setShowSummary] = useState(false)
  const [showStory, setShowStory] = useState(false)
  const scrollRef = useRef(null)
  const shellRef = useRef(null)

  useEffect(() => { api.crNovels().then(r => setNovels(r.novels || [])).catch(e => setErr(e.message || String(e))) }, [])
  useEffect(() => { store.set('nm-cr-novel', open) }, [open])
  useEffect(() => { store.set('nm-cr-size', size) }, [size])
  useEffect(() => { store.set('nm-cr-font', fontIdx) }, [fontIdx])
  useEffect(() => { store.set('nm-cr-lh', lh) }, [lh])

  // chapter list when a novel is opened
  useEffect(() => {
    if (!open) { setChapters([]); setCh(null); return }
    let alive = true
    api.crChapters(open).then(r => {
      if (!alive) return
      setChapters(r.chapters || [])
      const nums = (r.chapters || []).map(c => c.n)
      const want = n[open]
      load(open, want && nums.includes(want) ? want : nums[0])
    }).catch(e => setErr(e.message || String(e)))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // arrow keys turn the page, as the site's shortcuts do
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (/input|select|textarea/i.test(e.target?.tagName || '')) return
      if (e.key === 'ArrowRight' && ch?.next != null) load(open, ch.next)
      if (e.key === 'ArrowLeft' && ch?.prev != null) load(open, ch.prev)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ch])

  async function load(novel, num) {
    if (num == null) return
    try {
      const r = await api.crChapter(novel, num)
      setCh(r); setShowList(false); setShowSettings(false); setShowSummary(false); setErr('')
      setN(prev => { const nx = { ...prev, [novel]: num }; store.set('nm-cr-ch', nx); return nx })
      setTimeout(() => scrollRef.current?.scrollTo({ top: 0 }), 30)
    } catch (e) { setErr(e.message || String(e)) }
  }

  const title = useMemo(() => (novels || []).find(x => x.id === open)?.title || open, [novels, open])

  function tapText() {
    if (window.getSelection && String(window.getSelection())) return     // selecting text is not a tap
    if (hint) { setHint(false); store.set('nm-cr-hint-seen', true) }
    setControls(v => !v)
  }
  function fullscreen() {
    const el = shellRef.current
    if (!el) return
    if (document.fullscreenElement) document.exitFullscreen?.(); else el.requestFullscreen?.()
  }

  // ── library: three cards across ──
  if (!open) {
    return (
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 14px 28px' }}>
        <div style={{ fontSize: 20, fontWeight: 800 }}>Corpus Reader</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', margin: '2px 0 14px' }}>
          {novels ? `${novels.length} novels` : 'Loading…'} · tap one to read
        </div>
        {err && <div style={{ color: '#f87171', fontSize: 12, marginBottom: 10 }}>{err}</div>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '16px 12px', maxWidth: 760, margin: '0 auto' }}>
          {(novels || []).map(nv => <NovelCard key={nv.id} n={nv} last={n[nv.id]} onOpen={() => setOpen(nv.id)} />)}
        </div>
      </div>
    )
  }

  // ── reading page ──
  const chapLabel = ch ? `Chapter ${ch.n}${ch.title ? `: ${ch.title}` : ''}` : 'Loading…'
  const hide = !controls
  return (
    <div ref={shellRef} className="cr-shell" style={INK}>
      <style>{CSS}</style>

      <div ref={scrollRef} className="cr-scroll">
        {hint && (
          <div className="cr-hint"><Icon d={IC.hand} size={22} /><span><b>Tap</b> the page to show or hide the controls.</span></div>
        )}
        {err && <div style={{ color: '#f87171', fontSize: 12, margin: '10px 16px 0' }}>{err}</div>}
        <article className="cr-article" onClick={tapText}>
          {!ch ? <div className="cr-body" style={{ opacity: .6 }}>Loading…</div> : (
            <>
              <header className="cr-head">
                <div style={{ minWidth: 0 }}>
                  <h2 className="cr-title">{chapLabel}</h2>
                  <div className="cr-sub">
                    {ch.novel_title} · {ch.words.toLocaleString()} words · about {Math.max(1, Math.round(ch.words / 230))} min
                  </div>
                </div>
                <div className="cr-tools" onClick={e => e.stopPropagation()}>
                  <div className="cr-pills">
                    {SIZES.map(([label, px, reading]) => (
                      <button key={px} className={`cr-pill${size === reading ? ' on' : ''}`} style={{ fontSize: px, fontWeight: px === 14 ? 600 : 500 }}
                        onClick={() => setSize(reading)} aria-label={`Text size ${reading}`}>{label}</button>
                    ))}
                  </div>
                  <select className="cr-select" value={fontIdx} onChange={e => setFontIdx(Number(e.target.value))} aria-label="Font">
                    {FONTS.map(([name], i) => <option key={name} value={i} style={{ background: '#0f1421', color: '#d6d8e0' }}>{name}</option>)}
                  </select>
                </div>
              </header>
              {showSummary && ch.summary && <div className="cr-summary">{ch.summary}</div>}
              <div className="cr-body" style={{ fontFamily: FONTS[fontIdx][1], fontSize: size, lineHeight: `${lh}%`, '--p-gap': '1.2em' }}>
                {ch.paragraphs.map((p, i) => <p key={i}>{p}</p>)}
              </div>
            </>
          )}
        </article>
      </div>

      {/* top-right pager: previous · chapter · next */}
      <div className={`cr-pager${hide ? ' cr-hide-r' : ''}`}>
        <button className="cr-ico" disabled={ch?.prev == null} onClick={() => load(open, ch.prev)} aria-label="Previous chapter"><Icon d={IC.prev} /></button>
        <button className="cr-chap" onClick={() => setShowList(true)} aria-label="Open chapter list"><span>{chapLabel}</span><Icon d={IC.down} size={14} /></button>
        <button className="cr-ico" disabled={ch?.next == null} onClick={() => load(open, ch.next)} aria-label="Next chapter"><Icon d={IC.next} /></button>
      </div>

      {/* right rail */}
      <aside className={`cr-rail${hide ? ' cr-hide-rail' : ''}`} aria-label="Reader navigation">
        <button className="cr-ico" onClick={() => setOpen(null)} aria-label="Library"><Icon d={IC.home} /></button>
        <hr />
        <button className="cr-ico" onClick={() => setShowList(true)} aria-label="Chapters"><Icon d={IC.list} /></button>
        <button className={`cr-ico${showSummary ? ' on' : ''}`} disabled={!ch?.summary} onClick={() => setShowSummary(v => !v)} aria-label="Summary"><Icon d={IC.summary} /></button>
        <button className={`cr-ico${showStory ? ' on' : ''}`} onClick={() => setShowStory(true)} aria-label="Story so far" title="Story so far"><Icon d={IC.book} /></button>
        <button className={`cr-ico${showSettings ? ' on' : ''}`} onClick={() => setShowSettings(v => !v)} aria-label="Settings"><Icon d={IC.settings} /></button>
        <button className="cr-ico" onClick={fullscreen} aria-label="Fullscreen"><Icon d={IC.full} /></button>
      </aside>

      {/* bottom bar on phones */}
      <div className={`cr-bottom${hide ? ' cr-hide-b' : ''}`}>
        <div className="cr-grp">
          <button className="cr-ico" disabled={ch?.prev == null} onClick={() => load(open, ch.prev)} aria-label="Previous chapter"><Icon d={IC.prev} /></button>
          <button className="cr-chap" onClick={() => setShowList(true)}>{ch ? `Ch ${ch.n}` : '…'}</button>
          <button className="cr-ico" disabled={ch?.next == null} onClick={() => load(open, ch.next)} aria-label="Next chapter"><Icon d={IC.next} /></button>
        </div>
        <div style={{ display: 'flex', gap: 2 }}>
          <button className="cr-ico big" onClick={() => setOpen(null)} aria-label="Library"><Icon d={IC.home} /></button>
          <button className="cr-ico big" onClick={() => setShowList(true)} aria-label="Chapters"><Icon d={IC.list} /></button>
          <button className="cr-ico big" disabled={!ch?.summary} onClick={() => setShowSummary(v => !v)} aria-label="Summary"><Icon d={IC.summary} /></button>
          <button className="cr-ico big" onClick={() => setShowStory(true)} aria-label="Story so far"><Icon d={IC.book} /></button>
          <button className="cr-ico big" onClick={() => setShowSettings(v => !v)} aria-label="Settings"><Icon d={IC.settings} /></button>
        </div>
      </div>

      {showStory && <StoryPopup novel={open} title={title} onClose={() => setShowStory(false)} />}

      {showSettings && (
        <div className="cr-panel">
          <label>Font
            <select className="cr-select" value={fontIdx} onChange={e => setFontIdx(Number(e.target.value))}>
              {FONTS.map(([name], i) => <option key={name} value={i}>{name}</option>)}
            </select>
          </label>
          <label>Text size · {size}px
            <input type="range" min="14" max="30" value={size} onChange={e => setSize(Number(e.target.value))} />
          </label>
          <label>Line height · {lh}%
            <input type="range" min="130" max="230" step="5" value={lh} onChange={e => setLh(Number(e.target.value))} />
          </label>
        </div>
      )}

      {showList && (
        <div className="cr-drawer" onClick={() => setShowList(false)}>
          <div onClick={e => e.stopPropagation()}>
            <header><span>{title}</span><button className="cr-ico" style={{ width: 32, height: 32, borderRadius: 10 }} onClick={() => setShowList(false)} aria-label="Close">✕</button></header>
            <div className="cr-list">
              {chapters.map(c => (
                <button key={c.n} className={c.n === ch?.n ? 'cur' : ''} onClick={() => load(open, c.n)}>
                  {`Chapter ${c.n}${c.title ? `: ${c.title}` : ''}`}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
