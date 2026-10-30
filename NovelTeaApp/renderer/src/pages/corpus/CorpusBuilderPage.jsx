import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import BrainGraph from '../../components/corpus/BrainGraph'

/* Corpus Builder — add novels to the corpus and run the full extraction
   pipeline (v3 extraction → merge → genome). Uses the
   Claude subscription CLI when no API key is set. */

function useIsMobile() {
  const [m, setM] = useState(typeof window !== 'undefined' && window.innerWidth < 768)
  useEffect(() => {
    const on = () => setM(window.innerWidth < 768)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return m
}

export default function CorpusBuilderPage() {
  const isMobile = useIsMobile()
  const [novels, setNovels] = useState([])
  const [queue, setQueue] = useState([])
  const [activeJob, setActiveJob] = useState(null)   // {id, log, status, started, finished}
  // Picture-in-Picture: the console is drawn onto a canvas, the canvas becomes a video stream, and the browser floats that video
  // over other apps (Safari on iPhone supports this). pipRef holds the pieces so they can be torn down.
  const [pipOn, setPipOn] = useState(false)        // the live-video panel is showing
  const videoRef = useRef(null)
  const pipDataRef = useRef({ job: null, lines: [], elapsed: '' })
  const [showAdd, setShowAdd] = useState(false)
  const [showAddChapter, setShowAddChapter] = useState(false)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [compact, setCompact] = useState(true)   // collapse repetitive log lines
  const [copied, setCopied] = useState(false)
  const [aborting, setAborting] = useState(false)

  function drawPip(canvas) {
    const ctx = canvas.getContext('2d')
    const { job, lines, elapsed } = pipDataRef.current
    const W = canvas.width, H = canvas.height
    ctx.fillStyle = '#05070d'; ctx.fillRect(0, 0, W, H)
    ctx.fillStyle = '#0f1a2e'; ctx.fillRect(0, 0, W, 38)
    ctx.font = 'bold 20px Menlo, Consolas, monospace'
    ctx.textBaseline = 'middle'
    const status = job?.status || 'idle'
    ctx.fillStyle = '#dceeff'; ctx.fillText(String(job?.novel || 'Corpus Builder').slice(0, 30), 12, 20)
    const tag = status.toUpperCase() + (elapsed ? '  ' + elapsed : '')
    ctx.fillStyle = status === 'running' ? '#34d399' : status === 'error' ? '#f87171' : '#7fd0ff'
    ctx.textAlign = 'right'; ctx.fillText(tag, W - 12, 20); ctx.textAlign = 'left'
    ctx.font = '17px Menlo, Consolas, monospace'
    const rows = Math.floor((H - 52) / 25)
    const maxW = W - 24
    // wrap every line to the width (a continuation row is indented), then keep the LAST rows and draw them from the bottom up,
    // so the newest line is always the bottom line of the picture - like a terminal that has scrolled to the end
    const wrapped = []
    for (const l of lines.slice(-rows)) {
      let s = String(l)
      let cols = charColors(l)
      if (/^\d{2}:\d{2}:\d{2}\s/.test(s)) { s = s.slice(3); cols = cols.slice(3) }      // drop the hour: HH:MM:SS -> MM:SS
      let first = true
      while (s.length > 0) {
        let n = s.length
        while (n > 1 && ctx.measureText((first ? '' : '   ') + s.slice(0, n)).width > maxW) n -= 1
        wrapped.push({ text: s.slice(0, n), cols: cols.slice(0, n), indent: first ? 0 : 3 })
        s = s.slice(n); cols = cols.slice(n)
        first = false
      }
    }
    const shown = wrapped.slice(-rows)
    const bottom = H - 12
    shown.forEach((r, i) => {
      const y = bottom - (shown.length - 1 - i) * 25
      let x = 10 + (r.indent ? ctx.measureText('   ').width : 0)
      let st = 0
      for (let k = 1; k <= r.text.length; k++) {
        if (k === r.text.length || r.cols[k] !== r.cols[st]) {
          const run = r.text.slice(st, k)
          ctx.fillStyle = r.cols[st]
          ctx.fillText(run, x, y)
          x += ctx.measureText(run).width
          st = k
        }
      }
    })
  }

  // The live video: while the panel is on, the console is drawn onto a canvas twice a second and the canvas is shown as a video on the
  // page itself. Its native controls give Safari's own Picture-in-Picture button (a direct tap on a native control always counts).
  // iOS has no picture-in-picture inside a Home Screen web app, so this opens the stand-alone video page in Safari itself
  // (x-safari-https:// makes iOS hand the address to Safari; outside the Home Screen app a normal new tab is enough)
  function openInSafari() {
    const url = `${window.location.origin}/api/corpus-builder/live-video?job=${encodeURIComponent(activeJob?.id || '')}`
    const standalone = window.navigator.standalone === true || window.matchMedia?.('(display-mode: standalone)').matches
    if (standalone) window.location.href = url.replace(/^http/, 'x-safari-http')
    else window.open(url, '_blank')
  }

  function floatVideo() {
    const v = videoRef.current
    if (!v) return
    v.play().catch(() => {})
    try {
      if (v.webkitSupportsPresentationMode) {
        if (v.webkitSupportsPresentationMode('picture-in-picture')) { v.webkitSetPresentationMode('picture-in-picture'); return }
        alert('Safari says this video cannot float (no picture-in-picture for it yet). Wait a second for the picture to appear, then tap Float again.')
        return
      }
      if (v.requestPictureInPicture) { v.requestPictureInPicture().catch(e => alert('Could not float the video: ' + (e?.message || e))); return }
      alert('This browser has no picture-in-picture for video.')
    } catch (e) {
      alert('Could not float the video: ' + (e?.message || e))
    }
  }

  useEffect(() => {
    if (!pipOn) return undefined
    const video = videoRef.current
    if (!video) return undefined
    const canvas = document.createElement('canvas')
    canvas.width = 720; canvas.height = 405
    drawPip(canvas)
    const stream = canvas.captureStream(4)
    let ac = null
    try {
      const AC = window.AudioContext || window.webkitAudioContext
      ac = new AC()
      const dst = ac.createMediaStreamDestination()
      const osc = ac.createOscillator(); const gain = ac.createGain()
      gain.gain.value = 0.001                                    // inaudible, but a real audio track
      osc.connect(gain); gain.connect(dst); osc.start()
      dst.stream.getAudioTracks().forEach(tr => stream.addTrack(tr))
      ac.resume().catch(() => {})
    } catch (e) { /* no audio track: the Float button reports what Safari says */ }
    video.srcObject = stream
    video.muted = true
    video.play().catch(() => {})
    const timer = setInterval(() => drawPip(canvas), 500)     // a changing frame keeps the video live (and the clock ticking)
    return () => {
      clearInterval(timer)
      try { ac && ac.close() } catch {}
      try { stream.getTracks().forEach(tr => tr.stop()) } catch {}
      try { video.pause(); video.srcObject = null } catch {}
    }
  }, [pipOn])

  useEffect(() => {
    // what the floating video shows: the same lines as the console (compact view), plus the job's name, status and clock
    pipDataRef.current = {
      job: activeJob,
      lines: compact ? compactLog(activeJob?.log || []) : (activeJob?.log || []),
      elapsed: activeJob?.started ? elapsed() : '',
    }
  })

  async function abortJob() {
    if (!activeJob?.id || aborting) return
    setAborting(true)
    try { await api.cbAbort(activeJob.id) } catch {}
    // poll will pick up the aborted status; clear the flag shortly after
    setTimeout(() => setAborting(false), 2000)
  }
  const pollRef = useRef(null)
  const consoleRef = useRef(null)
  const logEndRef = useRef(null)

  function copyLog() {
    const text = (activeJob?.log || []).join('\n')
    const done = () => { setCopied(true); setTimeout(() => setCopied(false), 1500) }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done))
    } else {
      fallbackCopy(text, done)
    }
  }

  function fallbackCopy(text, done) {
    // Works over plain HTTP / LAN where navigator.clipboard is unavailable
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'; ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus(); ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      done()
    } catch {}
  }

  async function refresh() {
    try {
      const [n, q] = await Promise.all([api.cbNovels(), api.cbQueue()])
      setNovels(n.novels || [])
      setQueue(q.queue || [])
    } catch {}
  }

  useEffect(() => { refresh() }, [])

  // Find the currently-running/queued job and attach the console to it.
  // Retries a few times because the queue worker takes a moment to create its
  // first job after /queue/run returns.
  async function attachRunningJob(tries = 8) {
    for (let i = 0; i < tries; i++) {
      try {
        const r = await api.cbJobs()
        const job = (r.jobs || []).find(j => j.status === 'running' || j.status === 'queued')
        if (job) {
          setActiveJob(job)
          setTimeout(() => consoleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
          return true
        }
      } catch {}
      await new Promise(res => setTimeout(res, 700))
    }
    return false
  }

  // On mount, resume watching any job already running (e.g. queue worker)
  useEffect(() => { attachRunningJob(1) }, [])

  // While the console is CLOSED, keep an eye on background jobs so the header
  // can offer a "Console" button to reopen them — and so the end-of-process
  // chime still plays even with the console closed.
  const [bgJobs, setBgJobs] = useState({ running: null, latest: null })
  const bgRunningRef = useRef(null)
  useEffect(() => {
    if (activeJob) { bgRunningRef.current = null; return }   // console open — its poll chimes
    let alive = true
    async function check() {
      try {
        const r = await api.cbJobs()
        const jobs = r.jobs || []
        const running = jobs.find(j => j.status === 'running' || j.status === 'queued') || null
        const latest = jobs.slice().sort((a, b) => (b.started || 0) - (a.started || 0))[0] || null
        // a job we were watching just finished → confirm chime + reopen its
        // console and scroll back to the pipeline it just processed
        const prev = bgRunningRef.current
        if (prev && (!running || running.id !== prev)) {
          const fin = jobs.find(j => j.id === prev)
          if (fin && (fin.status === 'done' || fin.status === 'error' || fin.status === 'aborted')) {
            chime(fin.status)
            setActiveJob(fin)
            setTimeout(() => consoleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
          }
        }
        bgRunningRef.current = running ? running.id : null
        if (alive) setBgJobs({ running, latest })
      } catch {}
    }
    check()
    const t = setInterval(check, 4000)
    return () => { alive = false; clearInterval(t) }
  }, [activeJob])

  function reopenConsole() {
    const job = bgJobs.running || bgJobs.latest
    if (!job) return
    setActiveJob(job)
    setTimeout(() => consoleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
  }

  // Poll the active job for live log
  useEffect(() => {
    if (!activeJob?.id || activeJob.id === 'queue' || activeJob.id === 'err') return
    pollRef.current = setInterval(async () => {
      try {
        const j = await api.cbJob(activeJob.id)
        setActiveJob(j)
        if (j.status === 'done' || j.status === 'error' || j.status === 'aborted') {
          clearInterval(pollRef.current)
          chime(j.status)   // audible ding when a process ends
          // bring the finished pipeline's console back into view
          setTimeout(() => consoleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
          refresh()
          // Don't auto-hop to the next job if the user aborted.
          if (j.status !== 'aborted') {
            try {
              const r = await api.cbJobs()
              const nextRunning = (r.jobs || []).find(
                x => (x.status === 'running' || x.status === 'queued') && x.id !== j.id
              )
              if (nextRunning) setActiveJob(nextRunning)
            } catch {}
          }
        }
      } catch {}
    }, 1000)
    return () => clearInterval(pollRef.current)
  }, [activeJob?.id])

  // Elapsed-time ticker while a job runs
  useEffect(() => {
    if (activeJob?.status === 'running' || activeJob?.status === 'queued') {
      const t = setInterval(() => setNow(Date.now()), 1000)
      return () => clearInterval(t)
    }
  }, [activeJob?.status])

  // Auto-scroll the console as new log lines arrive
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [activeJob?.log?.length])

  async function runNovel(novelId, opts) {
    setBusy(true)
    try {
      const res = await api.cbRun({ novel_id: novelId, nemotron_only: nemotronOnly, ...opts })
      // No client-side `started`: the poll below replaces this object with the
      // server's, whose `started` is stamped when the pipeline actually begins.
      // Seeding a browser timestamp here made the timer jump on the first poll.
      setActiveJob({ id: res.job_id, novel: novelId, status: 'running', log: ['> starting pipeline…'] })
      // bring the console into view immediately
      setTimeout(() => consoleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
    } catch (e) {
      setActiveJob({ id: 'err', novel: novelId, status: 'error', error: e.message, log: [`✗ ${e.message}`] })
    } finally { setBusy(false) }
  }

  // "Nemotron only": pins the whole job (extraction, merge steps, rolling summary, genome...) to Nemotron, whatever the dropdown or
  // settings say. Remembered between visits.
  const [nemotronOnly, setNemotronOnly] = useState(() => { try { return localStorage.getItem('nm-cb-nemotron-only') === '1' } catch { return false } })
  useEffect(() => { try { localStorage.setItem('nm-cb-nemotron-only', nemotronOnly ? '1' : '0') } catch {} }, [nemotronOnly])

  // Elapsed time for the active job.
  //
  // The baseline MUST come from the server: `started` is stamped server-side
  // when the pipeline actually begins (not when it was queued), and mixing that
  // with a browser Date.now() baseline made the timer jump on the first poll
  // whenever the two clocks disagreed.
  //
  // `clockSkew` converts the browser clock into server time using the job's own
  // `now` field, so a machine whose clock is off no longer shows a wrong or
  // negative elapsed value. While a job is still queued there is no start time
  // yet, so we show nothing rather than counting queue wait as run time.
  function elapsed() {
    const started = activeJob?.started
    if (!started) return ''
    const serverNow = activeJob?.now
    const skew = typeof serverNow === 'number' ? (now / 1000) - serverNow : 0
    const end = activeJob.finished || (now / 1000) - skew
    const s = Math.max(0, Math.floor(end - started))
    const m = Math.floor(s / 60)
    return m > 0 ? `${m}m ${s % 60}s` : `${s}s`
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '14px 12px' : '20px 24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: isMobile ? 'stretch' : 'center', flexDirection: isMobile ? 'column' : 'row',
        justifyContent: 'space-between', gap: isMobile ? 10 : 0, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: isMobile ? 18 : 20, fontWeight: 800 }}>Corpus Builder</div>
          <div style={{ fontSize: isMobile ? 11 : 12, color: 'var(--text-muted)', marginTop: 2 }}>
            Add novels (upload plain-text chapters you have the right to use) and run the extraction pipeline: v3 schema, merge, genome. No API key needed if you use the Claude subscription engine.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexDirection: isMobile ? 'column' : 'row' }}>
          {!activeJob && (bgJobs.running || bgJobs.latest) && (
            <button onClick={reopenConsole} title={bgJobs.running
              ? `A job is running (${bgJobs.running.novel || bgJobs.running.id}) — reopen its console`
              : 'Reopen the console for the most recent job'}
              style={{
                padding: isMobile ? '11px 16px' : '9px 16px', fontWeight: 700, fontSize: 13,
                width: isMobile ? '100%' : 'auto',
                background: 'var(--bg-elevated)',
                color: bgJobs.running ? 'var(--green)' : 'var(--text-secondary)',
                border: `1px solid ${bgJobs.running ? 'var(--green)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-sm)',
              }}>
              {bgJobs.running ? '● Console — job running' : '⧉ Console'}
            </button>
          )}
          <label title="Run every step of the jobs you start here (extraction, merge, conflicts, rolling summary, genome) on Nemotron, whatever engine the top-bar dropdown or Settings has selected. Applies to Run and Queue."
            style={{
              display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700,
              color: nemotronOnly ? 'var(--green)' : 'var(--text-muted)',
              padding: isMobile ? '11px 4px' : '9px 4px', whiteSpace: 'nowrap',
            }}>
            <input type="checkbox" checked={nemotronOnly} onChange={e => setNemotronOnly(e.target.checked)} />
            Nemotron only
          </label>
          <button onClick={() => setShowAddChapter(true)} disabled={novels.length === 0}
            title={novels.length === 0 ? 'Add a novel first' : 'Add chapters to an existing novel'}
            style={{
              padding: isMobile ? '11px 16px' : '9px 16px', fontWeight: 700, fontSize: 13,
              width: isMobile ? '100%' : 'auto',
              background: 'var(--bg-elevated)',
              color: novels.length === 0 ? 'var(--text-muted)' : 'var(--text-primary)',
              border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            }}>＋ Add Chapters</button>
          <button onClick={() => setShowAdd(true)} style={{
            padding: isMobile ? '11px 16px' : '9px 16px', fontWeight: 700, fontSize: 13,
            width: isMobile ? '100%' : 'auto',
            background: 'linear-gradient(135deg,#059669,#0891b2)', color: '#fff',
            border: 'none', borderRadius: 'var(--radius-sm)',
          }}>＋ Add Novel</button>
        </div>
      </div>

      {/* ── LIVE CONSOLE (sticky, prominent) ─────────────────────────── */}
      {activeJob && (
        <div ref={consoleRef} style={{
          position: 'sticky', top: 0, zIndex: 20, marginBottom: 18,
          border: '1px solid rgba(56,189,248,0.4)', borderRadius: 10, overflow: 'hidden',
          boxShadow: '0 6px 28px rgba(0,0,0,0.5)',
        }}>
          {/* console title bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '8px 12px',
            background: 'linear-gradient(90deg,#0b1220,#111a2e)', borderBottom: '1px solid rgba(56,189,248,0.25)' }}>
            {!isMobile && <span style={{ display: 'flex', gap: 5 }}>
              <Dot c="#ff5f57" /><Dot c="#febc2e" /><Dot c="#28c840" />
            </span>}
            <span style={{ fontSize: isMobile ? 11 : 12, fontWeight: 700, color: '#dceeff',
              maxWidth: isMobile ? 160 : 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {isMobile ? '' : 'Pipeline Console — '}{activeJob.novel || activeJob.id}
            </span>
            <StatusPill status={activeJob.status} />
            {activeJob.started && <span style={{ fontSize: 11, color: '#7fd0ff' }}>⏱ {elapsed()}</span>}
            {activeJob.status === 'running' && <Spinner />}
            <div style={{ flex: 1 }} />
            {activeJob.error && !isMobile && <span style={{ fontSize: 11, color: '#f87171' }}>{activeJob.error}</span>}
            {(activeJob.status === 'running' || activeJob.status === 'queued') && activeJob.id !== 'queue' && (
              <button onClick={abortJob} disabled={aborting} title="Stop the pipeline now" style={{
                fontSize: 11, fontWeight: 700, padding: '2px 11px', borderRadius: 6,
                color: '#fff', background: aborting ? 'rgba(239,68,68,0.5)' : '#ef4444',
                border: '1px solid #ef4444', whiteSpace: 'nowrap',
              }}>{aborting ? 'Aborting…' : '⛔ Abort'}</button>
            )}
            <button onClick={() => setCompact(c => !c)} title="Collapse repetitive lines" style={consoleBtn(compact)}>
              {compact ? 'Compact' : 'Raw'}
            </button>
            <button onClick={() => setPipOn(v => !v)} title="Show the console as a live video (use the video's own button to float it)" style={consoleBtn(pipOn)}>
              {pipOn ? '▣ Video on' : '▣ Video'}
            </button>
            <button onClick={copyLog} title="Copy the full RAW log (never the compacted view)" style={consoleBtn(copied)}>
              {copied ? '✓ Copied raw' : '⎘ Copy raw'}
            </button>
            {(activeJob.status === 'done' || activeJob.status === 'error' || activeJob.status === 'aborted') && (
              <button onClick={() => setActiveJob(null)} style={consoleBtn(false)}>Close</button>
            )}
          </div>
          {pipOn && (
            <div style={{ background: '#05070d', borderBottom: '1px solid rgba(56,189,248,0.25)', padding: 8 }}>
              <video ref={videoRef} controls muted playsInline autoPlay
                style={{ width: '100%', display: 'block', aspectRatio: '16 / 9', background: '#05070d', borderRadius: 6 }} />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                <button onClick={floatVideo} style={consoleBtn(false)}>⧉ Float (picture-in-picture)</button>
                <button onClick={openInSafari} style={consoleBtn(false)} title="Floating needs Safari itself, not the Home Screen app">↗ Open in Safari</button>
                <span style={{ fontSize: 10.5, color: '#5b7a99' }}>Live video of this console.</span>
              </div>
            </div>
          )}
          {/* console body */}
          <div style={{
            height: isMobile ? 180 : 260, overflowY: 'auto', background: '#05070d', color: '#7fd0ff',
            padding: '10px 12px', fontFamily: 'Consolas, "SF Mono", monospace',
            fontSize: isMobile ? 10.5 : 11.5, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          }}>
            {(compact ? compactLog(activeJob.log || []) : (activeJob.log || [])).map((l, i) => (
              <div key={i} style={{ color: lineColor(l) }}>
                {lineSegments(l).map((sg, j) => <span key={j} style={{ color: sg.c, fontWeight: sg.c !== lineColor(l) ? 600 : 400 }}>{sg.t}</span>)}
              </div>
            ))}
            {activeJob.status === 'running' && (activeJob.log || []).length > 0 &&
              <div style={{ color: '#5b7a99' }}>▊ working…</div>}
            {(!activeJob.log || activeJob.log.length === 0) && <div style={{ opacity: 0.5 }}>starting…</div>}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {/* Interactive corpus brain */}
      <div style={{
        marginBottom: 20, padding: isMobile ? '8px 4px 6px' : '14px 10px 10px', borderRadius: 'var(--radius-lg)',
        background: 'radial-gradient(ellipse at center, #0b1220 0%, #070a12 75%)',
        border: '1px solid var(--border-soft)',
      }}>
        <BrainGraph height={isMobile ? 380 : 460} isMobile={isMobile} />
      </div>

      {/* Novel table / cards */}
      <div style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', overflow: 'hidden', marginBottom: 20 }}>
        {!isMobile && (
          <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 90px 90px 90px 1.4fr', gap: 8,
            padding: '9px 14px', background: 'var(--bg-surface)', fontSize: 10, fontWeight: 700,
            color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            <span>Novel</span><span>Raw</span><span>Extracted</span><span>Genome</span><span>Pipeline</span>
          </div>
        )}
        {novels.length === 0 && (
          <div style={{ padding: 20, fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No novels yet. Click “Add Novel” to upload raw chapter files.
          </div>
        )}
        {novels.map(n => (
          <NovelRow key={n.id} n={n} busy={busy} isMobile={isMobile} onRun={runNovel}
            onQueue={async (opts) => { await api.cbQueueAdd({ novel_id: n.id, nemotron_only: nemotronOnly, ...opts }); refresh() }} />
        ))}
      </div>

      {/* Queue */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 700 }}>Extraction Queue <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({queue.length})</span></span>
          {queue.some(q => q.status === 'pending') && (
            <button onClick={async () => {
              // Show a console immediately so it's obvious the queue started,
              // then attach to the real job the worker creates.
              // No `started` here either — attachRunningJob() swaps in the real
              // server job, and its server-stamped start time is the only
              // baseline the timer should ever use.
              setActiveJob({ id: 'queue', novel: 'queue', status: 'running', log: ['> starting queue…'] })
              setTimeout(() => consoleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
              await api.cbQueueRun()
              refresh()
              attachRunningJob()
            }} style={{
              padding: '6px 13px', fontWeight: 700, fontSize: 12,
              background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 'var(--radius-sm)',
            }}>▶ Run Queue</button>
          )}
        </div>
        {queue.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>Queue is empty.</div>
        )}
        {queue.map(q => (
          <div key={q.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
            border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-sm)', marginBottom: 6, fontSize: 12 }}>
            <StatusPill status={q.status} />
            <span style={{ fontWeight: 600 }}>{q.novel_id}</span>
            <span style={{ color: 'var(--text-muted)' }}>ch {q.start}–{q.end}</span>
            <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
              {[q.convert && 'convert', q.extract && 'extract', q.merge && 'merge', q.rolling_summary && 'summary', q.genome && 'genome'].filter(Boolean).join(' · ')}
            </span>
            <div style={{ flex: 1 }} />
            {q.error && <span style={{ fontSize: 10, color: 'var(--red)' }}>{q.error}</span>}
            <button onClick={async () => { await api.cbQueueRemove(q.id); refresh() }} style={{
              fontSize: 11, color: 'var(--text-muted)', padding: '2px 8px',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            }}>✕</button>
          </div>
        ))}
      </div>

      {showAdd && <AddNovelModal onClose={() => setShowAdd(false)} onDone={refresh} />}
      {showAddChapter && (
        <AddChapterModal
          novels={novels}
          onClose={() => setShowAddChapter(false)}
          onDone={async (run) => {
            await refresh()
            if (!run) return
            // The modal reports the exact chapter range it just wrote. Deriving
            // it here from next_chapter would be wrong: that field means "next
            // chapter to EXTRACT" (e.g. 101 on a novel with 200 raw files), so
            // it would re-run 100 already-extracted chapters.
            const { start, end } = run
            if (start && end && end >= start) {
              runNovel(run.novelId, {
                start, end,
                convert: true, extract: true, merge: true, rolling_summary: true, genome: true,
              })
            }
          }}
        />
      )}
    </div>
  )
}

function NovelRow({ n, busy, isMobile, onRun, onQueue }) {
  // One-click "next chapter": extract + merge that single chapter, then genome.
  const nextCh = n.next_chapter
  const hasNext = typeof nextCh === 'number'

  // Delta COUNT vs extraction FRONTIER. They match on a healthy novel, but an
  // aborted run can leave deltas far ahead of the unbroken run (ch5099-5105
  // extracted while the frontier was 226), and then the count alone reads as a
  // chapter number it isn't. Flag the divergence instead of hiding it.
  const outOfOrder = typeof n.extracted_through === 'number' &&
                     n.extracted_through < (n.extracted || 0)

  // Default the advanced range to start at the next un-extracted chapter
  // (e.g. 68–77), not 1–50, so you rarely need to change it.
  const defStart = hasNext ? nextCh : 1
  const defEnd = Math.min(defStart + 9, n.raw_chapters || defStart + 9)

  const [open, setOpen] = useState(false)
  const [adv, setAdv] = useState(false)
  const [start, setStart] = useState(defStart)
  const [end, setEnd] = useState(defEnd)
  const [steps, setSteps] = useState({ convert: (n.raw_html || 0) > 0, extract: true, merge: true, rolling_summary: true, genome: true })
  // Split extraction: 4 smaller LLM calls per chapter instead of 1. Defaults ON
  // (measured richer on every engine); the value is persisted to Settings so
  // the corpus scripts — which read the config, not this page — see it too.
  const [splitExtraction, setSplitExtraction] = useState(true)
  // V4: the same calls also extract the Chapter Mechanics (how each chapter is built). Needs split extraction.
  const [schemaV4, setSchemaV4] = useState(false)
  useEffect(() => {
    api.getSettings()
      .then(s => {
        const v = (s.generation || {}).split_extraction
        if (v !== undefined && v !== null) setSplitExtraction(!!v)
        setSchemaV4((s.generation || {}).extraction_schema === 'v4')
      })
      .catch(() => {})
  }, [])
  const nextOpts = {
    start: nextCh, end: nextCh,
    convert: (n.raw_html || 0) > 0, extract: true, merge: true, rolling_summary: true, genome: true,
  }

  // Keep the range following the next chapter as extraction progresses, unless
  // the user has manually opened Advanced and edited it.
  const [rangeTouched, setRangeTouched] = useState(false)
  useEffect(() => {
    if (!rangeTouched && hasNext) {
      setStart(nextCh)
      setEnd(Math.min(nextCh + 9, n.raw_chapters || nextCh + 9))
    }
  }, [nextCh])

  const pipelineBtn = (
    <button onClick={() => setOpen(o => !o)} style={{
      fontSize: 11, padding: isMobile ? '7px 12px' : '4px 10px', borderRadius: 'var(--radius-sm)',
      background: open ? 'var(--accent-dim)' : 'var(--bg-elevated)',
      border: `1px solid ${open ? 'var(--accent)' : 'var(--border)'}`, color: 'var(--text-secondary)',
    }}>⚙ Pipeline</button>
  )

  return (
    <div style={{ borderTop: '1px solid var(--border-soft)' }}>
      {isMobile ? (
        /* ── Mobile card header ── */
        <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontWeight: 700, fontSize: 13, wordBreak: 'break-word' }}>{n.id.replace(/_/g, ' ')}</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 11 }}>
            <Badge label="Raw" value={`${n.raw_chapters || 0}${n.raw_html ? ` +${n.raw_html}htm` : ''}`} />
            {/* Count and frontier diverge when deltas are non-contiguous, so
                show "N (to chM)" rather than letting N read as a chapter number. */}
            <Badge label="Extracted"
              value={outOfOrder ? `${n.extracted} (to ch${n.extracted_through})` : (n.extracted || 0)}
              good={n.extracted > 0} />
            <Badge label="Next" value={hasNext ? `ch${nextCh}` : '✓ done'} good={!hasNext} />
            <Badge label="Summary" value={n.has_rolling_summary ? '✓' : '—'} good={n.has_rolling_summary} />
            <Badge label="Genome" value={n.has_genome ? '✓' : '—'} good={n.has_genome} />
          </div>
          <div>{pipelineBtn}</div>
        </div>
      ) : (
        /* ── Desktop grid row ── */
        <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 90px 90px 90px 1.4fr', gap: 8,
          padding: '10px 14px', alignItems: 'center', fontSize: 12.5 }}>
          <span style={{ fontWeight: 600 }}>{n.id}</span>
          <span>{n.raw_chapters || 0}{n.raw_html ? ` (+${n.raw_html} htm)` : ''}</span>
          <span style={{ color: n.extracted > 0 ? 'var(--green)' : 'var(--text-muted)' }}>
            {n.extracted || 0}
            {/* "233" alone reads as "through ch233" when 7 of those deltas are
                really ch5099-5105 and the frontier is 226. Spell out the reach. */}
            {outOfOrder && (
              <span style={{ color: 'var(--amber)', fontSize: 10 }} title={`Deltas are non-contiguous: ${n.extracted} files, but chapters 1-${n.extracted_through} are the unbroken run`}>
                {' '}· to ch{n.extracted_through}
              </span>
            )}
            {hasNext && <span style={{ color: 'var(--text-muted)', fontSize: 10 }}> · next ch{nextCh}</span>}
          </span>
          <span>{n.has_genome ? <span style={{ color: 'var(--green)' }}>✓</span> : '—'}</span>
          <div style={{ display: 'flex', gap: 6 }}>{pipelineBtn}</div>
        </div>
      )}
      {open && (
        <div style={{ padding: isMobile ? '4px 14px 16px' : '8px 14px 14px', background: 'var(--bg-card)',
          display: 'flex', flexDirection: 'column', gap: 12 }}>

          {/* ── Primary: one-click Next Chapter ── */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
            {hasNext ? (
              <>
                <button disabled={busy} onClick={() => onRun(n.id, nextOpts)} style={{
                  fontSize: 13, fontWeight: 800, padding: isMobile ? '11px 18px' : '8px 18px', borderRadius: 'var(--radius-sm)',
                  background: 'linear-gradient(135deg,#059669,#0891b2)', color: '#fff', border: 'none',
                  flex: isMobile ? 1 : 'none',
                }}>▶ Extract Next (ch{nextCh})</button>
                <button onClick={() => onQueue(nextOpts)} title="Add ch{nextCh} to the queue" style={{
                  fontSize: 12, fontWeight: 700, padding: isMobile ? '11px 14px' : '8px 14px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
                }}>＋ Queue Next</button>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  extracts &amp; merges ch{nextCh}, then updates genome
                </span>
              </>
            ) : (
              <span style={{ fontSize: 12, color: 'var(--green)', fontWeight: 600 }}>
                ✓ All {n.raw_chapters} raw chapters extracted
              </span>
            )}

            {!isMobile && <div style={{ flex: 1 }} />}

            {/* Applies to BOTH run paths — the green Extract Next button and the
                Advanced custom-range run — so it lives here, not inside Advanced. */}
            <label
              title="Extract each chapter across 4 smaller LLM calls (prose / voice / plot / world) instead of one big call. Measured richer on every engine — Claude went 29.7 KB to 53.9 KB per chapter, prose samples 3 to 10 — but costs 4 API calls per chapter instead of 1. Partial runs are checkpointed, so an abort resumes where it stopped."
              style={{
                fontSize: 11, display: 'flex', gap: 5, alignItems: 'center',
                cursor: 'pointer', whiteSpace: 'nowrap',
                padding: '4px 9px', borderRadius: 'var(--radius-sm)',
                border: `1px solid ${splitExtraction ? 'var(--green)' : 'var(--border)'}`,
                color: splitExtraction ? 'var(--green)' : 'var(--text-muted)',
                background: 'var(--bg-elevated)', fontWeight: splitExtraction ? 700 : 500,
              }}>
              <input type="checkbox" checked={splitExtraction}
                onChange={e => {
                  const v = e.target.checked
                  setSplitExtraction(v)
                  // The extraction scripts run as separate processes and read this
                  // from the config file, so persist immediately rather than
                  // passing it through the job payload.
                  api.saveGenerationSettings({ split_extraction: v }).catch(() => {})
                }} />
              Split extraction {splitExtraction ? '(4 calls/ch)' : '(1 call/ch)'}
            </label>
            <label
              title="V4 extraction: the same 4 calls also extract the Chapter Mechanics (beats with their meaning, purpose and motive, cast roles, fights, scene joins, set-piece runs) into each chapter's delta. Needs split extraction; ignored on Ollama's 10-way plan. Untick to extract the plain V3 delta."
              style={{
                fontSize: 11, display: 'flex', gap: 5, alignItems: 'center',
                cursor: splitExtraction ? 'pointer' : 'not-allowed', whiteSpace: 'nowrap', opacity: splitExtraction ? 1 : 0.5,
                padding: '4px 9px', borderRadius: 'var(--radius-sm)',
                border: `1px solid ${schemaV4 && splitExtraction ? 'var(--green)' : 'var(--border)'}`,
                color: schemaV4 && splitExtraction ? 'var(--green)' : 'var(--text-muted)',
                background: 'var(--bg-elevated)', fontWeight: schemaV4 && splitExtraction ? 700 : 500,
              }}>
              <input type="checkbox" checked={schemaV4 && splitExtraction} disabled={!splitExtraction}
                onChange={e => {
                  const v = e.target.checked
                  setSchemaV4(v)
                  api.saveGenerationSettings({ extraction_schema: v ? 'v4' : 'v3' }).catch(() => {})
                }} />
              V4 + Chapter Mechanics
            </label>
          </div>

          {/* ── Advanced: custom range (collapsed by default) ── */}
          <button onClick={() => setAdv(a => !a)} style={{
            alignSelf: 'flex-start', fontSize: 10.5, color: 'var(--text-muted)',
            background: 'none', border: 'none', padding: 0, cursor: 'pointer',
          }}>{adv ? '▾ Hide advanced' : '▸ Advanced (custom range / steps)'}</button>

          {adv && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: isMobile ? 14 : 12, alignItems: 'center',
              paddingTop: 4, borderTop: '1px dashed var(--border-soft)' }}>
              <label style={{ fontSize: 11, display: 'flex', gap: 5, alignItems: 'center' }}>
                Chapters <input type="number" value={start} min={1} onChange={e => { setRangeTouched(true); setStart(+e.target.value) }} style={inpS} /> –
                <input type="number" value={end} min={1} onChange={e => { setRangeTouched(true); setEnd(+e.target.value) }} style={inpS} />
              </label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: isMobile ? 14 : 10 }}>
                {[['convert', 'Convert'], ['extract', 'Extract'], ['merge', 'Merge'], ['rolling_summary', 'Summary'], ['genome', 'Genome']].map(([s, label]) => (
                  <label key={s} style={{ fontSize: 11, display: 'flex', gap: 4, alignItems: 'center' }}>
                    <input type="checkbox" checked={steps[s]} onChange={e => setSteps(v => ({ ...v, [s]: e.target.checked }))} />{label}
                  </label>
                ))}
              </div>
              {!isMobile && <div style={{ flex: 1 }} />}
              <div style={{ display: 'flex', gap: 8, width: isMobile ? '100%' : 'auto' }}>
                <button disabled={busy} onClick={() => onRun(n.id, { start, end, ...steps })} style={{
                  fontSize: 12, fontWeight: 700, padding: isMobile ? '10px 14px' : '5px 14px', borderRadius: 'var(--radius-sm)',
                  flex: isMobile ? 1 : 'none',
                  background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
                }}>▶ Run Range</button>
                <button onClick={() => onQueue({ start, end, ...steps })} style={{
                  fontSize: 12, fontWeight: 700, padding: isMobile ? '10px 14px' : '5px 14px', borderRadius: 'var(--radius-sm)',
                  flex: isMobile ? 1 : 'none',
                  background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
                }}>＋ Queue Range</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Badge({ label, value, good }) {
  return (
    <span style={{
      display: 'inline-flex', gap: 4, alignItems: 'center',
      padding: '3px 8px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)',
    }}>
      <span style={{ color: 'var(--text-muted)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span style={{ fontWeight: 700, color: good ? 'var(--green)' : 'var(--text-primary)' }}>{value}</span>
    </span>
  )
}

function AddNovelModal({ onClose, onDone }) {
  const [title, setTitle] = useState('')
  const [novelId, setNovelId] = useState('')
  const [files, setFiles] = useState([])
  const [step, setStep] = useState('form')  // form | uploading | done
  const [msg, setMsg] = useState('')

  async function create() {
    if (!title.trim() && !novelId.trim()) { setMsg('Enter a title.'); return }
    setStep('uploading'); setMsg('')
    try {
      const res = await api.cbCreateNovel(title.trim(), novelId.trim())
      const nid = res.novel_id
      if (files.length > 0) {
        const up = await api.cbUpload(nid, files)
        setMsg(`Created “${nid}” · uploaded ${up.count} files`)
      } else {
        setMsg(`Created “${nid}”. Add raw files to raw/${nid}/ then run the pipeline.`)
      }
      setStep('done')
      onDone && onDone()
    } catch (e) {
      setMsg(e.message || 'Failed'); setStep('form')
    }
  }

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 300, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 14 }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 460, maxWidth: '100%', maxHeight: '90vh', overflowY: 'auto', background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 20 }}>
        <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 4 }}>Add Novel to Corpus</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 16 }}>
          Upload plain-text chapter files (.txt) that you wrote or have the right to use.
        </div>

        <label style={lbl}>Title</label>
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder="a reference novel" style={inp} />

        <label style={lbl}>Novel ID (optional)</label>
        <input value={novelId} onChange={e => setNovelId(e.target.value)} placeholder="auto from title" style={inp} />

        <label style={lbl}>Raw chapter files</label>
        <input type="file" multiple accept=".txt" onChange={e => setFiles([...e.target.files])}
          style={{ ...inp, padding: 6 }} />
        {files.length > 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>{files.length} file(s) selected</div>}

        {msg && <div style={{ fontSize: 11, color: step === 'done' ? 'var(--green)' : 'var(--red)', margin: '4px 0 8px' }}>{msg}</div>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 10 }}>
          <button onClick={onClose} style={{ fontSize: 12, padding: '7px 14px', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)' }}>
            {step === 'done' ? 'Close' : 'Cancel'}
          </button>
          {step !== 'done' && (
            <button onClick={create} disabled={step === 'uploading'} style={{ fontSize: 12, fontWeight: 700, padding: '7px 16px', background: 'linear-gradient(135deg,#059669,#0891b2)', color: '#fff', border: 'none', borderRadius: 'var(--radius-sm)' }}>
              {step === 'uploading' ? 'Creating…' : 'Create & Upload'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Add chapters to a novel in the corpus by uploading plain-text (.txt) chapter files you have the right to use.
 * They land in raw/<novel>/ with their filenames kept (name them ch1.txt, ch2.txt ... to control the numbering).
 */
function AddChapterModal({ novels, initialNovel, onClose, onDone }) {
  const [novelId, setNovelId] = useState(initialNovel || (novels[0]?.id ?? ''))
  const [files, setFiles] = useState([])
  const [runAfter, setRunAfter] = useState(true)
  const [step, setStep] = useState('form')         // form | working | done
  const [msg, setMsg] = useState('')

  const novel = novels.find(n => n.id === novelId)

  async function submit() {
    if (!novelId) { setMsg('Pick a novel.'); return }
    if (files.length === 0) { setMsg('Choose at least one .txt file.'); return }
    setStep('working'); setMsg('')
    try {
      const up = await api.cbUpload(novelId, files)
      setMsg(`Uploaded ${up.count} file(s) to raw/${novelId}/`)
      // Filenames are preserved on upload, so the range comes from the names themselves.
      const nums = (up.saved || [])
        .map(n => (String(n).match(/ch(\d+)/i) || [])[1])
        .filter(Boolean).map(Number)
      const range = nums.length ? { start: Math.min(...nums), end: Math.max(...nums) } : null
      if (up.count > 0 && runAfter && range) onDone && onDone({ novelId, ...range })
      else onDone && onDone(null)
      setStep('done')
    } catch (e) {
      setMsg(e.message || 'Failed'); setStep('form')
    }
  }

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 300, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 14 }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 520, maxWidth: '100%', maxHeight: '90vh', overflowY: 'auto', background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 20 }}>
        <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 4 }}>Add Chapters</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 16 }}>
          Upload plain-text chapters to a novel in your corpus. Only add text you wrote or have the right to use.
        </div>

        <label style={lbl}>Novel</label>
        <select value={novelId} onChange={e => setNovelId(e.target.value)} style={inp}>
          {novels.length === 0 && <option value="">No novels in corpus</option>}
          {novels.map(n => (
            <option key={n.id} value={n.id}>{n.id} ({n.raw_chapters} chapters)</option>
          ))}
        </select>
        {novel && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
            Name new files <b style={{ color: 'var(--accent)' }}>ch{novel.next_raw}.txt</b> onward
            {novel.extracted > 0 && ` · ${novel.extracted} extracted so far`}
          </div>
        )}

        <label style={lbl}>Chapter files (.txt)</label>
        <input type="file" multiple accept=".txt"
          onChange={e => setFiles([...e.target.files])} style={{ ...inp, padding: 6 }} />
        {files.length > 0 && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
            {files.length} file(s) selected. Filenames are kept as-is, so name them chN.txt to control chapter numbering.
          </div>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-secondary)', marginBottom: 10 }}>
          <input type="checkbox" checked={runAfter} onChange={e => setRunAfter(e.target.checked)} />
          Run the pipeline on the new chapters afterwards
        </label>

        {msg && <div style={{ fontSize: 11, color: step === 'done' ? 'var(--green)' : 'var(--amber)', marginBottom: 8 }}>{msg}</div>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 10 }}>
          <button onClick={onClose} style={{ fontSize: 12, padding: '7px 14px', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)' }}>
            {step === 'done' ? 'Close' : 'Cancel'}
          </button>
          {step !== 'done' && (
            <button onClick={submit} disabled={step === 'working' || !novelId} style={{
              fontSize: 12, fontWeight: 700, padding: '7px 16px',
              background: 'linear-gradient(135deg,#059669,#0891b2)', color: '#fff',
              border: 'none', borderRadius: 'var(--radius-sm)',
            }}>
              {step === 'working' ? 'Uploading…' : '＋ Add Chapters'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function StatusPill({ status }) {
  const map = {
    pending:  ['var(--text-muted)', 'Pending'],
    queued:   ['var(--text-muted)', 'Queued'],
    running:  ['var(--amber)', 'Running'],
    done:     ['var(--green)', 'Done'],
    error:    ['var(--red)', 'Error'],
    aborted:  ['#f87171', 'Aborted'],
  }
  const [color, label] = map[status] || ['var(--text-muted)', status || '?']
  return <span style={{ fontSize: 10, fontWeight: 700, color, border: `1px solid ${color}`, padding: '1px 7px', borderRadius: 10 }}>{label}</span>
}

function Dot({ c }) {
  return <span style={{ width: 10, height: 10, borderRadius: '50%', background: c, display: 'inline-block' }} />
}

function Spinner() {
  return (
    <span style={{
      width: 11, height: 11, borderRadius: '50%',
      border: '2px solid rgba(56,189,248,0.3)', borderTopColor: '#38bdf8',
      display: 'inline-block', animation: 'cb-spin 0.7s linear infinite',
    }}>
      <style>{'@keyframes cb-spin{to{transform:rotate(360deg)}}'}</style>
    </span>
  )
}

// Colour console lines by content for readability
// Audible chime when a pipeline process ends (success = pleasant two-tone,
// error/abort = lower buzz). Uses Web Audio so no sound file is needed.
// One shared AudioContext, unlocked on the first user gesture — a context
// created cold is 'suspended' by autoplay policy and plays NOTHING, which is
// why end-of-job chimes could be silent if you never clicked the page.
let _audioCtx = null
function _audio() {
  const AC = window.AudioContext || window.webkitAudioContext
  if (!AC) return null
  if (!_audioCtx) _audioCtx = new AC()
  if (_audioCtx.state === 'suspended') _audioCtx.resume().catch(() => {})
  return _audioCtx
}
if (typeof window !== 'undefined') {
  const unlock = () => { _audio(); window.removeEventListener('pointerdown', unlock) }
  window.addEventListener('pointerdown', unlock)
}

function chime(status) {
  try {
    const ctx = _audio()
    if (!ctx) return
    const good = status === 'done'
    // done → rising confirm triad; error/abort → low double-buzz
    const notes = good ? [660, 880, 1174] : [300, 200]
    notes.forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain()
      o.type = good ? 'sine' : 'square'
      o.frequency.value = f
      o.connect(g); g.connect(ctx.destination)
      const t = ctx.currentTime + i * 0.16
      g.gain.setValueAtTime(0.0001, t)
      g.gain.exponentialRampToValueAtTime(good ? 0.28 : 0.22, t + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.15)
      o.start(t); o.stop(t + 0.16)
    })
  } catch {}
}

function lineColor(l) {
  // strip a leading HH:MM:SS timestamp before matching
  const s = String(l).replace(/^\d{2}:\d{2}:\d{2}\s/, '')
  if (/error|fail|traceback|✗|exception|⚠/i.test(s)) return '#f87171'
  if (/\[OK\]|→ OK|✓|done|complete|success|FIXED|passed/i.test(s)) return '#34d399'
  if (/^\$ /.test(s)) return '#a78bfa'      // command / step headers
  if (/warn/i.test(s)) return '#fbbf24'
  return '#7fd0ff'
}


// ── per-part colours inside a console line ──
// The chapter tag ([ch147]) and the agent / key details (agent 2 (key 2), [agent 3 - key 3 - extract v3]) each get their own colour, so a
// line can be traced at a glance. Chapters cycle through a palette (neighbouring chapters differ); agents use the same colours as the
// Pipeline cards.
const CH_COLORS = ['#f9a8d4', '#fdba74', '#bef264', '#5eead4', '#93c5fd', '#d8b4fe', '#fda4af', '#fcd34d']
const AGENT_COLORS = ['#e07a5f', '#3d9be9', '#5cc8a1', '#e8b93a', '#a78bfa', '#f472b6']
function charColors(l) {
  const s = String(l)
  const cols = new Array(s.length).fill(lineColor(l))
  const paint = (re, pick) => {
    re.lastIndex = 0
    let m
    while ((m = re.exec(s))) { const c = pick(m); for (let i = m.index; i < m.index + m[0].length; i++) cols[i] = c }
  }
  paint(/\[ch(\d+)\]/g, m => CH_COLORS[Number(m[1]) % CH_COLORS.length])
  paint(/agent (\d+)(?: - key \d+| \(key \d+\))?/g, m => AGENT_COLORS[(Number(m[1]) - 1) % AGENT_COLORS.length])
  return cols
}
function lineSegments(l) {
  const s = String(l), cols = charColors(l), out = []
  let st = 0
  for (let i = 1; i <= s.length; i++) {
    if (i === s.length || cols[i] !== cols[st]) { out.push({ t: s.slice(st, i), c: cols[st] }); st = i }
  }
  return out
}

// Split a "HH:MM:SS rest" line into its timestamp + body.
function splitTs(s) {
  const m = /^(\d{2}:\d{2}:\d{2})\s(.*)$/.exec(String(s))
  return m ? { ts: m[1], body: m[2] } : { ts: '', body: String(s) }
}

// Compact view: ONE line per chapter for the repetitive extract chatter, and keep
// step headers / validation / merge results / errors each as their own line.
// Every kept line retains its timestamp. Everything else is passed through.
function compactLog(log) {
  const out = []
  // Drop the two per-chapter sub-step lines entirely; fold the [v3] Extracting +
  // [OK] pair into one "ch68 → OK  <path>" line, timestamped at the OK moment.
  let pendingCh = null   // { ts, ch } from a "[v3] Extracting chapter N" line

  for (const raw of log) {
    const { ts, body } = splitTs(raw)

    // sub-steps: noise — skip
    if (/^\s*-\s*(Programmatic style analysis|LLM full extraction)/i.test(body)) continue
    // merge per-chapter "Merging chN.json" — skip (the merge stats line stays)
    if (/^\s*Merging ch\d+\.json/i.test(body)) continue

    // extract header — remember the chapter, emit nothing yet
    let m = /^\[v3\]\s*Extracting chapter\s*(\d+)/i.exec(body)
    if (m) { pendingCh = { ts, ch: m[1] }; continue }

    // extract OK — fold into one line with the remembered chapter
    m = /^\[OK\]\s*(.*ch0*\d+\.json)/i.exec(body)
    if (m && pendingCh) {
      out.push(`${ts || pendingCh.ts} ch${pendingCh.ch} → OK  ${m[1]}`)
      pendingCh = null
      continue
    }
    // extract ERROR after a header — fold too
    if (pendingCh && /error|fail|cap|limit/i.test(body)) {
      out.push(`${ts || pendingCh.ts} ch${pendingCh.ch} ✗ ${body.replace(/^\[ERROR\]\s*Ch\d+:\s*/i, '')}`)
      pendingCh = null
      continue
    }

    // everything else (step headers "$ …", "chN: OK (x/y)", merge stats, verify,
    // genome, errors, warnings) — keep verbatim, with its timestamp.
    out.push(raw)
  }
  // if an extract header had no matching OK yet (still running), surface it
  if (pendingCh) out.push(`${pendingCh.ts} ch${pendingCh.ch} …extracting`)
  return out
}

function consoleBtn(active) {
  return {
    fontSize: 11, fontWeight: 600, padding: '2px 9px', borderRadius: 6,
    color: active ? '#34d399' : '#9fd4ff',
    background: 'rgba(56,189,248,0.12)',
    border: `1px solid ${active ? 'rgba(52,211,153,0.5)' : 'rgba(56,189,248,0.3)'}`,
    whiteSpace: 'nowrap',
  }
}

const inp = { width: '100%', padding: '7px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)', marginBottom: 12 }
const inpS = { width: 56, padding: '3px 6px', fontSize: 11, borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }
const lbl = { display: 'block', fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }
