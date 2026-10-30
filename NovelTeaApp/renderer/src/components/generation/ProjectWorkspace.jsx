import { Component, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import useStore from '../../store/useStore'
import useIsMobile from '../../hooks/useIsMobile'
import GenerateWorkspace from './GenerateWorkspace'
import { SidePanelContext } from '../../hooks/useNarrowLayout'

// The project workspace: the white page (GenerateWorkspace) in the middle, the pre-generation tools (planning: brief,
// arcs, skeleton, characters…) on the left and the post-generation tools (reader, editor, revision, critique,
// assistant…) on the right.
//   • DESKTOP (1200px and wider): both panels are FIXTURES, always open either side of the page, with no buttons to
//     open or close them. The chips along the top of a panel switch its tool; the divider between a panel and the page
//     drags to resize it (double-click resets), and the width is remembered.
//   • PHONE / NARROW WINDOW: each panel is a slide-out covering the whole workspace (100%), opened from the
//     "Pre-generation" / "Post-generation" buttons (a bar of their own on a phone, the title bar otherwise); the ✕, Esc
//     or the same button closes it.
//
// `tools` comes from ProjectView (it owns the project data and the save handlers the tabs need):
//   [{ id, label, short, icon, stage: 'pre' | 'post', render: () => <Tab …/>, heavy? }]
// The tab components are hosted unchanged. A tool stays mounted once opened (hidden, not unmounted) so
// what was typed in it survives closing the panel; it is re-created fresh the next time it is OPENED
// after the project data changed (the tabs copy project fields into local state when they mount, so that
// is what the old tab switch did too). `heavy` tools (the 3D map) only exist while open.

const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v } catch { return d } }
const lsSet = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

class ToolBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  componentDidCatch(error, info) { console.error(`Tool "${this.props.label}" crashed:`, error, info?.componentStack) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div style={{ padding: 20, fontSize: 12, color: 'var(--text-secondary)' }}>
        <div style={{ color: 'var(--red)', fontWeight: 700, marginBottom: 6 }}>{this.props.label} hit an error</div>
        <div style={{ marginBottom: 10 }}>{String(this.state.error?.message || this.state.error).slice(0, 240)}</div>
        <button onClick={() => this.setState({ error: null })}
          style={{ padding: '6px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}>Try again</button>
      </div>
    )
  }
}

// The tool chips along the top of a panel: a row that slides sideways, with a small ‹ and › at either end (dimmed when
// there is nothing further that way). Picking a chip scrolls it into view.
function ChipRow({ list, current, onPick, fixed }) {
  const ref = useRef(null)
  const [edge, setEdge] = useState({ start: true, end: true })
  const measure = useCallback(() => {
    const el = ref.current
    if (!el) return
    setEdge({ start: el.scrollLeft <= 2, end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 2 })
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el) return
    measure()
    el.addEventListener('scroll', measure, { passive: true })
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    if (ro) ro.observe(el)
    return () => { el.removeEventListener('scroll', measure); if (ro) ro.disconnect() }
  }, [measure, list.length])
  useEffect(() => {      // keep the chosen tool's chip in view
    const el = ref.current
    const chip = el && el.querySelector('[aria-pressed="true"]')
    if (!el || !chip) return
    const a = chip.offsetLeft, b = a + chip.offsetWidth
    if (a < el.scrollLeft) el.scrollTo({ left: a - 24, behavior: 'smooth' })
    else if (b > el.scrollLeft + el.clientWidth) el.scrollTo({ left: b - el.clientWidth + 24, behavior: 'smooth' })
  }, [current])
  const slide = dir => ref.current && ref.current.scrollBy({ left: dir * Math.max(120, ref.current.clientWidth * 0.7), behavior: 'smooth' })
  const arrow = (dir, disabled, label) => (
    <button onClick={() => slide(dir)} disabled={disabled} aria-label={label} title={label}
      style={{
        flexShrink: 0, width: 22, height: 26, minHeight: 0, padding: 0, fontSize: 15, lineHeight: 1, borderRadius: 6, fontWeight: 700,
        background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
        opacity: disabled ? 0.3 : 1, cursor: disabled ? 'default' : 'pointer',
      }}>{dir < 0 ? '‹' : '›'}</button>
  )
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px 8px' }}>
      {arrow(-1, edge.start, 'Slide the tools left')}
      <div ref={ref} className="tab-scroll" style={{ display: 'flex', gap: 4, overflowX: 'auto', flex: 1, minWidth: 0, scrollbarWidth: 'none' }}>
        {list.map(t => (
          <button key={t.id} onClick={() => onPick(t.id)} aria-pressed={current === t.id}
            style={{
              flexShrink: 0, fontSize: 11, fontWeight: current === t.id ? 700 : 500, padding: '3px 11px', minHeight: fixed ? 26 : 32, borderRadius: 999,
              background: current === t.id ? 'var(--accent-dim)' : 'transparent',
              color: current === t.id ? 'var(--accent-light)' : 'var(--text-secondary)',
              border: `1px solid ${current === t.id ? 'var(--accent)' : 'var(--border)'}`, whiteSpace: 'nowrap',
            }}>{t.icon} {t.short || t.label}</button>
        ))}
      </div>
      {arrow(1, edge.end, 'Slide the tools right')}
    </div>
  )
}

export default function ProjectWorkspace({ projectId, tools, revision = 0, renderPlan }) {
  const isMobile = useIsMobile()
  const narrowScreen = useIsMobile(1200)
  const fixed = !narrowScreen            // desktop: the two panels are fixtures either side of the page
  const setProjectTab = useStore(s => s.setProjectTab)
  const activeTab = useStore(s => s.activeProjectTab)
  const setWorkspacePanels = useStore(s => s.setWorkspacePanels)
  const toggleRequest = useStore(s => s.workspaceToggle)

  // Which tool each panel shows (null = closed), and the last tool each side's button reopens. Both are remembered
  // per project, so a refresh comes back to the same pre-gen / post-gen panels and tools.
  const panelKey = `nm-ws-open:${projectId}`
  const savedPanels = () => { try { return JSON.parse(lsGet(panelKey, '{}')) || {} } catch { return {} } }
  const known = id => (id && tools.some(t => t.id === id) ? id : null)
  const [open, setOpen] = useState(() => { const s = savedPanels(); return { left: known(s.left), right: known(s.right) } })
  const [inst, setInst] = useState({})                                  // id -> { key, rev }: hosted tools
  // 0 = not chosen yet: the page picks the LATEST chapter when the project loads (never "the one you last looked at")
  const [chapterNum, setChapterNum] = useState(0)
  useEffect(() => { setChapterNum(0) }, [projectId])
  const [pageRefresh, setPageRefresh] = useState(0)                     // bumped when a tool panel closes: reload the page
  const [widths, setWidths] = useState(() => ({ left: Number(lsGet('nm-ws-w:left', '')) || 0, right: Number(lsGet('nm-ws-w:right', '')) || 0 }))
  const widthsRef = useRef(widths)
  widthsRef.current = widths
  const defaultW = () => Math.min(480, Math.max(340, Math.round((typeof window !== 'undefined' ? window.innerWidth : 1440) * 0.27)))
  const widthOf = side => Math.min(Math.max(widths[side] || defaultW(), 280), 760)
  const dirty = useRef(false)   // a tool was used since the page last reloaded: it reloads when the pointer returns to it

  const leftTools = useMemo(() => tools.filter(t => t.stage === 'pre'), [tools])
  const rightTools = useMemo(() => tools.filter(t => t.stage === 'post'), [tools])
  const sideOf = id => (leftTools.some(t => t.id === id) ? 'left' : 'right')
  const lastOpened = useRef((() => { const s = savedPanels(); return { left: known(s.lastLeft), right: known(s.lastRight) } })())
  const selfSet = useRef(null)   // a tab id this component just wrote to the store itself (so the effect below ignores it)

  const ensureInstance = useCallback((id) => {
    setInst(m => {
      const cur = m[id]
      if (!cur) return { ...m, [id]: { key: 0, rev: revision } }
      if (cur.rev !== revision) return { ...m, [id]: { key: cur.key + 1, rev: revision } }
      return m
    })
  }, [revision])

  const openTool = useCallback((id) => {
    const side = leftTools.some(t => t.id === id) ? 'left' : 'right'
    ensureInstance(id)
    lastOpened.current[side] = id
    const other = side === 'left' ? 'right' : 'left'
    if (fixed) {
      if (side === 'right') setPageRefresh(n => n + 1)               // leaving a post tool: it may have changed the chapter
      setOpen(o => ({ ...o, [side]: id }))                            // the other panel stays exactly as it is
    } else {
      if (other === 'right' && open.right) setPageRefresh(n => n + 1)   // a post tool is being closed: reload the page
      setOpen(o => ({ ...o, [side]: id, [other]: null }))
    }
    selfSet.current = id
    setProjectTab(id)       // keeps the sidebar / nav state in step with what is open
  }, [leftTools, ensureInstance, setProjectTab, open.right, fixed])

  // the tools restored from the last visit need their panels mounted
  useEffect(() => { if (open.left) ensureInstance(open.left); if (open.right) ensureInstance(open.right) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    lsSet(panelKey, JSON.stringify({ left: open.left, right: open.right, lastLeft: lastOpened.current.left, lastRight: lastOpened.current.right }))
  }, [panelKey, open.left, open.right]) // eslint-disable-line react-hooks/exhaustive-deps

  // desktop: both panels always show a tool (the one last used, else the first)
  useEffect(() => {
    if (!fixed) return
    const l = lastOpened.current.left || leftTools[0]?.id
    const r = lastOpened.current.right || rightTools[0]?.id
    if (l) ensureInstance(l)
    if (r) ensureInstance(r)
    setOpen(o => ({ left: o.left || l || null, right: o.right || r || null }))
  }, [fixed, leftTools, rightTools]) // eslint-disable-line react-hooks/exhaustive-deps

  const closeSide = useCallback((side) => {
    if (fixed) return          // desktop panels are fixtures: nothing closes them
    setOpen(o => (o[side] ? { ...o, [side]: null } : o))
    if (side === 'right') setPageRefresh(n => n + 1)   // a post tool may have changed the chapter
    selfSet.current = 'generate'
    setProjectTab('generate')
  }, [setProjectTab, fixed])

  const openSide = side => {
    const list = side === 'left' ? leftTools : rightTools
    const id = lastOpened.current[side] || list[0]?.id
    if (id) openTool(id)
  }

  // the old tab switches (sidebar items, "Engines →", Overview shortcuts) now open the matching panel
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (selfSet.current === activeTab) { selfSet.current = null; return }   // our own write, not a request
    const t = tools.find(x => x.id === activeTab)
    if (t) { if (open[sideOf(t.id)] !== t.id) openTool(t.id) }
    else if (activeTab === 'generate' && !fixed) {   // "Generate" (sidebar, Overview's button) = back to the page
      if (open.left) closeSide('left')
      if (open.right) closeSide('right')
    }
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = e => {
      if (e.key !== 'Escape' || fixed) return
      if (open.right) closeSide('right')
      else if (open.left) closeSide('left')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, closeSide, fixed])


  // tell the title bar which panels are open (it draws the desktop buttons) …
  useEffect(() => { setWorkspacePanels({ left: !!open.left, right: !!open.right, fixed }) }, [open.left, open.right, fixed]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => setWorkspacePanels({ left: false, right: false, fixed: false }), []) // eslint-disable-line react-hooks/exhaustive-deps
  // … and do what its buttons ask. Starts from the request already in the store, so a stale one isn't replayed.
  const seenRequest = useRef(toggleRequest?.n || 0)
  useEffect(() => {
    if (!toggleRequest || toggleRequest.n === seenRequest.current) return
    seenRequest.current = toggleRequest.n
    const side = toggleRequest.side
    if (open[side]) closeSide(side); else openSide(side)
  }, [toggleRequest]) // eslint-disable-line react-hooks/exhaustive-deps

  function Panel({ side, list, title }) {
    const current = open[side]
    const isOpen = !!current
    const tool = list.find(t => t.id === current)
    const dir = side === 'left' ? -1 : 1
    const base = fixed
      ? { position: 'relative', flex: '0 0 auto', width: widthOf(side), zIndex: 1,
          borderLeft: side === 'right' ? '1px solid var(--border)' : 'none', borderRight: side === 'left' ? '1px solid var(--border)' : 'none' }
      : { position: 'absolute', top: 0, bottom: 0, zIndex: 160, [side]: 0, width: '100%',
          borderLeft: side === 'right' ? '1px solid var(--border)' : 'none', borderRight: side === 'left' ? '1px solid var(--border)' : 'none',
          boxShadow: isOpen ? `${-dir * 8}px 0 28px rgba(0,0,0,0.4)` : 'none',
          transform: isOpen ? 'translateX(0)' : `translateX(${dir * 105}%)`,
          visibility: isOpen ? 'visible' : 'hidden',
          transition: 'transform 0.25s ease, visibility 0s linear ' + (isOpen ? '0s' : '0.25s') }
    return (
      <section role="complementary" aria-label={`${title} tools`} aria-hidden={fixed ? false : !isOpen}
        onPointerDownCapture={fixed ? () => { dirty.current = true } : undefined}
        onKeyDownCapture={fixed ? () => { dirty.current = true } : undefined}
        className={fixed ? 'ws-onecol' : undefined}
        style={{ ...base, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--bg-card)' }}>
        <header style={{ flexShrink: 0, borderBottom: '1px solid var(--border-soft)', background: 'var(--bg-surface)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: fixed ? '6px 12px 2px' : '8px 12px 4px' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{title}</div>
              <div style={{ fontSize: 14, fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{tool ? `${tool.icon}  ${tool.label}` : ''}</div>
            </div>
            {!fixed && (
              <button onClick={() => closeSide(side)} aria-label={`Close ${title} panel`} title="Close (Esc)"
                style={{ width: 36, height: 36, borderRadius: 8, fontSize: 16, color: 'var(--text-secondary)', background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}>✕</button>
            )}
          </div>
          <ChipRow list={list} current={current} onPick={openTool} fixed={fixed} />
        </header>
        <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', position: 'relative' }}>
          {list.map(t => {
            const i = inst[t.id]
            if (!i || (t.heavy && current !== t.id)) return null
            return (
              <div key={`${t.id}:${i.key}`} style={{
                display: current === t.id ? 'flex' : 'none', flex: 1, minWidth: 0, minHeight: 0, overflow: 'hidden',
              }}>
                <SidePanelContext.Provider value={fixed}>
                  <ToolBoundary label={t.label}>{t.render({ chapterNum })}</ToolBoundary>
                </SidePanelContext.Provider>
              </div>
            )
          })}
        </div>
      </section>
    )
  }

  // the divider between a fixed panel and the page: drag to resize, double-click to reset
  const divider = side => (
    <div role="separator" aria-orientation="vertical" aria-label={`Resize the ${side === 'left' ? 'Pre' : 'Post'}-generation panel`}
      title="Drag to resize · double-click to reset"
      onDoubleClick={() => { setWidths(m => ({ ...m, [side]: 0 })); lsSet(`nm-ws-w:${side}`, '') }}
      onPointerDown={e => {
        e.preventDefault()
        const row = e.currentTarget.parentElement.getBoundingClientRect()
        const other = side === 'left' ? 'right' : 'left'
        const move = ev => {
          const raw = side === 'left' ? ev.clientX - row.left : row.right - ev.clientX
          const w = Math.min(760, Math.max(280, Math.round(raw)), row.width - widthOf(other) - 520)
          setWidths(m => ({ ...m, [side]: w }))
        }
        const up = () => {
          window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
          document.body.style.userSelect = ''
          lsSet(`nm-ws-w:${side}`, String(widthsRef.current[side] || ''))
        }
        document.body.style.userSelect = 'none'
        window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
      }}
      style={{ width: 7, margin: '0 -3px', flexShrink: 0, cursor: 'col-resize', zIndex: 5, background: 'transparent', position: 'relative' }}
      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(124,58,237,0.35)' }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }} />
  )

  const barButton = (side, text, list) => (
    <button onClick={() => (open[side] ? closeSide(side) : openSide(side))} aria-expanded={!!open[side]}
      aria-label={text.replace(/[◀▶]/g, '').trim()}
      title={`${list.map(t => t.label.split(' (')[0]).join(' · ')}`}
      style={{
        fontSize: isMobile ? 12 : 13, fontWeight: 700, padding: isMobile ? '2px 12px' : '6px 18px', minHeight: isMobile ? 30 : 38,
        flex: isMobile ? 1 : undefined, borderRadius: 'var(--radius-sm)', whiteSpace: 'nowrap',
        background: open[side] ? 'var(--accent-dim)' : 'var(--bg-elevated)',
        border: `1px solid ${open[side] ? 'var(--accent)' : 'var(--border)'}`,
        color: open[side] ? 'var(--accent-light)' : 'var(--text-primary)',
      }}>{text}</button>
  )

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
      {/* the two stage buttons: on a phone they sit on a bar of their own; on a narrow desktop window, in the title bar;
          on a wide desktop there are none, the panels are always open */}
      {isMobile && <div role="toolbar" aria-label="Tool panels" style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexShrink: 0,
        padding: isMobile ? '4px 8px' : '6px 16px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-soft)',
      }}>
        {barButton('left', '◀ Pre-generation', leftTools)}
        {barButton('right', 'Post-generation ▶', rightTools)}
      </div>}

      <div style={{ flex: 1, display: 'flex', minHeight: 0, minWidth: 0, position: 'relative', overflow: 'hidden' }}>
        {fixed && Panel({ side: 'left', list: leftTools, title: 'Pre-generation' })}
        {fixed && divider('left')}
        <div style={{ flex: 1, minWidth: 0, display: 'flex' }}
          onMouseEnter={fixed ? () => { if (dirty.current) { dirty.current = false; setPageRefresh(n => n + 1) } } : undefined}>
          <GenerateWorkspace projectId={projectId} chapterNum={chapterNum} setChapterNum={setChapterNum}
            refreshToken={pageRefresh} renderPlan={renderPlan} />
        </div>
        {fixed && divider('right')}
        {fixed && Panel({ side: 'right', list: rightTools, title: 'Post-generation' })}

        {!fixed && Panel({ side: 'left', list: leftTools, title: 'Pre-generation' })}
        {!fixed && Panel({ side: 'right', list: rightTools, title: 'Post-generation' })}
      </div>
    </div>
  )
}
