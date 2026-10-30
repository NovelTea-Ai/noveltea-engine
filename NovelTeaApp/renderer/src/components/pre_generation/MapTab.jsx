import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import CharacterMap3D from './CharacterMap3D'
import LocationMap3D from './LocationMap3D'
import { Panel, PanelTitle, Spinner } from '../shared/projectUi'

export const ROLE_COLOR_JS = {
  protagonist: '#f59e0b', antagonist: '#ef4444', minor_antagonist: '#f97316',
  ally: '#10b981', rival: '#eab308', mentor: '#8b5cf6', love_interest: '#ec4899',
  side: '#3b82f6', beast: '#14b8a6',
}

export function MapTab({ project, projectId, afterGenerate, onSave }) {
  const [locations, setLocations] = useState(project.location_map || [])
  const [contras, setContras] = useState(project.location_map_contradictions || [])
  const [extracting, setExtracting] = useState(false)
  const [result, setResult] = useState(null)
  const [editIdx, setEditIdx] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [fixingId, setFixingId] = useState(null)
  const [reviewing, setReviewing] = useState(false)
  const [reviewMsg, setReviewMsg] = useState('')
  const [selectedChapter, setSelectedChapter] = useState('')
  const [viewMode, setViewMode] = useState('characters') // 'characters' | 'locations'
  const [selectedChar, setSelectedChar] = useState(null)
  const [selectedLoc, setSelectedLoc] = useState(null)

  useEffect(() => {
    setLocations(project.location_map || [])
    setContras(project.location_map_contradictions || [])
  }, [project.id])

  const facts = project.facts_log || []

  // Earliest chapter each character is actually mentioned in, derived from
  // facts_log (reliable, per-chapter) rather than character_list.first_chapter
  // (sparse/only populated for a few characters). Names are matched against
  // character_list so techniques/items/locations that also appear as fact
  // subjects don't get treated as characters.
  const knownCharNames = useMemo(() => {
    const set = new Set()
    ;(project.character_list || []).forEach(c => { if (c.name) set.add(c.name.trim()) })
    return set
  }, [project.character_list])

  const characterFirstChapter = useMemo(() => {
    const map = {}
    facts.forEach(f => {
      const subj = (f.subject || '').trim()
      if (!knownCharNames.has(subj)) return
      if (f.chapter == null) return
      if (map[subj] == null || f.chapter < map[subj]) map[subj] = f.chapter
    })
    return map
  }, [facts, knownCharNames])

  const charactersForMap = useMemo(() => {
    return (project.character_list || [])
      .filter(c => c.name)
      .map(c => ({
        name: c.name, role: c.role || 'side', faction: c.faction || '',
        motivation: c.motivation || '', archetype: c.archetype || '',
        firstChapter: characterFirstChapter[c.name.trim()] ?? c.first_chapter ?? null,
      }))
      .filter(c => c.firstChapter != null)   // only characters we can actually place on a chapter timeline
      .sort((a, b) => a.firstChapter - b.firstChapter)
  }, [project.character_list, characterFirstChapter])

  // Every chapter the dropdown should offer: any chapter with a NEW location,
  // a NEW connection, a NEW character, OR simply any fact at all recorded
  // against it (covers chapters like ch2 that develop existing items/techniques
  // rather than introduce a new place or person — those still deserve a
  // GPS/character snapshot even though nothing NEW landed on the map that
  // chapter). This is "every written chapter with any ledger data," not just
  // chapters that expanded the map/cast.
  const chaptersWithMapData = useMemo(() => {
    const nums = new Set()
    locations.forEach(l => {
      if (l.chapter != null) nums.add(l.chapter)
      ;(l.connections || []).forEach(c => { if (c.chapter != null) nums.add(c.chapter) })
    })
    charactersForMap.forEach(c => { if (c.firstChapter != null) nums.add(c.firstChapter) })
    facts.forEach(f => { if (f.chapter != null) nums.add(f.chapter) })
    return [...nums].sort((a, b) => a - b)
  }, [locations, charactersForMap, facts])

  const charactersForSelectedLayer = useMemo(() => {
    return charactersForMap.map(c => ({
      ...c, visible: !selectedChapter || c.firstChapter <= Number(selectedChapter),
    }))
  }, [charactersForMap, selectedChapter])

  // GPS-style snapshot for the selected chapter: every location whose FIRST
  // appearance is this chapter or earlier (i.e. "on the map by this point"),
  // which connections were freshly established THIS chapter, and which
  // characters/facts the Facts ledger ties to this specific chapter — pieced
  // together entirely from location_map + facts_log, nothing invented.
  const chapterSnapshot = useMemo(() => {
    if (!selectedChapter) return null
    const ch = Number(selectedChapter)
    const knownLocations = locations.filter(l => (l.chapter ?? Infinity) <= ch)
    const newLocations = locations.filter(l => l.chapter === ch)
    const newConnections = []
    locations.forEach(l => {
      (l.connections || []).forEach(c => {
        if (c.chapter === ch) newConnections.push({ from: l.name, to: c.to, relation: c.relation })
      })
    })
    const chFacts = facts.filter(f => f.chapter === ch)
    const charLocations = {}
    // best-effort character->location pin: a character fact recorded the same
    // chapter a location was first established suggests they were there —
    // shown as "seen around" rather than asserted as precise fact.
    chFacts.forEach(f => {
      (f.characters || []).forEach(ch2 => {
        newLocations.forEach(l => {
          charLocations[ch2] = charLocations[ch2] || new Set()
          charLocations[ch2].add(l.name)
        })
      })
    })
    return { knownLocations, newLocations, newConnections, chFacts, charLocations }
  }, [selectedChapter, locations, facts])

  async function runReview() {
    setReviewing(true)
    setReviewMsg('')
    try {
      const r = await api.continuityReview(projectId)
      if (r.location_contradictions?.length) setContras(c => [...c, ...r.location_contradictions])
      const symNote = r.symbol_flags?.length
        ? ` Also flagged ${r.symbol_flags.length} orphaned symbol${r.symbol_flags.length !== 1 ? 's' : ''} (introduced once, never returned to): ${r.symbol_flags.map(f => `${f.symbol} (ch.${f.chapter})`).join(', ')}.`
        : ''
      setReviewMsg((r.total > 0
        ? `Reviewed all ${r.chapters_reviewed} chapters — found ${r.total} new contradiction${r.total !== 1 ? 's' : ''} (${r.fact_contradictions.length} fact, ${r.location_contradictions.length} location).`
        : `Reviewed all ${r.chapters_reviewed} chapters — no contradictions found.`) + symNote)
    } catch (e) {
      setReviewMsg(`✗ Review failed: ${e.message}`)
    } finally {
      setReviewing(false)
    }
  }

  async function runExtract(full = false) {
    setExtracting(true)
    setResult(null)
    try {
      const r = await api.locationMapExtract(projectId, full)
      setResult(r)
      if (r.contradictions?.length) {
        setContras(c => [...c, ...r.contradictions])
      }
      if (r.total > 0) {
        // simplest correct refresh: full extract responses don't return the
        // whole map, so pull the freshly-saved project state back down
        afterGenerate && afterGenerate({ field: 'location_map', provider: 'map-extract' })
      }
    } catch (e) {
      setResult({ total: 0, added_locations: [], added_connections: [], contradictions: [], error: e.message })
      alert(`Location Map extraction failed: ${e.message}`)
    } finally {
      setExtracting(false)
    }
  }

  async function fixContradiction(id) {
    setFixingId(id)
    try {
      const r = await api.locationMapFix(projectId, id)
      setContras(cs => cs.map(c => c.id === id ? { ...c, status: r.resolved ? 'resolved' : 'fix_attempted', resolution: r.summary } : c))
      afterGenerate && afterGenerate({ field: 'location_map', provider: 'map-fix' })
      if (r.growth_warning?.length) {
        alert(`Fix applied, but chapter length grew more than expected:\n${r.growth_warning.join('\n')}`)
      }
    } catch (e) {
      alert(`Fix failed: ${e.message}`)
    } finally {
      setFixingId(null)
    }
  }

  async function saveMap(updated) {
    setSaving(true)
    setLocations(updated)
    try { await api.locationMapUpdate(projectId, updated) }
    finally { setSaving(false) }
  }

  function startEdit(i) { setEditIdx(i); setEditForm({ ...locations[i], connections: locations[i].connections || [] }) }
  async function commitEdit() {
    const updated = locations.map((l, i) => i === editIdx ? { ...editForm } : l)
    setEditIdx(null); setEditForm(null)
    await saveMap(updated)
  }
  async function deleteLocation(i) {
    const name = locations[i].name
    // also strip any connections pointing AT the deleted node
    const updated = locations.filter((_, idx) => idx !== i)
      .map(l => ({ ...l, connections: (l.connections || []).filter(c => c.to !== name) }))
    await saveMap(updated)
  }
  function addConnection() {
    setEditForm(f => ({ ...f, connections: [...(f.connections || []), { to: '', relation: '', chapter: null }] }))
  }
  function updateConnection(idx, field, value) {
    setEditForm(f => ({ ...f, connections: f.connections.map((c, i) => i === idx ? { ...c, [field]: value } : c) }))
  }
  function removeConnection(idx) {
    setEditForm(f => ({ ...f, connections: f.connections.filter((_, i) => i !== idx) }))
  }

  const EF = editForm || {}
  const otherNames = locations.map(l => l.name).filter(n => n !== EF.name)

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
        <Panel style={{ marginBottom: 12 }}>
          <PanelTitle action={
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={() => runExtract(false)} disabled={extracting} title="Scans only chapters not yet mapped, or edited since their last scan — same incremental ledger as Discovery" style={{
                fontSize: 11, padding: '5px 12px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                background: extracting ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#3b82f6,#06b6d4)',
                color: extracting ? 'var(--text-muted)' : '#fff', border: 'none',
                display: 'flex', alignItems: 'center', gap: 5,
              }}>{extracting ? <Spinner size={11} /> : '🗺'} Update Map</button>
              <button onClick={() => runExtract(true)} disabled={extracting} style={{
                fontSize: 10, padding: '4px 8px', background: 'transparent', border: 'none',
                color: 'var(--text-muted)', textDecoration: 'underline', cursor: 'pointer',
              }}>re-scan all chapters</button>
              <button onClick={runReview} disabled={reviewing} title="Actively re-reads every written chapter against the full facts + map ledgers, hunting for contradictions — not just checking newly-scanned chapters" style={{
                fontSize: 11, padding: '5px 12px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                background: reviewing ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#8b5cf6,#6366f1)',
                color: reviewing ? 'var(--text-muted)' : '#fff', border: 'none',
                display: 'flex', alignItems: 'center', gap: 5,
              }}>{reviewing ? <Spinner size={11} /> : '🔍'} Review for Contradictions</button>
            </div>
          }>Local Geography — {locations.length} location{locations.length !== 1 ? 's' : ''}</PanelTitle>
          <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Tracks what's near what and how long it takes to get there — separate from the grand-scale regions in World Bible.
            Built ONLY from what the written chapters actually show, cross-checked against the Facts ledger — never
            speculative. <b>Update Map</b> only scans chapters not yet mapped, or edited since their last scan (edits drop that
            chapter back onto the list automatically) — the same incremental ledger Discovery uses, so nothing gets scanned twice.
            <b>Review for Contradictions</b> re-reads the WHOLE story against the whole ledger (facts + map together), catching
            drift between already-scanned chapters that extraction alone wouldn't.
            Every generated or dialogue-shaped chapter checks this map before placing a scene, so a duty or scene can't get
            assigned to somewhere that contradicts an already-established distance or adjacency.
          </div>
          {reviewMsg && (
            <div style={{ marginTop: 8, fontSize: 11, color: reviewMsg.startsWith('✗') ? 'var(--red)' : 'var(--text-secondary)' }}>{reviewMsg}</div>
          )}

          {result && (
            <div style={{ marginTop: 10, fontSize: 11, lineHeight: 1.6 }}>
              {result.error ? (
                <span style={{ color: 'var(--red)' }}>✗ {result.error}</span>
              ) : result.total === 0 && !result.contradictions?.length ? (
                <span style={{ color: 'var(--text-muted)' }}>{result.message || 'Nothing new — all chapters already scanned.'}</span>
              ) : (
                <>
                  <span style={{ color: 'var(--green)' }}>✓ Added {result.added_locations?.length || 0} locations, {result.added_connections?.length || 0} connections</span>
                  {result.scanned?.length > 0 && <span style={{ color: 'var(--text-muted)' }}> from {result.scanned.map(n => `ch${n}`).join(', ')}</span>}
                </>
              )}
            </div>
          )}
        </Panel>

        {contras.filter(c => c.status === 'open').length > 0 && (
          <Panel style={{ marginBottom: 12, background: 'rgba(245,158,11,0.06)', border: '1px solid var(--amber, #f59e0b)' }}>
            <PanelTitle>⚠ {contras.filter(c => c.status === 'open').length} open contradiction{contras.filter(c => c.status === 'open').length !== 1 ? 's' : ''}</PanelTitle>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {contras.filter(c => c.status === 'open').map(c => (
                <div key={c.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '8px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)' }}>
                  <div style={{ flex: 1, fontSize: 11, color: 'var(--text-secondary)' }}>
                    <b style={{ color: 'var(--text-primary)' }}>{c.from} → {c.to}</b>
                    <div style={{ marginTop: 3 }}>ch{c.existing.chapter}: "{c.existing.relation}"</div>
                    <div>ch{c.new.chapter}: "{c.new.relation}"</div>
                  </div>
                  <button onClick={() => fixContradiction(c.id)} disabled={fixingId === c.id} style={{
                    flexShrink: 0, fontSize: 11, padding: '6px 12px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                    background: fixingId === c.id ? 'var(--bg-card)' : 'var(--amber, #f59e0b)',
                    color: fixingId === c.id ? 'var(--text-muted)' : '#000', border: 'none',
                    display: 'flex', alignItems: 'center', gap: 5,
                  }}>{fixingId === c.id ? <Spinner size={11} /> : '🛠'} Fix</button>
                </div>
              ))}
            </div>
          </Panel>
        )}
        {contras.some(c => c.status !== 'open') && (
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 12, paddingLeft: 4 }}>
            {contras.filter(c => c.status === 'resolved').length} contradiction{contras.filter(c => c.status === 'resolved').length !== 1 ? 's' : ''} resolved.
          </div>
        )}

        {(locations.length > 0 || charactersForMap.length > 0) && (
          <Panel style={{ marginBottom: 12 }}>
            <PanelTitle action={
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', borderRadius: 'var(--radius-sm)', overflow: 'hidden', border: '1px solid var(--border)' }}>
                  <button onClick={() => setViewMode('characters')} style={{
                    padding: '5px 12px', fontSize: 11, fontWeight: 700, border: 'none',
                    background: viewMode === 'characters' ? 'var(--accent, #7c3aed)' : 'var(--bg-elevated)',
                    color: viewMode === 'characters' ? '#fff' : 'var(--text-secondary)',
                  }}>👤 Characters</button>
                  <button onClick={() => setViewMode('locations')} style={{
                    padding: '5px 12px', fontSize: 11, fontWeight: 700, border: 'none',
                    background: viewMode === 'locations' ? 'var(--accent, #7c3aed)' : 'var(--bg-elevated)',
                    color: viewMode === 'locations' ? '#fff' : 'var(--text-secondary)',
                  }}>🗺 Locations</button>
                </div>
                {chaptersWithMapData.length > 0 && (
                  <select value={selectedChapter} onChange={e => setSelectedChapter(e.target.value)}
                    style={{ padding: '5px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 'var(--radius-sm)' }}>
                    <option value="">📍 Full map (all chapters)</option>
                    {chaptersWithMapData.map(n => <option key={n} value={n}>Chapter {n}</option>)}
                  </select>
                )}
              </div>
            }>{viewMode === 'characters' ? 'Character Web' : 'Map View'}{selectedChapter ? ` — as of Chapter ${selectedChapter}` : ''}</PanelTitle>

            {viewMode === 'characters' ? (
              charactersForMap.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)', fontSize: 12 }}>
                  No characters placeable on a chapter timeline yet — run Extract Facts so characters get a first-mentioned chapter.
                </div>
              ) : (
                <>
                  <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 8 }}>
                    Drag to orbit, scroll/pinch to zoom, click a dot for that character. Position reflects relationship
                    clustering (same faction pulls together, the protagonist anchors center) — not geography.
                    {selectedChapter && ` Showing the ${charactersForSelectedLayer.filter(c => c.visible).length} character(s) introduced by chapter ${selectedChapter}.`}
                  </div>
                  <CharacterMap3D characters={charactersForSelectedLayer} onSelect={setSelectedChar} />
                  {selectedChar && (
                    <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border-soft)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ width: 10, height: 10, borderRadius: '50%', background: ROLE_COLOR_JS[selectedChar.role] || '#6366f1', display: 'inline-block' }} />
                        <b style={{ fontSize: 13 }}>{selectedChar.name}</b>
                        <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'capitalize' }}>{selectedChar.role?.replace(/_/g, ' ')}</span>
                      </div>
                      {selectedChar.faction && <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}><b style={{ color: 'var(--text-muted)' }}>Faction:</b> {selectedChar.faction}</div>}
                      {selectedChar.archetype && <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}><b style={{ color: 'var(--text-muted)' }}>Archetype:</b> {selectedChar.archetype}</div>}
                      {selectedChar.motivation && <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}><b style={{ color: 'var(--text-muted)' }}>Motivation:</b> {selectedChar.motivation}</div>}
                      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>First appears: Chapter {selectedChar.firstChapter}</div>
                    </div>
                  )}
                </>
              )
            ) : (
              <>
                <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 8 }}>
                  Drag to orbit, scroll/pinch to zoom, click a node for its details. The chapter dropdown works like a
                  BIM-viewer layer toggle — locations/connections not yet on the map by that chapter are hidden, not just dimmed.
                </div>
                <LocationMap3D locations={locations} asOfChapter={selectedChapter ? Number(selectedChapter) : null} onSelect={setSelectedLoc} />
                {selectedLoc && (
                  <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border-soft)' }}>
                    <b style={{ fontSize: 13 }}>{selectedLoc.name}</b>
                    {selectedLoc.description && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 3 }}>{selectedLoc.description}</div>}
                    {(selectedLoc.connections || []).length > 0 && (
                      <div style={{ marginTop: 5, fontSize: 10.5, color: 'var(--text-muted)' }}>
                        {selectedLoc.connections.map((c, i) => <div key={i}>↳ <b style={{ color: 'var(--text-secondary)' }}>{c.to}</b>: {c.relation}</div>)}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>First appears: Chapter {selectedLoc.chapter}</div>
                  </div>
                )}
              </>
            )}

            {viewMode === 'locations' && chapterSnapshot && (
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border-soft)' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
                  📍 GPS — Chapter {selectedChapter} snapshot
                </div>

                {chapterSnapshot.newLocations.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <span style={{ fontSize: 10.5, color: 'var(--green)', fontWeight: 700 }}>New location{chapterSnapshot.newLocations.length !== 1 ? 's' : ''} this chapter</span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 4 }}>
                      {chapterSnapshot.newLocations.map(l => (
                        <span key={l.name} title={l.description} style={{ fontSize: 10.5, padding: '3px 8px', borderRadius: 10, background: 'rgba(16,185,129,0.12)', border: '1px solid #10b981', color: 'var(--text-secondary)' }}>{l.name}</span>
                      ))}
                    </div>
                  </div>
                )}

                {chapterSnapshot.newConnections.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <span style={{ fontSize: 10.5, color: '#f59e0b', fontWeight: 700 }}>New connection{chapterSnapshot.newConnections.length !== 1 ? 's' : ''} established</span>
                    <div style={{ marginTop: 4, fontSize: 10.5, color: 'var(--text-secondary)' }}>
                      {chapterSnapshot.newConnections.map((c, i) => (
                        <div key={i}>↳ <b>{c.from}</b> ↔ <b>{c.to}</b>: {c.relation}</div>
                      ))}
                    </div>
                  </div>
                )}

                {Object.keys(chapterSnapshot.charLocations).length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <span style={{ fontSize: 10.5, color: '#06b6d4', fontWeight: 700 }}>Who's where (from facts recorded this chapter)</span>
                    <div style={{ marginTop: 4, fontSize: 10.5, color: 'var(--text-secondary)' }}>
                      {Object.entries(chapterSnapshot.charLocations).map(([name, locs]) => (
                        <div key={name}>↳ <b>{name}</b> — seen around {[...locs].join(', ')}</div>
                      ))}
                    </div>
                  </div>
                )}

                {chapterSnapshot.chFacts.length > 0 && (
                  <div>
                    <span style={{ fontSize: 10.5, color: 'var(--text-muted)', fontWeight: 700 }}>All facts recorded this chapter ({chapterSnapshot.chFacts.length})</span>
                    <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.7 }}>
                      {chapterSnapshot.chFacts.map(f => (
                        <div key={f.id}>• <b style={{ color: 'var(--text-secondary)' }}>{f.subject}</b> ({f.category}): {f.statement}</div>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ marginTop: 8, fontSize: 9.5, color: 'var(--text-muted)' }}>
                  {chapterSnapshot.knownLocations.length} location{chapterSnapshot.knownLocations.length !== 1 ? 's' : ''} on the map by this point in the story.
                </div>
              </div>
            )}
          </Panel>
        )}

        <Panel>
          {locations.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)', fontSize: 12 }}>
              No locations tracked yet. Write some chapters, then click Extract Map.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {locations.map((l, i) => (
                <div key={i} style={{
                  padding: '9px 12px', borderRadius: 'var(--radius-sm)',
                  background: editIdx === i ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: '1px solid var(--border-soft)',
                }}>
                  {editIdx === i ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <input value={EF.name || ''} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                        placeholder="Location name" style={{ padding: '4px 8px', fontSize: 12, fontWeight: 700, borderRadius: 4 }} />
                      <textarea value={EF.description || ''} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                        rows={2} placeholder="Description" style={{ padding: '4px 8px', fontSize: 11, borderRadius: 4, resize: 'vertical' }} />
                      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Connections</div>
                      {(EF.connections || []).map((c, ci) => (
                        <div key={ci} style={{ display: 'flex', gap: 4 }}>
                          <select value={c.to} onChange={e => updateConnection(ci, 'to', e.target.value)}
                            style={{ flex: 1, padding: '3px 6px', fontSize: 10.5, borderRadius: 4 }}>
                            <option value="">— select location —</option>
                            {otherNames.map(n => <option key={n} value={n}>{n}</option>)}
                          </select>
                          <input value={c.relation} onChange={e => updateConnection(ci, 'relation', e.target.value)}
                            placeholder="relation (e.g. 10min walk)" style={{ flex: 2, padding: '3px 6px', fontSize: 10.5, borderRadius: 4 }} />
                          <button onClick={() => removeConnection(ci)} style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                        </div>
                      ))}
                      <button onClick={addConnection} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: 'var(--bg-card)', border: '1px dashed var(--border)', color: 'var(--text-muted)', alignSelf: 'flex-start' }}>+ Add connection</button>
                      <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                        <button onClick={commitEdit} disabled={saving} className="btn-primary" style={{ padding: '4px 10px', fontSize: 11 }}>✓ Save</button>
                        <button onClick={() => setEditIdx(null)} className="btn-ghost" style={{ padding: '4px 10px', fontSize: 11 }}>✕ Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{l.name}</div>
                        {l.description && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>{l.description}</div>}
                        {(l.connections || []).length > 0 && (
                          <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>
                            {l.connections.map((c, ci) => (
                              <div key={ci}>↳ <b style={{ color: 'var(--cyan, #06b6d4)' }}>{c.to}</b>: {c.relation}</div>
                            ))}
                          </div>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                        <button onClick={() => startEdit(i)} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                        <button onClick={() => deleteLocation(i)} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
