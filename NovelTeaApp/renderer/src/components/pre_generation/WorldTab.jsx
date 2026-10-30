import { useEffect, useState } from 'react'
import { FieldSurveyButton, Panel, PanelTitle } from '../shared/projectUi'
import { ARC_COLORS } from './common'

/* ══════════════════════════════════════
   WORLD BIBLE TAB
══════════════════════════════════════ */
export function WorldTab({ project, projectId, afterGenerate, onSave }) {
  const [world, setWorld] = useState(project.world_bible || null)
  const [saving, setSaving] = useState(false)
  // Editing state per section
  const [editSection, setEditSection] = useState(null) // 'meta' | 'faction:N' | 'location:N' | 'rule:N'
  const [editForm, setEditForm] = useState(null)

  useEffect(() => { setWorld(project.world_bible || null) }, [project.id])

  function onGenDone(res) {
    afterGenerate(res)
    if (res.field === 'world' && res.result) setWorld(res.result)
  }

  async function save(updated) {
    setSaving(true)
    setWorld(updated)
    await onSave({ world_bible: updated })
    setSaving(false)
  }

  // ── Meta (name, power tiers, rules) ──────────────────────────────
  function startEditMeta() {
    setEditSection('meta')
    setEditForm({
      world_name: world?.world_name || '',
      power_tiers: (world?.power_tiers || []).join('\n'),
      rules: (world?.rules || []).join('\n'),
    })
  }
  async function saveMeta() {
    const updated = {
      ...world,
      world_name: editForm.world_name,
      power_tiers: editForm.power_tiers.split('\n').map(s => s.trim()).filter(Boolean),
      rules: editForm.rules.split('\n').map(s => s.trim()).filter(Boolean),
    }
    setEditSection(null)
    await save(updated)
  }

  // ── Factions ─────────────────────────────────────────────────────
  // 'role' (ally|enemy|neutral) is the ORIGINAL World Bible field, driving the
  // card's accent color — kept as-is. Everything absorbed from the old
  // standalone Factions & Powers system (type/tier/alignment/leader/etc.)
  // collapses into one freeform `tags` field (comma-separated) rather than
  // a dedicated input per attribute — simpler form, still searchable/visible.
  function startEditFaction(i, isNew = false) {
    setEditSection(`faction:${i}`)
    setEditForm(isNew ? { name: '', role: 'neutral', description: '', tags: [] }
      : { ...world.factions[i], tags: (world.factions[i].tags || []) })
  }
  async function saveFaction(i, isNew) {
    const factions = isNew
      ? [...(world.factions || []), editForm]
      : (world.factions || []).map((f, idx) => idx === i ? editForm : f)
    setEditSection(null)
    await save({ ...world, factions })
  }
  async function deleteFaction(i) {
    await save({ ...world, factions: world.factions.filter((_, idx) => idx !== i) })
  }

  // ── Locations ─────────────────────────────────────────────────────
  // 'importance' is the ORIGINAL World Bible field (short "why it matters"
  // summary, used in the compact list view) — kept as-is. Everything
  // absorbed from the old standalone Sacred Grounds & Ruins system (type/
  // danger_level/status/conditions/dangers/rewards/scheme/known_to)
  // collapses into `tags`, same as factions above.
  function startEditLocation(i, isNew = false) {
    setEditSection(`location:${i}`)
    setEditForm(isNew ? { name: '', importance: '', tags: [] }
      : { ...world.key_locations[i], tags: (world.key_locations[i].tags || []) })
  }
  async function saveLocation(i, isNew) {
    const locs = isNew
      ? [...(world.key_locations || []), editForm]
      : (world.key_locations || []).map((l, idx) => idx === i ? editForm : l)
    setEditSection(null)
    await save({ ...world, key_locations: locs })
  }
  async function deleteLocation(i) {
    await save({ ...world, key_locations: world.key_locations.filter((_, idx) => idx !== i) })
  }

  // ── Races ────────────────────────────────────────────────────────
  // NEW list (World Bible had no races concept before) — absorbed from the
  // old standalone Races & Species system, same `tags` collapse as above.
  function startEditRace(i, isNew = false) {
    setEditSection(`race:${i}`)
    setEditForm(isNew ? { name: '', description: '', tags: [] }
      : { ...world.races[i], tags: (world.races[i].tags || []) })
  }
  async function saveRace(i, isNew) {
    const races = isNew
      ? [...(world.races || []), editForm]
      : (world.races || []).map((r, idx) => idx === i ? editForm : r)
    setEditSection(null)
    await save({ ...world, races })
  }
  async function deleteRace(i) {
    await save({ ...world, races: world.races.filter((_, idx) => idx !== i) })
  }

  const EF = editForm || {}
  const tagsStr = (EF.tags || []).join(', ')
  function setTagsFromStr(str) {
    setEditForm(f => ({ ...f, tags: str.split(',').map(s => s.trim()).filter(Boolean) }))
  }

  if (!world) return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
      <Panel>
        <PanelTitle action={
          <div style={{ display: 'flex', gap: 6 }}>
            <FieldSurveyButton field="world" projectId={projectId} onDone={onGenDone} small />
          </div>
        }>World Bible</PanelTitle>
        <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
          No world defined yet. AI will design the world name, power tiers, factions, key locations, and rules based on your premise.
        </div>
      </Panel>
    </div>
  )

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* ── World Meta ── */}
      <Panel>
        <PanelTitle action={
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={startEditMeta} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>✎ Edit</button>
            <FieldSurveyButton field="world" projectId={projectId} onDone={onGenDone} small />
          </div>
        }>{world.world_name || 'World'}</PanelTitle>

        {editSection === 'meta' ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>World Name</div>
              <input value={EF.world_name} onChange={e => setEditForm(f => ({ ...f, world_name: e.target.value }))} style={{ width: '100%', padding: '5px 8px', fontSize: 13, borderRadius: 'var(--radius-sm)' }} />
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Power Tiers (one per line, weakest → strongest)</div>
              <textarea value={EF.power_tiers} onChange={e => setEditForm(f => ({ ...f, power_tiers: e.target.value }))} rows={5} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>World Rules (one per line)</div>
              <textarea value={EF.rules} onChange={e => setEditForm(f => ({ ...f, rules: e.target.value }))} rows={4} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={saveMeta} disabled={saving} className="btn-primary" style={{ padding: '6px 16px', fontSize: 12 }}>{saving ? 'Saving…' : '✓ Save'}</button>
              <button onClick={() => setEditSection(null)} className="btn-ghost" style={{ padding: '6px 14px', fontSize: 12 }}>Cancel</button>
            </div>
          </div>
        ) : (
          <>
            {world.power_tiers?.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 8 }}>Power Tiers</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {world.power_tiers.map((tier, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ fontSize: 11, padding: '3px 10px', borderRadius: 20, background: `${ARC_COLORS[i % ARC_COLORS.length]}22`, color: ARC_COLORS[i % ARC_COLORS.length], border: `1px solid ${ARC_COLORS[i % ARC_COLORS.length]}55` }}>{tier}</span>
                      {i < world.power_tiers.length - 1 && <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>→</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {world.rules?.length > 0 && (
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 8 }}>World Rules</div>
                {world.rules.map((r, i) => (
                  <div key={i} style={{ fontSize: 11, color: 'var(--text-secondary)', padding: '4px 0', borderBottom: '1px solid var(--border-soft)', display: 'flex', gap: 8 }}>
                    <span style={{ color: 'var(--text-muted)' }}>{i + 1}.</span>{r}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Panel>

      {/* ── Factions ── */}
      <Panel>
        <PanelTitle action={
          <button onClick={() => startEditFaction(world.factions?.length || 0, true)} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add</button>
        }>Factions ({world.factions?.length || 0})</PanelTitle>
        {editSection?.startsWith('faction:') && (() => {
          const idx = parseInt(editSection.split(':')[1])
          const isNew = idx >= (world.factions?.length || 0)
          return (
            <div style={{ background: 'var(--bg-input)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)', padding: 12, marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Name</div>
                  <input value={EF.name || ''} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Role</div>
                  <select value={EF.role || 'neutral'} onChange={e => setEditForm(f => ({ ...f, role: e.target.value }))} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
                    {['ally','enemy','neutral'].map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Description</div>
                <textarea value={EF.description || ''} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))} rows={2} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Tags (comma separated — e.g. type, tier, alignment, leader, territory…)</div>
                <input value={tagsStr} onChange={e => setTagsFromStr(e.target.value)} placeholder="Sect, Righteous, led by Elder Chen, controls the Eastern Peaks…" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => saveFaction(idx, isNew)} disabled={saving} className="btn-primary" style={{ padding: '5px 14px', fontSize: 12 }}>{saving ? 'Saving…' : '✓ Save'}</button>
                <button onClick={() => setEditSection(null)} className="btn-ghost" style={{ padding: '5px 12px', fontSize: 12 }}>Cancel</button>
              </div>
            </div>
          )
        })()}
        <div className="card-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
          {(world.factions || []).map((f, i) => {
            const c = f.role === 'ally' ? 'var(--green)' : f.role === 'enemy' ? 'var(--red)' : 'var(--amber)'
            return (
              <div key={i} style={{ background: 'var(--bg-elevated)', border: `1px solid ${c}33`, borderLeft: `3px solid ${c}`, borderRadius: 'var(--radius-sm)', padding: '10px 12px', position: 'relative' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{f.name}</span>
                  <div style={{ display: 'flex', gap: 3 }}>
                    <button onClick={() => startEditFaction(i)} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                    <button onClick={() => deleteFaction(i)} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                  </div>
                </div>
                <div style={{ fontSize: 9, color: c, fontWeight: 700, marginBottom: 5, textTransform: 'uppercase' }}>{f.role}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{f.description}</div>
                {(f.tags || []).length > 0 && (
                  <div style={{ display: 'flex', gap: 5, marginTop: 6, flexWrap: 'wrap' }}>
                    {f.tags.map((t, ti) => <span key={ti} style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{t}</span>)}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </Panel>

      {/* ── Key Locations ── */}
      <Panel>
        <PanelTitle action={
          <button onClick={() => startEditLocation(world.key_locations?.length || 0, true)} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add</button>
        }>Key Locations ({world.key_locations?.length || 0})</PanelTitle>
        {editSection?.startsWith('location:') && (() => {
          const idx = parseInt(editSection.split(':')[1])
          const isNew = idx >= (world.key_locations?.length || 0)
          return (
            <div style={{ background: 'var(--bg-input)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)', padding: 12, marginBottom: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Location Name</div>
                <input value={EF.name || ''} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Why it matters</div>
                <textarea value={EF.importance || ''} onChange={e => setEditForm(f => ({ ...f, importance: e.target.value }))} rows={2} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Tags (comma separated — e.g. type, danger level, status, conditions, dangers, rewards…)</div>
                <input value={tagsStr} onChange={e => setTagsFromStr(e.target.value)} placeholder="Ancient Tomb, Heaven danger, Sealed, guarded by a dragon…" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => saveLocation(idx, isNew)} disabled={saving} className="btn-primary" style={{ padding: '5px 14px', fontSize: 12 }}>{saving ? 'Saving…' : '✓ Save'}</button>
                <button onClick={() => setEditSection(null)} className="btn-ghost" style={{ padding: '5px 12px', fontSize: 12 }}>Cancel</button>
              </div>
            </div>
          )
        })()}
        {(world.key_locations || []).map((loc, i) => (
          <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid var(--border-soft)' }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <span style={{ fontWeight: 600, fontSize: 12, minWidth: 120, flexShrink: 0 }}>{loc.name}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', flex: 1 }}>{loc.importance}</span>
              <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                <button onClick={() => startEditLocation(i)} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                <button onClick={() => deleteLocation(i)} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
              </div>
            </div>
            {(loc.tags || []).length > 0 && (
              <div style={{ display: 'flex', gap: 5, marginTop: 4, flexWrap: 'wrap' }}>
                {loc.tags.map((t, ti) => <span key={ti} style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{t}</span>)}
              </div>
            )}
          </div>
        ))}
      </Panel>

      {/* ── Races & Species ── */}
      <Panel>
        <PanelTitle action={
          <button onClick={() => startEditRace(world.races?.length || 0, true)} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add</button>
        }>Races & Species ({world.races?.length || 0})</PanelTitle>
        {editSection?.startsWith('race:') && (() => {
          const idx = parseInt(editSection.split(':')[1])
          const isNew = idx >= (world.races?.length || 0)
          return (
            <div style={{ background: 'var(--bg-input)', border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)', padding: 12, marginBottom: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Name</div>
                <input value={EF.name || ''} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Description</div>
                <textarea value={EF.description || ''} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))} rows={2} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Tags (comma separated — e.g. category, power tier, alignment, homeland…)</div>
                <input value={tagsStr} onChange={e => setTagsFromStr(e.target.value)} placeholder="Beast Clan, Tier 3, homeland: Frostpeak Range…" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => saveRace(idx, isNew)} disabled={saving} className="btn-primary" style={{ padding: '5px 14px', fontSize: 12 }}>{saving ? 'Saving…' : '✓ Save'}</button>
                <button onClick={() => setEditSection(null)} className="btn-ghost" style={{ padding: '5px 12px', fontSize: 12 }}>Cancel</button>
              </div>
            </div>
          )
        })()}
        <div className="card-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
          {(world.races || []).map((r, i) => (
            <div key={i} style={{ background: 'var(--bg-elevated)', border: '1px solid rgba(14,165,233,0.3)', borderLeft: '3px solid #0ea5e9', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontWeight: 600, fontSize: 12 }}>{r.name}</span>
                <div style={{ display: 'flex', gap: 3 }}>
                  <button onClick={() => startEditRace(i)} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                  <button onClick={() => deleteRace(i)} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                </div>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{r.description}</div>
              {(r.tags || []).length > 0 && (
                <div style={{ display: 'flex', gap: 5, marginTop: 6, flexWrap: 'wrap' }}>
                  {r.tags.map((t, ti) => <span key={ti} style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.3)', color: '#0ea5e9' }}>{t}</span>)}
                </div>
              )}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
