import { useEffect, useState } from 'react'
import { api } from '../../api'
import useStore from '../../store/useStore'
import { SYSTEM_ENGINES, BLUEPRINT_ONLY_ENGINES, ENGINE_FIELDS, ARRAY_FIELDS, LONG_FIELDS } from '../../components/pre_generation/systemEngines'
import { Panel, PanelTitle } from '../../components/shared/projectUi'

// Blueprint's own nav shows every project system (from SYSTEM_ENGINES) PLUS
// entries that exist ONLY in the Blueprint library (BLUEPRINT_ONLY_ENGINES,
// e.g. Character Templates — no project generate button, so it's never in
// SYSTEM_ENGINES itself). The Project page's Systems tab never sees this
// combined list — it imports SYSTEM_ENGINES directly.
const ALL_BLUEPRINT_ENGINES = [...SYSTEM_ENGINES, ...BLUEPRINT_ONLY_ENGINES]

/* Blueprint — a global library of reference-backed blueprints for each
   system_type (Power Levels, World Bible, ...), meant to be used in a
   project verbatim, interactively adapted, or ignored for fresh generation.
   (Renamed from "Standard" — same feature, same storage — for clarity: a
   Blueprint is a reusable template a project builds FROM, not a fixed
   requirement a project must conform TO.)
   Reuses the project's own Systems tab building blocks DIRECTLY (SYSTEM_ENGINES'
   labels/icons/colors/renderItem, ENGINE_FIELDS, Panel/PanelTitle) rather than
   a parallel copy — the author asked for this to look exactly the same, and
   importing the real source is the only way that stays true after either
   page changes, not just true today. */

function useIsNarrow() {
  const [n, setN] = useState(() => window.innerWidth < 768)
  useEffect(() => {
    const on = () => setN(window.innerWidth < 768)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return n
}

function friendlyError(e) {
  const msg = String(e.message || e)
  const m = msg.match(/\d{3}\s+(\{.*\})/s) || msg.match(/(\{.*"detail".*\})/s)
  if (m) {
    try { return JSON.parse(m[1]).detail || msg } catch { /* fall through */ }
  }
  return msg
}

function fieldLabel(field) {
  return field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export default function BlueprintsPage() {
  const isNarrow = useIsNarrow()
  const appendConsoleLine = useStore(s => s.appendConsoleLine)
  const setConsoleRunningAbortable = useStore(s => s.setConsoleRunningAbortable)
  const clearConsoleRunning = useStore(s => s.clearConsoleRunning)
  const [systemTypes, setSystemTypes] = useState(ALL_BLUEPRINT_ENGINES.map(e => e.key))
  const [activeType, setActiveType] = useState(ALL_BLUEPRINT_ENGINES[0].key)
  const [navOpen, setNavOpen] = useState(!isNarrow)
  const [blueprints, setBlueprints] = useState([])
  const [loadingList, setLoadingList] = useState(false)
  const [error, setError] = useState('')
  const [viewing, setViewing] = useState(null)

  // Paste-to-LLM extraction
  const [pasteText, setPasteText] = useState('')
  const [extractHint, setExtractHint] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [items, setItems] = useState([])
  const [pendingItem, setPendingItem] = useState(null)
  const [pendingEditIdx, setPendingEditIdx] = useState(null) // null while reviewing the freshly-extracted item; an index while editing an already-collected one

  // Save form
  const [blueprintId, setBlueprintId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [source, setSource] = useState('')
  const [overview, setOverview] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedOk, setSavedOk] = useState('')

  useEffect(() => {
    api.blueprintSystemTypes().then(r => {
      if (r.system_types?.length) setSystemTypes(r.system_types)
    }).catch(() => {})
  }, [])

  async function loadList(type) {
    setLoadingList(true); setError('')
    try {
      const r = await api.blueprintList(type)
      setBlueprints(r.standards || r.blueprints || [])
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setLoadingList(false)
    }
  }

  useEffect(() => { loadList(activeType); setViewing(null) }, [activeType])

  const engine = ALL_BLUEPRINT_ENGINES.find(e => e.key === activeType) || ALL_BLUEPRINT_ENGINES[0]
  const isWorldBible = engine.isWorldBible || false
  const activeFields = ENGINE_FIELDS[activeType] || ['name', 'description']

  // World Bible extraction/review — separate state from the generic
  // single-list flow above, since a World Bible blueprint is ONE consolidated
  // object (world_name, power_tiers, rules, factions[], key_locations[],
  // races[]) reviewed as a whole, not a growing list of individually-
  // extracted homogeneous cards like every other system.
  const [wbPending, setWbPending] = useState(null)   // the extracted/edited consolidated object, pre-save

  function switchType(type) {
    setActiveType(type)
    setItems([]); setPendingItem(null); setPendingEditIdx(null); setPasteText(''); setExtractHint('')
    setBlueprintId(''); setDisplayName(''); setSource(''); setOverview(''); setSavedOk('')
    setWbPending(null)
    if (isNarrow) setNavOpen(false)
  }

  async function doExtract(bulk) {
    if (!pasteText.trim()) { setError('Paste some reference text first.'); return }
    setExtracting(true); setError(''); setPendingItem(null); setPendingEditIdx(null)
    // Announce which engine/model is about to run in the SAME global console
    // every other AI action in the app uses — before the (possibly slow or
    // hanging) call even starts, not just after it succeeds or fails. This
    // endpoint is a pure Settings lookup, so it resolves instantly even if
    // the extract call itself is about to sit unresponsive for minutes.
    let modelLabel = ''
    try {
      modelLabel = (await api.blueprintActiveModel()).model || ''
    } catch { /* best-effort — proceed without the label rather than block extraction */ }
    // Fresh id per extraction — POST /api/blueprints/abort with this same id
    // (wired to the console's Abort button below) actually kills the
    // in-flight LLM call, not just the UI's own waiting state.
    const abortKey = `blueprint_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
    appendConsoleLine(`⎔ Blueprint extract (${engine.label}${bulk ? ', bulk' : ''}): 🤖 using ${modelLabel || 'configured engine'}…`)
    setConsoleRunningAbortable(`blueprint:${activeType}`, abortKey, api.blueprintAbort)
    try {
      const r = await api.blueprintExtract(activeType, { text: pasteText, hint: extractHint.trim() || null, bulk, abort_key: abortKey })
      appendConsoleLine(`⎔ Blueprint extract: ✓ response received from ${r.model || modelLabel || 'engine'}`, 'success')
      if (bulk) {
        // Real bug this fixes: a paste naming several distinct entries
        // (multiple named techniques/abilities in one block, say) was only
        // ever coming back as ONE item. Bulk mode returns items[] instead
        // of item — add them all straight to the collected list (each is
        // still individually editable/removable there, same as a manual
        // add), rather than reviewing N items one at a time first.
        setItems(prev => [...prev, ...(r.items || [])])
        maybeAutofillBlueprintId()
        setPasteText(''); setExtractHint('')
      } else {
        setPendingItem(r.item)
      }
    } catch (e) {
      const msg = friendlyError(e)
      const wasAborted = /\b499\b/.test(String(e.message || ''))
      if (!wasAborted) setError(msg)   // an intentional Abort isn't an error banner — the console line covers it
      appendConsoleLine(`⎔ Blueprint extract: ${wasAborted ? '⏹' : '✗'} ${msg}`, wasAborted ? 'warn' : 'error')
    } finally {
      setExtracting(false)
      clearConsoleRunning()
    }
  }

  // World Bible extraction — one consolidated object back (world_name,
  // power_tiers, rules, factions[], key_locations[], races[]), not a list of
  // repeated items. bulk is never offered for this type from the UI, so this
  // always calls /extract with bulk=false.
  async function doExtractWorldBible() {
    if (!pasteText.trim()) { setError('Paste some reference text first.'); return }
    setExtracting(true); setError(''); setWbPending(null)
    let modelLabel = ''
    try { modelLabel = (await api.blueprintActiveModel()).model || '' } catch {}
    const abortKey = `blueprint_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
    appendConsoleLine(`⎔ Blueprint extract (${engine.label}): 🤖 using ${modelLabel || 'configured engine'}…`)
    setConsoleRunningAbortable(`blueprint:${activeType}`, abortKey, api.blueprintAbort)
    try {
      const r = await api.blueprintExtract(activeType, { text: pasteText, hint: extractHint.trim() || null, bulk: false, abort_key: abortKey })
      appendConsoleLine(`⎔ Blueprint extract: ✓ response received from ${r.model || modelLabel || 'engine'}`, 'success')
      setWbPending({
        world_name: r.item?.world_name || '',
        power_tiers: r.item?.power_tiers || [],
        rules: r.item?.rules || [],
        factions: r.item?.factions || [],
        key_locations: r.item?.key_locations || [],
        races: r.item?.races || [],
      })
      if (!blueprintId.trim()) {
        setBlueprintId(`world_${Date.now().toString(36)}`)
        if (!displayName.trim()) setDisplayName(`World Bible — ${new Date().toLocaleDateString()}`)
      }
      setPasteText(''); setExtractHint('')
    } catch (e) {
      const msg = friendlyError(e)
      const wasAborted = /\b499\b/.test(String(e.message || ''))
      if (!wasAborted) setError(msg)
      appendConsoleLine(`⎔ Blueprint extract: ${wasAborted ? '⏹' : '✗'} ${msg}`, wasAborted ? 'warn' : 'error')
    } finally {
      setExtracting(false)
      clearConsoleRunning()
    }
  }

  // Small helpers for editing wbPending's three tag-bearing lists inline —
  // same "name + description/importance + comma-separated tags" shape the
  // project's own WorldTab editor uses (ProjectView.jsx), so a saved
  // blueprint's items slot straight into a project's World Bible unchanged.
  function wbUpdateListItem(listKey, i, patch) {
    setWbPending(p => ({ ...p, [listKey]: p[listKey].map((it, idx) => idx === i ? { ...it, ...patch } : it) }))
  }
  function wbAddListItem(listKey, blank) {
    setWbPending(p => ({ ...p, [listKey]: [...(p[listKey] || []), blank] }))
  }
  function wbRemoveListItem(listKey, i) {
    setWbPending(p => ({ ...p, [listKey]: p[listKey].filter((_, idx) => idx !== i) }))
  }

  async function doSaveWorldBible() {
    setSaving(true); setError(''); setSavedOk('')
    try {
      const r = await api.blueprintSave({
        system_type: activeType,
        standard_id: blueprintId.trim(),
        display_name: displayName.trim() || blueprintId.trim(),
        source: source.trim(),
        overview: overview.trim(),
        rules: wbPending.rules || [],
        items: [wbPending],   // single consolidated object, in a one-element array — see standards.py save_standard()
      })
      setSavedOk(r.path || 'Saved.')
      loadList(activeType)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setSaving(false)
    }
  }

  // Real bug this fixes: the Save button silently stayed disabled after
  // extracting items because blueprintId is a SEPARATE manual field the
  // extraction flow never touched — nothing indicated why the button
  // wouldn't respond. Auto-fill a reasonable default the first time items
  // go from empty to non-empty (never overwrites something already typed),
  // so the common case just works; the inline hint below the button covers
  // whatever this doesn't.
  function maybeAutofillBlueprintId() {
    if (blueprintId.trim()) return
    const base = `${activeType}_${Date.now().toString(36)}`
    setBlueprintId(base)
    if (!displayName.trim()) setDisplayName(`${engine.label} — ${new Date().toLocaleDateString()}`)
  }

  function acceptPendingItem() {
    setItems(prev => [...prev, pendingItem])
    maybeAutofillBlueprintId()
    setPendingItem(null); setPasteText(''); setExtractHint('')
  }

  function startEditCollected(i) {
    setPendingItem({ ...items[i] })
    setPendingEditIdx(i)
  }

  function saveEditedItem() {
    if (pendingEditIdx === null) return
    setItems(prev => prev.map((it, i) => i === pendingEditIdx ? pendingItem : it))
    setPendingItem(null); setPendingEditIdx(null)
  }

  function removeItem(i) {
    setItems(prev => prev.filter((_, idx) => idx !== i))
  }

  async function doSave() {
    setSaving(true); setError(''); setSavedOk('')
    try {
      const r = await api.blueprintSave({
        system_type: activeType,
        standard_id: blueprintId.trim(),
        display_name: displayName.trim() || blueprintId.trim(),
        source: source.trim(),
        overview: overview.trim(),
        rules: [],
        items,
      })
      setSavedOk(r.path || 'Saved.')
      loadList(activeType)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setSaving(false)
    }
  }

  async function doDelete(s) {
    setError('')
    try {
      await api.blueprintDelete(s.system_type, s.standard_id)
      loadList(activeType)
      if (viewing?.standard_id === s.standard_id) setViewing(null)
    } catch (e) {
      setError(friendlyError(e))
    }
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: isNarrow ? '14px 14px 8px' : '18px 20px 10px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {isNarrow && (
            <button onClick={() => setNavOpen(v => !v)} style={{
              fontSize: 14, padding: '4px 10px', borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
            }}>☰</button>
          )}
          <div>
            <div style={{ fontSize: 18, fontWeight: 800 }}>⎔ Blueprint</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              A global reference library — use a saved blueprint verbatim, adapt it interactively per project, or generate fresh.
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div style={{ margin: '0 20px 10px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--red-dim)', color: 'var(--red)', fontSize: 12 }}>{error}</div>
      )}

      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', position: 'relative' }}>
        {/* Left nav — same shape as SystemsTab's own engine nav, including
            the .nm-engine-nav mobile-scrollbar treatment (index.css) now
            that the shared engine list has grown past what a short mobile
            viewport shows without scrolling. */}
        {(navOpen || !isNarrow) && (
          <div className="nm-engine-nav" style={{
            width: isNarrow ? '100%' : 200, flexShrink: 0, borderRight: '1px solid var(--border)',
            overflowY: 'auto', WebkitOverflowScrolling: 'touch', scrollbarGutter: 'stable',
            padding: '10px 8px',
            ...(isNarrow ? { position: 'absolute', inset: 0, zIndex: 40, background: 'var(--bg-base)' } : {}),
          }}>
            {ALL_BLUEPRINT_ENGINES.filter(e => systemTypes.includes(e.key)).map(e => {
              const active = e.key === activeType
              return (
                <button key={e.key} onClick={() => switchType(e.key)} style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 8,
                  padding: '8px 10px', marginBottom: 3, borderRadius: 'var(--radius-sm)',
                  background: active ? 'var(--accent-dim)' : 'transparent',
                  border: active ? `1px solid ${e.color}` : '1px solid transparent',
                  textAlign: 'left', cursor: 'pointer',
                }}>
                  <span style={{ fontSize: 14 }}>{e.icon}</span>
                  <span style={{ fontSize: 12, fontWeight: active ? 700 : 500, color: active ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{e.label}</span>
                </button>
              )
            })}
          </div>
        )}

        {/* Main content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: isNarrow ? 14 : 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>{engine.desc}</div>

          {/* Existing blueprints */}
          <Panel>
            <PanelTitle action={
              <button onClick={() => loadList(activeType)} disabled={loadingList}
                style={{ fontSize: 11, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                {loadingList ? '…' : '↻'}
              </button>
            }>
              Existing {engine.label} Blueprints
            </PanelTitle>
            {blueprints.length === 0 && !loadingList ? (
              <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--text-muted)' }}>
                <div style={{ fontSize: 28, marginBottom: 8 }}>{engine.icon}</div>
                <div style={{ fontSize: 12 }}>No {engine.label} blueprints saved yet.</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {blueprints.map(s => (
                  <div key={s.standard_id} style={{
                    padding: '8px 10px', borderRadius: 'var(--radius)', background: 'var(--bg-elevated)',
                    border: `1px solid ${engine.color}22`, borderLeft: `3px solid ${engine.color}`,
                    display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
                  }}>
                    <div style={{ flex: 1, minWidth: 160 }}>
                      <div style={{ fontWeight: 700, fontSize: 12 }}>{s.display_name}</div>
                      <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 2 }}>{s.item_count} items · {s.source}</div>
                    </div>
                    <button onClick={async () => {
                      setError('')
                      try { setViewing(await api.blueprintGet(activeType, s.standard_id)) }
                      catch (e) { setError(friendlyError(e)) }
                    }} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>View</button>
                    <button onClick={() => doDelete(s)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                  </div>
                ))}
              </div>
            )}
            {viewing && (
              <div style={{ marginTop: 12, padding: 10, borderRadius: 'var(--radius)', background: 'var(--bg-elevated)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 700 }}>{viewing.display_name}</div>
                  <button onClick={() => setViewing(null)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>Close</button>
                </div>
                {viewing.overview && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 10, lineHeight: 1.4 }}>{viewing.overview}</div>}
                {isWorldBible ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {viewing.world_name && <div style={{ fontSize: 12, fontWeight: 700 }}>{viewing.world_name}</div>}
                    {['factions', 'key_locations', 'races'].map(listKey => (viewing[listKey] || []).length > 0 && (
                      <div key={listKey}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 5 }}>{fieldLabel(listKey)} ({viewing[listKey].length})</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                          {viewing[listKey].map((item, i) => (
                            <div key={i} style={{ padding: '6px 8px', borderRadius: 'var(--radius)', background: 'var(--bg-card)', border: `1px solid ${engine.color}22`, borderLeft: `3px solid ${engine.color}` }}>
                              <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
                              {(item.description || item.importance) && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{item.description || item.importance}</div>}
                              {(item.tags || []).length > 0 && (
                                <div style={{ display: 'flex', gap: 5, marginTop: 4, flexWrap: 'wrap' }}>
                                  {item.tags.map((t, ti) => <span key={ti} style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{t}</span>)}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {(viewing[engine.listKey] || []).map((item, i) => (
                      <div key={i} style={{
                        padding: '8px 10px', borderRadius: 'var(--radius)', background: 'var(--bg-card)',
                        border: `1px solid ${engine.color}22`, borderLeft: `3px solid ${engine.color}`,
                      }}>
                        {engine.renderItem(item)}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Panel>

          {/* Paste-to-LLM extraction */}
          {isWorldBible ? (
          <Panel>
            <PanelTitle>Paste reference text → LLM extracts a consolidated World Bible (meta + factions + locations + races)</PanelTitle>
            <textarea
              value={pasteText}
              onChange={e => setPasteText(e.target.value)}
              placeholder="Paste reference text here (a wiki page's content, a rulebook excerpt, notes — the LLM will structure it into world_name, power_tiers, rules, factions, key_locations, and races all at once)…"
              rows={8}
              style={{
                width: '100%', padding: 10, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
                background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, fontFamily: 'monospace',
                resize: 'vertical', boxSizing: 'border-box', marginBottom: 8,
              }}
            />
            <input
              value={extractHint}
              onChange={e => setExtractHint(e.target.value)}
              placeholder="Optional note (e.g. 'this source only covers factions, skip locations')"
              style={{
                width: '100%', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
                background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, boxSizing: 'border-box', marginBottom: 8,
              }}
            />
            <button onClick={doExtractWorldBible} disabled={extracting || !pasteText.trim()} className="btn-primary"
              style={{ padding: '7px 14px', fontSize: 12, opacity: (extracting || !pasteText.trim()) ? 0.6 : 1 }}>
              {extracting ? 'Extracting…' : '✦ Extract World Bible'}
            </button>
          </Panel>
          ) : (
          <Panel>
            <PanelTitle>Paste reference text → LLM extracts a {engine.listLabel.replace(/s$/, '')}</PanelTitle>
            <textarea
              value={pasteText}
              onChange={e => setPasteText(e.target.value)}
              placeholder={`Paste reference text here (a wiki page's content, a rulebook excerpt, notes — the LLM will structure it into the ${engine.label} schema)…`}
              rows={8}
              style={{
                width: '100%', padding: 10, borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
                background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, fontFamily: 'monospace',
                resize: 'vertical', boxSizing: 'border-box', marginBottom: 8,
              }}
            />
            <input
              value={extractHint}
              onChange={e => setExtractHint(e.target.value)}
              placeholder="Optional note (e.g. 'extract just this one rank/location')"
              style={{
                width: '100%', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
                background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, boxSizing: 'border-box', marginBottom: 8,
              }}
            />
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={() => doExtract(false)} disabled={extracting || !pasteText.trim()} className="btn-primary"
                style={{ padding: '7px 14px', fontSize: 12, opacity: (extracting || !pasteText.trim()) ? 0.6 : 1 }}>
                {extracting ? 'Extracting…' : `✦ Extract one ${engine.listLabel.replace(/s$/, '')}`}
              </button>
              <button onClick={() => doExtract(true)} disabled={extracting || !pasteText.trim()}
                title={`Use this when the paste names SEVERAL distinct ${engine.listLabel.toLowerCase()} — each one becomes its own card`}
                style={{
                  padding: '7px 14px', fontSize: 12, borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
                  opacity: (extracting || !pasteText.trim()) ? 0.6 : 1,
                }}>
                {extracting ? 'Extracting…' : `⊞ Extract multiple ${engine.listLabel}`}
              </button>
            </div>
          </Panel>
          )}

          {/* World Bible review — one consolidated object, edited inline
              (meta fields + 3 tag-bearing lists), not the generic per-item
              drawer the other systems use. */}
          {isWorldBible && wbPending && (
            <Panel>
              <PanelTitle>Review extracted World Bible</PanelTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>World Name</div>
                  <input value={wbPending.world_name} onChange={e => setWbPending(p => ({ ...p, world_name: e.target.value }))}
                    style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', boxSizing: 'border-box' }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Power Tiers (one per line, weakest → strongest)</div>
                  <textarea value={wbPending.power_tiers.join('\n')} onChange={e => setWbPending(p => ({ ...p, power_tiers: e.target.value.split('\n') }))} rows={4}
                    style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical', boxSizing: 'border-box' }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>World Rules (one per line)</div>
                  <textarea value={wbPending.rules.join('\n')} onChange={e => setWbPending(p => ({ ...p, rules: e.target.value.split('\n') }))} rows={4}
                    style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical', boxSizing: 'border-box' }} />
                </div>

                {[
                  { listKey: 'factions', label: 'Factions', textField: 'description', blank: { name: '', description: '', tags: [] } },
                  { listKey: 'key_locations', label: 'Key Locations', textField: 'importance', blank: { name: '', importance: '', tags: [] } },
                  { listKey: 'races', label: 'Races & Species', textField: 'description', blank: { name: '', description: '', tags: [] } },
                ].map(({ listKey, label, textField, blank }) => (
                  <div key={listKey}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label} ({wbPending[listKey].length})</div>
                      <button onClick={() => wbAddListItem(listKey, blank)} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 3, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add</button>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {wbPending[listKey].map((item, i) => (
                        <div key={i} style={{ padding: 8, borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 5 }}>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <input value={item.name || ''} onChange={e => wbUpdateListItem(listKey, i, { name: e.target.value })} placeholder="Name"
                              style={{ flex: 1, padding: '4px 7px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
                            <button onClick={() => wbRemoveListItem(listKey, i)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                          </div>
                          <textarea value={item[textField] || ''} onChange={e => wbUpdateListItem(listKey, i, { [textField]: e.target.value })}
                            placeholder={textField === 'importance' ? 'Why it matters' : 'Description'} rows={2}
                            style={{ padding: '4px 7px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
                          <input value={(item.tags || []).join(', ')} onChange={e => wbUpdateListItem(listKey, i, { tags: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                            placeholder="Tags (comma separated)" style={{ padding: '4px 7px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
                        </div>
                      ))}
                    </div>
                  </div>
                ))}

                <div style={{ display: 'flex', gap: 8 }}>
                  <button onClick={() => setWbPending(null)} className="btn-ghost" style={{ padding: '6px 14px', fontSize: 12, borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>✗ Discard</button>
                </div>
              </div>
            </Panel>
          )}

          {/* Review the freshly-extracted (or being-edited) item, using the
              SAME field editor shape as the project's Systems tab drawer */}
          {!isWorldBible && pendingItem && (
            <Panel>
              <PanelTitle>{pendingEditIdx !== null ? `Edit ${engine.listLabel.replace(/s$/, '')}` : `Review new ${engine.listLabel.replace(/s$/, '')}`}</PanelTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {activeFields.map(field => {
                  const val = pendingItem[field]
                  const displayVal = Array.isArray(val) ? val.join(', ') : (val ?? '')
                  const isLong = LONG_FIELDS.has(field)
                  const isArr = ARRAY_FIELDS.has(field)
                  return (
                    <div key={field}>
                      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>
                        {fieldLabel(field)}{isArr ? ' (comma separated)' : ''}
                      </div>
                      {isLong ? (
                        <textarea
                          value={displayVal}
                          onChange={e => setPendingItem(p => ({ ...p, [field]: e.target.value }))}
                          rows={3}
                          style={{ width: '100%', padding: '5px 8px', fontSize: 11, borderRadius: 'var(--radius-sm)', resize: 'vertical', boxSizing: 'border-box' }}
                        />
                      ) : (
                        <input
                          value={displayVal}
                          onChange={e => setPendingItem(p => ({ ...p, [field]: isArr ? e.target.value.split(',').map(s => s.trim()).filter(Boolean) : e.target.value }))}
                          style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', boxSizing: 'border-box' }}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                <button onClick={pendingEditIdx !== null ? saveEditedItem : acceptPendingItem} className="btn-primary" style={{ padding: '6px 14px', fontSize: 12 }}>
                  {pendingEditIdx !== null ? '✓ Save changes' : '✓ Add to blueprint'}
                </button>
                <button onClick={() => { setPendingItem(null); setPendingEditIdx(null) }}
                  style={{ padding: '6px 14px', fontSize: 12, borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                  ✗ Discard
                </button>
              </div>
            </Panel>
          )}

          {/* Save form — World Bible saves the single wbPending object;
              every other system saves its collected items list. */}
          {isWorldBible ? (
            <Panel>
              <PanelTitle>Save World Bible blueprint</PanelTitle>
              {!wbPending && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 10 }}>
                  Extract a World Bible above before saving a blueprint.
                </div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: isNarrow ? '1fr' : '1fr 1fr', gap: 8, marginBottom: 8 }}>
                <input placeholder="blueprint_id (e.g. my_novel)" value={blueprintId} onChange={e => setBlueprintId(e.target.value)}
                  style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12 }} />
                <input placeholder="Display name (e.g. a reference novel)" value={displayName} onChange={e => setDisplayName(e.target.value)}
                  style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12 }} />
              </div>
              <input placeholder="Source (novel/wiki this came from)" value={source} onChange={e => setSource(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, boxSizing: 'border-box', marginBottom: 8 }} />
              <textarea placeholder="Overview (2-4 sentences)" value={overview} onChange={e => setOverview(e.target.value)} rows={2}
                style={{ width: '100%', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, resize: 'vertical', boxSizing: 'border-box', marginBottom: 10 }} />

              <button onClick={doSaveWorldBible} disabled={saving || !wbPending || !blueprintId.trim()} className="btn-primary"
                style={{ padding: '7px 14px', fontSize: 12, opacity: (saving || !wbPending || !blueprintId.trim()) ? 0.6 : 1 }}>
                {saving ? 'Saving…' : '💾 Save blueprint'}
              </button>
              {!saving && (!wbPending || !blueprintId.trim()) && (
                <div style={{ fontSize: 11, color: 'var(--amber, #f59e0b)', marginTop: 6 }}>
                  {!wbPending
                    ? 'Extract a World Bible above before saving.'
                    : 'blueprint_id is required — type one in the field above (it auto-fills after extracting, but was left blank).'}
                </div>
              )}
              {savedOk && <span style={{ marginLeft: 10, fontSize: 12, color: 'var(--green)' }}>Saved to {savedOk}</span>}
            </Panel>
          ) : (
          <Panel>
            <PanelTitle>{items.length} {engine.listLabel} collected</PanelTitle>
            {items.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 10 }}>
                Extract at least one item above before saving a blueprint.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
                {items.map((item, i) => (
                  <div key={i} style={{
                    padding: '8px 10px', borderRadius: 'var(--radius)', background: 'var(--bg-elevated)',
                    border: `1px solid ${engine.color}22`, borderLeft: `3px solid ${engine.color}`,
                    display: 'flex', gap: 8, alignItems: 'flex-start',
                  }}>
                    <div style={{ flex: 1 }}>{engine.renderItem(item)}</div>
                    <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                      <button onClick={() => startEditCollected(i)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                      <button onClick={() => removeItem(i)} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: isNarrow ? '1fr' : '1fr 1fr', gap: 8, marginBottom: 8 }}>
              <input placeholder="blueprint_id (e.g. my_novel)" value={blueprintId} onChange={e => setBlueprintId(e.target.value)}
                style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12 }} />
              <input placeholder="Display name (e.g. a reference novel)" value={displayName} onChange={e => setDisplayName(e.target.value)}
                style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12 }} />
            </div>
            <input placeholder="Source (novel/wiki this came from)" value={source} onChange={e => setSource(e.target.value)}
              style={{ width: '100%', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, boxSizing: 'border-box', marginBottom: 8 }} />
            <textarea placeholder="Overview (2-4 sentences)" value={overview} onChange={e => setOverview(e.target.value)} rows={2}
              style={{ width: '100%', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, resize: 'vertical', boxSizing: 'border-box', marginBottom: 10 }} />

            <button onClick={doSave} disabled={saving || items.length === 0 || !blueprintId.trim()} className="btn-primary"
              style={{ padding: '7px 14px', fontSize: 12, opacity: (saving || items.length === 0 || !blueprintId.trim()) ? 0.6 : 1 }}>
              {saving ? 'Saving…' : '💾 Save blueprint'}
            </button>
            {!saving && (items.length === 0 || !blueprintId.trim()) && (
              <div style={{ fontSize: 11, color: 'var(--amber, #f59e0b)', marginTop: 6 }}>
                {items.length === 0
                  ? 'Extract or add at least one item above before saving.'
                  : 'blueprint_id is required — type one in the field above (it auto-fills after extracting, but was left blank).'}
              </div>
            )}
            {savedOk && <span style={{ marginLeft: 10, fontSize: 12, color: 'var(--green)' }}>Saved to {savedOk}</span>}
          </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
