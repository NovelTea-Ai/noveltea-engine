import { Fragment, useEffect, useState } from 'react'
import { api } from '../../api'
import useNarrowLayout from '../../hooks/useNarrowLayout'
import { FieldSurveyButton, Panel, PanelTitle, SkeletonDetail, Spinner, copyTextToClipboard } from '../shared/projectUi'
import { AdvStringList } from './common'

/* ══════════════════════════════════════
   CHAPTER SKELETON TAB
══════════════════════════════════════ */
/**
 * Sequential chapter-skeleton generation — one chapter per call, inside its
 * arc's contract, with the previous chapter in full context.
 *
 * Replaces the batch generator, which asked for 20 chapters in a single call
 * using only a 5-chapter tail as context and produced 7 flat fields each.
 */
export function SequentialSkeletonPanel({ chapters, arcs, projectId, onChanged }) {
  const [warnings, setWarnings] = useState([])
  // When on, the SCENE STRUCTURE question is guaranteed to include an option
  // built around a real, not-yet-used corpus narrative pattern (see
  // _forced_pattern_for_chapter, generate.py) — offered as a genuine choice
  // among the interview's options, never silently written in without the
  // author picking it.
  const [forcePattern, setForcePattern] = useState(false)

  // "planned" = really planned (scenes, or at least a purpose / key event): the blank placeholder "+ Add" saves is not a plan
  const isPlanned = c => !!c && Number.isInteger(c.number) && ((c.scenes || []).length > 0 || !!String(c.purpose || '').trim() || !!String(c.key_event || '').trim())
  const planned = new Set(chapters.filter(isPlanned).map(c => c.number))
  const arcChapters = arcs.flatMap(a => a.chapters || [])
  const nextCh = arcChapters.filter(n => !planned.has(n)).sort((a, b) => a - b)[0] ?? null
  // Interactive is the ONLY way to plan/replan a chapter skeleton now — the
  // direct one-shot button (and its "run to chapter N" batch loop) was
  // removed deliberately: planning happens one chapter per interview, the
  // author steering every chapter, never a silent multi-chapter batch run.
  // Target defaults to the next unplanned chapter, falling back to the last
  // planned one once every arc chapter has a skeleton, and stays editable.
  const lastPlannedCh = chapters.length ? Math.max(...chapters.map(c => c.number || 0)) : null
  const [interactiveCh, setInteractiveCh] = useState(null)   // null = follow the default below
  const interactiveTarget = interactiveCh ?? nextCh ?? lastPlannedCh
  const arcOf = n => arcs.find(a => (a.chapters || []).includes(n))

  if (!arcs.length) {
    return (
      <Panel>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>
          Generate at least one arc first — skeletons are planned inside an arc, so the
          chapter inherits its function, tension curve and the reveals it still owes.
        </div>
      </Panel>
    )
  }

  const arc = nextCh != null ? arcOf(nextCh) : null
  const inArc = arc ? (arc.chapters || []).filter(n => planned.has(n)).length : 0
  const arcTotal = arc ? (arc.chapters || []).length : 0

  return (
    <Panel>
      <PanelTitle action={
        interactiveTarget != null && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <label style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              chapter&nbsp;
              <input type="number" min={1} value={interactiveCh ?? interactiveTarget}
                onChange={e => setInteractiveCh(e.target.value ? Number(e.target.value) : null)}
                title="Which chapter the Interactive skeleton interview plans/replans — defaults to the next unplanned chapter, or the last planned one once every chapter has a skeleton"
                style={{ width: 44, padding: '2px 4px', fontSize: 10, borderRadius: 4 }} />
            </label>
            <FieldSurveyButton field="chapter_skeleton" projectId={projectId} chapterNumber={interactiveTarget}
              small label="⚡ Interactive" forcePattern={forcePattern}
              onDone={res => { setWarnings(res.warnings || []); onChanged && onChanged() }} />
          </div>
        )
      }>
        Sequential Skeleton Builder — {planned.size}/{arcChapters.length || '?'} planned
      </PanelTitle>

      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginBottom: 10, lineHeight: 1.55 }}>
        Each chapter is planned through a field-by-field interview, seeing the previous
        chapter in full and its arc's contract — function, tension curve, and which of
        the arc's promised reveals are still owed.
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: 'var(--text-secondary)', marginBottom: 8, cursor: 'pointer' }}
        title="Guarantees the scene-structure question offers a real, not-yet-used corpus narrative pattern as one of its options — you still choose whether to take it.">
        <input type="checkbox" checked={forcePattern} onChange={e => setForcePattern(e.target.checked)} />
        Force a matching corpus pattern into the scene-structure options
      </label>

      {arc && (
        <div style={{ fontSize: 10.5, marginBottom: 8 }}>
          <span style={{ color: 'var(--text-muted)' }}>Next chapter's arc: </span>
          <b>{arc.label}</b>
          <span style={{ color: 'var(--text-muted)' }}> — {inArc}/{arcTotal} of its chapters planned</span>
        </div>
      )}

      {warnings.filter(w => !/^(Overlap gate|Plan gate|Systems gate)/.test(w)).length > 0 && (
        <div style={{
          fontSize: 10.5, color: 'var(--amber)', background: 'rgba(245,158,11,0.08)',
          border: '1px solid rgba(245,158,11,0.3)', borderRadius: 6,
          padding: '6px 9px', marginBottom: 8,
        }}>
          <b>Plan check:</b>
          {warnings.filter(w => !/^(Overlap gate|Plan gate|Systems gate)/.test(w)).map((w, i) => <div key={i}>• {w}</div>)}
        </div>
      )}
    </Panel>
  )
}

/**
 * Round-trip validation — measure a written chapter against the skeleton that
 * specified it. Reports per-check results rather than one score, so a miss
 * points at the specific thing to fix instead of condemning the whole chapter.
 */
// Scene count / Word count describe the chapter's overall shape, not a
// localized gap — fixing those really means a rewrite, so they stay
// report-only. Every other failed check gets a tailored, localized fix — see
// fix_validation_check's docstring (generate.py) for each one's instruction.
export const UNFIXABLE_CHECK_PREFIXES = ['Scene count', 'Word count']

export const isCheckFixable = (name) => !UNFIXABLE_CHECK_PREFIXES.some(p => name.startsWith(p))

export function ChapterValidationPanel({ projectId, chapters }) {
  const [ch, setCh] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [fixingCheck, setFixingCheck] = useState(null)
  const [fixErr, setFixErr] = useState('')

  const planned = chapters.map(c => c.number).filter(Number.isInteger).sort((a, b) => a - b)

  async function run(n) {
    if (!n) return
    setBusy(true); setErr(''); setResult(null)
    try {
      setResult(await api.validateChapter(projectId, Number(n)))
    } catch (e) {
      setErr(e.message || 'Validation failed')
    } finally { setBusy(false) }
  }

  async function fixCheck(c) {
    if (fixingCheck) return
    setFixingCheck(c.check); setFixErr('')
    try {
      const res = await api.fixValidationCheck(projectId, Number(result.chapter), c.check, c.planned, c.actual)
      setResult(res.validation)
    } catch (e) {
      setFixErr(e.message || 'Fix failed')
    } finally { setFixingCheck(null) }
  }

  return (
    <Panel>
      <PanelTitle action={
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select value={ch} onChange={e => setCh(e.target.value)} disabled={busy}
            style={{ fontSize: 10, padding: '3px 6px', borderRadius: 4 }}>
            <option value="">chapter…</option>
            {planned.map(n => <option key={n} value={n}>Ch {n}</option>)}
          </select>
          <button onClick={() => run(ch)} disabled={busy || !ch}
            className="btn-primary" style={{ fontSize: 10, padding: '4px 12px' }}>
            {busy ? <Spinner size={10} /> : '✓ Validate'}
          </button>
        </div>
      }>Round-trip Validation</PanelTitle>

      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55, marginBottom: 8 }}>
        Measures a written chapter against the FULL skeleton that specified it — scene count,
        word budget, style DNA, planned reveals, the hook landing, named characters actually
        appearing, anti-patterns staying out, and per-scene dialogue density. Answers "did it
        build what was specified?" rather than "is it good?".
      </div>

      {err && <div style={{ fontSize: 11, color: 'var(--red)', marginBottom: 8 }}>{err}</div>}

      {result && (
        <>
          <div style={{ fontSize: 11, marginBottom: 8 }}>
            <b>Ch {result.chapter}</b>
            {result.title ? ` — ${result.title}` : ''}
            <span style={{ color: 'var(--text-muted)' }}>
              {' · '}{result.measured.words} words, {result.measured.paragraphs} paragraphs
            </span>
            {(result.passed + result.failed) > 0 && (
              <span style={{ marginLeft: 8 }}>
                <b style={{ color: 'var(--green)' }}>{result.passed} passed</b>
                {result.failed > 0 && <b style={{ color: 'var(--red)' }}> · {result.failed} failed</b>}
              </span>
            )}
          </div>

          {result.note && (
            <div style={{
              fontSize: 10.5, color: 'var(--amber)', background: 'rgba(245,158,11,0.08)',
              border: '1px solid rgba(245,158,11,0.3)', borderRadius: 6,
              padding: '6px 9px', marginBottom: 8,
            }}>{result.note}</div>
          )}

          {fixErr && <div style={{ fontSize: 11, color: 'var(--red)', marginBottom: 8 }}>{fixErr}</div>}

          {result.checks.map((c, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'flex-start', gap: 8, padding: '4px 0',
              borderTop: i ? '1px solid var(--border-soft)' : 'none', fontSize: 10.5,
            }}>
              <span style={{
                width: 14, flexShrink: 0, fontWeight: 700,
                color: c.ok === true ? 'var(--green)' : c.ok === false ? 'var(--red)' : 'var(--text-muted)',
              }}>{c.ok === true ? '✓' : c.ok === false ? '✕' : '—'}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div>{c.check}</div>
                {(c.planned != null || c.actual != null) && (
                  <div style={{ color: 'var(--text-muted)' }}>
                    planned <b>{String(c.planned)}</b> · actual <b style={{
                      color: c.ok === false ? 'var(--red)' : 'var(--text-secondary)',
                    }}>{String(c.actual)}</b>
                    {c.note ? ` — ${c.note}` : ''}
                  </div>
                )}
              </div>
              {c.ok === false && isCheckFixable(c.check) && (
                <button onClick={() => fixCheck(c)} disabled={!!fixingCheck}
                  title="Apply a localized, targeted fix for just this issue, then re-validate"
                  style={{
                    flexShrink: 0, fontSize: 9.5, padding: '3px 9px', borderRadius: 'var(--radius-sm)',
                    background: fixingCheck === c.check ? 'var(--bg-elevated)' : 'var(--accent)',
                    color: fixingCheck === c.check ? 'var(--text-muted)' : '#fff',
                    border: 'none', display: 'flex', alignItems: 'center', gap: 4,
                  }}>{fixingCheck === c.check ? <Spinner size={9} /> : '🔧 Fix'}</button>
              )}
            </div>
          ))}
        </>
      )}
    </Panel>
  )
}

export function ChapterSkeletonTab({ chapters: initChapters, arcs, projectId, afterGenerate, onSave }) {
  const [chapters, setChapters] = useState(initChapters)
  const [editIdx, setEditIdx] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [copiedAll, setCopiedAll] = useState(false)
  const [copyAllErr, setCopyAllErr] = useState('')
  // The plan-check warning lives on the chapter's own card: the orange ⚠ opens it, and the AI can fix the plan from there.
  const [warnOpen, setWarnOpen] = useState(null)      // chapter number whose warning box is open
  const [fixing, setFixing] = useState(null)          // chapter being re-planned
  const [fixResult, setFixResult] = useState(null)
  async function fixPlan(n) {
    setFixing(n); setFixResult(null)
    try {
      const r = await api.skeletonFix(projectId, n)
      setFixResult({ n, ...r })
      afterGenerate({})
    } catch (e) { setFixResult({ n, error: e.message || 'The fix failed' }) }
    finally { setFixing(null) }
  }
  const warnsOf = ch => ch.gate_warnings || []

  // Mobile (or a side panel): card list instead of a wide table; editor becomes a slide-over
  const isNarrow = useNarrowLayout()

  useEffect(() => { setChapters(initChapters) }, [JSON.stringify(initChapters)])

  const arcLabels = arcs.map(a => a.label).filter(Boolean)

  function onGenDone(res) {
    afterGenerate(res)
    // Let afterGenerate's reload drive the update via initChapters — don't overwrite with partial result
  }

  async function syncFromChapters() {
    setSyncing(true)
    setSyncMsg('')
    try {
      const res = await api.syncSkeleton(projectId)
      if (res.synced > 0) {
        setChapters(res.chapter_skeletons)
        setSyncMsg(`✓ Synced ${res.synced} chapter${res.synced !== 1 ? 's' : ''} (${res.synced_chapters.map(n => `Ch${n}`).join(', ')})`)
      } else {
        setSyncMsg('No written chapters to sync — generate some chapters first.')
      }
    } catch (e) {
      setSyncMsg(`✗ ${e.message?.slice(0, 80) || 'Sync failed'}`)
    } finally {
      setSyncing(false)
      setTimeout(() => setSyncMsg(''), 4000)
    }
  }

  function startEdit(i) {
    setEditIdx(i)
    setEditForm({ ...chapters[i] })
  }

  async function saveEdit() {
    setSaving(true)
    const updated = chapters.map((c, i) => i === editIdx ? { ...c, ...editForm } : c)
    setChapters(updated)
    setEditIdx(null)
    await onSave({ chapter_skeletons: updated })
    setSaving(false)
  }

  async function deleteChapter(i) {
    const updated = chapters.filter((_, idx) => idx !== i)
    setChapters(updated)
    if (editIdx === i) setEditIdx(null)
    await onSave({ chapter_skeletons: updated })
  }

  async function addChapter() {
    // the next chapter an arc covers that has no entry yet (not just "one past the last one")
    const have = new Set(chapters.map(c => c.number))
    const arcNums = arcs.flatMap(a => a.chapters || []).filter(Number.isInteger).sort((a, b) => a - b)
    const next = arcNums.find(n => !have.has(n)) ?? ((chapters.length ? Math.max(...chapters.map(c => c.number || 0)) : 0) + 1)
    const newCh = { number: next, title: `Chapter ${next}`, arc: arcLabels[0] || '', purpose: '', key_event: '', hook: '', tension: 50 }
    const updated = [...chapters, newCh]
    setChapters(updated)
    setEditIdx(updated.length - 1)
    setEditForm(newCh)
    await onSave({ chapter_skeletons: updated })
  }

  function warnBox(ch) {
    const ws = warnsOf(ch)
    const res = fixResult && fixResult.n === ch.number ? fixResult : null
    if (!ws.length && !res) return null
    if (warnOpen !== ch.number && !res) return null
    return (
      <div onClick={e => e.stopPropagation()} style={{
        fontSize: 10.5, color: 'var(--amber)', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.3)',
        borderRadius: 6, padding: '6px 9px', margin: '6px 0', lineHeight: 1.5, whiteSpace: 'normal',
      }}>
        {ws.length > 0 && <b>Chapter {ch.number} — plan check:</b>}
        {ws.map((w, i) => <div key={i}>• {w}</div>)}
        {ws.length > 0 && (
          <button onClick={() => fixPlan(ch.number)} disabled={fixing != null}
            title="The AI re-plans this chapter itself: it remixes Blueprint entries, narrative patterns and comparable corpus chapters (adapted to your story, never copied) to replace what clashes, then re-checks the result. Your old plan stays on Undo."
            style={{
              marginTop: 6, padding: '4px 12px', fontSize: 11, fontWeight: 700, borderRadius: 6, cursor: fixing != null ? 'default' : 'pointer',
              background: fixing === ch.number ? 'var(--bg-elevated)' : 'var(--amber)', color: fixing === ch.number ? 'var(--text-muted)' : '#1f1300',
              border: 'none', display: 'inline-flex', alignItems: 'center', gap: 6, opacity: fixing != null && fixing !== ch.number ? 0.5 : 1,
            }}>{fixing === ch.number ? <><Spinner /> Re-planning with a remix… (a couple of minutes)</> : '✦ Fix with AI — remix blueprints + corpus'}</button>
        )}
        {res && (
          <div style={{ marginTop: 6, color: res.error ? 'var(--red)' : res.warnings?.length ? 'var(--amber)' : 'var(--green)' }}>
            {res.error ? `✗ ${res.error}`
              : res.message ? res.message
              : res.warnings?.length ? `Re-planned — ${res.warnings.length} warning(s) remain; you can run the fix again or edit the plan.`
              : '✓ Re-planned: the warning is cleared. Your previous plan is on Undo.'}
            {res.remix_used && !res.error && (
              <span style={{ color: 'var(--text-muted)' }}> · remix from {['blueprints', 'patterns', 'chapters'].filter(k => res.remix_used[k]).join(', ') || 'no corpus matches'}</span>
            )}
          </div>
        )}
      </div>
    )
  }
  function warnFlag(ch, size) {
    const n = warnsOf(ch).length
    if (!n) return null
    return (
      <button onClick={e => { e.stopPropagation(); setWarnOpen(warnOpen === ch.number ? null : ch.number) }}
        title={`${n} plan-check warning${n !== 1 ? 's' : ''} — click to see them and let the AI fix this plan`}
        style={{ fontSize: size, padding: size > 10 ? '2px 8px' : '2px 6px', borderRadius: 3, background: 'rgba(245,158,11,0.15)', border: '1px solid var(--amber)', color: 'var(--amber)', fontWeight: 700, flexShrink: 0, marginRight: 3 }}>
        ⚠ {n}
      </button>
    )
  }
  const EF = editForm || {}
  const arcLabelSet = new Set(arcLabels)
  const orphanCount = chapters.filter(ch => ch.arc && !arcLabelSet.has(ch.arc)).length

  async function fixOrphans() {
    if (!arcs.length) return
    const updated = chapters.map(ch => {
      if (ch.arc && arcLabelSet.has(ch.arc)) return ch
      // Assign to whichever arc covers this chapter number, or fallback to first arc
      const num = ch.number || 0
      const matched = arcs.find(a => a.chapters && a.chapters.includes(num))
      return { ...ch, arc: matched ? matched.label : arcs[0].label }
    })
    setChapters(updated)
    await onSave({ chapter_skeletons: updated })
  }

  async function copyAllChapters() {
    if (!chapters.length) return
    setCopyAllErr('')
    const text = chapters.map(ch => {
      const lines = [`Chapter ${ch.number}${ch.title ? `: ${ch.title}` : ''}`]
      if (ch.arc) lines.push(`Arc: ${ch.arc}`)
      if (ch.tension != null) lines.push(`Tension: ${ch.tension}`)
      if (ch.purpose) lines.push(`\nPurpose: ${ch.purpose}`)
      if (ch.key_event) lines.push(`\nKey Event: ${ch.key_event}`)
      if (ch.hook) lines.push(`\nHook: ${ch.hook}`)
      return lines.join('\n')
    }).join('\n\n---\n\n')
    const ok = await copyTextToClipboard(text, () => setCopyAllErr('Copy failed — your browser blocked clipboard access. Try selecting the text manually.'))
    if (ok) {
      setCopiedAll(true)
      setTimeout(() => setCopiedAll(false), 2000)
    }
  }

  if (chapters.length === 0) return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
      <div style={{ textAlign: 'center', maxWidth: 420, margin: '10px auto 16px' }}>
        <div style={{ fontSize: 36, marginBottom: 12 }}>◈</div>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 8 }}>No chapters planned yet</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Plan chapters one at a time — each sees the previous chapter in full and its
          arc's contract, so the prose engine gets a scene-level specification.
        </div>
      </div>
      <SequentialSkeletonPanel
        chapters={chapters} arcs={arcs} projectId={projectId}
        onChanged={() => afterGenerate({})}
      />
    </div>
  )

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
      {/* Table */}
      <div style={{ flex: 1, overflowY: 'auto', padding: isNarrow ? '12px 10px' : '16px 20px' }}>
        <SequentialSkeletonPanel
          chapters={chapters} arcs={arcs} projectId={projectId}
          onChanged={() => afterGenerate({})}
        />
        <div style={{ height: 10 }} />
        <ChapterValidationPanel projectId={projectId} chapters={chapters} />
        <div style={{ height: 10 }} />
        <Panel>
          <PanelTitle action={
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={addChapter} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add</button>
              <button onClick={copyAllChapters} title="Copy every planned chapter's title/arc/purpose/key event/hook as readable text" style={{
                fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)',
                background: copiedAll ? 'var(--green-dim)' : 'var(--bg-elevated)',
                border: `1px solid ${copiedAll ? 'var(--green)' : 'var(--border)'}`,
                color: copiedAll ? 'var(--green)' : 'var(--text-secondary)',
                transition: 'all 0.2s',
              }}>{copiedAll ? '✓ Copied' : '⎘ Copy All'}</button>
              <button onClick={syncFromChapters} disabled={syncing} title="Update skeleton entries for chapters already written" style={{
                fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)',
                background: syncing ? 'var(--bg-elevated)' : 'var(--bg-elevated)',
                border: '1px solid var(--green)', color: 'var(--green)',
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                {syncing ? <Spinner size={9} /> : '⇄'} Sync Written
              </button>
              {orphanCount > 0 && (
                <button onClick={fixOrphans} title="Reassign chapters whose arc was deleted" style={{
                  fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--amber)', color: 'var(--amber)', background: 'var(--bg-elevated)',
                  display: 'flex', alignItems: 'center', gap: 4,
                }}>⚠ Fix {orphanCount} Orphaned</button>
              )}
              {/* The batch generator ("Append Next 20") is deliberately gone —
                  it planned 20 chapters in one call off a 5-chapter tail and
                  would overwrite sequential work. Generation now lives in
                  SequentialSkeletonPanel above. */}
            </div>
          }>{chapters.length} chapters planned{syncMsg && <span style={{ fontSize: 10, fontWeight: 400, color: syncMsg.startsWith('✓') ? 'var(--green)' : 'var(--amber)', marginLeft: 10 }}>{syncMsg}</span>}</PanelTitle>
          {copyAllErr && <div style={{ fontSize: 10.5, color: 'var(--amber)', marginBottom: 8 }}>{copyAllErr}</div>}
          {isNarrow ? (
            /* mobile: tappable cards instead of a wide table */
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {chapters.map((ch, i) => {
                const isOrphan = ch.arc && !arcLabelSet.has(ch.arc)
                // The interactive interview's skeleton has no top-level purpose/tension — only
                // per-scene purpose and a tension_curve object. Same gap as SkeletonDetail/the
                // View Plan preview above: fall back rather than show nothing for that chapter.
                const purpose = ch.purpose || ch.scenes?.[0]?.purpose
                const tension = ch.tension ?? ch.tension_curve?.peak
                return (
                  <div key={i} onClick={() => startEdit(i)} style={{
                    padding: '10px 12px', borderRadius: 'var(--radius)',
                    background: editIdx === i ? 'var(--accent-dim)' : isOrphan ? 'rgba(245,158,11,0.07)' : 'var(--bg-elevated)',
                    border: `1px solid ${editIdx === i ? 'var(--accent)' : 'var(--border-soft)'}`,
                    cursor: 'pointer',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent-light)', flexShrink: 0 }}>#{ch.number || i + 1}</span>
                      <span style={{ fontSize: 12, fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ch.title || '—'}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>T{tension ?? '—'}</span>
                      {warnFlag(ch, 11)}
                      <button onClick={e => { e.stopPropagation(); startEdit(i) }} title="Edit this chapter's skeleton" style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, background: 'var(--accent-dim)', border: '1px solid var(--accent)', color: 'var(--accent-light)', flexShrink: 0 }}>✎ Edit</button>
                      <button onClick={e => { e.stopPropagation(); deleteChapter(i) }} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)', flexShrink: 0 }}>✕</button>
                    </div>
                    {(ch.arc || purpose) && (
                      <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                        {ch.arc && <span style={{ color: isOrphan ? 'var(--amber)' : 'var(--cyan)', fontWeight: 600 }}>{isOrphan ? `⚠ ${ch.arc}` : ch.arc}{purpose ? ' · ' : ''}</span>}
                        {purpose && <span>{String(purpose).slice(0, 90)}{String(purpose).length > 90 ? '…' : ''}</span>}
                      </div>
                    )}
                    {warnBox(ch)}
                    {/* Scene/beat detail — only present on sequentially-planned chapters */}
                    <SkeletonDetail ch={ch} />
                  </div>
                )
              })}
            </div>
          ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>{['#','Title','Arc','Purpose','T',''].map(h => (
                <th key={h} style={{ padding: '5px 8px', textAlign: 'left', fontSize: 10, color: 'var(--text-muted)', fontWeight: 700, borderBottom: '1px solid var(--border-soft)' }}>{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {chapters.map((ch, i) => {
                const isOrphan = ch.arc && !arcLabelSet.has(ch.arc)
                // Same schema fallback as the mobile card view above.
                const purpose = ch.purpose || ch.scenes?.[0]?.purpose
                const tension = ch.tension ?? ch.tension_curve?.peak
                return (
                <Fragment key={i}>
                <tr style={{ borderBottom: '1px solid var(--border-soft)', background: editIdx === i ? 'var(--accent-dim)' : isOrphan ? 'rgba(245,158,11,0.07)' : 'transparent' }}>
                  <td style={{ padding: '5px 8px', fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{ch.number || i + 1}</td>
                  <td style={{ padding: '5px 8px', fontSize: 11, cursor: 'pointer' }} onClick={() => startEdit(i)}>{ch.title || '—'}</td>
                  <td style={{ padding: '5px 8px', fontSize: 11, color: isOrphan ? 'var(--amber)' : 'var(--text-muted)', whiteSpace: 'nowrap' }}>{isOrphan ? `⚠ ${ch.arc}` : (ch.arc || '—')}</td>
                  <td style={{ padding: '5px 8px', fontSize: 11, color: 'var(--text-muted)', maxWidth: 200 }}>{purpose || '—'}</td>
                  <td style={{ padding: '5px 8px', fontSize: 11, textAlign: 'right', whiteSpace: 'nowrap' }}>{tension ?? '—'}</td>
                  <td style={{ padding: '5px 4px', whiteSpace: 'nowrap' }}>
                    {warnFlag(ch, 10)}
                    <button onClick={() => startEdit(i)} title="Edit this chapter's skeleton" style={{ fontSize: 10, padding: '2px 8px', borderRadius: 3, background: 'var(--accent-dim)', border: '1px solid var(--accent)', color: 'var(--accent-light)', marginRight: 3 }}>✎ Edit</button>
                    <button onClick={() => deleteChapter(i)} style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                  </td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-soft)' }}>
                  <td></td>
                  <td colSpan={5} style={{ padding: '0 8px' }}>
                    {warnBox(ch)}
                    <SkeletonDetail ch={ch} />
                  </td>
                </tr>
                </Fragment>
              )})}

            </tbody>
          </table>
          )}
        </Panel>
      </div>

      {/* Edit panel — a full-page overlay instead of a cramped 320px sidebar.
          Editing a real skeleton means reading/writing long structured text
          (purpose, key_event, canon_lock, per-character intentions, per-scene
          notes) — a narrow drawer with 2-row textareas made that a chore.
          This takes the whole viewport (minus a small margin) and lays flat
          fields and the advanced editor side-by-side on wide screens so
          there's room to actually work, single column on mobile. */}
      {editIdx !== null && editForm && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.55)',
          display: 'flex', alignItems: isNarrow ? 'stretch' : 'center', justifyContent: 'center',
          padding: isNarrow ? 0 : 24,
        }} onClick={() => setEditIdx(null)}>
          <div onClick={e => e.stopPropagation()} style={{
            width: isNarrow ? '100%' : 'min(1100px, 96vw)',
            height: isNarrow ? '100%' : 'min(92vh, 1000px)',
            background: 'var(--bg-surface)', borderRadius: isNarrow ? 0 : 'var(--radius-lg)',
            border: isNarrow ? 'none' : '1px solid var(--border)',
            display: 'flex', flexDirection: 'column', overflow: 'hidden',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}>
            {/* Sticky header — always visible while the body scrolls */}
            <div style={{
              flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '14px 20px', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)',
            }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent)' }}>
                Editing Chapter {EF.number}{EF.title ? ` — ${EF.title}` : ''}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={saveEdit} disabled={saving} className="btn-primary" style={{ padding: '7px 18px', fontSize: 12 }}>{saving ? 'Saving…' : '✓ Save'}</button>
                <button onClick={() => setEditIdx(null)} className="btn-ghost" style={{ padding: '7px 14px', fontSize: 12 }}>✕ Close</button>
              </div>
            </div>

            {/* Scrollable body — this is the whole point: plenty of room to
                read and edit, not squeezed into a sidebar. */}
            <div style={{
              flex: 1, overflowY: 'auto', padding: isNarrow ? '14px' : '20px 24px',
              display: 'grid', gridTemplateColumns: isNarrow ? '1fr' : 'minmax(320px, 420px) 1fr',
              gap: isNarrow ? 16 : 28, alignContent: 'start',
            }}>
              {/* Left column: the core flat fields, generously sized */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Title</div>
                  <input value={EF.title || ''} onChange={e => setEditForm(f => ({ ...f, title: e.target.value }))} style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)' }} />
                </div>

                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Arc</div>
                  {arcLabels.length > 0
                    ? <select value={EF.arc || ''} onChange={e => setEditForm(f => ({ ...f, arc: e.target.value }))} style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)' }}>
                        <option value="">— no arc —</option>
                        {arcLabels.map(l => <option key={l} value={l}>{l}</option>)}
                      </select>
                    : <input value={EF.arc || ''} onChange={e => setEditForm(f => ({ ...f, arc: e.target.value }))} style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)' }} />
                  }
                </div>

                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Purpose</div>
                  <textarea value={EF.purpose || ''} onChange={e => setEditForm(f => ({ ...f, purpose: e.target.value }))} rows={5} style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)', resize: 'vertical', lineHeight: 1.5 }} />
                </div>

                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Key Event</div>
                  <textarea value={EF.key_event || ''} onChange={e => setEditForm(f => ({ ...f, key_event: e.target.value }))} rows={6} style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)', resize: 'vertical', lineHeight: 1.5 }} />
                </div>

                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Hook / Cliffhanger</div>
                  <textarea value={EF.hook || ''} onChange={e => setEditForm(f => ({ ...f, hook: e.target.value }))} rows={4} style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)', resize: 'vertical', lineHeight: 1.5 }} />
                </div>

                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Tension ({EF.tension ?? 50}/100)</div>
                  <input type="range" min={0} max={100} value={EF.tension ?? 50} onChange={e => setEditForm(f => ({ ...f, tension: Number(e.target.value) }))} style={{ width: '100%', accentColor: 'var(--accent)' }} />
                </div>
              </div>

              {/* Right column: canon lock, characters, scenes, anti-patterns,
                  hard constraints — the structural-discipline schema, given
                  real room instead of a squeezed accordion. */}
              <div>
                <SkeletonAdvancedEditor editForm={editForm} setEditForm={setEditForm} defaultOpen />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Small shared bits for the advanced skeleton editor below ── */
export function AdvField({ label, value, onChange, rows = 2, placeholder }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
      {rows === 1
        ? <input value={value || ''} placeholder={placeholder} onChange={e => onChange(e.target.value)}
            style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
        : <textarea value={value || ''} placeholder={placeholder} rows={rows} onChange={e => onChange(e.target.value)}
            style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
      }
    </div>
  )
}

/**
 * Everything _skeleton_record_schema defines beyond the 6 flat fields already
 * editable above — collapsed by default (mirrors SkeletonDetail's own "▼ Full
 * skeleton detail" toggle) since most edits are to the flat fields and this
 * is a lot of form for fields usually populated via the Interactive interview
 * rather than hand-typed. Every sub-field here maps 1:1 to a key in
 * _skeleton_record_schema (generate.py) — see that docstring for what each
 * one is FOR, not just its shape.
 */
export function SkeletonAdvancedEditor({ editForm, setEditForm, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const f = editForm || {}
  const set = (key, val) => setEditForm(cur => ({ ...cur, [key]: val }))
  const setPath = (key, subkey, val) => setEditForm(cur => ({ ...cur, [key]: { ...(cur[key] || {}), [subkey]: val } }))

  const characters = Array.isArray(f.characters_in_chapter) ? f.characters_in_chapter : []
  const scenes = Array.isArray(f.scenes) ? f.scenes : []
  const setCharAt = (i, patch) => set('characters_in_chapter', characters.map((c, idx) => idx === i ? { ...c, ...patch } : c))
  const setSceneAt = (i, patch) => set('scenes', scenes.map((s, idx) => idx === i ? { ...s, ...patch } : s))

  return (
    <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 8 }}>
      <button onClick={() => setOpen(x => !x)} style={{
        fontSize: 10, padding: '3px 10px', width: '100%',
        background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 4,
        color: 'var(--accent-light)',
      }}>{open ? '▲ Hide advanced fields' : '▼ Advanced (canon lock, characters, scenes, constraints…)'}</button>

      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
          <AdvField label="Hook withholds" placeholder="What must stay unresolved past this chapter's end"
            value={f.hook_withholds} onChange={v => set('hook_withholds', v)} rows={3} />
          <AdvField label="Author notes" placeholder="Explicit warnings for the generation model"
            value={f.author_notes} onChange={v => set('author_notes', v)} rows={4} />

          <div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3, fontWeight: 700 }}>Canon lock</div>
            <AdvField label="Staging rule" placeholder="Any ceremony/mechanic prop this chapter reuses"
              value={f.canon_lock?.staging_rule} onChange={v => setPath('canon_lock', 'staging_rule', v)} rows={3} />
            <div style={{ height: 4 }} />
            <AdvField label="Numeric canon" placeholder="Specific numbers/ranks/grades this chapter depends on"
              value={f.canon_lock?.numeric_canon} onChange={v => setPath('canon_lock', 'numeric_canon', v)} rows={3} />
          </div>

          <div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3, fontWeight: 700 }}>Characters in chapter</div>
            {characters.map((c, i) => (
              <div key={i} style={{ border: '1px solid var(--border-soft)', borderRadius: 6, padding: 8, marginBottom: 6 }}>
                <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  <input value={c.name || ''} placeholder="Character name"
                    onChange={e => setCharAt(i, { name: e.target.value })}
                    style={{ flex: 1, padding: '5px 8px', fontSize: 12, fontWeight: 600, borderRadius: 'var(--radius-sm)' }} />
                  <button onClick={() => set('characters_in_chapter', characters.filter((_, idx) => idx !== i))}
                    style={{ fontSize: 10, padding: '0 8px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                </div>
                <AdvField label="Enters believing" value={c.enters_believing} rows={2}
                  onChange={v => setCharAt(i, { enters_believing: v })} />
                <div style={{ height: 4 }} />
                <AdvField label="True intention" value={c.true_intention} rows={2}
                  onChange={v => setCharAt(i, { true_intention: v })} />
                <div style={{ height: 4 }} />
                <AdvField label="Knowledge state" value={c.knowledge_state} rows={2}
                  onChange={v => setCharAt(i, { knowledge_state: v })} />
                <div style={{ height: 4 }} />
                <AdvField label="Arc within chapter" value={c.arc_within_chapter} rows={2}
                  onChange={v => setCharAt(i, { arc_within_chapter: v })} />
              </div>
            ))}
            <button onClick={() => set('characters_in_chapter', [...characters, { name: '', enters_believing: '', true_intention: '', knowledge_state: '', arc_within_chapter: '' }])}
              style={{ fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add character</button>
          </div>

          <div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3, fontWeight: 700 }}>Scenes</div>
            {scenes.map((s, i) => (
              <div key={i} style={{ border: '1px solid var(--border-soft)', borderRadius: 6, padding: 8, marginBottom: 6 }}>
                <div style={{ display: 'flex', gap: 4, marginBottom: 4, alignItems: 'center' }}>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>#{s.scene_number ?? i + 1}</span>
                  <input value={s.scene_type || ''} placeholder="scene_type (dialogue/action/…)"
                    onChange={e => setSceneAt(i, { scene_type: e.target.value })}
                    style={{ flex: 1, padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
                  <button onClick={() => set('scenes', scenes.filter((_, idx) => idx !== i))}
                    style={{ fontSize: 10, padding: '0 8px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                </div>
                <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  <input value={s.pov_character || ''} placeholder="POV character"
                    onChange={e => setSceneAt(i, { pov_character: e.target.value })}
                    style={{ flex: 1, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
                  <input value={s.pacing || ''} placeholder="pacing"
                    onChange={e => setSceneAt(i, { pacing: e.target.value })}
                    style={{ width: 90, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
                  <input type="number" value={s.tension_level ?? ''} placeholder="tension"
                    onChange={e => setSceneAt(i, { tension_level: e.target.value ? Number(e.target.value) : undefined })}
                    style={{ width: 60, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
                  <input type="number" value={s.estimated_word_count ?? ''} placeholder="~words"
                    onChange={e => setSceneAt(i, { estimated_word_count: e.target.value ? Number(e.target.value) : undefined })}
                    style={{ width: 70, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
                </div>
                <AdvField label="Structure notes" value={s.structure_notes} rows={4}
                  onChange={v => setSceneAt(i, { structure_notes: v })} />
                <div style={{ height: 4 }} />
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Min dialogue lines (0 = not applicable)</div>
                <input type="number" min={0} value={s.min_dialogue_lines ?? 0}
                  onChange={e => setSceneAt(i, { min_dialogue_lines: Number(e.target.value) || 0 })}
                  style={{ width: 70, padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
              </div>
            ))}
            <button onClick={() => set('scenes', [...scenes, { scene_number: scenes.length + 1, scene_type: '', pov_character: '', tension_level: 5, pacing: 'steady', estimated_word_count: 300, structure_notes: '' }])}
              style={{ fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add scene</button>
          </div>

          <AdvStringList label="Anti-patterns (do NOT)" items={f.anti_patterns}
            onChange={v => set('anti_patterns', v)} placeholder="e.g. must be instant, not a climb-then-collapse" />

          <AdvField label="Hard constraints" placeholder="3-6 checks that must hold true in the generated prose"
            value={f.hard_constraints?.description} onChange={v => setPath('hard_constraints', 'description', v)} rows={4} />

          <AdvStringList label="Reveals" items={f.reveals}
            onChange={v => set('reveals', v)} placeholder="what the reader learns this chapter" />

          <AdvField label="Pattern used" placeholder="power_reveal | strategic_victory | comedy_sequence | …"
            value={f.pattern_used} onChange={v => set('pattern_used', v)} rows={1} />
          <AdvField label="Pattern escalation note" placeholder="how this instance raises the stakes past the last use"
            value={f.pattern_escalation_note} onChange={v => set('pattern_escalation_note', v)} />
        </div>
      )}
    </div>
  )
}
