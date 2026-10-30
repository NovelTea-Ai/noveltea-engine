import { useEffect, useState } from 'react'
import useStore from '../../store/useStore'
import { api } from '../../api'
import VoiceMatchPanel from './VoiceMatchPanel'
import { Spinner } from '../shared/projectUi'

/* ══════════════════════════════════════
   EDITOR TAB
══════════════════════════════════════ */
export function EditorTab({ projectId }) {
  const [chapters, setChapters] = useState([])
  const [selected, setSelected] = useState(null)
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')
  const [error, setError] = useState('')
  const [shortenOpen, setShortenOpen] = useState(false)
  const [shortenTarget, setShortenTarget] = useState('')
  const [shortening, setShortening] = useState(false)
  const [shortenError, setShortenError] = useState('')
  // Voice deviation — compares this chapter against a CHOSEN corpus novel's
  // own voice fingerprint (author picks from the dropdown), reporting which
  // specific signals deviate rather than a single "AI detected" score.
  const { registry, loadCorpusStats } = useStore()
  const [voiceOpen, setVoiceOpen] = useState(false)
  const [voiceMatchOpen, setVoiceMatchOpen] = useState(false)
  const [voiceNovelId, setVoiceNovelId] = useState('')
  const [voiceResult, setVoiceResult] = useState(null)
  const [voiceChecking, setVoiceChecking] = useState(false)
  const [voiceError, setVoiceError] = useState('')
  useEffect(() => { if (!registry) loadCorpusStats() }, [])

  useEffect(() => {
    api.listGenerated(projectId)
      .then(r => {
        setChapters(r.chapters || [])
        if (r.chapters?.length > 0 && !selected) {
          // Restore the chapter that was open before a refresh (F5 / Safari
          // pull-to-refresh on iPhone) — fall back to the first chapter.
          let restore = null
          try { restore = Number(localStorage.getItem(`nm-reader-ch:${projectId}`)) || null } catch {}
          const nums = r.chapters.map(c => c.number)
          loadChapter(restore && nums.includes(restore) ? restore : r.chapters[0].number)
        }
      })
      .catch(() => setChapters([]))
  }, [projectId])

  async function loadChapter(num) {
    setSelected(num)
    try { localStorage.setItem(`nm-reader-ch:${projectId}`, String(num)) } catch {}
    setLoading(true)
    setError('')
    setSavedMsg('')
    try {
      const r = await api.getGenerated(projectId, num)
      setDraft(r.text || '')
    } catch (e) {
      setError(e.message)
      setDraft('')
    } finally {
      setLoading(false)
    }
  }

  async function saveChapter() {
    if (!selected) return
    setSaving(true)
    setSavedMsg('')
    try {
      await api.saveGenerated(projectId, selected, draft)
      setSavedMsg('Saved')
      setTimeout(() => setSavedMsg(''), 2000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const wordCount = draft ? draft.trim().split(/\s+/).filter(Boolean).length : 0

  async function shortenChapter() {
    const target = Number(shortenTarget)
    if (!target || target <= 0) { setShortenError('Enter a target word count.'); return }
    setShortening(true)
    setShortenError('')
    try {
      const r = await api.shortenChapter(projectId, selected, draft, target)
      setDraft(r.text || draft)
      setShortenOpen(false)
      setShortenTarget('')
      setSavedMsg(`Shortened ${r.original_word_count.toLocaleString()} → ${r.word_count.toLocaleString()} words — review, then Save`)
      setTimeout(() => setSavedMsg(''), 5000)
    } catch (e) {
      setShortenError(e.message)
    } finally {
      setShortening(false)
    }
  }

  async function checkVoiceDeviation() {
    if (!selected || !voiceNovelId) { setVoiceError('Pick a corpus novel to compare against.'); return }
    setVoiceChecking(true)
    setVoiceError('')
    setVoiceResult(null)
    try {
      setVoiceResult(await api.voiceDeviation(projectId, selected, voiceNovelId, draft))
    } catch (e) {
      setVoiceError(e.message)
    } finally {
      setVoiceChecking(false)
    }
  }

  const [voiceFixing, setVoiceFixing] = useState(false)
  async function fixVoiceDeviation() {
    if (!voiceResult?.findings?.length) return
    setVoiceFixing(true)
    setVoiceError('')
    try {
      const r = await api.voiceDeviationFix(projectId, selected, draft, voiceResult.findings)
      setDraft(r.text || draft)
      setVoiceResult(null)   // stale now that the text changed — re-run Check to see the new state
      setSavedMsg(`Voice-fixed ${r.original_word_count.toLocaleString()} → ${r.word_count.toLocaleString()} words — review, then Save`)
      setTimeout(() => setSavedMsg(''), 5000)
    } catch (e) {
      setVoiceError(e.message)
    } finally {
      setVoiceFixing(false)
    }
  }

  const [pickerOpen, setPickerOpen] = useState(false)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Mobile chapter picker */}
      <div className="mobile-only" style={{
        padding: '8px 12px', borderBottom: '1px solid var(--border-soft)',
        background: 'var(--bg-surface)', flexShrink: 0, position: 'relative',
      }}>
        <button onClick={() => setPickerOpen(o => !o)} style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px', borderRadius: 'var(--radius-sm)',
          background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          fontSize: 12, color: 'var(--text-primary)',
        }}>
          <span>{selected ? `Chapter ${selected}` : 'Select a chapter…'}</span>
          <span style={{ color: 'var(--text-muted)' }}>{pickerOpen ? '▲' : '▼'}</span>
        </button>
        {pickerOpen && (
          <div style={{
            position: 'absolute', zIndex: 100, left: 12, right: 12, top: '100%', marginTop: 2,
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
          }}>
            {chapters.map(ch => (
              <button key={ch.number} onClick={() => { loadChapter(ch.number); setPickerOpen(false) }} style={{
                width: '100%', textAlign: 'left', padding: '10px 14px',
                borderBottom: '1px solid var(--border-soft)', fontSize: 12,
                color: selected === ch.number ? 'var(--accent-light)' : 'var(--text-primary)',
                background: selected === ch.number ? 'var(--accent-dim)' : 'transparent',
              }}>Chapter {ch.number}</button>
            ))}
          </div>
        )}
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Desktop chapter list */}
        <div className="desktop-only" style={{
          width: 180, flexShrink: 0, borderRight: '1px solid var(--border-soft)',
          overflowY: 'auto', padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 4,
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '0 8px 8px' }}>
            Chapters
          </div>
          {chapters.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '8px', fontStyle: 'italic' }}>No chapters yet.</div>
          )}
          {chapters.map(ch => (
            <button key={ch.number} onClick={() => loadChapter(ch.number)} style={{
              textAlign: 'left', padding: '7px 10px', borderRadius: 'var(--radius-sm)',
              background: selected === ch.number ? 'var(--accent-dim)' : 'transparent',
              color: selected === ch.number ? 'var(--accent-light)' : 'var(--text-secondary)',
              border: selected === ch.number ? '1px solid var(--accent)' : '1px solid transparent',
              fontSize: 11, fontWeight: selected === ch.number ? 600 : 400,
            }}>Chapter {ch.number}</button>
          ))}
        </div>

        {/* editor pane */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{
            padding: '8px 12px', borderBottom: '1px solid var(--border-soft)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0, flexWrap: 'wrap', gap: 6,
          }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {selected ? `Chapter ${selected} — ${wordCount.toLocaleString()} words` : 'Select a chapter'}
            </span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {savedMsg && <span style={{ fontSize: 11, color: 'var(--green)' }}>{savedMsg}</span>}
              {error && <span style={{ fontSize: 11, color: 'var(--red)' }}>{error}</span>}
              <button onClick={() => { setShortenOpen(o => !o); setShortenError('') }}
                disabled={!selected || !draft} title="Condense this chapter to a target length, keeping the content"
                style={{
                  fontSize: 11, padding: '5px 12px', fontWeight: 600,
                  background: shortenOpen ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: `1px solid ${shortenOpen ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius-sm)',
                  color: shortenOpen ? 'var(--accent-light)' : 'var(--text-secondary)',
                  opacity: !selected || !draft ? 0.5 : 1,
                }}>
                ✂ Shorten
              </button>
              <button onClick={() => { setVoiceOpen(o => !o); setVoiceError('') }}
                disabled={!selected || !draft} title="Compare this chapter's voice against a chosen corpus novel's own — flags which specific signals deviate, not a single AI score"
                style={{
                  fontSize: 11, padding: '5px 12px', fontWeight: 600,
                  background: voiceOpen ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: `1px solid ${voiceOpen ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius-sm)',
                  color: voiceOpen ? 'var(--accent-light)' : 'var(--text-secondary)',
                  opacity: !selected || !draft ? 0.5 : 1,
                }}>
                🎯 Voice Check
              </button>
              <button onClick={() => setVoiceMatchOpen(o => !o)}
                disabled={!selected || !draft} title="How closely this chapter matches your corpus voice — every Author DNA style target, measured on the current draft (free, no AI call)"
                style={{
                  fontSize: 11, padding: '5px 12px', fontWeight: 600,
                  background: voiceMatchOpen ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                  border: `1px solid ${voiceMatchOpen ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 'var(--radius-sm)',
                  color: voiceMatchOpen ? 'var(--accent-light)' : 'var(--text-secondary)',
                  opacity: !selected || !draft ? 0.5 : 1,
                }}>
                🎼 Voice Match
              </button>
              <button onClick={saveChapter} disabled={saving || !selected} style={{
                fontSize: 11, padding: '5px 16px', fontWeight: 600,
                background: 'var(--accent)', color: '#fff',
                border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
                opacity: saving || !selected ? 0.5 : 1,
              }}>
                {saving ? <Spinner /> : '💾 Save'}
              </button>
            </div>
          </div>
          {shortenOpen && (
            <div style={{
              padding: '8px 12px', borderBottom: '1px solid var(--border-soft)',
              display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', flexShrink: 0,
              background: 'var(--bg-elevated)',
            }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Target words:</span>
              <input type="number" value={shortenTarget} onChange={e => setShortenTarget(e.target.value)}
                placeholder={`e.g. ${Math.max(50, Math.round(wordCount * 0.6))}`}
                disabled={shortening}
                style={{
                  width: 90, fontSize: 11, padding: '4px 8px',
                  background: 'var(--bg-surface)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
                }} />
              <button onClick={shortenChapter} disabled={shortening} style={{
                fontSize: 11, padding: '4px 12px', fontWeight: 600,
                background: 'var(--accent)', color: '#fff',
                border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
                opacity: shortening ? 0.6 : 1,
              }}>
                {shortening ? <Spinner size={11} /> : 'Go'}
              </button>
              <button onClick={() => { setShortenOpen(false); setShortenError('') }} disabled={shortening} style={{
                fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)',
              }}>Cancel</button>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                Condenses the draft, keeping plot/dialogue — result replaces the text below; Save to keep it.
              </span>
              {shortenError && <span style={{ fontSize: 11, color: 'var(--red)' }}>{shortenError}</span>}
            </div>
          )}
          {voiceMatchOpen && selected && (
            <VoiceMatchPanel projectId={projectId} chapterNumber={selected} draft={draft} />
          )}
          {voiceOpen && (
            <div style={{
              padding: '10px 12px', borderBottom: '1px solid var(--border-soft)',
              flexShrink: 0, background: 'var(--bg-elevated)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Compare against:</span>
                <select value={voiceNovelId} onChange={e => setVoiceNovelId(e.target.value)} disabled={voiceChecking}
                  style={{
                    fontSize: 11, padding: '4px 8px', minWidth: 200,
                    background: 'var(--bg-surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
                  }}>
                  <option value="">— pick a corpus novel —</option>
                  {(registry?.novels || []).map(n => (
                    <option key={n.id} value={n.id}>{n.title || n.id}</option>
                  ))}
                </select>
                <button onClick={checkVoiceDeviation} disabled={voiceChecking || !voiceNovelId} style={{
                  fontSize: 11, padding: '4px 12px', fontWeight: 600,
                  background: 'var(--accent)', color: '#fff',
                  border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
                  opacity: voiceChecking || !voiceNovelId ? 0.6 : 1,
                }}>
                  {voiceChecking ? <Spinner size={11} /> : 'Check'}
                </button>
                <button onClick={() => { setVoiceOpen(false); setVoiceError(''); setVoiceResult(null) }} disabled={voiceChecking} style={{
                  fontSize: 11, padding: '4px 10px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)',
                }}>Close</button>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
                Not an "AI detector" — compares this chapter's measurable writing patterns (sentence/paragraph
                uniformity, punctuation rates, repeated constructions, vocabulary repetition) against the chosen
                novel's own opening chapters, and reports which SPECIFIC signals deviate and by how much.
              </div>
              {voiceError && <div style={{ fontSize: 11, color: 'var(--red)', marginBottom: 8 }}>{voiceError}</div>}
              {voiceResult && (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                      {voiceResult.signals_deviated === 0
                        ? `✓ No signals deviate meaningfully from ${voiceResult.novel_id}'s own voice (${voiceResult.baseline_chapters_sampled} chapters sampled).`
                        : `${voiceResult.signals_deviated} of ${voiceResult.signals_checked} signals deviate from ${voiceResult.novel_id}'s own voice (${voiceResult.baseline_chapters_sampled} chapters sampled):`}
                    </div>
                    {voiceResult.signals_deviated > 0 && (
                      <button onClick={fixVoiceDeviation} disabled={voiceFixing}
                        title="Rewrite ONLY these flagged signals (sentence variation, punctuation, repeated constructions) — content, plot and dialogue meaning stay unchanged"
                        style={{
                          fontSize: 10.5, padding: '4px 12px', fontWeight: 600, flexShrink: 0,
                          background: 'var(--accent)', color: '#fff',
                          border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
                          opacity: voiceFixing ? 0.6 : 1, display: 'flex', alignItems: 'center', gap: 4,
                        }}>
                        {voiceFixing ? <Spinner size={10} /> : '🔧'} Fix these {voiceResult.signals_deviated} signal{voiceResult.signals_deviated !== 1 ? 's' : ''}
                      </button>
                    )}
                  </div>
                  {voiceResult.findings.map((f, i) => (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0',
                      borderTop: i ? '1px solid var(--border-soft)' : 'none', fontSize: 11,
                    }}>
                      <span style={{
                        fontSize: 8.5, fontWeight: 700, padding: '2px 6px', borderRadius: 8, textTransform: 'uppercase', flexShrink: 0,
                        background: f.strength === 'High' ? 'rgba(239,68,68,0.15)' : f.strength === 'Medium' ? 'rgba(245,158,11,0.15)' : 'var(--bg-surface)',
                        color: f.strength === 'High' ? 'var(--red)' : f.strength === 'Medium' ? 'var(--amber)' : 'var(--text-muted)',
                      }}>{f.strength}</span>
                      <span style={{ flex: 1, color: 'var(--text-primary)' }}>{f.signal}</span>
                      <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>
                        {f.ratio != null ? `${f.ratio}× baseline` : 'absent in baseline'}
                        {' '}({f.chapter_value} vs {f.baseline_value})
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {loading ? (
            <div style={{ padding: 24, color: 'var(--text-muted)' }}>Loading…</div>
          ) : (
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              placeholder="Chapter text will appear here after generation…"
              style={{
                flex: 1, resize: 'none', padding: '20px 16px',
                fontSize: 14, lineHeight: 1.8,
                fontFamily: 'Georgia, "Times New Roman", serif',
                background: 'var(--bg-surface)', color: 'var(--text-primary)',
                border: 'none', outline: 'none', overflowY: 'auto',
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
