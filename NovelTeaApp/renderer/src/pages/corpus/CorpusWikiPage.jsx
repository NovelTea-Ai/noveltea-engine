import { useEffect, useState } from 'react'
import { api } from '../../api'

/* Corpus Wiki — step 1: pick a novel. Step 2: upload a saved wiki HTML page,
   parse every <a href> in its body client-side (DOMParser — no backend
   round-trip needed for this), and list them as clickable link cards below
   the upload button. Clicking a link opens it (new tab) AND opens a popup
   with a textarea — paste that page's content, tag it with a category, Save
   writes it to wiki/{novel_id}/{category}/{link_name}.txt (or temp/ when
   untagged) so it's associated with that link by name AND pre-sorted for
   later allocation. Deliberately minimal — nothing else yet. */

// Real bug, confirmed live: this page's upload step was parsing EVERY
// <a href> in the uploaded HTML with zero filtering — a real AllPages
// export showed 482 raw links, most of them Fandom's own platform chrome
// (Twitter/YouTube/Instagram/LinkedIn, app store badges, "What is Fandom?",
// "Careers", "Terms of Use", footer sitemap links), not wiki content. Fixed
// here rather than assumed fixed — filters wiki housekeeping namespaces
// (Special:/Category:/etc.) and known Fandom platform/social/footer URLs,
// leaving real article links untouched.
const _WIKI_SKIP_PREFIXES = [
  'Special:', 'File:', 'Category:', 'Template:', 'Help:', 'Talk:',
  'User:', 'User_talk:', 'Forum:', 'Board:', 'Thread:', 'MediaWiki:',
]
const _CHROME_HOST_SUFFIXES = [
  'twitter.com', 'x.com', 'youtube.com', 'instagram.com', 'linkedin.com',
  'facebook.com', 'tiktok.com', 'apps.apple.com', 'play.google.com',
  'fandom.com/what-is-fandom', 'wikia.org',
]
const _CHROME_LINK_TEXT = new Set([
  'what is fandom?', 'essentials', 'about', 'careers', 'press', 'contact',
  'terms of use', 'privacy policy', 'digital services act', 'global sitemap',
  'local sitemap', 'support', 'help', 'accessibility statement', 'media kit',
  'fandom apps', 'explore properties', 'advertise', 'manage preferences',
  'community central', 'do not sell or share my personal information',
])

function _isChromeLink(href, text) {
  const path = href.replace(/^\/wiki\//, '')
  if (_WIKI_SKIP_PREFIXES.some(p => path.startsWith(p))) return true
  const lowerHref = href.toLowerCase()
  if (_CHROME_HOST_SUFFIXES.some(h => lowerHref.includes(h))) return true
  if (_CHROME_LINK_TEXT.has((text || '').trim().toLowerCase())) return true
  return false
}

// Same category set the project's own Systems tab already uses
// (ProjectView.jsx SystemsTab field list) — reusing it here so a tag picked
// during scraping lines up with where the content would actually go later,
// not a parallel taxonomy that needs remapping.
const TAG_OPTIONS = [
  { value: '', label: '— Untagged —' },
  { value: 'characters', label: 'Character' },
  { value: 'power_levels', label: 'Power Levels' },
  { value: 'techniques', label: 'Techniques' },
  { value: 'weapons', label: 'Weapons' },
  { value: 'alchemy', label: 'Alchemy' },
  { value: 'arrays', label: 'Arrays' },
  { value: 'artifact_forging', label: 'Artifact Forging' },
  { value: 'sacred_grounds', label: 'Sacred Grounds' },
  { value: 'races', label: 'Races & Species' },
  { value: 'factions', label: 'Factions & Powers' },
  { value: 'wars', label: 'Wars & Conflicts' },
]

function useIsMobile() {
  const [m, setM] = useState(typeof window !== 'undefined' && window.innerWidth < 640)
  useEffect(() => {
    const on = () => setM(window.innerWidth < 640)
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return m
}

function SavePopup({ novelId, link, onClose, onSaved }) {
  const isMobile = useIsMobile()
  const [content, setContent] = useState('')
  const [tag, setTag] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  // Once a save succeeds, the button greys out and stays that way — editing
  // the text re-enables it (a real change to save), matching "if it's saved
  // grey out that button" without permanently locking the popup.
  const [justSaved, setJustSaved] = useState(false)

  async function handleSave() {
    if (!content.trim()) { setError('Nothing to save — paste the page content first.'); return }
    setSaving(true); setError('')
    try {
      const r = await api.corpusWikiSaveLinkContent(novelId, link.text, content, tag, link.href)
      onSaved(link.href, r.path)
      setJustSaved(true)
      // Popup stays open, textarea stays filled — only the button state changes.
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setSaving(false)
    }
  }

  function handleContentChange(e) {
    setContent(e.target.value)
    if (justSaved) setJustSaved(false)
  }

  function handleTagChange(e) {
    setTag(e.target.value)
    if (justSaved) setJustSaved(false)
  }

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000,
      display: 'flex', alignItems: isMobile ? 'stretch' : 'center', justifyContent: 'center',
      padding: isMobile ? 0 : 20,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: '100%', maxWidth: isMobile ? '100%' : 720,
        height: isMobile ? '100%' : 'auto', maxHeight: isMobile ? '100%' : '85vh',
        display: 'flex', flexDirection: 'column',
        background: 'var(--bg-panel)', border: isMobile ? 'none' : '1px solid var(--border-soft)',
        borderRadius: isMobile ? 0 : 'var(--radius-lg)', overflow: 'hidden',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: isMobile ? '14px 14px' : '12px 16px', borderBottom: '1px solid var(--border-soft)',
          flexShrink: 0 }}>
          <div style={{ fontSize: isMobile ? 15 : 14, fontWeight: 700, overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 10 }}>
            Paste content for: {link.text}
          </div>
          <button onClick={onClose} style={{
            background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 20,
            cursor: 'pointer', flexShrink: 0, padding: 4,
          }}>✕</button>
        </div>

        {error && (
          <div style={{ margin: '10px 14px 0', padding: '8px 12px', borderRadius: 8, background: '#3a1616',
            color: '#f87171', fontSize: 12, flexShrink: 0 }}>{error}</div>
        )}

        <div style={{ padding: isMobile ? '12px 14px 0' : '16px 16px 0', flexShrink: 0 }}>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 4 }}>
            Tag (for later allocation)
          </label>
          <select value={tag} onChange={handleTagChange} style={{
            width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border-soft)',
            background: 'var(--bg-panel-2, rgba(255,255,255,0.03))', color: 'var(--text)', fontSize: 13,
            boxSizing: 'border-box',
          }}>
            {TAG_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>

        <textarea
          value={content}
          onChange={handleContentChange}
          placeholder="Paste the page's content here…"
          autoFocus={!isMobile}
          style={{
            flex: 1, minHeight: isMobile ? 200 : 320, margin: isMobile ? '12px 14px' : 16,
            padding: 12, borderRadius: 8,
            border: '1px solid var(--border-soft)', background: 'var(--bg-panel-2, rgba(255,255,255,0.03))',
            color: 'var(--text)', fontSize: isMobile ? 16 : 13, fontFamily: 'monospace',
            resize: isMobile ? 'none' : 'vertical', boxSizing: 'border-box',
          }}
        />

        <div style={{ display: 'flex', gap: 8, padding: isMobile ? '12px 14px' : '12px 16px',
          borderTop: '1px solid var(--border-soft)', flexShrink: 0 }}>
          <button onClick={handleSave} disabled={saving || justSaved} style={{
            flex: isMobile ? 1 : 'initial',
            padding: '10px 16px', fontSize: 14, fontWeight: 700, borderRadius: 8, border: 'none',
            background: (saving || justSaved) ? 'var(--bg-panel-2, rgba(255,255,255,0.08))' : 'var(--accent, #4f8cff)',
            color: (saving || justSaved) ? 'var(--text-muted)' : '#fff',
            cursor: (saving || justSaved) ? 'default' : 'pointer',
          }}>{saving ? 'Saving…' : justSaved ? '✓ Saved' : '💾 Save'}</button>
          <button onClick={onClose} style={{
            flex: isMobile ? 1 : 'initial',
            padding: '10px 16px', fontSize: 14, fontWeight: 700, borderRadius: 8,
            border: '1px solid var(--border-soft)', background: 'transparent', color: 'var(--text)', cursor: 'pointer',
          }}>Close</button>
        </div>
      </div>
    </div>
  )
}

export default function CorpusWikiPage() {
  const [novels, setNovels] = useState([])
  const [novelId, setNovelId] = useState('')
  const [loadingNovels, setLoadingNovels] = useState(true)
  const [error, setError] = useState('')

  const [fileName, setFileName] = useState('')
  const [links, setLinks] = useState([]) // [{href, text}]
  // "Done" tracking — a link turns red once it's been saved, either this
  // session (added locally right after a save) or in a PRIOR session
  // (loaded from disk via /saved-urls, keyed by each file's own Source:
  // header) — so already-saved links show red immediately on load, not
  // just after being clicked again.
  const [clicked, setClicked] = useState(() => new Set())
  const [popupLink, setPopupLink] = useState(null) // {href, text} | null — drives SavePopup

  useEffect(() => {
    api.registry().then(r => {
      const list = r.novels || []
      setNovels(list)
      if (list.length > 0) setNovelId(list[0].id)
    }).catch(e => setError(String(e.message || e)))
      .finally(() => setLoadingNovels(false))
  }, [])

  // Re-load which URLs are already saved whenever the novel changes — the
  // saved set is per-novel, so switching novels must refresh it rather than
  // carrying over the previous novel's red marks.
  useEffect(() => {
    if (!novelId) return
    api.corpusWikiSavedUrls(novelId)
      .then(r => setClicked(new Set(r.urls || [])))
      .catch(() => {}) // best-effort — a failed load just means nothing shows red yet, not a hard error
  }, [novelId])

  function handleFile(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file later
    if (!file) return
    setError('')
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const html = String(reader.result || '')
        const doc = new DOMParser().parseFromString(html, 'text/html')
        // Real bug, confirmed live: a saved wiki page's links are almost
        // always RELATIVE ("/wiki/Page_Name") — fine on the real wiki, but
        // once rendered inside THIS app's own page, the browser resolves
        // them against THIS app's own origin (http://<this-pc>:7432/wiki/...)
        // instead of the source wiki, so clicking one 404s here instead of
        // opening the real article. Recover the real absolute base from the
        // saved page's own metadata — confirmed present on a real Fandom
        // export: <meta name="twitter:url" content="https://<wiki>.fandom.com/...">
        // is the page's own canonical URL. <base href> and <link
        // rel="canonical"> are checked too (standard, just not present on
        // this particular export) since either is equally reliable when a
        // saved page does carry one.
        const baseHref =
          doc.querySelector('base[href]')?.getAttribute('href') ||
          doc.querySelector('link[rel="canonical"]')?.getAttribute('href') ||
          doc.querySelector('meta[property="og:url"]')?.getAttribute('content') ||
          doc.querySelector('meta[name="twitter:url"]')?.getAttribute('content') ||
          null
        // Real bug, confirmed live: searching the WHOLE document body picks
        // up Fandom's global header/footer/nav chrome along with the actual
        // page content — a real AllPages export had its real link list
        // inside a specific container (mw-allpages-body), but the header
        // nav, sidebar, and footer live in the SAME document and were never
        // excluded. Scope to the real content container when the page has
        // one (AllPages, a Category page, or a normal article all expose
        // one of these), falling back to the full body only if none exist.
        const container =
          doc.querySelector('.mw-allpages-body') ||
          doc.querySelector('.mw-parser-output') ||
          doc.querySelector('#mw-content-text') ||
          doc.body
        const anchors = Array.from(container ? container.querySelectorAll('a[href]') : [])
        const seen = new Set()
        const found = []
        for (const a of anchors) {
          const raw = a.getAttribute('href')
          if (!raw) continue
          // Resolve against the RECOVERED source base, never against
          // window.location (this app's own origin) — the whole point is
          // the original href, not wherever the app happens to be running.
          let href = raw
          if (baseHref && !/^https?:\/\//i.test(raw) && !raw.startsWith('#')) {
            try { href = new URL(raw, baseHref).href } catch { /* keep raw if it's not resolvable */ }
          }
          if (seen.has(href)) continue
          const text = a.textContent.trim() || href
          if (_isChromeLink(href, text)) continue
          seen.add(href)
          found.push({ href, text })
        }
        if (!baseHref && found.some(l => !/^https?:\/\//i.test(l.href))) {
          setError('Could not find this page\'s source URL in its metadata — links stayed relative and may not open correctly. Try re-saving the page (Ctrl+S) from the browser.')
        }
        setFileName(file.name)
        setLinks(found)
      } catch (err) {
        setError(`Could not parse this file: ${String(err.message || err)}`)
      }
    }
    reader.onerror = () => setError('Could not read this file.')
    reader.readAsText(file)
  }

  function handleLinkClick(l) {
    // Real link navigation (target="_blank") already opens the page — this
    // just also opens the save popup for it.
    setPopupLink(l)
  }

  function handleSaved(href) {
    setClicked(prev => new Set(prev).add(href))
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
      <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 4 }}>⟐ Corpus Wiki</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 20 }}>
        Pick a novel, upload a saved wiki page, get its links.
      </div>

      {error && (
        <div style={{ padding: '10px 14px', borderRadius: 8, background: '#3a1616', color: '#f87171',
          fontSize: 12, marginBottom: 16 }}>{error}</div>
      )}

      {/* Step 1 — novel dropdown */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ display: 'block', fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Novel</label>
        <select value={novelId} onChange={e => setNovelId(e.target.value)} disabled={loadingNovels} style={{
          width: '100%', maxWidth: 420, padding: '8px 12px', borderRadius: 8,
          border: '1px solid var(--border-soft)', background: 'var(--bg-panel)',
          color: 'var(--text)', fontSize: 13,
        }}>
          {loadingNovels && <option>Loading…</option>}
          {!loadingNovels && novels.length === 0 && <option value="">(no novels found)</option>}
          {novels.map(n => (
            <option key={n.id} value={n.id}>{n.title || n.id}</option>
          ))}
        </select>
      </div>

      {/* Step 2 — upload + parsed links */}
      <div style={{ marginBottom: 12 }}>
        <label style={{ display: 'block', fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Upload wiki page (.htm/.html)</label>
        <label style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer',
          fontSize: 13, fontWeight: 700, padding: '8px 16px',
          borderRadius: 8, border: '1px solid var(--border-soft)', color: 'var(--text)',
        }}>
          📁 {fileName ? `Loaded: ${fileName}` : 'Choose file…'}
          <input type="file" accept=".htm,.html,text/html" onChange={handleFile} style={{ display: 'none' }} />
        </label>
      </div>

      {links.length > 0 && (
        <div style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', fontSize: 12, fontWeight: 700,
            background: 'var(--bg-panel-2, rgba(255,255,255,0.03))', borderBottom: '1px solid var(--border-soft)' }}>
            {links.length} link{links.length === 1 ? '' : 's'} found
          </div>
          <div style={{ padding: 14, display: 'flex', flexWrap: 'wrap', gap: 8, maxHeight: 480, overflowY: 'auto' }}>
            {links.map((l, i) => {
              const isDone = clicked.has(l.href)
              return (
                <a key={`${l.href}-${i}`} href={l.href} target="_blank" rel="noopener noreferrer" title={l.href}
                  onClick={() => handleLinkClick(l)} style={{
                    fontSize: 12, padding: '6px 10px', borderRadius: 6, textDecoration: 'none',
                    border: `1px solid ${isDone ? '#f87171' : 'var(--border-soft)'}`,
                    color: isDone ? '#f87171' : 'var(--text)',
                    background: isDone ? 'rgba(248,113,113,0.1)' : 'var(--bg-panel)',
                  }}>{l.text}</a>
              )
            })}
          </div>
        </div>
      )}

      {popupLink && (
        <SavePopup
          novelId={novelId}
          link={popupLink}
          onClose={() => setPopupLink(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}
