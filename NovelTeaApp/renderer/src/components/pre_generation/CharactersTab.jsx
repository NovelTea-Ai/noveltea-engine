import { useEffect, useState } from 'react'
import useNarrowLayout from '../../hooks/useNarrowLayout'
import { api } from '../../api'
import { FieldSurveyButton, Panel, PanelTitle, Spinner } from '../shared/projectUi'

/* ══════════════════════════════════════
   CHARACTER DNA PICKER  (V4 Phase 6)
   Click a character's "◈ Corpus DNA" button → this modal. Left = the
   project character being edited (read-only preview of its DNA fields,
   live as traits are added). Right = every corpus character with a
   character_dna/ file, grouped by role, click-to-add one trait at a time —
   never a whole-character clone. See PHASE6_CHARACTER_DNA_PICKER.md.
══════════════════════════════════════ */
export const CDNA_ROLES = [
  { id: 'protagonist', label: 'Protagonist' },
  { id: 'deuteragonist', label: 'Deuteragonist' },
  { id: 'sidekick', label: 'Sidekick' },
  { id: 'mentor', label: 'Mentor' },
  { id: 'antagonist', label: 'Antagonist' },
]

export const CDNA_FIELD_LABEL = { personality_traits: 'Trait', core_belief: 'Core belief', speech_style: 'Speech style', banter_style: 'Banter style' }

export const CDNA_GROUNDING_COLOR = { strong: 'var(--green)', moderate: 'var(--amber)', thin: 'var(--text-muted)' }

export function CharacterDnaPickerModal({ editForm, setEditForm, onClose }) {
  const [allByRole, setAllByRole] = useState(null)   // { role: [...characters] } once loaded
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeRole, setActiveRole] = useState('protagonist')
  const [novelFilter, setNovelFilter] = useState('')
  const [justAdded, setJustAdded] = useState(null)   // brief inline confirmation, cleared after a beat

  // Mobile: one column, full-screen sheet instead of a fixed side-by-side
  // split — the existing left panel alone (260px) would eat most of a phone
  // viewport before the actual browse/add UI got any room at all. Same
  // 768px breakpoint + live resize tracking already used elsewhere in this
  // file (see ChapterSkeletonTab's isNarrow).
  const isNarrow = useNarrowLayout()
  const [showMyDna, setShowMyDna] = useState(false)   // narrow-only: "my character's DNA" summary is collapsed by default so browsing corpus characters isn't pushed below the fold

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.characterDna().then(res => {
      if (cancelled) return
      const byRole = {}
      for (const r of CDNA_ROLES) byRole[r.id] = []
      for (const c of (res.characters || [])) {
        if (byRole[c.role]) byRole[c.role].push(c)
      }
      for (const r of CDNA_ROLES) byRole[r.id].sort((a, b) => a.character_name.localeCompare(b.character_name))
      setAllByRole(byRole)
    }).catch(e => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [])

  const roleChars = allByRole?.[activeRole] || []
  const novelIds = [...new Set(roleChars.map(c => c.novel_id))].sort()
  const visible = novelFilter ? roleChars.filter(c => c.novel_id === novelFilter) : roleChars

  function addTrait(field, label) {
    setEditForm(f => {
      if (field === 'personality_traits') {
        const existing = f.personality_traits || []
        if (existing.includes(label)) return f
        return { ...f, personality_traits: [...existing, label] }
      }
      // single-value fields — only fill if empty, don't clobber an existing hand-written value silently
      if (f[field]) return f
      return { ...f, [field]: label }
    })
    setJustAdded(label)
    setTimeout(() => setJustAdded(cur => (cur === label ? null : cur)), 1500)
  }

  function isAdded(field, label) {
    if (field === 'personality_traits') return (editForm.personality_traits || []).includes(label)
    return editForm[field] === label
  }

  // Shared between desktop's permanent left sidebar and mobile's collapsible
  // summary bar — same content, two different containers.
  const myDnaFields = (
    <>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 5 }}>Personality traits</div>
        {(editForm.personality_traits || []).length === 0 ? (
          <div style={{ fontSize: 10.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>none yet</div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {editForm.personality_traits.map((t, i) => (
              <span key={i} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>{t}</span>
            ))}
          </div>
        )}
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 5 }}>Core belief</div>
        <div style={{ fontSize: 10.5, color: editForm.core_belief ? 'var(--text-primary)' : 'var(--text-muted)', fontStyle: editForm.core_belief ? 'normal' : 'italic' }}>{editForm.core_belief || 'none yet'}</div>
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 5 }}>Speech style</div>
        <div style={{ fontSize: 10.5, color: editForm.speech_style ? 'var(--text-primary)' : 'var(--text-muted)', fontStyle: editForm.speech_style ? 'normal' : 'italic' }}>{editForm.speech_style || 'none yet'}</div>
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 5 }}>Banter style</div>
        <div style={{ fontSize: 10.5, color: editForm.banter_style ? 'var(--text-primary)' : 'var(--text-muted)', fontStyle: editForm.banter_style ? 'normal' : 'italic' }}>{editForm.banter_style || 'none yet'}</div>
      </div>
    </>
  )

  const roleTabs = (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {CDNA_ROLES.map(r => {
        const count = allByRole?.[r.id]?.length ?? null
        const empty = count === 0
        return (
          <button key={r.id} onClick={() => !empty && setActiveRole(r.id)} disabled={empty}
            title={empty ? 'No corpus characters extracted for this role yet' : undefined}
            style={{
              fontSize: 11, padding: '5px 12px', borderRadius: 'var(--radius-sm)',
              background: activeRole === r.id ? 'var(--accent)' : 'var(--bg-elevated)',
              color: activeRole === r.id ? '#fff' : (empty ? 'var(--text-muted)' : 'var(--text-secondary)'),
              border: '1px solid ' + (activeRole === r.id ? 'var(--accent)' : 'var(--border)'),
              opacity: empty ? 0.5 : 1, cursor: empty ? 'default' : 'pointer',
            }}>
            {r.label}{count !== null ? ` (${count})` : ''}
          </button>
        )
      })}
    </div>
  )

  const characterList = loading ? (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', fontSize: 12 }}><Spinner size={12} /> Loading corpus DNA…</div>
  ) : error ? (
    <div style={{ color: 'var(--red)', fontSize: 12 }}>✗ {error}</div>
  ) : visible.length === 0 ? (
    <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: '30px 0' }}>
      No corpus characters extracted for this role yet — this fills in as the Character DNA pipeline (Corpus Pipeline tab) runs.
    </div>
  ) : (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {visible.map(c => (
        <div key={`${c.novel_id}/${c.character_id}`} style={{
          background: 'var(--bg-elevated)', border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius)', padding: '12px 14px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 700, fontSize: 13 }}>{c.character_name}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{c.novel_id}</span>
            {c.grounding && (
              <span title="How well-evidenced this build is — the LLM's own self-assessment" style={{
                fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 8,
                color: CDNA_GROUNDING_COLOR[c.grounding] || 'var(--text-muted)',
                border: `1px solid ${CDNA_GROUNDING_COLOR[c.grounding] || 'var(--text-muted)'}`,
                textTransform: 'uppercase', letterSpacing: 0.3,
              }}>{c.grounding}</span>
            )}
          </div>
          {c.archetype && <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginBottom: 8 }}>{c.archetype}</div>}

          {c.traits.length === 0 ? (
            <div style={{ fontSize: 10.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>no extractable traits in this file</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {c.traits.map((t, i) => {
                const added = isAdded(t.field, t.label)
                return (
                  <div key={i} style={isNarrow
                    ? { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, paddingBottom: 6, borderBottom: i < c.traits.length - 1 ? '1px solid var(--border-soft)' : 'none' }
                    : { display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 11 }}>
                    <span style={{ fontSize: 9, color: 'var(--text-muted)', minWidth: isNarrow ? 'auto' : 78, paddingTop: isNarrow ? 0 : 2 }}>{CDNA_FIELD_LABEL[t.field]}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ color: 'var(--text-primary)' }}>{t.label}</div>
                      {t.evidence && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, fontStyle: 'italic' }}>"{t.evidence}"</div>}
                    </div>
                    <button onClick={() => addTrait(t.field, t.label)} disabled={added} style={{
                      fontSize: 10, padding: '3px 9px', fontWeight: 600, borderRadius: 'var(--radius-sm)',
                      background: added ? 'var(--bg-card)' : 'var(--accent)',
                      color: added ? 'var(--text-muted)' : '#fff',
                      border: added ? '1px solid var(--border)' : 'none', flexShrink: 0,
                      alignSelf: isNarrow ? 'flex-start' : 'auto',
                    }}>{added ? '✓ added' : (justAdded === t.label ? '✓' : '+ Add')}</button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  )

  if (isNarrow) {
    return (
      <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 9999, display: 'flex', alignItems: 'flex-end' }}>
        <div style={{ background: 'var(--bg-card)', width: '100%', height: '92vh', borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border-soft)', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>Corpus Character DNA</div>
              <button onClick={onClose} title="Close" style={{ fontSize: 16, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>✕</button>
            </div>

            {/* collapsed summary bar — tap to expand "my character's" current DNA
                without it permanently eating screen space above the corpus list */}
            <button onClick={() => setShowMyDna(s => !s)} style={{
              fontSize: 11, padding: '7px 10px', borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span>Adding to: <b>{editForm.name || 'New Character'}</b></span>
              <span>{showMyDna ? '▲ hide' : '▼ show'}</span>
            </button>
            {showMyDna && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '10px 12px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)' }}>
                {myDnaFields}
              </div>
            )}

            {roleTabs}
            {novelIds.length > 1 && (
              <select value={novelFilter} onChange={e => setNovelFilter(e.target.value)} style={{
                fontSize: 11, padding: '6px 8px', background: 'var(--bg-elevated)',
                border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', width: '100%',
              }}>
                <option value="">All novels ({novelIds.length})</option>
                {novelIds.map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            )}
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 14 }}>
            {characterList}
          </div>

          <div style={{ padding: 12, borderTop: '1px solid var(--border-soft)' }}>
            <button onClick={onClose} className="btn-primary" style={{ width: '100%', padding: '9px', fontSize: 13 }}>Done</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', width: '90vw', maxWidth: 1100, height: '85vh', display: 'flex', overflow: 'hidden' }}>

        {/* ── left: the project character being edited ── */}
        <div style={{ width: 260, flexShrink: 0, borderRight: '1px solid var(--border-soft)', padding: 16, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{editForm.name || 'New Character'}</div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{editForm.role}</div>
          {myDnaFields}
          <div style={{ flex: 1 }} />
          <button onClick={onClose} className="btn-primary" style={{ padding: '7px', fontSize: 12 }}>Done</button>
        </div>

        {/* ── right: corpus characters ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border-soft)', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>Corpus Character DNA</div>
              <button onClick={onClose} title="Close" style={{ fontSize: 14, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>✕</button>
            </div>
            {roleTabs}
            {novelIds.length > 1 && (
              <select value={novelFilter} onChange={e => setNovelFilter(e.target.value)} style={{
                fontSize: 11, padding: '4px 8px', background: 'var(--bg-elevated)',
                border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', alignSelf: 'flex-start',
              }}>
                <option value="">All novels ({novelIds.length})</option>
                {novelIds.map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            )}
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 18 }}>
            {characterList}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════
   CHARACTERS TAB
══════════════════════════════════════ */
export const CHAR_ROLES = ['protagonist','antagonist','ally','rival','mentor','love_interest','neutral']

export const roleColor = { protagonist: 'var(--accent)', antagonist: 'var(--red)', ally: 'var(--green)', rival: 'var(--amber)', mentor: 'var(--cyan)', love_interest: 'var(--pink)', neutral: 'var(--text-muted)' }

export function CharactersTab({ project, projectId, afterGenerate, onSave }) {
  const [chars, setChars] = useState(project.character_list || [])
  const [editIdx, setEditIdx] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  const [dnaPickerOpen, setDnaPickerOpen] = useState(false)

  useEffect(() => { setChars(project.character_list || []) }, [project.id])

  function onGenDone(res) {
    afterGenerate(res)
    if (res.field === 'characters' && Array.isArray(res.result)) setChars(res.result)
  }

  function startEdit(i) {
    setEditIdx(i)
    setEditForm({ ...chars[i] })
    setAdding(false)
  }

  function startAdd() {
    setEditIdx(chars.length)
    setEditForm({ name: '', role: 'ally', archetype: '', motivation: '', secret: '', faction: '' })
    setAdding(true)
  }

  async function saveEdit() {
    setSaving(true)
    const updated = adding
      ? [...chars, editForm]
      : chars.map((c, i) => i === editIdx ? editForm : c)
    setChars(updated)
    setEditIdx(null)
    setAdding(false)
    await onSave({ character_list: updated })
    setSaving(false)
  }

  async function deleteChar(i) {
    const updated = chars.filter((_, idx) => idx !== i)
    setChars(updated)
    if (editIdx === i) setEditIdx(null)
    await onSave({ character_list: updated })
  }

  const EF = editForm || {}

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
      <Panel>
        <PanelTitle action={
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={startAdd} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>+ Add</button>
            <FieldSurveyButton field="characters" projectId={projectId} onDone={onGenDone} small />
          </div>
        }>
          Characters ({chars.length})
        </PanelTitle>

        {/* Edit / Add form */}
        {editIdx !== null && editForm && (
          <div style={{ background: 'var(--bg-input)', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', padding: '14px 16px', marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)' }}>{adding ? 'New Character' : `Editing: ${chars[editIdx]?.name}`}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Name</div>
                <input value={EF.name || ''} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Role</div>
                <select value={EF.role || 'ally'} onChange={e => setEditForm(f => ({ ...f, role: e.target.value }))} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
                  {CHAR_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Archetype</div>
                <input value={EF.archetype || ''} onChange={e => setEditForm(f => ({ ...f, archetype: e.target.value }))} placeholder="e.g. Hidden genius, Cold beauty" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Faction</div>
                <input value={EF.faction || ''} onChange={e => setEditForm(f => ({ ...f, faction: e.target.value }))} placeholder="Which faction (optional)" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Motivation</div>
              <textarea value={EF.motivation || ''} onChange={e => setEditForm(f => ({ ...f, motivation: e.target.value }))} rows={2} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Secret / Hidden arc</div>
              <textarea value={EF.secret || ''} onChange={e => setEditForm(f => ({ ...f, secret: e.target.value }))} rows={2} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
            </div>

            {/* DNA fields — generation already produces these (_build_prompt's
                "characters" branch, generate.py) and _character_dna_block_for_shaping
                feeds them into Dialogue Shaping, but until now this form had no way
                to VIEW or hand-edit them, and the Character DNA Picker below needs a
                visible target to append into. */}
            <div style={{ borderTop: '1px solid var(--border-soft)', paddingTop: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: 0.4 }}>Character DNA</div>
                <button onClick={() => setDnaPickerOpen(true)} title="Pull traits from a corpus character with real evidence behind each one" style={{
                  fontSize: 10.5, padding: '4px 10px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                  background: 'linear-gradient(135deg,#8b5cf6,#6366f1)', color: '#fff', border: 'none',
                }}>◈ Corpus DNA</button>
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Personality traits</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 5 }}>
                  {(EF.personality_traits || []).map((t, ti) => (
                    <span key={ti} style={{ fontSize: 10.5, padding: '3px 8px', borderRadius: 10, background: 'var(--bg-elevated)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 5 }}>
                      {t}
                      <button onClick={() => setEditForm(f => ({ ...f, personality_traits: (f.personality_traits || []).filter((_, i2) => i2 !== ti) }))} style={{ fontSize: 9, color: 'var(--text-muted)', background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}>✕</button>
                    </span>
                  ))}
                  {!(EF.personality_traits || []).length && <span style={{ fontSize: 10.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>none yet — add manually or via Corpus DNA</span>}
                </div>
                <input placeholder="Type a trait and press Enter" onKeyDown={e => {
                  if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                    const v = e.currentTarget.value.trim()
                    setEditForm(f => ({ ...f, personality_traits: [...(f.personality_traits || []), v] }))
                    e.currentTarget.value = ''
                  }
                }} style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Core belief</div>
                <input value={EF.core_belief || ''} onChange={e => setEditForm(f => ({ ...f, core_belief: e.target.value }))} placeholder="The one conviction that drives their decisions" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Speech style</div>
                  <input value={EF.speech_style || ''} onChange={e => setEditForm(f => ({ ...f, speech_style: e.target.value }))} placeholder="Vocabulary/formality/rhythm" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>Banter style</div>
                  <input value={EF.banter_style || ''} onChange={e => setEditForm(f => ({ ...f, banter_style: e.target.value }))} placeholder="'none' if they don't banter" style={{ width: '100%', padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={saveEdit} disabled={saving} className="btn-primary" style={{ padding: '6px 16px', fontSize: 12 }}>{saving ? 'Saving…' : '✓ Save'}</button>
              <button onClick={() => { setEditIdx(null); setAdding(false) }} className="btn-ghost" style={{ padding: '6px 14px', fontSize: 12 }}>Cancel</button>
            </div>
          </div>
        )}

        {dnaPickerOpen && editForm && (
          <CharacterDnaPickerModal
            editForm={editForm}
            setEditForm={setEditForm}
            onClose={() => setDnaPickerOpen(false)}
          />
        )}

        {chars.length === 0 ? (
          <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
            No characters yet. Let AI design your cast or add one manually.
          </div>
        ) : (
          <div className="card-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
            {chars.map((char, i) => (
              <div key={i} style={{ background: 'var(--bg-elevated)', border: `1px solid ${editIdx === i ? 'var(--accent)' : 'var(--border-soft)'}`, borderRadius: 'var(--radius)', padding: '12px 14px', position: 'relative' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, gap: 6 }}>
                  <span style={{ fontWeight: 700, fontSize: 13 }}>{char.name}</span>
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 10, background: `${roleColor[char.role] || 'var(--accent)'}22`, color: roleColor[char.role] || 'var(--accent)', border: `1px solid ${roleColor[char.role] || 'var(--accent)'}` }}>
                      {char.role}
                    </span>
                    <button onClick={() => startEdit(i)} title="Edit" style={{ fontSize: 11, padding: '1px 6px', borderRadius: 4, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                    <button onClick={() => deleteChar(i)} title="Delete" style={{ fontSize: 11, padding: '1px 6px', borderRadius: 4, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                  </div>
                </div>
                <div style={{ fontSize: 10, color: 'var(--accent-light)', marginBottom: 6 }}>{char.archetype}</div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4, marginBottom: 6 }}>{char.motivation}</div>
                {char.secret && (
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', fontStyle: 'italic', padding: '5px 8px', background: 'var(--bg-card)', borderRadius: 'var(--radius-sm)', borderLeft: '2px solid var(--amber)' }}>
                    🔒 {char.secret}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}
