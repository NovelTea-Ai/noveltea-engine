import { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api'

// Server page — a Task-Manager-style view of this machine (CPU / memory / disk /
// network) plus the list of processes THIS APP is responsible for, so a stale one
// hogging RAM or CPU can be ended from here. The list is built by the backend
// (routers/server.py) and only ever contains the app itself, things it spawned,
// its scripts/jobs and Ollama — never unrelated programs.

const HISTORY = 60          // samples kept per graph (2s apart = 2 minutes)
const METRICS_MS = 2000
const PROCS_MS = 4000

const GB = 1024 ** 3, MB = 1024 ** 2
const fmtBytes = b => (b == null ? '—' : b >= GB ? `${(b / GB).toFixed(1)} GB` : b >= MB ? `${Math.round(b / MB)} MB` : `${Math.round(b / 1024)} KB`)
const fmtRate = b => (b == null ? '—' : b >= MB ? `${(b / MB).toFixed(1)} MB/s` : b >= 1024 ? `${Math.round(b / 1024)} KB/s` : `${Math.round(b)} B/s`)
const fmtUptime = s => {
  if (s == null) return '—'
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : m ? `${m}m` : `${Math.floor(s)}s`
}

const COLORS = { cpu: '#38bdf8', memory: '#a78bfa', disk: '#34d399', network: '#f59e0b' }

// Filled line chart, newest sample at the right edge (like Task Manager).
function AreaChart({ data, max, color, height = 140, grid = true }) {
  const W = 600, H = 100
  const pts = data.slice(-HISTORY)
  const top = max || Math.max(1, ...pts)
  const off = HISTORY - pts.length
  const xy = (v, i) => [((off + i) / (HISTORY - 1)) * W, H - Math.min(1, Math.max(0, v / top)) * H]
  const line = pts.map((v, i) => xy(v, i).join(',')).join(' ')
  const area = pts.length ? `${xy(pts[0], 0)[0]},${H} ${line} ${xy(pts[pts.length - 1], pts.length - 1)[0]},${H}` : ''
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height, display: 'block', background: 'var(--bg-elevated)', borderRadius: 6 }}>
      {grid && [1, 2, 3].map(i => <line key={`h${i}`} x1="0" x2={W} y1={(H / 4) * i} y2={(H / 4) * i} stroke="var(--border-soft)" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />)}
      {grid && [1, 2, 3, 4, 5].map(i => <line key={`v${i}`} y1="0" y2={H} x1={(W / 6) * i} x2={(W / 6) * i} stroke="var(--border-soft)" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />)}
      {pts.length > 1 && <polygon points={area} fill={color} opacity="0.22" />}
      {pts.length > 1 && <polyline points={line} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />}
    </svg>
  )
}

function Tile({ id, active, onClick, title, value, sub, data, max }) {
  return (
    <button onClick={() => onClick(id)} style={{
      textAlign: 'left', padding: 10, borderRadius: 8, cursor: 'pointer',
      background: active ? 'var(--bg-elevated)' : 'transparent',
      border: `1px solid ${active ? COLORS[id] : 'var(--border-soft)'}`, display: 'flex', flexDirection: 'column', gap: 6,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{title}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: COLORS[id] }}>{value}</span>
      </div>
      <AreaChart data={data} max={max} color={COLORS[id]} height={38} grid={false} />
      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{sub}</div>
    </button>
  )
}

function Stat({ label, value, color }) {
  return (
    <div style={{ minWidth: 120 }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 600, color: color || 'var(--text-primary)' }}>{value}</div>
    </div>
  )
}

const card = { background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 16 }
const btn = (color) => ({
  padding: '5px 12px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)', cursor: 'pointer',
  background: 'var(--bg-elevated)', color, border: `1px solid ${color}`,
})

export default function ServerPage() {
  const [m, setM] = useState(null)
  const [procs, setProcs] = useState(null)
  const [err, setErr] = useState('')
  const [sel, setSel] = useState('memory')
  const [hist, setHist] = useState({ cpu: [], memory: [], disk: [], network: [] })
  const [confirm, setConfirm] = useState(null)   // pid awaiting a second click
  const [busy, setBusy] = useState(null)
  const [note, setNote] = useState('')
  const noteTimer = useRef(null)

  const flash = useCallback((msg) => {
    setNote(msg)
    clearTimeout(noteTimer.current)
    noteTimer.current = setTimeout(() => setNote(''), 8000)
  }, [])

  const pollMetrics = useCallback(async () => {
    try {
      const d = await api.serverMetrics()
      setM(d); setErr('')
      setHist(h => {
        const push = (arr, v) => [...arr, v].slice(-HISTORY)
        return {
          cpu: push(h.cpu, d.cpu.percent),
          memory: push(h.memory, d.memory.percent),
          disk: push(h.disk, d.disk.read_bps + d.disk.write_bps),
          network: push(h.network, d.network.sent_bps + d.network.recv_bps),
        }
      })
    } catch (e) { setErr('Server not reachable — is the NovelTea Engine backend running?') }
  }, [])

  const pollProcs = useCallback(async () => {
    try { setProcs(await api.serverProcesses()) } catch { /* covered by the metrics error */ }
  }, [])

  useEffect(() => {
    pollMetrics(); pollProcs()
    const a = setInterval(() => { if (!document.hidden) pollMetrics() }, METRICS_MS)
    const b = setInterval(() => { if (!document.hidden) pollProcs() }, PROCS_MS)
    return () => { clearInterval(a); clearInterval(b); clearTimeout(noteTimer.current) }
  }, [pollMetrics, pollProcs])

  async function endProcess(p) {
    if (confirm !== p.pid) { setConfirm(p.pid); setTimeout(() => setConfirm(c => (c === p.pid ? null : c)), 4000); return }
    setConfirm(null); setBusy(p.pid)
    try {
      const r = await api.serverKill(p.pid)
      flash(`Ended ${r.label || p.label} (PID ${p.pid}) — freed ${fmtBytes(r.freed_bytes)}`)
    } catch (e) { flash(`Couldn't end PID ${p.pid}: ${String(e.message || e).slice(0, 160)}`) }
    finally { setBusy(null); pollProcs(); pollMetrics() }
  }

  async function endStale() {
    setBusy('stale')
    try {
      const r = await api.serverKillStale()
      flash(r.ended.length ? `Ended ${r.ended.length} stale process(es) — freed ${fmtBytes(r.freed_bytes)}` : 'Nothing stale to end.')
    } catch (e) { flash(`Failed: ${String(e.message || e).slice(0, 160)}`) }
    finally { setBusy(null); pollProcs(); pollMetrics() }
  }

  async function unloadOllama() {
    setBusy('ollama')
    try {
      const r = await api.serverUnloadOllama()
      flash(r.unloaded.length ? `Unloaded from Ollama: ${r.unloaded.join(', ')}` : 'Ollama had no models loaded.')
    } catch (e) { flash(`Ollama: ${String(e.message || e).slice(0, 160)}`) }
    finally { setBusy(null); pollProcs(); pollMetrics() }
  }

  async function unloadColibri() {
    setBusy('colibri')
    try {
      const r = await api.serverUnloadColibri()
      flash(!r.was_loaded ? 'Colibrì had no model loaded.'
        : r.still_running ? 'Colibrì: stopped, but a process is still running — end it in the list below.'
        : `Unloaded Colibrì (${r.unloaded.join(', ')}) — freed ${fmtBytes(r.freed_bytes)}`)
    } catch (e) { flash(`Colibrì: ${String(e.message || e).slice(0, 160)}`) }
    finally { setBusy(null); pollProcs(); pollMetrics() }
  }

  const mem = m?.memory, cpu = m?.cpu, disk = m?.disk, net = m?.network
  const totals = procs?.totals
  const hasOllama = (procs?.processes || []).some(p => p.category === 'ollama')
  const hasColibri = (procs?.processes || []).some(p => p.category === 'colibri')

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>Server</h2>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>
            Live machine load, and everything this app has started — end anything stale to get its RAM and CPU back.
          </div>
        </div>
        {m && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Server up {fmtUptime(Date.now() / 1000 - m.server.started)} · PC up {fmtUptime(Date.now() / 1000 - m.boot_time)}
          {m.clients?.length ? ` · ${m.clients.length} client${m.clients.length > 1 ? 's' : ''} connected` : ''}
        </div>}
      </div>

      {err && <div style={{ ...card, borderColor: 'var(--red)', color: 'var(--red)', fontSize: 12 }}>{err}</div>}
      {note && <div style={{ ...card, padding: '10px 14px', fontSize: 12, color: 'var(--green)', borderColor: 'var(--green)' }}>{note}</div>}

      {/* Performance — tiles on the left, detail on the right */}
      <div style={{ ...card, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: '1 1 210px', maxWidth: 260 }}>
          <Tile id="cpu" active={sel === 'cpu'} onClick={setSel} title="CPU" data={hist.cpu} max={100}
            value={cpu ? `${cpu.percent}%` : '—'} sub={cpu ? `${cpu.mhz ? (cpu.mhz / 1000).toFixed(2) + ' GHz' : ''} · ${cpu.cores} cores / ${cpu.threads} threads` : ''} />
          <Tile id="memory" active={sel === 'memory'} onClick={setSel} title="Memory" data={hist.memory} max={100}
            value={mem ? `${mem.percent}%` : '—'} sub={mem ? `${fmtBytes(mem.used)} / ${fmtBytes(mem.total)}` : ''} />
          <Tile id="disk" active={sel === 'disk'} onClick={setSel} title={`Disk (${disk?.path || 'C:'})`} data={hist.disk}
            value={disk ? `${disk.percent}% full` : '—'} sub={disk ? `R ${fmtRate(disk.read_bps)} · W ${fmtRate(disk.write_bps)}` : ''} />
          <Tile id="network" active={sel === 'network'} onClick={setSel} title="Network" data={hist.network}
            value={net ? fmtRate(net.sent_bps + net.recv_bps) : '—'} sub={net ? `↑ ${fmtRate(net.sent_bps)} · ↓ ${fmtRate(net.recv_bps)}` : ''} />
        </div>

        <div style={{ flex: '3 1 340px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 20, fontWeight: 700 }}>{{ cpu: 'CPU', memory: 'Memory', disk: 'Disk', network: 'Network' }[sel]}</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {sel === 'memory' ? `${fmtBytes(mem?.total)} total` : sel === 'cpu' ? 'utilization, last 2 min' : 'last 2 min'}
            </span>
          </div>
          <AreaChart data={hist[sel]} max={sel === 'cpu' || sel === 'memory' ? 100 : undefined} color={COLORS[sel]} height={170} />

          {sel === 'memory' && mem && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 20px' }}>
              <Stat label="In use" value={fmtBytes(mem.used)} color={COLORS.memory} />
              <Stat label="Available" value={fmtBytes(mem.available)} />
              <Stat label="Committed" value={`${fmtBytes(mem.committed)} / ${fmtBytes(mem.commit_limit)}`} />
              <Stat label="Cached" value={fmtBytes(mem.cached)} />
              <Stat label="Paged pool" value={fmtBytes(mem.paged_pool)} />
              <Stat label="Non-paged pool" value={fmtBytes(mem.nonpaged_pool)} />
            </div>
          )}
          {sel === 'cpu' && cpu && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 20px' }}>
                <Stat label="Utilization" value={`${cpu.percent}%`} color={COLORS.cpu} />
                <Stat label="Speed" value={cpu.mhz ? `${(cpu.mhz / 1000).toFixed(2)} GHz` : '—'} />
                <Stat label="Cores" value={cpu.cores} />
                <Stat label="Logical processors" value={cpu.threads} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(70px, 1fr))', gap: 6 }}>
                {cpu.per_core.map((v, i) => (
                  <div key={i} title={`Logical processor ${i}: ${v}%`} style={{ background: 'var(--bg-elevated)', borderRadius: 4, height: 22, position: 'relative', overflow: 'hidden' }}>
                    <div style={{ position: 'absolute', inset: 0, width: `${v}%`, background: COLORS.cpu, opacity: 0.55 }} />
                    <span style={{ position: 'relative', fontSize: 9, padding: '0 5px', lineHeight: '22px', color: 'var(--text-primary)' }}>{i} · {Math.round(v)}%</span>
                  </div>
                ))}
              </div>
            </>
          )}
          {sel === 'disk' && disk && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 20px' }}>
              <Stat label="Used" value={`${fmtBytes(disk.used)} of ${fmtBytes(disk.total)}`} color={COLORS.disk} />
              <Stat label="Read" value={fmtRate(disk.read_bps)} />
              <Stat label="Write" value={fmtRate(disk.write_bps)} />
            </div>
          )}
          {sel === 'network' && net && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 20px' }}>
                <Stat label="Send" value={fmtRate(net.sent_bps)} color={COLORS.network} />
                <Stat label="Receive" value={fmtRate(net.recv_bps)} />
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Connected to this server: {m.clients?.length
                  ? m.clients.map(c => `${c.ip} (${c.kind}${c.connections > 1 ? `, ${c.connections} conn.` : ''})`).join(' · ')
                  : 'no clients right now'}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Processes this app is responsible for */}
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700 }}>Processes started by NovelTea Engine</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              {totals ? `${totals.count} running · ${fmtBytes(totals.memory_bytes)} RAM · ${totals.cpu_percent}% CPU` : 'loading…'}
              {totals?.stale ? ` · ${totals.stale} stale` : ''}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {hasOllama && (
              <button onClick={unloadOllama} disabled={busy === 'ollama'} style={btn('var(--accent)')}
                title="Drop every loaded model from Ollama's memory without ending Ollama — they reload on the next request">
                {busy === 'ollama' ? '…' : 'Unload Ollama models'}
              </button>
            )}
            {/* always shown (unlike Ollama's): greyed out while no Colibrì model is loaded */}
            <button onClick={unloadColibri} disabled={busy === 'colibri' || !hasColibri}
              style={{ ...btn('var(--accent)'), opacity: hasColibri ? 1 : 0.45, cursor: hasColibri ? 'pointer' : 'default' }}
              title={hasColibri
                ? 'Stop the local Colibrì model server and give back the RAM it holds — it loads again on the next Colibrì request, or with Start in Settings'
                : 'No Colibrì model is loaded right now — nothing to unload'}>
              {busy === 'colibri' ? '…' : 'Unload Colibrì model'}
            </button>
            <button onClick={endStale} disabled={busy === 'stale' || !totals?.stale}
              style={{ ...btn('var(--red)'), opacity: totals?.stale ? 1 : 0.45, cursor: totals?.stale ? 'pointer' : 'default' }}
              title="End every process currently flagged stale">
              {busy === 'stale' ? '…' : `End all stale${totals?.stale ? ` (${totals.stale})` : ''}`}
            </button>
          </div>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--text-muted)', fontSize: 10 }}>
                {['Process', 'PID', 'CPU', 'Memory', 'Running', 'Status', ''].map(h => <th key={h} style={{ padding: '6px 8px', fontWeight: 600 }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {(procs?.processes || []).map(p => (
                <tr key={p.pid} style={{ borderTop: '1px solid var(--border-soft)' }}>
                  <td style={{ padding: '7px 8px', maxWidth: 320 }} title={p.command || p.name}>
                    <div style={{ fontWeight: 600 }}>{p.label}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</div>
                  </td>
                  <td style={{ padding: '7px 8px', fontFamily: 'monospace', color: 'var(--text-muted)' }}>{p.pid}</td>
                  <td style={{ padding: '7px 8px' }}>{p.cpu_percent}%</td>
                  <td style={{ padding: '7px 8px', fontWeight: 600 }}>{fmtBytes(p.memory_bytes)}</td>
                  <td style={{ padding: '7px 8px', color: 'var(--text-secondary)' }}>{fmtUptime(p.uptime_s)}</td>
                  <td style={{ padding: '7px 8px' }}>
                    {p.stale ? <span title={p.stale_reason} style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 10, color: 'var(--red)', background: 'var(--red-dim, rgba(239,68,68,0.12))' }}>STALE</span>
                      : p.idle ? <span title={`No CPU activity for ${fmtUptime(p.idle_for_s)}`} style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 10, color: 'var(--amber)', background: 'var(--amber-dim, rgba(245,158,11,0.12))' }}>IDLE</span>
                      : <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 10, color: 'var(--green)', background: 'var(--green-dim, rgba(34,197,94,0.12))' }}>ACTIVE</span>}
                  </td>
                  <td style={{ padding: '7px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {p.protected
                      ? <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>this server</span>
                      : <button onClick={() => endProcess(p)} disabled={busy === p.pid}
                          style={confirm === p.pid ? { ...btn('#fff'), background: 'var(--red)', borderColor: 'var(--red)' } : btn('var(--red)')}>
                          {busy === p.pid ? '…' : confirm === p.pid ? 'Click again to confirm' : 'End'}
                        </button>}
                  </td>
                </tr>
              ))}
              {procs && !procs.processes.length && (
                <tr><td colSpan={7} style={{ padding: 14, color: 'var(--text-muted)', textAlign: 'center' }}>Nothing started by NovelTea Engine is running.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 10, lineHeight: 1.6 }}>
          Only the NovelTea Engine server, things it started, its pipeline / training scripts and Ollama are listed — nothing else on this PC.
          A process is <b>idle</b> after 2 minutes with no CPU work and <b>stale</b> after 15 (or if it's a leftover copy of the app).
          Ending Ollama's server stops embeddings and local models until it's started again — <b>Unload Ollama models</b> frees the RAM without that.
        </div>
      </div>
    </div>
  )
}
