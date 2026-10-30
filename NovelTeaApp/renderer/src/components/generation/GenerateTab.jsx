import useStore from '../../store/useStore'
import { useEffect, useState } from 'react'
import useNarrowLayout from '../../hooks/useNarrowLayout'
import { api } from '../../api'
import { FieldSurveyButton, Panel, PanelTitle } from '../shared/projectUi'

export function GenerateTab({ project, arcs, chapters, hasPremise, hasArcs, onSave, reload, projectId, afterGenerate, onOpenReader,
                      chapterNumber }) {
  // ── Console — now the GLOBAL app-wide console (see EngineConsole.jsx +
  // useStore's console slice + startConsolePoller). The backend's own
  // progress store (_PROGRESS[project_id]) is still the single source of
  // truth for what happened during a run; the shared poller in useStore
  // fetches it the same way this tab used to, so every action below just
  // needs to tell the STORE when something starts/stops instead of keeping
  // its own consoleOpen/consoleLines/running state.
  const { appendConsoleLine, setConsoleRunning, clearConsoleRunning } = useStore()
  const running = useStore(s => s.consoleRunning)
  const consoleOpen = useStore(s => s.consoleOpen)
  const [chapterNum, setChapterNum] = useState(1)
  // Default the chapter box to the NEXT unwritten chapter (highest generated + 1)
  // so you don't have to type it — e.g. with ch1 written, it pre-fills 2.
  useEffect(() => { if (chapterNumber) setChapterNum(chapterNumber) }, [chapterNumber])   // the page owns the chapter number
  // Progress polling and reconnect-on-navigate are now handled by the global
  // console poller in useStore.js (startConsolePoller) — it already fetches
  // /generate/progress and /generate/active for whichever project is open,
  // regardless of which tab/page is mounted. `flushProgress` used to force
  // one extra fetch right before a synthetic ✓/✗ line so the backend's own
  // final entries landed first; the poller's ~900ms cadence while `running`
  // is set makes that no longer necessary — a completion line arriving very
  // slightly ahead of the last backend line is a cosmetic non-issue.
  async function flushProgress() { /* no-op — kept as a call-site no-op, see above */ }

  // ── Abort: /api/generate/abandon KILLS the live Claude CLI subprocess
  // (taskkill /T on Windows — the whole node.exe process tree, not just the
  // parent) and clears the dedup lock. The console's own Abort button
  // (EngineConsole.jsx) calls this directly via the store's consoleField.
  function addLog(msg, type = 'info') { appendConsoleLine(msg, type) }

  const isNarrow = useNarrowLayout()
  // Discovery: harvest generator inventions back into the planning tabs
  const [discovering, setDiscovering] = useState(false)
  const [discoveryResult, setDiscoveryResult] = useState(null)
  async function runDiscovery(full = false) {
    setDiscovering(true)
    setDiscoveryResult(null)
    setConsoleRunning('discovery')   // activates the console + progress poller
    try {
      const r = await api.discover(projectId, full)
      await flushProgress()
      setDiscoveryResult(r)
      if (r.total > 0) reload && reload()   // refresh tabs so new entries show
    } catch (e) {
      await flushProgress()
      setDiscoveryResult({ total: 0, added: {}, error: e.message })
      addLog(`✗ Discovery failed: ${e.message}`, 'error')
    } finally { setDiscovering(false); clearConsoleRunning() }
  }
  // Corpus Suggestions: compare each chapter against the same chapter-number
  // range across sampled corpus novels' full craft schema, apply prose fixes
  const [suggesting, setSuggesting] = useState(false)
  const [suggestResult, setSuggestResult] = useState(null)
  async function runCorpusSuggestions(full = false) {
    setSuggesting(true)
    setSuggestResult(null)
    setConsoleRunning('suggestions')
    try {
      const r = await api.corpusSuggestions(projectId, full)
      await flushProgress()
      setSuggestResult(r)
      if (r.total > 0) reload && reload()
    } catch (e) {
      await flushProgress()
      setSuggestResult({ total: 0, changes: [], error: e.message })
      addLog(`✗ Corpus Suggestions failed: ${e.message}`, 'error')
    } finally { setSuggesting(false); clearConsoleRunning() }
  }
  // slider max = however many novels the corpus actually has (not a fixed 8).
  // Use the cheap registry endpoint — the old source (brainGraph) scans the
  // whole corpus and takes 10s+ on a slow machine; when it timed out its
  // failure was silently swallowed and the stale useState(8) default stuck,
  // showing "8" instead of the real 16 in the Generate tab.
  const [corpusTotal, setCorpusTotal] = useState(16)
  useEffect(() => {
    api.registry().then(d => {
      const n = Array.isArray(d) ? d.length : (d?.novels?.length || 0)
      if (n) setCorpusTotal(n)
    }).catch(() => {
      api.brainGraph().then(d => { if (d?.novel_count) setCorpusTotal(d.novel_count) }).catch(() => {})
    })
  }, [])
  // Per-project grep override (empty = use the global Settings default).
  const [grepOverride, setGrepOverride] = useState(() => window.__nmGrep || '')
  useEffect(() => { window.__nmGrep = grepOverride || null }, [grepOverride])

  async function planChapter() {
    setConsoleRunning('plan')
    addLog(`Planning chapter ${chapterNum}…`)
    try {
      const res = await api.planChapter(projectId, chapterNum)
      addLog(`✓ Chapter ${chapterNum} plan ready.`, 'success')
    } catch (e) {
      addLog(`✗ ${e.message}`, 'error')
    } finally {
      clearConsoleRunning()
    }
  }

  // Dialogue Shaping is now an interactive wizard (FieldSurveyButton with
  // field="dialogue_shaping") — the interview's Q&A drives which narration
  // gets converted, instead of an agent deciding autonomously. This handles
  // its onDone callback, logging the same summary the old one-shot version did.
  function handleDialogueShapingDone(res) {
    if (res.changed) {
      addLog(`✓ Chapter ${chapterNum} reshaped. ${res.summary || ''}`
        + (res.existing_characters_used?.length ? ` · developed: ${res.existing_characters_used.join(', ')}` : '')
        + (res.invented_characters?.length ? ` · invented: ${res.invented_characters.join(', ')}` : '')
        + (res.earlier_chapters_edited?.length ? ` · seeded into ch ${res.earlier_chapters_edited.join(', ')}` : ''), 'success')
      if (res.inspirations?.length) {
        addLog(`🧬 Voice DNA inspirations (${res.inspirations.length}):`, 'info')
        res.inspirations.forEach(i =>
          addLog(`   ${i.character || '?'} [${i.novel || '?'}]: “${(i.quote || '').slice(0, 120)}”`, 'info'))
      }
      if (onOpenReader) onOpenReader()
    } else {
      addLog(`Chapter ${chapterNum}: no reshaping applied.`, 'info')
    }
  }

  // Stage 4 of the Blueprint semantic search pipeline — see
  // corpus/STANDARDS_REVISION_PASS_PLAN.md. Same "interview then apply"
  // shape as Dialogue Shaping above, just enriching against the author's
  // saved Blueprint library + this project's own systems instead of voice_dna.
  function handleBlueprintEnrichmentDone(res) {
    if (res.changed) {
      addLog(`✓ Chapter ${chapterNum} enriched with Blueprint. ${res.summary || ''}`, 'success')
      if (onOpenReader) onOpenReader()
    } else {
      addLog(`Chapter ${chapterNum}: no enrichment applied.`, 'info')
    }
  }


  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* ── Controls — single flowing center column, no sidebar ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: isNarrow ? '12px 10px' : '16px 20px', display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 780, marginLeft: 'auto', marginRight: 'auto', width: '100%' }}>
        {/* Phase 2 — write */}
        <Panel>
          <PanelTitle>{`Chapter ${chapterNum} tools`}</PanelTitle>
          <FieldSurveyButton field="dialogue_shaping" projectId={projectId} chapterNumber={chapterNum}
            fullWidth label="🗣 Dialogue Shaping (Interactive)" disabled={!!running}
            onDone={handleDialogueShapingDone} />
          <FieldSurveyButton field="blueprint_enrichment" projectId={projectId} chapterNumber={chapterNum}
            fullWidth label="⎔ Enrich with Blueprint" disabled={!!running}
            onDone={handleBlueprintEnrichmentDone} />
        </Panel>

        {/* Discovery — harvest generator inventions back into planning */}
        <Panel>
          <PanelTitle>Discovery</PanelTitle>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
            The chapter generator is free to invent new characters, techniques, items and areas.
            Discovery adds anything new to the relevant tabs &amp; engines, AND checks whether any
            chapter/arc summary in planning has drifted out of sync with a hand-edited chapter —
            scanning only chapters it hasn't harvested yet (regenerated/edited chapters count as new again).
          </div>
          <button onClick={() => runDiscovery(false)} disabled={discovering} style={{
            width: '100%', padding: '9px 12px', fontWeight: 700, fontSize: 12,
            background: discovering ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#7c3aed,#c026d3)',
            color: discovering ? 'var(--text-muted)' : '#fff',
            border: 'none', borderRadius: 'var(--radius-sm)',
          }}>{discovering ? '🔍 Scanning chapters…' : '🔍 Run Discovery'}</button>
          {discoveryResult && (
            <div style={{ marginTop: 8, fontSize: 10.5, lineHeight: 1.6, color: 'var(--text-secondary)' }}>
              {discoveryResult.scanned?.length > 0 && (
                <div style={{ color: 'var(--text-muted)', marginBottom: 3 }}>
                  Scanned: {discoveryResult.scanned.map(n => `ch${n}`).join(', ')}
                </div>
              )}
              {discoveryResult.total === 0
                ? <span style={{ color: 'var(--text-muted)' }}>
                    {discoveryResult.message || 'Nothing new found — planning is up to date.'}
                  </span>
                : Object.entries(discoveryResult.added).filter(([, v]) => v.length > 0).map(([k, v]) => (
                    <div key={k}><b style={{ color: 'var(--accent-light)', textTransform: 'capitalize' }}>{k}</b>: {v.join(', ')}</div>
                  ))}

              {discoveryResult.skeleton_updates?.length > 0 && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-soft)' }}>
                  <b style={{ color: 'var(--amber, #f59e0b)' }}>Skeleton corrected</b> (chapter summary no longer matched the written text):
                  {discoveryResult.skeleton_updates.map((u, i) => (
                    <div key={i} style={{ marginTop: 2 }}>
                      ch{u.chapter}.{u.field} — <span style={{ color: 'var(--text-muted)' }}>{u.reason}</span>
                    </div>
                  ))}
                </div>
              )}

              {discoveryResult.arc_updates?.length > 0 && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-soft)' }}>
                  <b style={{ color: 'var(--amber, #f59e0b)' }}>Arc description corrected</b>:
                  {discoveryResult.arc_updates.map((u, i) => (
                    <div key={i} style={{ marginTop: 2 }}>
                      {u.arc} — <span style={{ color: 'var(--text-muted)' }}>{u.reason}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <button onClick={() => runDiscovery(true)} disabled={discovering} style={{
            marginTop: 6, width: '100%', padding: '3px 8px', fontSize: 9.5,
            background: 'transparent', border: 'none', color: 'var(--text-muted)',
            textDecoration: 'underline', cursor: 'pointer',
          }}>rescan all chapters</button>
        </Panel>

        {/* Corpus Suggestions — compare each chapter against the corpus's own
            craft schema for the same chapter range, apply concrete prose fixes */}
        <Panel>
          <PanelTitle>Corpus Suggestions</PanelTitle>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
            Reads the same chapter range (e.g. 1-10) across every corpus novel that has it extracted —
            tension curves, reveals, schemes, humor, reader psychology — and applies concrete craft
            fixes to your chapters. Free to invent new characters, techniques, items or areas when
            that's the real fix, inspired by (never copied from) the corpus. Only reviews chapters it
            hasn't checked yet (edited chapters count as new again). Any chapter it changes resets for
            Discovery, so you can re-harvest whatever it invented.
          </div>
          <button onClick={() => runCorpusSuggestions(false)} disabled={suggesting} style={{
            width: '100%', padding: '9px 12px', fontWeight: 700, fontSize: 12,
            background: suggesting ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#0891b2,#059669)',
            color: suggesting ? 'var(--text-muted)' : '#fff',
            border: 'none', borderRadius: 'var(--radius-sm)',
          }}>{suggesting ? '📖 Comparing to corpus…' : '📖 Run Corpus Suggestions'}</button>
          {suggestResult && (
            <div style={{ marginTop: 8, fontSize: 10.5, lineHeight: 1.6, color: 'var(--text-secondary)' }}>
              {suggestResult.reviewed?.length > 0 && (
                <div style={{ color: 'var(--text-muted)', marginBottom: 3 }}>
                  Reviewed: {suggestResult.reviewed.map(n => `ch${n}`).join(', ')}
                  {suggestResult.range && ` (vs. corpus ch${suggestResult.range[0]}-${suggestResult.range[1]})`}
                </div>
              )}
              {suggestResult.novels_compared?.length > 0 && (
                <div style={{ color: 'var(--text-muted)', marginBottom: 3 }}>
                  Compared against: {suggestResult.novels_compared.join(', ')}
                </div>
              )}
              {suggestResult.total === 0
                ? <span style={{ color: suggestResult.unverified ? 'var(--amber, #f59e0b)' : 'var(--text-muted)' }}>
                    {suggestResult.message || 'No changes needed — chapters already strong.'}
                  </span>
                : suggestResult.changes.map((c, i) => (
                    <div key={i} style={{ marginTop: 3 }}>
                      <b style={{ color: '#06b6d4' }}>ch{c.chapter}</b>: {c.summary}
                      {c.invented?.length > 0 && (
                        <span style={{ color: 'var(--accent-light)' }}> · invented: {c.invented.join(', ')}</span>
                      )}
                    </div>
                  ))}
              {suggestResult.discovery_reset?.length > 0 && (
                <div style={{ marginTop: 6, color: 'var(--amber, #f59e0b)' }}>
                  Discovery reset for: {suggestResult.discovery_reset.map(n => `ch${n}`).join(', ')} — run Discovery to harvest any new content.
                </div>
              )}
            </div>
          )}
          <button onClick={() => runCorpusSuggestions(true)} disabled={suggesting} style={{
            marginTop: 6, width: '100%', padding: '3px 8px', fontSize: 9.5,
            background: 'transparent', border: 'none', color: 'var(--text-muted)',
            textDecoration: 'underline', cursor: 'pointer',
          }}>re-review all chapters</button>
        </Panel>
      </div>
    </div>
  )
}
