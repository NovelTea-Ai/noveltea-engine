import { useState } from 'react'
import useStore from '../../store/useStore'
import { api } from '../../api'
import { FieldSurveyButton, Panel, PanelTitle, Spinner } from '../shared/projectUi'
import { ARC_COLORS, AdvStringList } from './common'

/* ══════════════════════════════════════
   ARC PLANNER TAB
══════════════════════════════════════ */
export const ARC_TEMPLATES = {
  'Standard (3 arcs)': [
    { label: 'Rising Star',     description: 'Protagonist enters the world, discovers their gift, wins first battles.' },
    { label: 'Trials & Growth', description: 'Major setbacks, rivals appear, character grows through struggle.' },
    { label: 'Pinnacle',        description: 'Final confrontation, long-awaited revenge, peak power revealed.' },
  ],
  'Classic Xianxia (5)': [
    { label: 'Awakening',       description: 'Hidden talent discovered, leaves home, enters cultivation world.' },
    { label: 'Foundation',      description: 'Builds power base, forms key relationships, first major enemy.' },
    { label: 'Rising Conflict', description: 'Enemies conspire, protagonist faces impossible odds, loses then rebounds.' },
    { label: 'Transcendence',   description: 'Crosses into a new power tier, old enemies become insignificant.' },
    { label: 'Apex',            description: 'Final battles, world-level stakes, legacy established.' },
  ],
  'LitRPG System (4)': [
    { label: 'Tutorial',        description: 'System awakens, first quests, learning the rules.' },
    { label: 'Rank Climb',      description: 'Grinding levels, dungeon raids, guild politics.' },
    { label: 'Hidden Game',     description: 'Discovers the game has deeper layers, allegiances shift.' },
    { label: 'Final Boss',      description: 'The true enemy revealed, every skill tested.' },
  ],
}

export function SequentialArcPanel({ arcs, projectId, project, onArcsChanged }) {
  const [busy, setBusy] = useState(false)
  const [warnings, setWarnings] = useState([])
  const { setConsoleRunning, clearConsoleRunning, appendConsoleLine } = useStore()

  const done = arcs.length

  // Progress display is the GLOBAL console now — /api/arc registers itself
  // in the backend's _ACTIVE_GENERATIONS under ("arc"|project_id), which the
  // shared poller in useStore.js picks up on its own, same as any other
  // generation. This just needs to flag "something's running" so the
  // console opens immediately instead of waiting for the next idle-poll tick.
  async function genArc(index, regenerate = false) {
    if (busy) return
    setBusy(true); setWarnings([])
    setConsoleRunning('arc')
    try {
      // total_arcs omitted: no fixed ceiling — the backend derives/extends it
      // per call so the author can keep adding arcs past any initial estimate.
      const r = await api.generateArc(projectId, index, null, regenerate)
      setWarnings(r.warnings || [])
      onArcsChanged && onArcsChanged({ field: 'arcs', provider: 'sequential arc builder' })
    } catch (e) {
      appendConsoleLine(e.message || 'Arc generation failed', 'error')
    } finally { setBusy(false); clearConsoleRunning() }
  }

  function onWizardDone(res) {
    onArcsChanged && onArcsChanged(res)
  }

  return (
    <Panel>
      <PanelTitle action={
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button onClick={() => genArc(done)} disabled={busy}
            className="btn-primary" style={{ fontSize: 10, padding: '4px 12px' }}>
            {busy ? <Spinner size={10} /> : (done === 0 ? '✦ Generate Arc 1' : `✦ Generate Arc ${done + 1}`)}
          </button>
          <FieldSurveyButton field="arcs" projectId={projectId} onDone={onWizardDone} small />
        </div>
      }>Sequential Arc Builder — {done} arc{done === 1 ? '' : 's'} written</PanelTitle>

      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginBottom: 10, lineHeight: 1.55 }}>
        Each arc is generated on its own, seeing every earlier arc in full — so it can
        escalate from what actually came before and close threads they opened.
        Review each one before generating the next; regenerate a weak arc without
        rerolling the whole spine. No fixed arc count — keep going as long as the
        story needs. <b>Interactive</b> asks a few pivotal A/B questions (with a
        recommended pick) before it writes the next arc.
      </div>

      {/* Progress rail — one segment per arc actually written; grows with the story */}
      {done > 0 && (
        <div style={{ display: 'flex', gap: 3, marginBottom: 10 }}>
          {arcs.map((a, i) => (
            <div key={i} title={a?.label || `Arc ${i + 1}`}
              style={{
                flex: 1, height: 5, borderRadius: 3,
                background: ARC_COLORS[i % ARC_COLORS.length],
              }} />
          ))}
        </div>
      )}

      {warnings.length > 0 && (
        <div style={{
          fontSize: 10.5, color: 'var(--amber)', background: 'rgba(245,158,11,0.08)',
          border: '1px solid rgba(245,158,11,0.3)', borderRadius: 6,
          padding: '6px 9px', marginBottom: 8,
        }}>
          <b>Continuity check:</b>
          {warnings.map((w, i) => <div key={i}>• {w}</div>)}
        </div>
      )}

      {done > 0 && (
        <button onClick={() => genArc(done - 1, true)} disabled={busy}
          style={{
            fontSize: 10, padding: '3px 10px', background: 'transparent',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            color: 'var(--text-muted)',
          }}>↻ Regenerate Arc {done}</button>
      )}
    </Panel>
  )
}

/** The extra keys sequential generation produces beyond label/description. */
export function ArcDetail({ arc }) {
  const rows = [
    ['Function', arc.arc_function],
    ['Power milestone', arc.power_milestone],
    ['Antagonist tier', arc.antagonist_tier],
  ].filter(r => r[1])
  const lists = [
    ['Reveals', arc.reveals_planned],
    ['Knowledge shifts', arc.knowledge_shifts],
    ['Opens threads', arc.opens_threads],
    ['Closes threads', arc.closes_threads],
    ['Genre contracts', arc.genre_contracts],
  ].filter(r => Array.isArray(r[1]) && r[1].length)
  const ts = arc.tension_shape
  if (!rows.length && !lists.length && !ts) return null

  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-soft)' }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ fontSize: 10.5, marginBottom: 3 }}>
          <span style={{ color: 'var(--text-muted)' }}>{k}: </span>
          <span style={{ color: 'var(--text-secondary)' }}>{v}</span>
        </div>
      ))}
      {ts && (
        <div style={{ fontSize: 10.5, marginBottom: 3 }}>
          <span style={{ color: 'var(--text-muted)' }}>Tension: </span>
          <span style={{ color: 'var(--text-secondary)' }}>
            {ts.start ?? '?'} → <b style={{ color: 'var(--amber)' }}>{ts.peak ?? '?'}</b> → {ts.end ?? '?'}
          </span>
        </div>
      )}
      {lists.map(([k, v]) => (
        <div key={k} style={{ fontSize: 10.5, marginTop: 4 }}>
          <div style={{ color: 'var(--text-muted)' }}>{k}:</div>
          {v.slice(0, 4).map((item, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)', paddingLeft: 8 }}>• {item}</div>
          ))}
        </div>
      ))}
    </div>
  )
}

/** The list-shaped _arc_record_schema fields — reveals_planned,
 * knowledge_shifts, opens_threads, closes_threads, genre_contracts — each
 * editable as a repeatable list of strings, same AdvStringList component the
 * Chapter Skeleton advanced editor already uses (see AdvStringList, defined
 * alongside SkeletonAdvancedEditor further down this file). */
export function ArcAdvancedEditor({ editForm, setEditForm }) {
  const f = editForm || {}
  const set = (key, val) => setEditForm(cur => ({ ...cur, [key]: val }))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <AdvStringList label="Reveals planned" items={f.reveals_planned}
        onChange={v => set('reveals_planned', v)} placeholder="what the reader learns during this arc" />
      <AdvStringList label="Knowledge shifts" items={f.knowledge_shifts}
        onChange={v => set('knowledge_shifts', v)} placeholder="who learns what, and who is still in the dark" />
      <AdvStringList label="Opens threads" items={f.opens_threads}
        onChange={v => set('opens_threads', v)} placeholder="questions/conflicts introduced here" />
      <AdvStringList label="Closes threads" items={f.closes_threads}
        onChange={v => set('closes_threads', v)} placeholder="threads resolved here — should reference an earlier arc's opened thread" />
      <AdvStringList label="Genre contracts" items={f.genre_contracts}
        onChange={v => set('genre_contracts', v)} placeholder="reader promises this arc keeps" />
    </div>
  )
}

export function ArcPlannerTab({ arcs, setLocalArcs, project, onSave, saving, projectId, afterGenerate }) {
  const [editIdx, setEditIdx]   = useState(null)
  const [editForm, setEditForm] = useState(null)

  function distribute(list, total) {
    if (!list.length) return list
    const per = Math.floor(total / list.length)
    let start = 1
    return list.map((arc, i) => {
      const count = i === list.length - 1 ? total - start + 1 : per
      const chapters = Array.from({ length: count }, (_, j) => start + j)
      start += count
      return { ...arc, chapters }
    })
  }

  function applyTemplate(name) {
    setLocalArcs(distribute(ARC_TEMPLATES[name].map(a => ({ ...a, chapters: [] })), project.target_chapters))
  }

  function addArc() {
    const next = [...arcs, { label: `New Arc ${arcs.length + 1}`, description: '', chapters: [] }]
    setLocalArcs(distribute(next, project.target_chapters))
  }

  function removeArc(i) {
    setLocalArcs(distribute(arcs.filter((_, idx) => idx !== i), project.target_chapters))
  }

  function saveEdit() {
    setLocalArcs(arcs.map((a, i) => i === editIdx ? editForm : a))
    setEditIdx(null)
  }

  function onGenDone(res) {
    if (res.result && Array.isArray(res.result)) setLocalArcs(res.result)
    afterGenerate(res)
  }

  return (
    <div className="split-flex" style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', gap: 16 }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <SequentialArcPanel
          arcs={arcs}
          projectId={projectId}
          project={project}
          onArcsChanged={onGenDone}
        />
        <Panel>
          {/* The all-at-once generators (AI Design Arcs / Update / Survey) are
              deliberately gone — they rewrote every arc in a single call, which
              is what produced two-sentence arcs and would clobber sequential
              work. Generation now lives in SequentialArcPanel above. */}
          <PanelTitle action={
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <button onClick={addArc} style={{ fontSize: 10, padding: '3px 10px', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)' }}>+ Add</button>
              <button onClick={() => onSave({ arcs })} disabled={saving} className="btn-primary" style={{ fontSize: 10, padding: '3px 12px' }}>
                {saving ? <Spinner size={10} /> : 'Save'}
              </button>
            </div>
          }>Arcs ({arcs.length})</PanelTitle>

          {arcs.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
              No arcs yet — pick a template, use AI, or add one manually.
            </div>
          ) : (
            arcs.map((arc, i) => {
              const color = ARC_COLORS[i % ARC_COLORS.length]
              return (
                <div key={i} style={{ border: `1px solid ${color}33`, borderLeft: `3px solid ${color}`, borderRadius: 'var(--radius)', padding: '12px 14px', marginBottom: 8, background: 'var(--bg-elevated)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <div>
                      <span style={{ fontSize: 9, fontWeight: 700, color, marginRight: 8 }}>Arc {i + 1}</span>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>{arc.label?.replace(/^Arc \d+:\s*/i, '') || `Arc ${i + 1}`}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button onClick={() => { setEditIdx(i); setEditForm({ ...arc }) }}
                        title="Edit this arc's full plan"
                        style={{ fontSize: 10, padding: '2px 8px', borderRadius: 3, background: 'var(--accent-dim)', border: '1px solid var(--accent)', color: 'var(--accent-light)' }}>✎ Edit</button>
                      <button onClick={() => removeArc(i)} style={{ fontSize: 10, padding: '2px 6px', color: 'var(--red)' }}>✕</button>
                    </div>
                  </div>
                  {arc.description && <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 5 }}>{arc.description}</div>}
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                    Ch. {arc.chapters?.[0] ?? '?'} – {arc.chapters?.[arc.chapters.length - 1] ?? '?'} · {arc.chapters?.length ?? 0} chapters
                  </div>
                  {/* Sequentially-generated arcs carry 9 extra keys the old
                      all-at-once call never produced. */}
                  <ArcDetail arc={arc} />
                </div>
              )
            })
          )}
        </Panel>
      </div>

      {/* Full-page arc editor — same pattern as the Chapter Skeleton editor
          (see SkeletonAdvancedEditor): editing a real arc plan means reading/
          writing long structured text (description, reveals_planned,
          knowledge_shifts, opens/closes_threads, genre_contracts), which a
          2-field inline card editor (label + description only) couldn't
          touch at all — every other field was locked to whatever the AI
          generated. This gives every _arc_record_schema field real room. */}
      {editIdx !== null && editForm && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.55)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
        }} onClick={() => setEditIdx(null)}>
          <div onClick={e => e.stopPropagation()} style={{
            width: 'min(1000px, 96vw)', height: 'min(90vh, 950px)',
            background: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border)', display: 'flex', flexDirection: 'column',
            overflow: 'hidden', boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}>
            <div style={{
              flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '14px 20px', borderBottom: '1px solid var(--border)',
            }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent)' }}>
                Editing {editForm.label || `Arc ${editIdx + 1}`}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={saveEdit} className="btn-primary" style={{ padding: '7px 18px', fontSize: 12 }}>✓ Save</button>
                <button onClick={() => setEditIdx(null)} className="btn-ghost" style={{ padding: '7px 14px', fontSize: 12 }}>✕ Close</button>
              </div>
            </div>

            <div style={{
              flex: 1, overflowY: 'auto', padding: '20px 24px',
              display: 'grid', gridTemplateColumns: 'minmax(300px, 400px) 1fr', gap: 28, alignContent: 'start',
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Label</div>
                  <input value={editForm.label || ''} onChange={e => setEditForm(f => ({ ...f, label: e.target.value }))}
                    style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)', fontWeight: 600 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Description</div>
                  <textarea value={editForm.description || ''} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                    rows={7} placeholder="What happens in this arc? The power milestone crossed, the emotional stakes."
                    style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)', resize: 'vertical', lineHeight: 1.5 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Chapters (comma-separated numbers)</div>
                  <input value={(editForm.chapters || []).join(', ')}
                    onChange={e => setEditForm(f => ({ ...f, chapters: e.target.value.split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n)) }))}
                    placeholder="12, 13, 14" style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)' }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Arc function</div>
                  <input value={editForm.arc_function || ''} onChange={e => setEditForm(f => ({ ...f, arc_function: e.target.value }))}
                    placeholder="setup | escalation | payoff | climax | resolution | transition"
                    style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)' }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Power milestone</div>
                  <textarea value={editForm.power_milestone || ''} onChange={e => setEditForm(f => ({ ...f, power_milestone: e.target.value }))}
                    rows={2} placeholder="The realm/tier the protagonist reaches by arc end"
                    style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)', resize: 'vertical', lineHeight: 1.5 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 700 }}>Antagonist tier</div>
                  <textarea value={editForm.antagonist_tier || ''} onChange={e => setEditForm(f => ({ ...f, antagonist_tier: e.target.value }))}
                    rows={2} placeholder="Who opposes them here and why they outclass the last antagonist"
                    style={{ width: '100%', padding: '8px 10px', fontSize: 13, borderRadius: 'var(--radius-sm)', resize: 'vertical', lineHeight: 1.5 }} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, fontWeight: 700 }}>Tension shape</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {['start', 'peak', 'end'].map(k => (
                      <div key={k} style={{ flex: 1 }}>
                        <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2, textTransform: 'capitalize' }}>{k}</div>
                        <input type="number" min={0} max={100} value={editForm.tension_shape?.[k] ?? ''}
                          onChange={e => setEditForm(f => ({ ...f, tension_shape: { ...(f.tension_shape || {}), [k]: e.target.value ? Number(e.target.value) : undefined } }))}
                          style={{ width: '100%', padding: '6px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <ArcAdvancedEditor editForm={editForm} setEditForm={setEditForm} />
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="split-flex-sidebar" style={{ width: 240, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Panel>
          <PanelTitle>Templates</PanelTitle>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 10 }}>Auto-distributes {project.target_chapters} chapters</div>
          {Object.keys(ARC_TEMPLATES).map(name => (
            <button key={name} onClick={() => applyTemplate(name)} style={{
              width: '100%', textAlign: 'left', padding: '8px 10px', marginBottom: 6,
              borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)',
              border: '1px solid var(--border)', fontSize: 11, color: 'var(--text-secondary)',
              transition: 'all 0.12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--text-primary)' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
            >{name}</button>
          ))}
        </Panel>

        {arcs.length > 0 && (
          <Panel>
            <PanelTitle>Distribution</PanelTitle>
            {arcs.map((arc, i) => {
              const pct = Math.round(((arc.chapters || []).length / project.target_chapters) * 100)
              const color = ARC_COLORS[i % ARC_COLORS.length]
              return (
                <div key={i} style={{ marginBottom: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{arc.label?.slice(0, 18) || `Arc ${i+1}`}</span>
                    <span style={{ fontSize: 10, color, fontWeight: 600 }}>{(arc.chapters || []).length} ch</span>
                  </div>
                  <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2 }}>
                    <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
                  </div>
                </div>
              )
            })}
          </Panel>
        )}
      </div>
    </div>
  )
}
