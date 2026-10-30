import { useEffect, useState } from 'react'
import useStore from '../../store/useStore'
import { api } from '../../api'
import { RawPassage } from '../../components/corpus/CorpusMechanics'

// "project_system" deliberately excluded — it's scoped to ONE project
// (novel_id holds the owning project_id, see knowledge_search's docstring),
// so a cross-novel corpus search box has no meaningful way to filter to it
// without leaking one project's private systems data alongside another's.
const SEARCH_CATEGORIES = [
  { id: '', label: 'All' },
  { id: 'reveal', label: 'Reveals' },
  { id: 'scheme', label: 'Schemes' },
  { id: 'symbol', label: 'Symbols' },
  { id: 'glossary', label: 'Techniques/Items' },
  { id: 'dialogue', label: 'Dialogue' },
  { id: 'prose', label: 'Prose' },
  { id: 'pattern', label: 'Narrative Patterns' },
  { id: 'blueprint', label: 'Blueprints' },
  { id: 'humor', label: 'Humor' },
  { id: 'mechanics', label: 'Chapter Mechanics' },
]

export default function CorpusPage() {
  const { registry, loadCorpusStats } = useStore()
  const [selected, setSelected] = useState(null)
  const [patterns, setPatterns] = useState([])
  const [entities, setEntities] = useState([])
  const [panelOpen, setPanelOpen] = useState(false)

  // Semantic search — V4 Phase 4. Cross-novel by design (searches the WHOLE
  // corpus regardless of which novel is selected in the browser below), so
  // results replace the per-novel detail panel rather than living inside it.
  const [searchQuery, setSearchQuery] = useState('')
  const [searchCategory, setSearchCategory] = useState('')
  const [searchNovel, setSearchNovel] = useState('')       // '' = every novel
  const [chFrom, setChFrom] = useState('')                 // source-chapter range, either end optional
  const [chTo, setChTo] = useState('')
  const [rawOpen, setRawOpen] = useState(null)              // {novel, chapter, quote}: the raw passage around a result
  const [searchResults, setSearchResults] = useState(null)   // null = not searched yet; [] = no results
  const [searching, setSearching] = useState(false)
  const [searchErr, setSearchErr] = useState(null)

  const novels = registry?.novels || []
  const selectedNovel = novels.find(n => n.id === selected)

  useEffect(() => {
    if (!registry) loadCorpusStats()
  }, [])

  useEffect(() => {
    if (selected) {
      setPatterns([])
      setEntities([])
      api.patterns(selected).then(setPatterns).catch(() => {})
      api.entities(selected).then(setEntities).catch(() => {})
    }
  }, [selected])

  function pickNovel(id) {
    setSelected(id)
    setPanelOpen(false)
  }

  async function runSearch() {
    if (!searchQuery.trim() || searching) return
    setSearching(true)
    setSearchErr(null)
    try {
      const res = await api.knowledgeSearch(searchQuery.trim(), 24, searchCategory || null,
        { novel_id: searchNovel || null, chapter_from: chFrom, chapter_to: chTo })
      setSearchResults(res.results || [])
    } catch (e) {
      setSearchErr(e.message)
      setSearchResults(null)
    } finally {
      setSearching(false)
    }
  }

  function clearSearch() {
    setSearchQuery('')
    setSearchResults(null)
    setSearchErr(null)
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Mobile novel picker — dropdown bar */}
      <div className="mobile-only" style={{
        padding: '10px 12px', borderBottom: '1px solid var(--border-soft)',
        background: 'var(--bg-surface)', flexShrink: 0,
      }}>
        <button onClick={() => setPanelOpen(o => !o)} style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px', borderRadius: 'var(--radius-sm)',
          background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          fontSize: 12, color: 'var(--text-primary)',
        }}>
          <span>{selectedNovel ? selectedNovel.title : 'Select a novel…'}</span>
          <span style={{ color: 'var(--text-muted)' }}>{panelOpen ? '▲' : '▼'}</span>
        </button>
        {panelOpen && (
          <div style={{
            position: 'absolute', zIndex: 100, left: 12, right: 12, marginTop: 4,
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
          }}>
            {novels.map(n => (
              <button key={n.id} onClick={() => pickNovel(n.id)} style={{
                width: '100%', textAlign: 'left', padding: '10px 14px',
                borderBottom: '1px solid var(--border-soft)', fontSize: 12,
                color: selected === n.id ? 'var(--accent-light)' : 'var(--text-primary)',
                background: selected === n.id ? 'var(--accent-dim)' : 'transparent',
              }}>
                <div style={{ fontWeight: 600 }}>{n.title}</div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{n.chapters_extracted} chapters</div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Semantic search — searches the WHOLE corpus regardless of which
          novel is selected below. Local embeddings (Ollama + nomic-embed-text),
          not keyword matching — "find every symbolic use of fire" works even
          when the word "fire" never appears in the query itself. */}
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid var(--border-soft)',
        background: 'var(--bg-surface)', flexShrink: 0,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') runSearch() }}
            placeholder="Search the corpus by meaning — e.g. 'a betrayal that shocks everyone', 'symbolic use of fire'…"
            style={{ flex: 1, minWidth: 220, padding: '8px 12px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}
          />
          <select value={searchCategory} onChange={e => setSearchCategory(e.target.value)}
            style={{
              padding: '8px 10px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
            }}>
            {SEARCH_CATEGORIES.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <select value={searchNovel} onChange={e => setSearchNovel(e.target.value)} title="Search one novel only"
            style={{
              padding: '8px 10px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)', maxWidth: 200,
              background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
            }}>
            <option value="">All novels</option>
            {novels.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
          <span title="Only results from these source chapters (leave either box empty for an open end)"
            style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
            ch
            <input type="number" min={1} value={chFrom} onChange={e => setChFrom(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') runSearch() }} placeholder="from"
              style={{ width: 64, padding: '8px 6px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
            –
            <input type="number" min={1} value={chTo} onChange={e => setChTo(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') runSearch() }} placeholder="to"
              style={{ width: 64, padding: '8px 6px', fontSize: 11, borderRadius: 'var(--radius-sm)' }} />
          </span>
          <button onClick={runSearch} disabled={searching || !searchQuery.trim()} style={{
            padding: '8px 16px', fontSize: 12, fontWeight: 700, borderRadius: 'var(--radius-sm)',
            background: searchQuery.trim() ? 'var(--accent)' : 'var(--bg-elevated)',
            color: searchQuery.trim() ? '#fff' : 'var(--text-muted)', border: 'none',
            opacity: searching ? 0.6 : 1,
          }}>{searching ? '…' : '🔍 Search'}</button>
          {searchResults !== null && (
            <button onClick={clearSearch} style={{
              padding: '8px 12px', fontSize: 11, fontWeight: 600, borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
            }}>✕ Clear</button>
          )}
        </div>
        {searchErr && <div style={{ fontSize: 11, color: 'var(--red)' }}>{searchErr}</div>}
      </div>

      {/* Main layout */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Desktop novel list */}
        <div className="desktop-only" style={{
          width: 220, flexShrink: 0,
          background: 'var(--bg-surface)', borderRight: '1px solid var(--border)',
          overflowY: 'auto', padding: 10,
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', padding: '4px 6px 8px' }}>
            CORPUS LIBRARY
          </div>
          {novels.length === 0 && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '8px 6px' }}>No novels extracted yet</div>
          )}
          {novels.map(n => (
            <button key={n.id} onClick={() => setSelected(n.id)} style={{
              width: '100%', textAlign: 'left', padding: '8px 10px',
              borderRadius: 'var(--radius-sm)', marginBottom: 2,
              background: selected === n.id ? 'var(--accent-glow)' : 'transparent',
              border: `1px solid ${selected === n.id ? 'var(--accent)' : 'transparent'}`,
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>
                {n.title}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                {n.chapters_extracted} ch extracted{n.highest_chapter_extracted > n.chapters_extracted ? ` · up to ch ${n.highest_chapter_extracted}` : ''}
              </div>
            </button>
          ))}
        </div>

        {/* Detail panel */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {searchResults !== null ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 800 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {searchResults.length === 0
                  ? `No results for "${searchQuery}".`
                  : `${searchResults.length} result(s) for "${searchQuery}" — ranked by semantic similarity, not keyword match.`}
              </div>
              {searchResults.map((r, i) => (
                <div key={i} style={{
                  background: 'var(--bg-surface)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius)', padding: '12px 14px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 10, textTransform: 'uppercase',
                        background: 'var(--accent-dim)', color: 'var(--accent-light)',
                      }}>{r.category}</span>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{r.novel_title}</span>
                      {r.chapter != null && (
                        <button onClick={() => setRawOpen({ novel: r.novel_id, chapter: r.chapter,
                            quote: ['prose', 'dialogue'].includes(r.category) ? r.text : ((r.meta?.quotes || [])[0] || '') })}
                          title="Read the raw chapter around this"
                          style={{ fontSize: 10, color: 'var(--accent-light)', background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}>ch.{r.chapter} ↗</button>
                      )}
                    </div>
                    <span style={{ fontSize: 10, color: 'var(--teal)', fontWeight: 700 }}>{Math.round(r.score * 100)}% match</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    {r.category === 'dialogue' && r.meta?.character && <b style={{ color: 'var(--text-primary)' }}>{r.meta.character}: </b>}
                    {r.text}
                  </div>
                  {r.meta?.thread_type && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>thread_type: {r.meta.thread_type}</div>
                  )}
                  {r.category === 'pattern' && Array.isArray(r.meta?.chapter_range) && r.meta.chapter_range.length > 0 && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                      chapters {r.meta.chapter_range[0]}–{r.meta.chapter_range[r.meta.chapter_range.length - 1]} of {r.novel_title}
                      {r.meta.average_chapter_span != null && ` · avg span ${r.meta.average_chapter_span} ch`}
                    </div>
                  )}
                  {r.category === 'pattern' && r.meta?.gen_guidance && (
                    <div style={{ fontSize: 10.5, color: 'var(--text-secondary)', marginTop: 4, fontStyle: 'italic' }}>
                      {r.meta.gen_guidance}
                    </div>
                  )}
                  {r.category === 'blueprint' && r.meta?.blueprint_id && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>blueprint_id: {r.meta.blueprint_id}</div>
                  )}
                </div>
              ))}
              {rawOpen && <RawPassage {...rawOpen} onClose={() => setRawOpen(null)} />}
            </div>
          ) : !selected ? (
            <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
              Select a novel to explore its Story DNA, or search the corpus above
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 800 }}>

              {/* Patterns */}
              <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 16 }}>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 12 }}>
                  Narrative Patterns ({patterns.length})
                </div>
                {patterns.length === 0
                  ? <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No patterns discovered yet</div>
                  : patterns.map((p, i) => (
                    <div key={i} style={{
                      padding: '10px 12px', marginBottom: 8,
                      background: 'var(--bg-elevated)', borderRadius: 'var(--radius)',
                      border: '1px solid var(--border)',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 600, fontSize: 12, color: 'var(--accent)' }}>
                          {p.pattern_id?.replace(/_/g, ' ') || p.id}
                        </span>
                        <span style={{ fontSize: 11, color: 'var(--teal)', flexShrink: 0 }}>
                          ★ {p.reader_satisfaction_on_payoff || p.satisfaction || '—'}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 16, fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                        <span>Occurrences: <b style={{ color: 'var(--text-primary)' }}>{p.occurrences || p.count || '—'}</b></span>
                        <span>Type: <b style={{ color: 'var(--text-primary)' }}>{p.pattern_type || '—'}</b></span>
                        {Array.isArray(p.chapter_range) && p.chapter_range.length === 2 && (
                          <span>Chapters: <b style={{ color: 'var(--text-primary)' }}>{p.chapter_range[0]}–{p.chapter_range[1]}</b></span>
                        )}
                        {p.average_chapter_span != null && (
                          <span>Avg span: <b style={{ color: 'var(--text-primary)' }}>{p.average_chapter_span} ch</b></span>
                        )}
                      </div>
                      {p.gen_guidance && (
                        <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 6, fontStyle: 'italic' }}>
                          {p.gen_guidance}
                        </div>
                      )}
                    </div>
                  ))
                }
              </div>

              {/* Entities */}
              <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 16 }}>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 12 }}>
                  Entities ({entities.length})
                </div>
                <div className="card-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 8 }}>
                  {entities.slice(0, 30).map((e, i) => (
                    <div key={i} style={{
                      padding: '8px 10px', background: 'var(--bg-elevated)',
                      border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                    }}>
                      <div style={{ fontWeight: 600, fontSize: 12 }}>{e.canonical_name}</div>
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                        {e.type} · {e.role} · {e.appearances} appearances
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
