import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import useStore from '../../store/useStore'

const FLAG_LABELS = {
  thin: 'thin extraction', reveals_unconfirmed: 'no reveals (unconfirmed)', reveals_confirmed_none: 'no reveals (confirmed none)',
  knowledge_unconfirmed: 'no knowledge state (unconfirmed)', few_dialogue: 'few dialogue samples', short_summary: 'short summary',
  prose_not_verbatim: 'excerpts not verbatim', dialogue_not_verbatim: 'quotes not verbatim', style_dna_empty: 'style DNA empty',
  style_dna_zero: 'style DNA empty', title_is_header: 'page header as title', guessed_scheme_refs: 'guessed scheme chapters',
  schema_incomplete: 'missing fields',
}
const FLAG_HELP = {
  thin: 'Bottom tier: fewer facts/reveals/timeline/dialogue/glossary than most chapters in the corpus (per 10k characters).',
  reveals_unconfirmed: 'Zero reveals in a chapter of normal length and nobody ever checked whether it truly has none — it may be a miss. The Empty-field Check card settles it.',
  reveals_confirmed_none: 'Zero reveals, and the model checked and confirmed the chapter genuinely has none — not a problem.',
  knowledge_unconfirmed: 'No knowledge-state entries and never ruled on (mostly older extractions from before the field existed).',
  few_dialogue: 'Fewer than 5 dialogue samples.',
  schema_incomplete: 'The delta is missing keys newer extractions have (knowledge_state or style_dna).',
  guessed_scheme_refs: 'A scheme names a setup/payoff chapter other than this one — the chapter text rarely states that, so it is a guess.',
  title_is_header: 'chapter_title holds the page header ("… Chapter 65") rather than a real title.',
  prose_not_verbatim: 'Prose excerpts that are not actually in the chapter text (paraphrased?).',
  dialogue_not_verbatim: 'Dialogue quotes that are not actually in the chapter text.',
}

// Delta Upgrade card only — the "which chapters could be upgraded?" scan (no LLM, ~25s for the whole corpus).
// Results come from corpus/delta_quality.json, which is also refreshed automatically after each extraction.
function DeltaScanPanel() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [lock, setLock] = useState(null)   // null = not loaded yet; else "auto" | "haiku" | "nemotron_lightning"
  const [lowEffort, setLowEffort] = useState(null)   // null = not loaded yet
  const [lockBusy, setLockBusy] = useState(false)
  const running = !!data?.job?.running

  const load = useCallback(async () => {
    try { setData(await api.deltaAuditStatus()); setErr('') } catch (e) { setErr(e.message || 'failed') }
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!running) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [running, load])
  useEffect(() => {
    api.deltaUpgradeConfigGet()
      .then(r => { setLock(r.lock || 'auto'); setLowEffort(r.claude_effort === 'low') })
      .catch(() => { setLock('auto'); setLowEffort(false) })
  }, [])

  async function scan() {
    try { await api.deltaAuditRun(); await load() } catch (e) { setErr(e.message || 'failed to start') }
  }

  // Checking one un-checks the other -- upgrade_deltas_config.json's "model" is a single value,
  // so these two locks are mutually exclusive; un-checking the active one goes back to "auto".
  async function setClaudeLowEffort(checked) {
    setLockBusy(true)
    try { await api.deltaUpgradeEffortSet(checked ? 'low' : null); setLowEffort(checked) }
    catch (err2) { setErr(err2.message || 'failed to save') }
    finally { setLockBusy(false) }
  }

  async function setGatedLock(which, checked) {
    const next = checked ? which : 'auto'
    setLockBusy(true)
    try { await api.deltaUpgradeConfigSet(next); setLock(next) }
    catch (err2) { setErr(err2.message || 'failed to save') }
    finally { setLockBusy(false) }
  }

  const rows = data?.novels || []
  const shown = showAll ? rows : rows.slice(0, 8)
  const th = { textAlign: 'left', padding: '4px 6px', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', fontSize: 9, letterSpacing: '0.06em' }
  const tiers = data?.tiers || {}
  const tierTotal = (tiers.A || 0) + (tiers.B || 0) + (tiers.C || 0) || 1

  return (
    <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700 }}>Upgrade scan</div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
            Scores every extracted chapter against the whole corpus and lists what could be upgraded — no LLM, about 25 seconds.
            {data?.generated ? ` Last scan: ${data.generated}.` : ' Not scanned yet.'}
          </div>
          <label title="Skips whichever engine is selected up top and forces Haiku for every Delta Upgrade call. Targeted (single/few-field) chapters get an adaptive topup, checked after every pass, that stops as soon as the field clears the corpus's normal range — up to 3 Haiku passes; still short after that, one finishing pass on Sonnet 5 instead of settling for Haiku's best. Broad 'thin' chapters still get a fixed 3 Haiku passes per group (no Sonnet escalation there). Much faster per call than Nemotron/Sonnet via the CLI for the common case, at Haiku's quality — takes effect on the job's NEXT launch, not one already running."
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: 'var(--text-secondary)', marginTop: 6, cursor: lock === null ? 'default' : 'pointer', opacity: lockBusy ? 0.6 : 1 }}>
            <input type="checkbox" checked={lock === 'haiku'} disabled={lock === null || lockBusy}
              onChange={(e) => setGatedLock('haiku', e.target.checked)}
              style={{ width: 13, height: 13, cursor: 'pointer' }} />
            Hard-lock to Haiku (gated topup, escalates to Sonnet 5)
          </label>
          <label title="Same idea as the Haiku lock, using NVIDIA's own two tiers instead: forces Nemotron Lightning 30B for every Delta Upgrade call. Targeted (single/few-field) chapters get the same adaptive topup — up to 3 checked Lightning passes, still short after that -> one finishing pass on Nemotron Ultra 550B. Broad 'thin' chapters get a fixed 3 Lightning passes per group (no Ultra escalation there). Lightning is small/fast; whether it's actually faster than the CLI-bound Claude models on this account depends on your Nemotron API key pool, not the CLI — takes effect on the job's NEXT launch, not one already running."
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: 'var(--text-secondary)', marginTop: 4, cursor: lock === null ? 'default' : 'pointer', opacity: lockBusy ? 0.6 : 1 }}>
            <input type="checkbox" checked={lock === 'nemotron_lightning'} disabled={lock === null || lockBusy}
              onChange={(e) => setGatedLock('nemotron_lightning', e.target.checked)}
              style={{ width: 13, height: 13, cursor: 'pointer' }} />
            Hard-lock to Nemotron Lightning (gated topup, escalates to Ultra)
          </label>
          <label title="Every Claude call Delta Upgrade makes (the selected Claude model, the Haiku lock, and its Sonnet finishing pass) runs with the Claude CLI's --effort low: quicker replies and lighter on your subscription's limits, with less careful reasoning on hard chapters. Nemotron calls are unaffected. Unlike the locks, this takes effect on the very next call, even in a run that's already going."
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: 'var(--text-secondary)', marginTop: 4, cursor: lowEffort === null ? 'default' : 'pointer', opacity: lockBusy ? 0.6 : 1 }}>
            <input type="checkbox" checked={!!lowEffort} disabled={lowEffort === null || lockBusy}
              onChange={(e) => setClaudeLowEffort(e.target.checked)}
              style={{ width: 13, height: 13, cursor: 'pointer' }} />
            Claude: low effort (faster, lighter on limits)
          </label>
        </div>
        <button onClick={scan} disabled={running} style={{
          padding: '5px 12px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)', cursor: running ? 'default' : 'pointer',
          background: 'var(--bg-elevated)', color: 'var(--accent)', border: '1px solid var(--accent)', opacity: running ? 0.6 : 1,
        }}>{running ? <><Spinner size={10} /> Scanning…</> : '🔍 Scan for upgrades'}</button>
      </div>

      {(err || (data?.job?.ok === false && data?.job?.error)) && (
        <div style={{ fontSize: 11, color: 'var(--red)' }}>{err || `Scan failed: ${data.job.error}`}</div>
      )}

      {data?.scanned && (
        <>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 18px', fontSize: 11 }}>
            <span><b>{data.total.toLocaleString()}</b> chapters</span>
            <span style={{ color: 'var(--accent)' }}><b>{data.candidates.toLocaleString()}</b> upgrade candidates</span>
            <span style={{ color: 'var(--green)' }}><b>{data.upgraded.toLocaleString()}</b> already upgraded</span>
            <span style={{ color: 'var(--text-muted)' }} title="Tiers are relative to the whole corpus, so about a third fall in C by design">
              tiers: A {tiers.A || 0} · B {tiers.B || 0} · C {tiers.C || 0}
            </span>
          </div>
          <div style={{ display: 'flex', height: 5, borderRadius: 3, overflow: 'hidden', background: 'rgba(255,255,255,0.06)' }}>
            <div style={{ width: `${100 * (tiers.A || 0) / tierTotal}%`, background: 'var(--green)' }} />
            <div style={{ width: `${100 * (tiers.B || 0) / tierTotal}%`, background: 'var(--amber)' }} />
            <div style={{ width: `${100 * (tiers.C || 0) / tierTotal}%`, background: 'var(--red)' }} />
          </div>

          {/* Nothing-there vs. missed-it: an empty field is "confirmed none" only if the model looked and said so
              (delta.confirmed_empty); otherwise nobody knows. */}
          {data.empty_fields && (
            <div style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 4 }}>
                Empty fields — genuinely nothing there, or missed?
              </div>
              <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                <thead><tr style={{ color: 'var(--text-muted)', fontSize: 9, textTransform: 'uppercase' }}>
                  <th style={{ textAlign: 'left', padding: '2px 4px', fontWeight: 700 }}>Field</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px', fontWeight: 700 }} title="The model looked at the chapter and answered none">Confirmed none</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px', fontWeight: 700 }} title="Empty and never ruled on — could be a miss">Unconfirmed</th>
                </tr></thead>
                <tbody>
                  {['reveals', 'knowledge_state', 'character_voice_samples', 'prose_samples', 'facts', 'timeline_events'].map(k => {
                    const e = data.empty_fields[k] || { confirmed_none: 0, unconfirmed: 0 }
                    return (
                      <tr key={k} style={{ borderTop: '1px solid var(--border-soft)' }}>
                        <td style={{ padding: '3px 4px', color: 'var(--text-primary)' }}>{k.replace(/_/g, ' ')}</td>
                        <td style={{ padding: '3px 4px', textAlign: 'right', color: 'var(--green)' }}>{e.confirmed_none}</td>
                        <td style={{ padding: '3px 4px', textAlign: 'right', fontWeight: 700, color: e.unconfirmed ? 'var(--amber)' : 'var(--text-muted)' }}>{e.unconfirmed}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 5 }}>
                {data.resolve_chapters} chapter(s) have an important field that is empty and unchecked — run the <b>Empty-field Check</b> card to settle each one
                (it fills the field, or records that the chapter genuinely has none).
              </div>
            </div>
          )}

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {Object.entries(data.flags || {}).map(([f, n]) => (
              <span key={f} title={FLAG_HELP[f] || ''} style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 10, background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
              }}>{FLAG_LABELS[f] || f} <b style={{ color: 'var(--text-primary)' }}>{n}</b></span>
            ))}
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-soft)' }}>
                  <th style={th}>Novel (lowest average first)</th>
                  <th style={{ ...th, textAlign: 'right' }}>Chapters</th>
                  <th style={{ ...th, textAlign: 'right' }} title="Average richness score, 0-100">Score</th>
                  <th style={{ ...th, textAlign: 'right' }}>Candidates</th>
                  <th style={th}>Main problems</th>
                </tr>
              </thead>
              <tbody>
                {shown.map(n => (
                  <tr key={n.novel_id} style={{ borderBottom: '1px solid var(--border-soft)' }}>
                    <td style={{ padding: '5px 6px', color: 'var(--text-primary)' }}>{n.novel_id}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', color: 'var(--text-secondary)' }}>{n.chapters}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', fontWeight: 700,
                      color: n.mean_score < 35 ? 'var(--red)' : n.mean_score < 55 ? 'var(--amber)' : 'var(--green)' }}>{n.mean_score}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', color: 'var(--accent)' }}>
                      {n.candidates}{n.upgraded ? <span style={{ color: 'var(--green)' }} title="already upgraded"> (+{n.upgraded} done)</span> : ''}
                    </td>
                    <td style={{ padding: '5px 6px', color: 'var(--text-muted)', fontSize: 10 }}>
                      {Object.entries(n.top_flags || {}).map(([f, c]) => `${FLAG_LABELS[f] || f} ${c}`).join(' · ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > 8 && (
            <button onClick={() => setShowAll(s => !s)} style={{ alignSelf: 'flex-start', fontSize: 10, color: 'var(--text-muted)', padding: 0 }}>
              {showAll ? 'Show fewer novels' : `Show all ${rows.length} novels`}
            </button>
          )}
        </>
      )}
    </div>
  )
}

// "checked 4 min ago" for a card's saved values
function ago(ts) {
  if (!ts) return 'not checked yet'
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts))
  if (s < 60) return 'checked just now'
  if (s < 3600) return `checked ${Math.round(s / 60)} min ago`
  if (s < 86400) return `checked ${Math.round(s / 3600)} h ago`
  return `checked ${Math.round(s / 86400)} d ago`
}

// One colour per agent (a parallel worker; on Nvidia each has its own key), shared by the agent rows and the table badges
const AGENT_COLORS = ['#e07a5f', '#3d9be9', '#5cc8a1', '#e8b93a', '#a78bfa', '#f472b6']
const agentColor = n => AGENT_COLORS[((n || 1) - 1) % AGENT_COLORS.length]
function AgentBadge({ agent, keyNo }) {
  if (!agent) return null
  return <span title={keyNo ? `Agent ${agent} · Nvidia key ${keyNo}` : `Agent ${agent}`}
    style={{ display: 'inline-block', fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 8, marginRight: 5,
      background: agentColor(agent), color: '#10131a', verticalAlign: 'middle' }}>A{agent}{keyNo ? `·K${keyNo}` : ''}</span>
}

const HEALTH_COLOR = { ok: 'var(--green)', working: 'var(--green)', warn: 'var(--amber)', error: 'var(--red)', info: 'var(--text-muted)' }

// What the card's ⟳ found: why a stopped job is stuck (engine limit, stale worklist, crash, stalled...), what it already fixed,
// and one-click actions for the rest.
function HealthStrip({ health, jobKey, onRestart, busy }) {
  const [open, setOpen] = useState(true)
  if (!health || !health.verdict) return null
  const finds = health.findings || []
  const color = HEALTH_COLOR[health.level] || 'var(--text-muted)'
  const fixed = finds.filter(f => f.fixed).length
  return (
    <div style={{ borderLeft: `3px solid ${color}`, background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', padding: '7px 10px' }}>
      <button onClick={() => setOpen(o => !o)} style={{ display: 'flex', gap: 6, alignItems: 'baseline', width: '100%', textAlign: 'left',
        background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text-primary)' }}>
        <span style={{ fontSize: 11.5, fontWeight: 700, color }}>{health.verdict}</span>
        {fixed > 0 && <span style={{ fontSize: 10, color: 'var(--green)' }}>✓ {fixed} fixed</span>}
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>{ago(health.checked_at)} {finds.length ? (open ? '▲' : '▼') : ''}</span>
      </button>
      {open && finds.map((f, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 5, fontSize: 11, lineHeight: 1.5, color: 'var(--text-secondary)' }}>
          <span style={{ color: f.fixed ? 'var(--green)' : (HEALTH_COLOR[f.level] || 'inherit'), flexShrink: 0 }}>{f.fixed ? '✓' : f.level === 'error' ? '✗' : f.level === 'warn' ? '!' : '•'}</span>
          <span style={{ flex: 1 }}>{f.text}</span>
          {f.action && (
            <button disabled={busy} onClick={() => onRestart(jobKey)} style={{ flexShrink: 0, fontSize: 10.5, fontWeight: 600, padding: '3px 10px',
              borderRadius: 'var(--radius-sm)', background: 'var(--accent)', border: 'none', color: '#fff', opacity: busy ? 0.6 : 1 }}>{f.action.label}</button>
          )}
        </div>
      ))}
    </div>
  )
}

function JobCard({ jobKey, job, onRestart, onStop, restarting, stopping, jobErr, onRefresh, refreshing }) {
  const pct = job.total ? Math.round((100 * job.done) / job.total) : 0
  const novels = [...(job.novels || [])].sort((a, b) => a.novel_id.localeCompare(b.novel_id))
  // Novels with an item being worked on right now -- their name turns amber in the table below.
  // Multi-slot jobs (Delta Upgrade) list every in-flight item in live.active; others report one.
  const working = new Set(!job.running ? [] : (Array.isArray(job.live?.active) && job.live.active.length
    ? job.live.active.map(a => a.novel) : (job.live?.novel ? [job.live.novel] : [])))
  // Not running is ambiguous on its own — "never started," "crashed
  // mid-way," and "finished everything" all look identical as a bare
  // STOPPED badge. Distinguish the good case: stopped AND every shortlisted
  // item is actually done (confirmed live against character_dna's own log:
  // "258 already done, 0 failed" is what a genuinely complete run reports).
  const isDone = !job.running && job.total > 0 && job.done >= job.total

  // character_dna only — one-click action behind the "N stale" badge.
  // rebuilds: { "novel/char_id": { status: 'running'|'done'|'error', rebuild_id } }
  const [rebuilds, setRebuilds] = useState({})
  const staleList = novels.flatMap(n => n.stale || [])

  async function startRebuild(c) {
    const key = `${c.novel_id}/${c.character_id}`
    setRebuilds(r => ({ ...r, [key]: { status: 'starting' } }))
    try {
      const res = await api.characterDnaRebuild(c.novel_id, c.character_id)
      setRebuilds(r => ({ ...r, [key]: { status: 'running', rebuild_id: res.rebuild_id } }))
      pollRebuild(key, res.rebuild_id)
    } catch (e) {
      setRebuilds(r => ({ ...r, [key]: { status: 'error', error: e.message } }))
    }
  }

  function pollRebuild(key, rebuildId) {
    const iv = setInterval(async () => {
      try {
        const job = await api.characterDnaRebuildStatus(rebuildId)
        if (job.status === 'done' || job.status === 'error') {
          clearInterval(iv)
          setRebuilds(r => ({ ...r, [key]: { status: job.status, outcome: job.outcome, error: job.error } }))
        }
      } catch {
        clearInterval(iv)
        setRebuilds(r => ({ ...r, [key]: { status: 'error', error: 'lost track of rebuild status' } }))
      }
    }, 4000)
  }

  return (
    <div style={{
      position: 'relative', background: 'var(--bg-surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)', padding: 18, display: 'flex', flexDirection: 'column', gap: 12,
    }}>
      {/* the card's own refresh: recompute this card's true values now (top-right corner) */}
      <button onClick={() => onRefresh(jobKey, true)} disabled={refreshing}
        title="Refresh: recount this card and check why it is stuck — repairs what it safely can and tells you the rest"
        aria-label={`Refresh ${job.label}`}
        style={{
          position: 'absolute', top: 8, right: 8, width: 26, height: 26, borderRadius: '50%', padding: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, lineHeight: 1,
          background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
          cursor: refreshing ? 'default' : 'pointer', animation: refreshing ? 'spin 0.9s linear infinite' : 'none',
        }}>⟳</button>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, paddingRight: 30 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 7, height: 7, borderRadius: '50%',
            background: job.running ? 'var(--green)' : isDone ? 'var(--accent)' : 'var(--red)',
            boxShadow: job.running ? '0 0 6px var(--green)' : isDone ? '0 0 6px var(--accent)' : 'none',
          }} />
          <span style={{ fontSize: 14, fontWeight: 700 }}>{job.label}</span>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
            color: job.running ? 'var(--green)' : isDone ? 'var(--accent)' : 'var(--red)',
            background: job.running ? 'var(--green-dim, rgba(34,197,94,0.12))'
              : isDone ? 'var(--accent-dim, rgba(79,140,255,0.12))' : 'var(--red-dim)',
          }}>{job.running ? 'RUNNING' : isDone ? '✓ DONE' : 'STOPPED'}</span>
          {/* character_dna only — built characters whose roster data grew
              (new chapters via Corpus Builder) since their DNA was built.
              Notification only, never auto-rebuilt (LLM spend stays the
              author's call) — a plain Restart SKIPS these (build_one()'s
              skip check is "does a valid file exist," not "is it current"),
              so this badge is the only signal a rebuild would help; acting
              on it currently means a manual `--char novel/id --force` run,
              not yet a one-click UI action. */}
          {job.stale_count > 0 && (
            <span title="Built characters whose roster data has grown since their DNA was generated — consider a rebuild" style={{
              fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
              color: 'var(--amber)', background: 'var(--amber-dim, rgba(245,158,11,0.12))',
            }}>{job.stale_count} stale</span>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: job.never_checked ? 'var(--amber)' : job.running ? 'var(--green)' : 'var(--text-muted)' }}
              title={job.running ? 'Running: the numbers refresh each time the orange novel changes' : "These counts are the card's last saved values; ⟳ recomputes them now"}>
              {refreshing ? 'checking…' : ago(job.checked_at)}
            </span>
            {job.running && (
              <button onClick={() => onStop(jobKey)} disabled={stopping || restarting}
                title="Stop this job without restarting it"
                style={{
                  padding: '5px 12px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-elevated)', color: 'var(--red)', border: '1px solid var(--red)',
                  opacity: (stopping || restarting) ? 0.6 : 1,
                }}>
                {stopping ? '…' : '■ Stop'}
              </button>
            )}
            <button onClick={() => onRestart(jobKey)} disabled={restarting || stopping}
              title={job.running ? 'Kill and relaunch — picks up any engine/model change from Settings immediately' : 'Start this job'}
              style={{
                padding: '5px 12px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)',
                background: job.running ? 'var(--bg-elevated)' : 'var(--accent)',
                color: job.running ? 'var(--text-secondary)' : '#fff',
                border: job.running ? '1px solid var(--border)' : 'none',
                opacity: (restarting || stopping) ? 0.6 : 1,
              }}>
              {restarting ? '…' : job.running ? 'Restart' : '▶ Start'}
            </button>
          </div>
          {jobErr && (
            <div style={{ fontSize: 10, color: 'var(--red)', maxWidth: 260, textAlign: 'right' }}>{jobErr}</div>
          )}
        </div>
      </div>

      <HealthStrip health={job.health} jobKey={jobKey} onRestart={onRestart} busy={restarting || stopping} />

      {/* Jobs that run several items at once (Delta Upgrade) report each in-flight item in
          live.active -- one row per chapter, instead of only whichever one reported last. */}
      {job.running && Array.isArray(job.live?.active) && job.live.active.length > 0 ? (
        <div style={{
          fontSize: 11, fontFamily: 'Consolas, "SF Mono", monospace', color: 'var(--green)',
          background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)',
          borderRadius: 'var(--radius-sm)', padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          <div>▶ {job.live.active.length} {job.live.active.some(a => a.agent) ? (job.live.active.length === 1 ? 'agent' : 'agents') : 'running at once'}{job.live.model && <span style={{ opacity: 0.75 }}> — {job.live.model}</span>}</div>
          {job.live.active.map(a => (
            <div key={`${a.novel}-${a.chapter ?? a.unit}-${a.agent ?? ''}`} style={{ borderTop: '1px solid rgba(52,211,153,0.15)', paddingTop: 5,
              borderLeft: a.agent ? `3px solid ${agentColor(a.agent)}` : 'none', paddingLeft: a.agent ? 8 : 0 }}>
              <div>
                <AgentBadge agent={a.agent} keyNo={a.key} />
                <b>{a.novel}</b>{a.chapter != null ? ` ch${a.chapter}` : (a.unit ? ` · ${a.unit}` : '')}
                <span style={{ opacity: 0.7 }}>{a.size ? ` · ${a.size}` : ''} · since {a.started}</span>
              </div>
              <div style={{ opacity: 0.85 }}>{String(a.step || '').replace(/^ch\d+\s*/, '') || 'starting'}{a.preview ? <span style={{ opacity: 0.7 }}> — {a.preview}</span> : null}</div>
            </div>
          ))}
        </div>
      ) : job.running && job.live && (
        <div style={{
          fontSize: 11, fontFamily: 'Consolas, "SF Mono", monospace', color: 'var(--green)',
          background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)',
          borderRadius: 'var(--radius-sm)', padding: '6px 10px',
        }}>
          ▶ Now processing <b>{job.live.novel}</b>
          {job.live.character && <> — <b>{job.live.character}</b></>}
          {job.live.batch_size != null && <> ({job.live.batch_size} records{job.live.kind ? `, ${job.live.kind}` : ''})</>}
          {job.live.model && <span style={{ opacity: 0.75 }}> — {job.live.model}</span>}:
          {/* character_dna's live-status carries input volume instead of a text
              preview (facts/quotes/chapters read) — shown as its own line so
              the author can see what's actually feeding each LLM call, not
              just which character it's on. */}
          {(job.live.facts != null || job.live.quotes != null) && (
            <div style={{ marginTop: 2, opacity: 0.85 }}>
              {job.live.facts} fact(s), {job.live.quotes} quote(s)
              {job.live.chapters_read?.length ? `, reading ch.${job.live.chapters_read.join(', ')}` : ''}
            </div>
          )}
          {job.live.preview && <div style={{ marginTop: 2, opacity: 0.85 }}>{job.live.preview}</div>}
        </div>
      )}

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
          <span style={{ color: 'var(--text-secondary)' }}>{job.done.toLocaleString()} / {job.total.toLocaleString()} records</span>
          <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{pct}%</span>
        </div>
        <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
          <div style={{ height: '100%', width: `${pct}%`, background: 'var(--accent)', borderRadius: 3, transition: 'width 0.4s' }} />
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border-soft)' }}>
              <th style={{ textAlign: 'left', padding: '4px 6px', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', fontSize: 9, letterSpacing: '0.06em' }}>{job.rowLabel || 'Novel'}</th>
              <th style={{ textAlign: 'right', padding: '4px 6px', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', fontSize: 9, letterSpacing: '0.06em' }}>Done</th>
              <th style={{ textAlign: 'right', padding: '4px 6px', color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', fontSize: 9, letterSpacing: '0.06em' }}>Total</th>
              <th style={{ padding: '4px 6px', width: '30%' }}></th>
            </tr>
          </thead>
          <tbody>
            {novels.map(n => {
              const npct = n.total ? Math.round((100 * n.done) / n.total) : 0
              const complete = n.done >= n.total
              return (
                <tr key={n.novel_id} style={{ borderBottom: '1px solid var(--border-soft)' }}>
                  <td title={working.has(n.novel_id) ? 'being worked on right now' : undefined}
                    style={{ padding: '5px 6px', color: working.has(n.novel_id) ? 'var(--amber)' : 'var(--text-primary)',
                             fontWeight: working.has(n.novel_id) ? 700 : undefined, transition: 'color 0.3s' }}>
                    {job.running && Array.isArray(job.live?.active) && job.live.active.filter(a => a.agent && (a.novel === n.novel_id || n.novel_id.startsWith(a.novel + ' '))).map(a => <AgentBadge key={a.agent} agent={a.agent} keyNo={a.key} />)}
                    {n.novel_id}</td>
                  <td style={{ padding: '5px 6px', textAlign: 'right', color: 'var(--text-secondary)' }}>{n.done.toLocaleString()}</td>
                  <td style={{ padding: '5px 6px', textAlign: 'right', color: 'var(--text-secondary)' }}>{n.total.toLocaleString()}</td>
                  <td style={{ padding: '5px 6px' }}>
                    <div style={{ height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 2 }}>
                      <div style={{
                        height: '100%', width: `${npct}%`, borderRadius: 2,
                        background: complete ? 'var(--green)' : 'var(--accent)',
                      }} />
                    </div>
                  </td>
                </tr>
              )
            })}
            {novels.length === 0 && (
              <tr><td colSpan={4} style={{ padding: '10px 6px', color: 'var(--text-muted)', textAlign: 'center' }}>No data yet</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {jobKey === 'delta_upgrade' && <DeltaScanPanel />}

      {staleList.length > 0 && (
        <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Stale — roster grew since these were built
          </div>
          {staleList.map(c => {
            const key = `${c.novel_id}/${c.character_id}`
            const rb = rebuilds[key]
            return (
              <div key={key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, fontSize: 11, padding: '4px 0' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{c.character_name} <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>({c.novel_id})</span></span>
                {(!rb || rb.status === 'error') ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {rb?.status === 'error' && <span title={rb.error} style={{ fontSize: 9, color: 'var(--red)' }}>failed</span>}
                    <button onClick={() => startRebuild(c)} style={{
                      fontSize: 10, padding: '3px 10px', fontWeight: 600, borderRadius: 'var(--radius-sm)',
                      background: 'var(--bg-elevated)', color: 'var(--amber)', border: '1px solid var(--amber)',
                    }}>{rb?.status === 'error' ? 'Retry' : 'Rebuild'}</button>
                  </div>
                ) : rb.status === 'starting' || rb.status === 'running' ? (
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 5 }}>
                    <Spinner size={10} /> rebuilding… (up to a few minutes)
                  </span>
                ) : (
                  <span style={{ fontSize: 10, color: rb.outcome === 'built' ? 'var(--green)' : 'var(--text-muted)' }}>
                    {rb.outcome === 'built' ? '✓ rebuilt' : rb.outcome || 'done'}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Spinner({ size = 14 }) {
  return <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite', fontSize: size }}>⟳</span>
}

export default function CorpusPipelinePage() {
  const [status, setStatus] = useState(null)
  const [err, setErr] = useState(null)
  const [jobErrs, setJobErrs] = useState({})
  const [restarting, setRestarting] = useState(null)
  const [stopping, setStopping] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState({})     // {jobKey: true} while that card recomputes
  const { appendConsoleLine, openConsole } = useStore()

  // Opening the page shows every card's LAST SAVED values at once (no counting); a card's ⟳ recomputes that card only.
  // Only running / doing-now is polled, every 6 s — cheap, no counting.
  async function load() {
    try {
      const res = await api.pipelineCached()
      setStatus(res)
      setErr(null)
      return res
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  // check = the card's ⟳ (and Refresh all): recount, then diagnose and repair. The automatic first fill is a plain recount.
  async function refreshJob(key, check = false) {
    setRefreshing(r => ({ ...r, [key]: true }))
    try {
      const res = await api.pipelineJob(key, check)
      setStatus(s => ({ ...(s || {}), jobs: { ...((s || {}).jobs || {}), [key]: res.status } }))
      setJobErrs(e => ({ ...e, [key]: null }))
    } catch (e) {
      setJobErrs(prev => ({ ...prev, [key]: `Refresh failed: ${e.message}` }))
    } finally {
      setRefreshing(r => ({ ...r, [key]: false }))
    }
  }

  async function refreshAll() {
    for (const key of Object.keys(status?.jobs || {})) await refreshJob(key, true)    // one card at a time, each shows as it lands
  }

  useEffect(() => {
    let dead = false
    load().then(res => {      // a card that has never been checked fills itself in, one at a time
      const never = Object.entries(res?.jobs || {}).filter(([, j]) => j.never_checked).map(([k]) => k)
      ;(async () => { for (const k of never) { if (dead) return; await refreshJob(k) } })()
    })
    // A running card recounts itself whenever its orange novel (the one being worked on) changes, so the numbers move with
    // the job without counting on a timer. A job that has just stopped checks itself (why it stopped, what is left).
    const wasRunning = {}
    const workingSig = {}
    const interval = setInterval(async () => {
      try {
        const live = await api.pipelineLive()
        const recount = [], justStopped = []
        for (const [k, j] of Object.entries(live.jobs || {})) {
          const l = j.live
          const names = Array.isArray(l?.active) && l.active.length ? l.active.map(a => a.novel) : (l?.novel ? [l.novel] : [])
          const sig = [...new Set(names)].sort().join('|')
          if (j.running && sig !== workingSig[k]) recount.push(k)          // first sight of it running, or the orange novel moved
          if (wasRunning[k] && !j.running) justStopped.push(k)
          wasRunning[k] = !!j.running
          workingSig[k] = j.running ? sig : undefined
        }
        setStatus(s => s && ({ ...s, jobs: Object.fromEntries(Object.entries(s.jobs || {}).map(([k, j]) =>
          [k, live.jobs?.[k] ? { ...j, running: live.jobs[k].running, live: live.jobs[k].live } : j])) }))
        for (const k of justStopped) refreshJob(k, true)
        for (const k of recount.filter(k => !justStopped.includes(k))) refreshJob(k, false)
      } catch { /* busy: next tick */ }
    }, 4000)
    return () => { dead = true; clearInterval(interval) }
  }, [])

  // Errors here go BOTH inline (next to the button that triggered them) AND
  // into the real Engine Console — a failed launch used to disappear with no
  // trace anywhere the author would actually look.
  // Both api.pipelineRestart/pipelineStop are synchronous on the backend —
  // they don't return until their taskkill/WMI-Create call has actually
  // completed (see _stop_pipeline_job/_launch_pipeline_job), so the
  // response itself IS the confirmation the state changed. The fixed
  // 800ms/1500ms sleeps that used to sit here before calling load() were
  // pure guesswork on top of that already-real wait, adding up to ~1-2s of
  // pure dead time to every click on top of the WMI calls' own genuine
  // ~1.5-2s-per-query cost (confirmed live, see _list_python_processes'
  // docstring) — removed; load() now fires immediately since there's
  // nothing left to wait out.
  async function restart(jobKey) {
    setRestarting(jobKey)
    setJobErrs(e => ({ ...e, [jobKey]: null }))
    try {
      await api.pipelineRestart(jobKey)
      await refreshJob(jobKey, true)
    } catch (e) {
      setJobErrs(prev => ({ ...prev, [jobKey]: e.message }))
      appendConsoleLine(`✗ Corpus Pipeline (${jobKey}) failed to start: ${e.message}`, 'error')
      openConsole()
    } finally {
      setRestarting(null)
    }
  }

  async function stop(jobKey) {
    setStopping(jobKey)
    setJobErrs(e => ({ ...e, [jobKey]: null }))
    try {
      await api.pipelineStop(jobKey)
      await refreshJob(jobKey, true)
    } catch (e) {
      setJobErrs(prev => ({ ...prev, [jobKey]: e.message }))
      appendConsoleLine(`✗ Corpus Pipeline (${jobKey}) failed to stop: ${e.message}`, 'error')
      openConsole()
    } finally {
      setStopping(null)
    }
  }

  const jobs = status?.jobs || {}

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Corpus Pipeline</h2>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
            Background classification jobs that enrich the corpus — Thread Typing, Symbol Filtering, and Knowledge Index
          </div>
        </div>
        <button onClick={refreshAll} disabled={loading || Object.values(refreshing).some(Boolean)} title="Recompute every card, one at a time" style={{
          padding: '6px 12px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)',
          background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
        }}>{Object.values(refreshing).some(Boolean) ? 'Refreshing…' : '↻ Refresh all'}</button>
      </div>

      {err && (
        <div style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--red)' }}>
          {err}
        </div>
      )}

      {!status && loading && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
      )}

      {Object.entries(jobs).map(([key, job]) => (
        <JobCard key={key} jobKey={key} job={job} onRestart={restart} onStop={stop} onRefresh={refreshJob}
          refreshing={!!refreshing[key]} restarting={restarting === key} stopping={stopping === key} jobErr={jobErrs[key]} />
      ))}
    </div>
  )
}
