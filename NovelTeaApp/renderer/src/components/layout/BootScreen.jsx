import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import NeuralBrain from '../corpus/NeuralBrain'

/* NovelTea Engine boot / landing screen — a "Jarvis"-style intro.
   Runs a short init sequence, pings the backend,
   then hands off to the main app via onReady(). */

const STEPS = [
  { key: 'core',   label: 'Initializing NovelTea Engine core' },
  { key: 'link',   label: 'Establishing backend link' },
  { key: 'net',    label: 'Scanning network interfaces' },
  { key: 'corpus', label: 'Mounting corpus' },
  { key: 'ready',  label: 'Systems online' },
]

export default function BootScreen({ onReady }) {
  const [stepIdx, setStepIdx] = useState(0)
  const [info, setInfo] = useState(null)
  const [statusLines, setStatusLines] = useState([])
  const [done, setDone] = useState(false)
  const [error, setError] = useState(null)
  const startedRef = useRef(false)

  function log(line) {
    setStatusLines(l => [...l.slice(-6), line])
  }

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true

    let cancelled = false
    const run = async () => {
      // core
      setStepIdx(0); log('> booting NovelTea Engine …')
      await wait(500)

      // backend link
      setStepIdx(1); log(`> handshaking with the server at ${window.location.host || 'localhost'}`)
      let online = false
      for (let i = 0; i < 20 && !cancelled; i++) {
        try { await api.health(); online = true; break } catch { await wait(400) }
      }
      if (!online) { setError('Engine not responding. Is the backend running?'); return }
      log('> engine online ✓')

      // network scan
      setStepIdx(2); log('> checking the local engine')
      let sys = null
      try { sys = await api.systemInfo() } catch { /* non-fatal */ }
      if (cancelled) return
      if (sys) {
        setInfo(sys)
        log(`> local  localhost:${sys.port}`)
      }

      // corpus
      setStepIdx(3)
      try {
        const stats = await api.corpusStats()
        log(`> corpus mounted · ${stats.novels || 0} novels · ${stats.chapters || 0} chapters`)
      } catch {
        log('> corpus not configured — set path in Settings')
      }
      await wait(400)

      // ready
      setStepIdx(4); log('> all systems online')
      await wait(600)
      if (!cancelled) setDone(true)
    }
    run()
    return () => { cancelled = true }
  }, [])

  // No auto-continue — the user enters by clicking the ENTER button.

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000, background: '#000',
      color: '#e9e4f5', fontFamily: 'ui-monospace,"SF Mono","Consolas",monospace', overflow: 'hidden',
    }}>
      <style>{keyframes}</style>

      {/* The living cortex — fullscreen, ambient */}
      <div style={{ position: 'absolute', inset: 0 }}>
        <NeuralBrain interactive={false} />
      </div>


      {/* HUD title */}
      <div style={{ position: 'absolute', left: 22, top: 20, pointerEvents: 'none' }}>
        <div style={{
          fontSize: 'clamp(20px, 4vw, 30px)', fontWeight: 800, letterSpacing: '0.14em',
          background: 'linear-gradient(90deg,#7fd4ff,#c026d3,#7fd4ff)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          backgroundSize: '200% auto', animation: 'nm-shine 4s linear infinite',
        }}>NOVELTEA ENGINE</div>
        <div style={{ fontSize: 10, color: '#8a7fa8', letterSpacing: '0.35em', marginTop: 6 }}>
          NOVEL CREATION ENGINE
        </div>
      </div>

      <div style={{
        position: 'absolute', right: 22, top: 24, textAlign: 'right', pointerEvents: 'none',
        color: '#8a7fa8', fontSize: 10, letterSpacing: '0.15em', lineHeight: 1.9,
      }}>
        162 NODES · STEEPING<br />{done ? 'ONLINE' : 'WAKING…'}
      </div>

      {/* Boot column — floats over the lower part of the brain */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0, padding: '0 16px 26px',
        display: 'flex', flexDirection: 'column', alignItems: 'center', pointerEvents: 'none',
      }}>
        {/* Step bar */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          {STEPS.map((s, i) => (
            <div key={s.key} title={s.label} style={{
              width: 34, height: 3, borderRadius: 2,
              background: i <= stepIdx ? '#c026d3' : 'rgba(255,255,255,0.12)',
              boxShadow: i === stepIdx ? '0 0 8px #c026d3' : 'none',
              transition: 'all 0.3s',
            }} />
          ))}
        </div>
        <div style={{ fontSize: 12.5, color: '#e3b8ff', marginBottom: 12, minHeight: 18 }}>
          {error ? <span style={{ color: '#f87171' }}>{error}</span> : STEPS[stepIdx]?.label + (done ? '' : ' …')}
        </div>

        {/* Console readout */}
        <div style={{
          width: 'min(560px, 92vw)', height: 110, overflow: 'hidden',
          background: 'rgba(12,6,24,0.72)', border: '1px solid rgba(139,47,214,0.4)',
          borderRadius: 10, padding: '10px 14px', fontSize: 11.5, lineHeight: 1.7,
          color: '#b9aed6', backdropFilter: 'blur(6px)',
        }}>
          {statusLines.map((l, i) => (
            <div key={i} style={{ opacity: 0.55 + (i / statusLines.length) * 0.45 }}>{l}</div>
          ))}
        </div>

        {/* Network card */}
        {info && (
          <div style={{ display: 'flex', gap: 10, marginTop: 14, flexWrap: 'wrap', justifyContent: 'center' }}>
            <NetChip label="LOCAL" value={`localhost:${info.port}`} />
          </div>
        )}

        {done && (
          <button onClick={() => onReady && onReady()} style={{
            marginTop: 18, padding: '10px 30px', fontSize: 13, fontWeight: 700, letterSpacing: '0.08em',
            background: 'linear-gradient(135deg,#8b2fd6,#c026d3)', color: '#fff',
            border: 'none', borderRadius: 999, cursor: 'pointer', pointerEvents: 'auto',
            boxShadow: '0 0 28px rgba(192,38,211,0.55)',
          }}>ENTER →</button>
        )}
      </div>
    </div>
  )
}

function NetChip({ label, value, accent }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 2, minWidth: 130,
      padding: '8px 14px', borderRadius: 8,
      background: 'rgba(8,14,24,0.8)',
      border: `1px solid ${accent ? 'rgba(56,189,248,0.5)' : 'rgba(255,255,255,0.1)'}`,
    }}>
      <span style={{ fontSize: 9, letterSpacing: '0.2em', color: accent ? '#38bdf8' : '#5b7a99' }}>{label}</span>
      <span style={{ fontSize: 12.5, color: '#dceeff', fontWeight: 600 }}>{value}</span>
    </div>
  )
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)) }

const keyframes = `
@keyframes nm-shine { to { background-position: 200% center; } }
@keyframes nm-spin  { to { transform: rotate(360deg); } }
@keyframes nm-spin2 { to { transform: rotate(-360deg); } }
@keyframes nm-pulse { 0%,100%{ transform: scale(1); opacity:1 } 50%{ transform: scale(1.06); opacity:0.85 } }
.nm-ring { position:absolute; inset:0; border-radius:50%; border:1px solid rgba(56,189,248,0.25); }
.nm-ring1 { animation: nm-spin 8s linear infinite; border-top-color:#38bdf8; }
.nm-ring2 { inset:22px; animation: nm-spin2 6s linear infinite; border-left-color:#a78bfa; }
.nm-ring3 { inset:44px; animation: nm-spin 4s linear infinite; border-bottom-color:#38bdf8; }
.nm-core {
  position:absolute; inset:66px; border-radius:50%;
  background: radial-gradient(circle at 40% 35%, #38bdf8, #1e3a8a 70%, #0b1220);
  display:flex; align-items:center; justify-content:center;
  animation: nm-pulse 2.4s ease-in-out infinite;
}
`
