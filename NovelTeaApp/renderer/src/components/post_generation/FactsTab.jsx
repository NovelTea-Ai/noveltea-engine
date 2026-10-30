import { useEffect, useState } from 'react'
import { api } from '../../api'
import { Panel, PanelTitle, Spinner } from '../shared/projectUi'

/* ══════════════════════════════════════
   FACTS TAB
   A durable ledger of atomic statements the author has made in the written
   chapters — power levels, relationships, promises, injuries, possessions,
   secrets, locations. Grepped by every chapter-generation and dialogue-
   shaping prompt so a contradiction 200 chapters later gets caught before
   it's written, not after.
══════════════════════════════════════ */
export const FACT_CATEGORY_COLOR = {
  power_level: '#f59e0b', relationship: '#ec4899', promise: '#8b5cf6',
  injury: '#ef4444', secret: '#06b6d4', possession: '#10b981',
  location: '#3b82f6', timeline: '#a855f7', physical_trait: '#f97316', other: 'var(--text-muted)',
}

export function FactsTab({ project, projectId, afterGenerate, onSave }) {
  const [facts, setFacts] = useState(project.facts_log || [])
  const [contras, setContras] = useState(project.facts_contradictions || [])
  const [extracting, setExtracting] = useState(false)
  const [result, setResult] = useState(null)
  const [filterCat, setFilterCat] = useState('')
  const [filterChar, setFilterChar] = useState('')
  const [search, setSearch] = useState('')
  const [editId, setEditId] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [fixingId, setFixingId] = useState(null)
  const [reviewing, setReviewing] = useState(false)
  const [reviewMsg, setReviewMsg] = useState('')

  useEffect(() => {
    setFacts(project.facts_log || [])
    setContras(project.facts_contradictions || [])
  }, [project.id])

  async function runReview() {
    setReviewing(true)
    setReviewMsg('')
    try {
      const r = await api.continuityReview(projectId)
      if (r.fact_contradictions?.length) setContras(c => [...c, ...r.fact_contradictions])
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
      const r = await api.factsExtract(projectId, full)
      setResult(r)
      if (r.total > 0) {
        setFacts(f => [...f, ...(r.added || [])])
      }
      if (r.contradictions?.length) {
        setContras(c => [...c, ...r.contradictions])
      }
    } catch (e) {
      setResult({ total: 0, added: [], contradictions: [], error: e.message })
      alert(`Facts extraction failed: ${e.message}`)
    } finally {
      setExtracting(false)
    }
  }

  async function fixContradiction(id) {
    setFixingId(id)
    try {
      const r = await api.factsFix(projectId, id)
      setContras(cs => cs.map(c => c.id === id ? { ...c, status: r.resolved ? 'resolved' : 'fix_attempted', resolution: r.summary } : c))
      afterGenerate && afterGenerate({ field: 'facts_log', provider: 'facts-fix' })
      if (r.growth_warning?.length) {
        alert(`Fix applied, but chapter length grew more than expected:\n${r.growth_warning.join('\n')}`)
      }
    } catch (e) {
      alert(`Fix failed: ${e.message}`)
    } finally {
      setFixingId(null)
    }
  }

  async function saveFacts(updated) {
    setSaving(true)
    setFacts(updated)
    try { await api.factsUpdate(projectId, updated) }
    finally { setSaving(false) }
  }

  function startEdit(f) { setEditId(f.id); setEditForm({ ...f }) }
  async function commitEdit() {
    const updated = facts.map(f => f.id === editId ? { ...editForm } : f)
    setEditId(null); setEditForm(null)
    await saveFacts(updated)
  }
  async function deleteFact(id) {
    await saveFacts(facts.filter(f => f.id !== id))
  }

  const allChars = [...new Set(facts.flatMap(f => f.characters || []))].sort()
  const filtered = facts
    .filter(f => !filterCat || f.category === filterCat)
    .filter(f => !filterChar || (f.characters || []).includes(filterChar))
    .filter(f => !search || `${f.subject} ${f.statement}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (b.chapter || 0) - (a.chapter || 0))

  const EF = editForm || {}

  // No longer a full-tab layout with its own scroll wrapper — Facts is now
  // rendered as a section INSIDE RevisionTab's single scrolling container
  // (see the author's "merge Facts under Revision, no need for its own tab"
  // request). Returns a Fragment of Panels instead of the old outer
  // flex/overflow div, so it just stacks naturally under Revision's own
  // Panels without a nested scroll region or duplicated padding.
  return (
    <>
        {/* ── Facts ── */}
        <div style={{
          fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase',
          letterSpacing: '0.08em', margin: '20px 0 10px', paddingTop: 12, borderTop: '1px solid var(--border-soft)',
        }}>Facts</div>
        <Panel style={{ marginBottom: 12 }}>
          <PanelTitle action={
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <button onClick={() => runExtract(false)} disabled={extracting} style={{
                fontSize: 11, padding: '5px 12px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                background: extracting ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#f59e0b,#ef4444)',
                color: extracting ? 'var(--text-muted)' : '#fff', border: 'none',
                display: 'flex', alignItems: 'center', gap: 5,
              }}>{extracting ? <Spinner size={11} /> : '📋'} Extract Facts</button>
              <button onClick={() => runExtract(true)} disabled={extracting} style={{
                fontSize: 10, padding: '4px 8px', background: 'transparent', border: 'none',
                color: 'var(--text-muted)', textDecoration: 'underline', cursor: 'pointer',
              }}>re-scan all chapters</button>
              <button onClick={runReview} disabled={reviewing} title="Actively re-reads every written chapter against the full ledger, hunting for contradictions — not just checking newly-scanned chapters" style={{
                fontSize: 11, padding: '5px 12px', fontWeight: 700, borderRadius: 'var(--radius-sm)',
                background: reviewing ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#8b5cf6,#6366f1)',
                color: reviewing ? 'var(--text-muted)' : '#fff', border: 'none',
                display: 'flex', alignItems: 'center', gap: 5,
              }}>{reviewing ? <Spinner size={11} /> : '🔍'} Review for Contradictions</button>
            </div>
          }>Facts Ledger — {facts.length} established fact{facts.length !== 1 ? 's' : ''}</PanelTitle>
          <div style={{ fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Every generated or dialogue-shaped chapter checks this ledger before writing, so a claim made in chapter 3
            (a spirit root's vein count, a debt owed, an injury, a secret) can't get silently contradicted 200 chapters later.
            Extraction is incremental — only chapters not yet scanned (or edited since) are read. <b>Review for Contradictions</b>
            is different: it re-reads the WHOLE story against the whole ledger (facts + map together) hunting for anything
            that doesn't add up, including drift between already-scanned chapters that extraction alone wouldn't catch.
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
                  <span style={{ color: 'var(--green)' }}>✓ Extracted {result.total} new facts</span>
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
                    <b style={{ color: 'var(--text-primary)' }}>{c.subject}</b> <span style={{ color: 'var(--text-muted)' }}>({c.category})</span>
                    <div style={{ marginTop: 3 }}>ch{c.existing.chapter}: "{c.existing.statement}"</div>
                    <div>ch{c.new.chapter}: "{c.new.statement}"</div>
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

        <Panel>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <input placeholder="Search facts…" value={search} onChange={e => setSearch(e.target.value)}
              style={{ flex: 1, minWidth: 160, padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
            <select value={filterCat} onChange={e => setFilterCat(e.target.value)}
              style={{ padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
              <option value="">All categories</option>
              {Object.keys(FACT_CATEGORY_COLOR).map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
            </select>
            {allChars.length > 0 && (
              <select value={filterChar} onChange={e => setFilterChar(e.target.value)}
                style={{ padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
                <option value="">All characters</option>
                {allChars.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            )}
          </div>

          {filtered.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)', fontSize: 12 }}>
              {facts.length === 0 ? 'No facts extracted yet. Write some chapters, then click Extract Facts.' : 'No facts match this filter.'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {filtered.map(f => (
                <div key={f.id} style={{
                  padding: '9px 12px', borderRadius: 'var(--radius-sm)',
                  background: editId === f.id ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: '1px solid var(--border-soft)',
                }}>
                  {editId === f.id ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <input value={EF.subject || ''} onChange={e => setEditForm(f => ({ ...f, subject: e.target.value }))}
                          placeholder="Subject" style={{ flex: 1, padding: '4px 8px', fontSize: 11, borderRadius: 4 }} />
                        <select value={EF.category || 'other'} onChange={e => setEditForm(f => ({ ...f, category: e.target.value }))}
                          style={{ padding: '4px 8px', fontSize: 11, borderRadius: 4 }}>
                          {Object.keys(FACT_CATEGORY_COLOR).map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                        <input type="number" value={EF.chapter || ''} onChange={e => setEditForm(f => ({ ...f, chapter: Number(e.target.value) }))}
                          placeholder="Ch#" style={{ width: 60, padding: '4px 8px', fontSize: 11, borderRadius: 4 }} />
                      </div>
                      <textarea value={EF.statement || ''} onChange={e => setEditForm(f => ({ ...f, statement: e.target.value }))}
                        rows={2} style={{ padding: '4px 8px', fontSize: 11, borderRadius: 4, resize: 'vertical' }} />
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button onClick={commitEdit} disabled={saving} className="btn-primary" style={{ padding: '4px 10px', fontSize: 11 }}>✓ Save</button>
                        <button onClick={() => setEditId(null)} className="btn-ghost" style={{ padding: '4px 10px', fontSize: 11 }}>✕ Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', flexShrink: 0, marginTop: 2 }}>ch{f.chapter ?? '?'}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2, flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-primary)' }}>{f.subject}</span>
                          <span style={{
                            fontSize: 9, padding: '1px 6px', borderRadius: 8,
                            background: `${FACT_CATEGORY_COLOR[f.category] || 'var(--text-muted)'}22`,
                            color: FACT_CATEGORY_COLOR[f.category] || 'var(--text-muted)', fontWeight: 600,
                          }}>{(f.category || 'other').replace(/_/g, ' ')}</span>
                        </div>
                        <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>{f.statement}</div>
                      </div>
                      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                        <button onClick={() => startEdit(f)} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>✎</button>
                        <button onClick={() => deleteFact(f.id)} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>
    </>
  )
}
