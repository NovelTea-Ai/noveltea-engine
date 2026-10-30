import { useEffect, useState } from 'react'
import { API_BASE, api } from '../../api'
import useStore from '../../store/useStore'
import { FieldSurveyButton, Panel, PanelTitle, Spinner } from '../shared/projectUi'

/* ══════════════════════════════════════
   GENERATE TAB
══════════════════════════════════════ */
/* ══════════════════════════════════════
   CRITIQUE TAB
   Author writes a free-text critique of an already-written chapter, an
   interactive interview proposes concrete fixes (same shape as Dialogue
   Shaping / Blueprint Enrichment), the chosen fix is applied to the
   chapter AND separately distilled into a tagged standing rule that future
   chapter generations are grounded in (project.critique_notes, injected
   in _build_chapter_prompt's critique_block — see generate.py).
══════════════════════════════════════ */
// Mirrors the backend's _CRITIQUE_TAG_OPTIONS exactly (generate.py) — kept
// as a plain JS list here since the tag is free-form text on the wire, this
// is only used for color-coding the posted rule cards, not validation.
export const CRITIQUE_TAG_COLOR = {
  pacing: '#f59e0b', dialogue: '#ec4899', characterization: '#8b5cf6',
  prose_style: '#06b6d4', worldbuilding: '#3b82f6', plot_logic: '#a855f7',
  reveal_pacing: '#10b981', conflict: '#ef4444', humor: '#f97316', other: 'var(--text-muted)',
}

// The chosen chapter measured beside the reference chapters its plan modelled (Author DNA "plan from this novel"): talk,
// build-up against fight, lines inside the fight, jump cuts. No AI call.
export function ReferenceCheck({ projectId, chapter }) {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setRes(null) }, [chapter])
  if (chapter == null) return null
  const pct = v => (v == null ? '—' : `${Math.round(v * 100)}%`)
  const row = (label, ours, refs, fmt = v => (v == null ? '—' : v)) => (
    <tr><td style={{ padding: '2px 8px 2px 0', color: 'var(--text-muted)' }}>{label}</td><td style={{ padding: '2px 8px', fontWeight: 700 }}>{fmt(ours)}</td>
      {refs.map((r, i) => <td key={i} style={{ padding: '2px 8px' }}>{fmt(r)}</td>)}</tr>)
  return (
    <div style={{ margin: '0 0 10px' }}>
      <button disabled={busy} onClick={async () => { setBusy(true); try { setRes(await api.referenceChapterCheck(projectId, chapter)) } catch (e) { setRes({ ok: false, reason: e.message }) } finally { setBusy(false) } }}
        style={{ fontSize: 10.5, padding: '4px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
        title="Measure this chapter beside the reference novel's chapters its plan modelled (no AI call)">
        {busy ? 'Measuring…' : '📏 Compare with the reference novel'}
      </button>
      {res && !res.ok && <div style={{ fontSize: 10.5, color: 'var(--amber)', marginTop: 4 }}>{res.reason}</div>}
      {res?.ok && (
        <div style={{ marginTop: 6, fontSize: 11 }}>
          <table style={{ borderCollapse: 'collapse' }}><tbody>
            <tr><td /><td style={{ padding: '2px 8px', fontWeight: 700 }}>This chapter</td>
              {res.references.map(r => <td key={r.chapter} style={{ padding: '2px 8px', color: 'var(--text-muted)' }}>{r.novel_title} ch {r.chapter}</td>)}</tr>
            {row('Words', res.ours.words, res.references.map(r => r.measured.words))}
            {row('Spoken', res.ours.spoken_share, res.references.map(r => r.measured.spoken_share), pct)}
            {row('Before the first blow', res.ours.words_before_first_fight, res.references.map(r => r.measured.words_before_first_fight))}
            {row('In the fight', res.ours.words_in_fights, res.references.map(r => r.measured.words_in_fights))}
            {row('After the fight', res.ours.words_after_last_fight, res.references.map(r => r.measured.words_after_last_fight))}
            {row('Lines inside the fight', res.ours.fight_lines, res.references.map(r => r.fight_lines))}
          </tbody></table>
          {res.notes.map((n, i) => <div key={i} style={{ fontSize: 10.5, color: 'var(--amber)', marginTop: 3 }}>• {n}</div>)}
          {!res.notes.length && <div style={{ fontSize: 10.5, color: 'var(--green)', marginTop: 3 }}>Built in line with the reference.</div>}
        </div>
      )}
    </div>
  )
}

export function CritiqueTab({ project, projectId, afterGenerate, onSave }) {
  const [chapters, setChapters] = useState([])
  const [selectedCh, setSelectedCh] = useState(null)
  const [critiqueText, setCritiqueText] = useState('')
  const [audioUrl, setAudioUrl] = useState(null)
  const [audioLoading, setAudioLoading] = useState(false)
  const [rules, setRules] = useState(project.critique_notes || [])
  const [editId, setEditId] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const { appendConsoleLine, openConsole } = useStore()

  useEffect(() => { setRules(project.critique_notes || []) }, [project.id])

  useEffect(() => {
    api.listGenerated(projectId).then(r => {
      setChapters(r.chapters || [])
      if (r.chapters?.length > 0 && selectedCh == null) setSelectedCh(r.chapters[r.chapters.length - 1].number)
    }).catch(() => setChapters([]))
  }, [projectId])

  // Whenever the selected chapter changes, check whether it already has
  // narration saved so the play button only shows when there's really
  // something to play — never a button that 404s.
  useEffect(() => {
    if (selectedCh == null) { setAudioUrl(null); return }
    setAudioLoading(true)
    api.narrateStatus(projectId, selectedCh)
      .then(r => setAudioUrl(r.exists ? `${API_BASE}${r.audio_url}` : null))
      .catch(() => setAudioUrl(null))
      .finally(() => setAudioLoading(false))
  }, [projectId, selectedCh])

  function handleDone(res) {
    if (res.saved_rule) {
      setRules(rs => [...rs, res.saved_rule])
    }
    if (res.changed) {
      appendConsoleLine(`✓ Chapter ${selectedCh} fixed from your critique.${res.saved_rule ? ' Standing rule saved for future chapters.' : ''}`, 'success')
      openConsole()
    } else if (res.saved_rule) {
      appendConsoleLine(`✓ Standing rule saved for future chapters (no change made to chapter ${selectedCh}).`, 'success')
      openConsole()
    }
    setCritiqueText('')
  }

  async function saveRules(updated) {
    setSaving(true)
    setRules(updated)
    try { await api.critiqueNotesUpdate(projectId, updated) }
    finally { setSaving(false) }
  }

  function startEdit(r) { setEditId(r.id); setEditForm({ ...r }) }
  async function commitEdit() {
    const updated = rules.map(r => r.id === editId ? { ...editForm } : r)
    setEditId(null); setEditForm(null)
    await saveRules(updated)
  }
  async function deleteRule(id) {
    await saveRules(rules.filter(r => r.id !== id))
  }

  const EF = editForm || {}

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
      <Panel style={{ marginBottom: 12 }}>
        <PanelTitle>Critique a Chapter</PanelTitle>
        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 10 }}>
          Pick a chapter, write what you want changed, then run the interview. It proposes concrete fixes —
          pick one or describe your own — applies the chosen fix to this chapter, and separately distills your
          critique into a standing rule future chapter generations will follow.
        </div>

        <select value={selectedCh ?? ''} onChange={e => setSelectedCh(Number(e.target.value))}
          style={{ padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', marginBottom: 8 }}>
          {chapters.length === 0 && <option value="">No chapters written yet</option>}
          {chapters.map(c => <option key={c.number} value={c.number}>Chapter {c.number}{c.title ? ` — ${c.title}` : ''}</option>)}
        </select>
        <ReferenceCheck projectId={projectId} chapter={selectedCh} />

        {selectedCh != null && (
          <div style={{ marginBottom: 10 }}>
            {audioLoading ? (
              <div style={{ fontSize: 10.5, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Spinner size={10} /> Checking for narration…
              </div>
            ) : audioUrl ? (
              <audio key={audioUrl} controls src={audioUrl} style={{ width: '100%', height: 32 }} />
            ) : (
              <div style={{ fontSize: 10.5, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                No narration saved for this chapter yet — narrate it from the Reader tab to listen while critiquing.
              </div>
            )}
          </div>
        )}

        <textarea value={critiqueText} onChange={e => setCritiqueText(e.target.value)}
          placeholder="What do you want changed? e.g. &quot;Too much internal monologue during the fight scene — cut to the action faster.&quot;"
          rows={4}
          style={{ width: '100%', padding: '8px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical', marginBottom: 8 }} />

        <FieldSurveyButton field="critique" projectId={projectId} chapterNumber={selectedCh}
          critiqueText={critiqueText}
          label="🗣 Critique Chapter (Interactive)" disabled={!selectedCh || !critiqueText.trim()}
          onDone={handleDone} />
      </Panel>

      <Panel>
        <PanelTitle>Posted Criticisms — {rules.length} standing rule{rules.length !== 1 ? 's' : ''}</PanelTitle>
        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 10 }}>
          Every future chapter generation reads these — edit or delete a rule if it no longer applies.
        </div>
        {rules.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)', fontSize: 12 }}>
            No criticisms posted yet. Critique a chapter above to start building standing rules.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {rules.slice().reverse().map(r => (
              <div key={r.id} style={{
                padding: '9px 12px', borderRadius: 'var(--radius-sm)',
                background: editId === r.id ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                border: '1px solid var(--border-soft)',
              }}>
                {editId === r.id ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <select value={EF.tag || 'other'} onChange={e => setEditForm(f => ({ ...f, tag: e.target.value }))}
                      style={{ padding: '4px 8px', fontSize: 11, borderRadius: 4, width: 160 }}>
                      {Object.keys(CRITIQUE_TAG_COLOR).map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
                    </select>
                    <textarea value={EF.rule || ''} onChange={e => setEditForm(f => ({ ...f, rule: e.target.value }))}
                      rows={2} style={{ padding: '4px 8px', fontSize: 11, borderRadius: 4, resize: 'vertical' }} />
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button onClick={commitEdit} disabled={saving} className="btn-primary" style={{ padding: '4px 10px', fontSize: 11 }}>✓ Save</button>
                      <button onClick={() => setEditId(null)} className="btn-ghost" style={{ padding: '4px 10px', fontSize: 11 }}>✕ Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                    <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', flexShrink: 0, marginTop: 2 }}>ch{r.chapter ?? '?'}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2, flexWrap: 'wrap' }}>
                        <span style={{
                          fontSize: 9, padding: '1px 6px', borderRadius: 8,
                          background: `${CRITIQUE_TAG_COLOR[r.tag] || 'var(--text-muted)'}22`,
                          color: CRITIQUE_TAG_COLOR[r.tag] || 'var(--text-muted)', fontWeight: 600,
                        }}>{(r.tag || 'other').replace(/_/g, ' ')}</span>
                      </div>
                      <div style={{ fontSize: 11.5, color: 'var(--text-primary)', fontWeight: 600 }}>{r.rule}</div>
                      {r.critique && (
                        <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 3, fontStyle: 'italic' }}>“{r.critique}”</div>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                      <button onClick={() => startEdit(r)} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                      <button onClick={() => deleteRule(r.id)} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                    </div>
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
