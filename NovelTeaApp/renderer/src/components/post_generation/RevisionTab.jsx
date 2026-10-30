import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import { Panel, PanelTitle, Spinner } from '../shared/projectUi'
import { FactsTab } from './FactsTab'

// Promise Check's flag text carries **bold** labels (the backend parses those
// same markers back out as the confirmed keys), so render them rather than
// showing raw asterisks. Deliberately minimal — bold only, not a markdown lib.
export function renderBoldMd(text) {
  return String(text || '').split(/(\*\*.+?\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <b key={i}>{part.slice(2, -2)}</b>
      : <span key={i}>{part}</span>
  )
}

/* ══════════════════════════════════════
   REVISION TAB  (V4 Phase 5)
   Two wizards that were backend-complete but had no UI:
   • Revision Intelligence — an agentic craft pass (pacing, flat dialogue,
     weak stakes, exposition dumps, repetition) persisted as a durable
     checklist with the same open/dismissed/fixed lifecycle as
     facts_contradictions. Costs an agent run.
   • Promise Check — zero-LLM drift detection over chapter_skeletons'
     target_psychology, walked one flag at a time as an A/B choice.
══════════════════════════════════════ */
export const REVISION_CATEGORY_META = {
  pacing_issues:    { label: 'Pacing',          color: '#f59e0b' },
  flat_dialogue:    { label: 'Flat dialogue',   color: '#ec4899' },
  weak_stakes:      { label: 'Weak stakes',     color: '#ef4444' },
  exposition_dumps: { label: 'Exposition dump', color: '#06b6d4' },
  repetition:       { label: 'Repetition',      color: '#8b5cf6' },
}

export function RevisionTab({ project, projectId, afterGenerate, onSave }) {
  const [checklist, setChecklist] = useState(project.revision_checklist || [])
  const [running, setRunning] = useState(false)
  const [runMsg, setRunMsg] = useState('')
  const [range, setRange] = useState('')
  const [filterCat, setFilterCat] = useState('')
  const [showResolved, setShowResolved] = useState(false)
  const [updatingId, setUpdatingId] = useState(null)

  // Promise Check — drift report is free to fetch (pure aggregation), so it
  // loads on mount; the wizard session only starts when the author asks.
  const [drift, setDrift] = useState(null)
  const [driftLoading, setDriftLoading] = useState(true)
  const [session, setSession] = useState(null)
  const [promiseBusy, setPromiseBusy] = useState(false)
  const [promiseMsg, setPromiseMsg] = useState('')

  useEffect(() => {
    setChecklist(project.revision_checklist || [])
  }, [project.id])

  const loadDrift = useCallback(async () => {
    setDriftLoading(true)
    try {
      setDrift(await api.promiseCheckStatus(projectId))
    } catch (e) {
      setDrift({ status: 'error', message: e.message })
    } finally {
      setDriftLoading(false)
    }
  }, [projectId])

  useEffect(() => { loadDrift() }, [loadDrift])

  async function runRevisionCheck() {
    setRunning(true)
    setRunMsg('')
    try {
      const r = await api.revisionCheck(projectId, range.trim() || null)
      if (r.items?.length) setChecklist(c => [...c, ...r.items])
      setRunMsg(r.total_new > 0
        ? `Reviewed chapters ${r.chapter_range} — ${r.total_new} new item${r.total_new !== 1 ? 's' : ''} flagged.`
        : `Reviewed chapters ${r.chapter_range} — nothing flagged. That's a good outcome, not a miss.`)
      afterGenerate?.()
    } catch (e) {
      setRunMsg(`✗ ${e.message}`)
    } finally {
      setRunning(false)
    }
  }

  async function setStatus(item_id, status) {
    setUpdatingId(item_id)
    try {
      await api.revisionChecklistUpdate(projectId, item_id, status)
      setChecklist(cs => cs.map(c => (c.id === item_id ? { ...c, status } : c)))
      afterGenerate?.()
    } catch (e) {
      setRunMsg(`✗ ${e.message}`)
    } finally {
      setUpdatingId(null)
    }
  }

  async function promiseStep(choice = null) {
    setPromiseBusy(true)
    setPromiseMsg('')
    try {
      const r = await api.promiseCheck(projectId, session?.session_id || null, choice)
      if (r.done) {
        setSession(null)
        setPromiseMsg(r.decisions_made
          ? `Done — ${r.decisions_made} decision${r.decisions_made !== 1 ? 's' : ''} recorded.`
          : (r.message || 'Nothing to walk through.'))
        loadDrift()
        afterGenerate?.()
      } else {
        setSession(r)
      }
    } catch (e) {
      setPromiseMsg(`✗ ${e.message}`)
      setSession(null)
    } finally {
      setPromiseBusy(false)
    }
  }

  const open     = checklist.filter(c => (c.status || 'open') === 'open')
  const resolved = checklist.filter(c => (c.status || 'open') !== 'open')
  const visible  = (showResolved ? checklist : open)
    .filter(c => !filterCat || c.category === filterCat)
    .slice()
    .sort((a, b) => (a.chapter || 0) - (b.chapter || 0))

  const lastRun = project.last_revision_check

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>

      {/* ── Promise Check ── */}
      <Panel style={{ marginBottom: 12 }}>
        <PanelTitle action={
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <button onClick={loadDrift} disabled={driftLoading} style={{
              fontSize: 10, padding: '4px 8px', background: 'transparent', border: 'none',
              color: 'var(--text-muted)', textDecoration: 'underline', cursor: 'pointer',
            }}>refresh</button>
            <button
              onClick={() => promiseStep(null)}
              disabled={promiseBusy || driftLoading || drift?.status !== 'drift_detected' || !!session}
              title={drift?.status === 'drift_detected'
                ? 'Walk each drift flag as a choice: re-anchor it, or accept it as intentional'
                : 'Available when drift is detected'}
              style={{
                fontSize: 11, padding: '5px 12px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                background: (promiseBusy || drift?.status !== 'drift_detected' || !!session)
                  ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#8b5cf6,#6366f1)',
                color: (promiseBusy || drift?.status !== 'drift_detected' || !!session)
                  ? 'var(--text-muted)' : '#fff',
                border: 'none', display: 'flex', alignItems: 'center', gap: 5,
              }}>{promiseBusy ? <Spinner size={11} /> : '⚖'} Walk Drift Flags</button>
          </div>
        }>Promise Check — story drift</PanelTitle>

        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Compares your opening chapter's promised reader emotions and genre contracts against
          a rolling average of the most recently planned chapters. Reads <b>chapter skeletons</b>,
          not written prose — so it works while you're still planning ahead. Free: pure aggregation,
          no model call anywhere in this flow.
        </div>

        {driftLoading ? (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 6, alignItems: 'center' }}>
            <Spinner size={11} /> Checking drift…
          </div>
        ) : drift?.status === 'insufficient_data' ? (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-muted)' }}>
            Not enough planned chapters yet — {drift.chapters_available || 0} with target psychology, needs 7.
            Plan more chapter skeletons and this fills in automatically.
          </div>
        ) : drift?.status === 'error' ? (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--red)' }}>✗ {drift.message}</div>
        ) : drift?.status === 'consistent' ? (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--green,#10b981)' }}>
            ✓ Consistent — chapter {drift.baseline_chapter}'s promises still hold across chapters {(drift.recent_window || []).join(', ')}.
          </div>
        ) : drift?.status === 'drift_detected' ? (
          <div style={{ marginTop: 10 }}>
            {(drift.flags || []).map((f, i) => (
              <div key={i} style={{
                fontSize: 11, lineHeight: 1.6, marginBottom: 6, padding: '7px 10px',
                background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)',
                borderLeft: '2px solid var(--amber,#f59e0b)',
              }}>{renderBoldMd(f.text)}</div>
            ))}
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              Baseline chapter {drift.baseline_chapter} vs. recent window {(drift.recent_window || []).join(', ')}.
            </div>
          </div>
        ) : null}

        {session && (
          <div style={{
            marginTop: 12, padding: 12, borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>{session.progress}</div>
            <div style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 10 }}>{renderBoldMd(session.flag)}</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {(session.options || []).map((o, i) => (
                <button key={i} onClick={() => promiseStep(i === 0 ? 'reanchor' : 'confirm')} disabled={promiseBusy}
                  title={o.description}
                  style={{
                    fontSize: 11, padding: '6px 12px', fontWeight: 600, borderRadius: 'var(--radius-sm)',
                    background: i === 0 ? 'linear-gradient(135deg,#8b5cf6,#6366f1)' : 'var(--bg-surface)',
                    color: i === 0 ? '#fff' : 'var(--text-secondary)',
                    border: i === 0 ? 'none' : '1px solid var(--border)',
                    display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2, maxWidth: 260,
                  }}>
                  <span>{o.label}</span>
                  <span style={{ fontSize: 9.5, fontWeight: 400, opacity: 0.85, textAlign: 'left' }}>{o.description}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {promiseMsg && (
          <div style={{ marginTop: 8, fontSize: 11, color: promiseMsg.startsWith('✗') ? 'var(--red)' : 'var(--text-secondary)' }}>{promiseMsg}</div>
        )}
      </Panel>

      {/* ── Revision Intelligence ── */}
      <Panel style={{ marginBottom: 12 }}>
        <PanelTitle action={
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              value={range}
              onChange={e => setRange(e.target.value)}
              placeholder="e.g. 10-15"
              title="Chapter range to review — blank reviews the 10 most recent"
              style={{
                fontSize: 10.5, padding: '4px 8px', width: 80,
                background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
              }} />
            <button onClick={runRevisionCheck} disabled={running} title="Agentic craft pass over written chapters — costs an agent run" style={{
              fontSize: 11, padding: '5px 12px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
              background: running ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#f59e0b,#ef4444)',
              color: running ? 'var(--text-muted)' : '#fff', border: 'none',
              display: 'flex', alignItems: 'center', gap: 5,
            }}>{running ? <Spinner size={11} /> : '✎'} Run Revision Check</button>
          </div>
        }>Revision Intelligence — {open.length} open item{open.length !== 1 ? 's' : ''}</PanelTitle>

        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          A craft-quality pass over <b>written</b> chapters — pacing, flat dialogue, weak stakes,
          exposition dumps, repetition. Distinct from Facts' contradiction hunt: this asks
          "is this good writing," not "is this true." Blank range reviews the 10 most recent chapters;
          a full-story scan on every click doesn't scale. Findings persist as a checklist you work
          through, rather than a report that vanishes when you close it.
          {lastRun && (
            <> Last run: chapters {lastRun.chapter_range} at {lastRun.at}.</>
          )}
        </div>

        {runMsg && (
          <div style={{ marginTop: 8, fontSize: 11, color: runMsg.startsWith('✗') ? 'var(--red)' : 'var(--text-secondary)' }}>{runMsg}</div>
        )}
      </Panel>

      {/* ── checklist ── */}
      {checklist.length > 0 && (
        <Panel>
          <PanelTitle action={
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <select value={filterCat} onChange={e => setFilterCat(e.target.value)} style={{
                fontSize: 10.5, padding: '4px 8px', background: 'var(--bg-elevated)',
                border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
              }}>
                <option value="">All categories</option>
                {Object.entries(REVISION_CATEGORY_META).map(([k, m]) => (
                  <option key={k} value={k}>{m.label}</option>
                ))}
              </select>
              <button onClick={() => setShowResolved(s => !s)} style={{
                fontSize: 10, padding: '4px 8px', background: 'transparent', border: 'none',
                color: 'var(--text-muted)', textDecoration: 'underline', cursor: 'pointer',
              }}>{showResolved ? 'hide resolved' : `show resolved (${resolved.length})`}</button>
            </div>
          }>Checklist</PanelTitle>

          {visible.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '8px 0' }}>
              {open.length === 0 ? 'Nothing open — all clear.' : 'Nothing matches that filter.'}
            </div>
          ) : visible.map(item => {
            const meta = REVISION_CATEGORY_META[item.category] || { label: item.category, color: 'var(--text-muted)' }
            const isResolved = (item.status || 'open') !== 'open'
            return (
              <div key={item.id} style={{
                padding: '9px 11px', marginBottom: 6, borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-elevated)', borderLeft: `2px solid ${meta.color}`,
                opacity: isResolved ? 0.55 : 1,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 4, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 9.5, fontWeight: 700, color: meta.color, textTransform: 'uppercase', letterSpacing: 0.4 }}>{meta.label}</span>
                  {item.chapter != null && (
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>ch. {item.chapter}</span>
                  )}
                  {isResolved && (
                    <span style={{ fontSize: 9.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>{item.status}</span>
                  )}
                  <div style={{ flex: 1 }} />
                  {updatingId === item.id ? <Spinner size={10} /> : isResolved ? (
                    <button onClick={() => setStatus(item.id, 'open')} style={{
                      fontSize: 10, padding: '3px 8px', background: 'transparent',
                      border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
                    }}>reopen</button>
                  ) : (
                    <>
                      <button onClick={() => setStatus(item.id, 'fixed')} style={{
                        fontSize: 10, padding: '3px 8px', background: 'transparent',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
                      }}>✓ fixed</button>
                      <button onClick={() => setStatus(item.id, 'dismissed')} style={{
                        fontSize: 10, padding: '3px 8px', background: 'transparent',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
                      }}>dismiss</button>
                    </>
                  )}
                </div>
                <div style={{ fontSize: 11.5, lineHeight: 1.6, color: 'var(--text-primary)' }}>{item.description}</div>
                {item.suggestion && (
                  <div style={{ fontSize: 10.5, lineHeight: 1.6, color: 'var(--text-muted)', marginTop: 4 }}>
                    <b>Suggestion:</b> {item.suggestion}
                  </div>
                )}
              </div>
            )
          })}
        </Panel>
      )}

      {/* Facts Ledger + Contradictions — merged in under Revision so it no
          longer needs its own top-level tab (author's explicit request:
          "no need for facts to have its own tab"). FactsTab already returns
          a Fragment of Panels sized for this container — see its own
          comment at the top of its return. */}
      <FactsTab project={project} projectId={projectId} afterGenerate={afterGenerate} onSave={onSave} />
    </div>
  )
}
