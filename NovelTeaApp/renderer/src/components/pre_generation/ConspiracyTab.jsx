import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api'
import useNarrowLayout from '../../hooks/useNarrowLayout'

// Conspiracy tab (Pre-generation): the book's hidden scheme as a zoomable tree. The final scheme is the root; it is reverse-engineered
// down into minor schemes, then the events / false flags / cover-ups that carry them out, then the clues / breadcrumbs / mistakes the
// hero can find. The arc and skeleton planners see the whole tree (marked secret); the chapter writer only sees what is pinned to its
// chapter, as surface events to show and clues to plant. On a phone (or in a side panel) the graph becomes a collapsible list.

// Palette: a lacquered screen. Slips of bamboo hung on red thread over black-red lacquer; gilt marks the seal and the chain
// you are following. Each type wears a small cord tab rather than a coloured border, and rank shows in the size of the slip.
const LQ = { lacquer: '#1c1210', lacquerHi: '#2b1b17', thread: '#9e2b25', gilt: '#c8a24a', slip: '#d8c79a', slipDim: '#b9a97d', ink: '#2a1e14', inkSoft: '#5e4b37' }
const SERIF = 'Georgia, "Iowan Old Style", "Palatino Linotype", serif'

const TYPES = {
  final_scheme: { label: 'Final scheme', color: '#c8a24a' },
  scheme:       { label: 'Scheme',       color: '#b5482f' },
  agent:        { label: 'Agent',        color: '#3d5a80' },
  event:        { label: 'Event',        color: '#c98a2b' },
  false_flag:   { label: 'False flag',   color: '#7d4a8f' },
  patsy:        { label: 'Patsy',        color: '#8a5a2b' },
  cover_up:     { label: 'Cover-up',     color: '#4f5a63' },
  clue:         { label: 'Clue',         color: '#2e7d86' },
  breadcrumb:   { label: 'Breadcrumb',   color: '#4f7d3a' },
  mistake:      { label: 'Mistake',      color: '#a8344f' },
}
// Rank is carried by the slip's size: the final scheme is the broadest slip, clues the narrowest.
const SIZE = {
  final_scheme: [250, 92], scheme: [214, 78], agent: [196, 70],
  event: [196, 70], false_flag: [196, 70], patsy: [196, 70], cover_up: [196, 70],
  clue: [176, 62], breadcrumb: [176, 62], mistake: [176, 62],
}
const sizeOf = n => SIZE[n.type] || [196, 70]
const SLOT = 230, GY = 64
const SHEET = { position: 'fixed', left: 0, right: 0, bottom: 0, maxHeight: '58vh', overflowY: 'auto', zIndex: 260, borderRadius: '14px 14px 0 0', boxShadow: '0 -8px 30px rgba(0,0,0,0.5)' }

const muted = { fontSize: 10.5, color: 'var(--text-muted)', lineHeight: 1.55 }
const btn = { fontSize: 10.5, padding: '4px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }
const primary = { ...btn, background: 'var(--accent)', border: '1px solid var(--accent)', color: '#fff', fontWeight: 700 }
const field = { width: '100%', padding: '5px 8px', fontSize: 11.5, borderRadius: 4, boxSizing: 'border-box' }
const newId = () => `c${Date.now() % 1e10}${Math.floor(Math.random() * 1000)}`

function useKids(nodes) {
  return useMemo(() => {
    const m = new Map()
    nodes.forEach(n => { const k = n.parent || null; if (!m.has(k)) m.set(k, []); m.get(k).push(n) })
    return m
  }, [nodes])
}

// Tidy top-down layout: leaves sit side by side in equal slots, every parent is centred over its children.
// Rows are as tall as the tallest slip that can sit in them, so smaller slips hang a little lower, like tags on a line.
const ROW_H = [92, 78, 70, 62, 62, 62, 62, 62]
// The book's volumes, growing as the book goes on then a shorter finale (mirrors book_volumes() in routers/conspiracy.py exactly).
export function bookVolumes(total, arcsTotal) {
  total = Math.max(40, Math.floor(total || 1500))
  const rnd = x => Math.floor(x + 0.5)
  if (arcsTotal) {
    const n = Math.max(2, Math.min(50, Math.floor(arcsTotal)))
    const w = [...Array.from({ length: n - 1 }, (_, i) => 1.2 ** i), 1.2 ** (n - 2) * 0.45]
    const sw = w.reduce((a, b) => a + b, 0)
    const lens = w.map(x => Math.max(10, rnd(total * x / sw)))
    lens[n - 1] = Math.max(10, lens[n - 1] + total - lens.reduce((a, b) => a + b, 0))
    let ch = 1
    return lens.map((L, i) => { const v = { volume: i + 1, chapters: [ch, ch + L - 1], arcs: [i + 1, i + 1] }; ch += L; return v })
  }
  const nv = total >= 3000 ? 9 : total >= 1500 ? 8 : total >= 600 ? 6 : 4
  const w = [...Array.from({ length: nv - 1 }, (_, i) => 1.35 ** i), 1.35 ** (nv - 2) * 0.45]
  const sw = w.reduce((a, b) => a + b, 0)
  const lens = w.map(x => Math.max(20, rnd(total * x / sw)))
  lens[lens.length - 1] = Math.max(20, lens[lens.length - 1] + total - lens.reduce((a, b) => a + b, 0))
  const out = []
  let ch = 1, arc = 1
  lens.forEach((L, i) => {
    const n = Math.max(1, rnd(L / Math.min(150, Math.max(30, rnd(L / 4)))))
    out.push({ volume: i + 1, chapters: [ch, ch + L - 1], arcs: [arc, arc + n - 1] })
    ch += L; arc += n
  })
  return out
}
const volumeOfArc = (vols, a) => (vols.find(v => a >= v.arcs[0] && a <= v.arcs[1]) || vols[vols.length - 1] || { volume: 1 }).volume
const storyKey = n => (n.chapter ?? (n.arc ? n.arc * 1000 : 1e6))
// 50 arc colours, spread round the wheel by the golden angle so neighbouring arcs never look alike; kept dark and low in
// saturation so the bamboo slips stay the brightest thing on the lacquer.
export const ARC_COLORS = Array.from({ length: 50 }, (_, i) => `hsl(${Math.round((i * 137.508 + 8) % 360)}, 34%, 21%)`)
const arcColor = a => ARC_COLORS[((a || 1) - 1) % ARC_COLORS.length]
// A node with no arc takes its parent's (the final scheme defaults to the reveal arc).
function arcsOf(nodes, revealArc) {
  const by = new Map(nodes.map(n => [n.id, n])), memo = new Map()
  const get = n => {
    if (!n) return revealArc
    if (memo.has(n.id)) return memo.get(n.id)
    const a = n.arc || (n.parent ? get(by.get(n.parent)) : revealArc)
    memo.set(n.id, a); return a
  }
  nodes.forEach(get)
  return memo
}
function layout(kids, collapsed, trunk, bandArcs) {
  const pos = new Map()
  let leaf = 0, maxDepth = 0
  const rowY = d => ROW_H.slice(0, d).reduce((a, h) => a + h + GY, 0)
  function place(n, depth) {
    maxDepth = Math.max(maxDepth, depth)
    const ch = collapsed.has(n.id) ? [] : [...(kids.get(n.id) || [])].sort((a, b) => storyKey(a) - storyKey(b))
    let cx
    if (!ch.length) { cx = leaf * SLOT + SLOT / 2; leaf += 1 }
    else { const xs = ch.map(c => place(c, depth + 1)); cx = (xs[0] + xs[xs.length - 1]) / 2 }
    const [w, h] = sizeOf(n)
    pos.set(n.id, { x: cx - w / 2, y: rowY(depth), w, h, cx })
    return cx
  }
  ;(kids.get(null) || []).forEach(r => place(r, 0))
  if (bandArcs) {   // PYRAMID: one horizontal band per arc, arc 1 first; inside a band, slips stack by their depth in the tree
    const depthOf = new Map()
    const walk = (n, d) => { depthOf.set(n.id, d); (kids.get(n.id) || []).forEach(c => walk(c, d + 1)) }
    ;(kids.get(null) || []).forEach(r => walk(r, 0))
    const arcs = [...new Set([...pos.keys()].map(id => bandArcs.get(id) || 1))].sort((a, b) => a - b)
    const order = trunk ? arcs : [...arcs].reverse()            // trunk at the bottom: arc 1 on top, the reveal at the base
    // Each row inside a band is packed tight, keeping the tree's left-to-right order (so threads cross as little as possible),
    // and centred: the many clues of the early arcs make a broad top, the few schemes of the reveal a narrow base - a pyramid.
    const GAPX = 22, bands = [], rows = []
    let y = 0
    order.forEach(a => {
      const ids = [...pos.keys()].filter(id => (bandArcs.get(id) || 1) === a)
      const depths = [...new Set(ids.map(id => depthOf.get(id) || 0))].sort((p, q) => (trunk ? q - p : p - q))
      const top = y
      depths.forEach((d, i) => {
        const row = ids.filter(id => (depthOf.get(id) || 0) === d).sort((p, q) => pos.get(p).cx - pos.get(q).cx)
        const rowY = top + 34 + i * (78 + 40)
        rows.push({ row, w: row.reduce((t, id) => t + pos.get(id).w, 0) + GAPX * Math.max(0, row.length - 1) })
        row.forEach(id => { const p = pos.get(id); p.y = rowY + (78 - p.h) / 2 })
      })
      y = top + 34 + depths.length * (78 + 40) + 4
      bands.push({ arc: a, y: top, h: y - top })
    })
    const width = Math.max(SLOT, ...rows.map(r => r.w))
    rows.forEach(({ row, w }) => {
      let x = (width - w) / 2
      row.forEach(id => { const p = pos.get(id); p.x = x; p.cx = x + p.w / 2; x += p.w + GAPX })
    })
    return { pos, width, height: y, bands }
  }
  const height = rowY(maxDepth + 1)
  if (trunk) {      // the final scheme becomes the trunk at the bottom; the branches at the top are the start of the book
    pos.forEach(p => { p.y = height - GY - p.y - p.h })
  }
  return { pos, width: Math.max(1, leaf) * SLOT, height, bands: [] }
}

function Graph({ nodes, kids, selected, onSelect, collapsed, onToggle, truth, dimmed, fresh, pending, decisions, trunk, bands, revealArc, arcLabels, bookChapters, arcsTotal }) {
  const wrap = useRef(null)
  const [view, setView] = useState({ x: 20, y: 20, k: 0.8 })
  const drag = useRef(null)
  const pts = useRef(new Map())      // pointers currently down (two of them = a pinch)
  const pinch = useRef(null)
  const touchPinch = useRef(null)
  const vols = useMemo(() => bookVolumes(bookChapters || 1500, arcsTotal), [bookChapters, arcsTotal])
  const tiny = typeof window !== 'undefined' && window.innerWidth < 600     // phone: no captions over the board    // pinch tracked from touch events (takes over from the pointer path)
  const bandArcs = useMemo(() => (bands ? arcsOf(nodes, revealArc || 2) : null), [bands, nodes, revealArc])
  const { pos, width, height, bands: bandRows } = useMemo(() => layout(kids, collapsed, trunk, bandArcs), [kids, collapsed, trunk, bandArcs])
  const byId = useMemo(() => new Map(nodes.map(n => [n.id, n])), [nodes])
  // the chain from the selected slip back up to the final scheme, lit in gilt
  const chain = useMemo(() => {
    const s = new Set()
    let cur = byId.get(selected)
    while (cur) { s.add(cur.id); cur = byId.get(cur.parent) }
    return s
  }, [selected, byId])

  const fit = useCallback(() => {
    const el = wrap.current
    if (!el) return
    const W = el.clientWidth, H = el.clientHeight
    // Fit the board's HEIGHT so the slips stay readable; a wide tree is panned sideways. Start centred on the final scheme.
    const k = Math.min(1, Math.max(0.32, (H - 70) / (height + 20)))
    const root = nodes.find(n => !n.parent), rp = root && pos.get(root.id)
    const cx = rp ? rp.cx : width / 2
    setView({ k, x: W / 2 - cx * k, y: Math.max(36, (H - height * k) / 2) })
  }, [width, height, nodes, pos])
  useEffect(() => { fit() }, [nodes.length, trunk]) // eslint-disable-line

  function onWheel(e) {
    e.preventDefault()
    const r = wrap.current.getBoundingClientRect()
    const mx = e.clientX - r.left, my = e.clientY - r.top
    setView(v => {
      const k = Math.min(2.5, Math.max(0.1, v.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)))
      return { k, x: mx - (mx - v.x) * (k / v.k), y: my - (my - v.y) * (k / v.k) }
    })
  }
  useEffect(() => {
    const el = wrap.current
    if (!el) return
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  })
  // Two-finger pinch at the touch level, so it works wherever the fingers land (on a slip or on the lacquer).
  const viewRef = useRef(view)
  viewRef.current = view
  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const mid = (t, r) => [(t[0].clientX + t[1].clientX) / 2 - r.left, (t[0].clientY + t[1].clientY) / 2 - r.top]
    const dist = t => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY) || 1
    const start = e => {
      if (e.touches.length !== 2) return
      e.preventDefault()
      const r = el.getBoundingClientRect(), [mx, my] = mid(e.touches, r)
      touchPinch.current = { d: dist(e.touches), mx, my, v: viewRef.current }
      drag.current = null; pinch.current = null
    }
    const move = e => {
      const pc = touchPinch.current
      if (!pc || e.touches.length !== 2) return
      e.preventDefault()
      const r = el.getBoundingClientRect(), [mx, my] = mid(e.touches, r)
      const k = Math.min(2.5, Math.max(0.1, pc.v.k * (dist(e.touches) / pc.d)))
      setView({ k, x: mx - (pc.mx - pc.v.x) * (k / pc.v.k), y: my - (pc.my - pc.v.y) * (k / pc.v.k) })
    }
    const end = e => { if (e.touches.length < 2) touchPinch.current = null }
    el.addEventListener('touchstart', start, { passive: false })
    el.addEventListener('touchmove', move, { passive: false })
    el.addEventListener('touchend', end)
    el.addEventListener('touchcancel', end)
    return () => {
      el.removeEventListener('touchstart', start); el.removeEventListener('touchmove', move)
      el.removeEventListener('touchend', end); el.removeEventListener('touchcancel', end)
    }
  }, [])
  const zoom = f => setView(v => {
    const el = wrap.current, cx = el.clientWidth / 2, cy = el.clientHeight / 2
    const k = Math.min(2.5, Math.max(0.1, v.k * f))
    return { k, x: cx - (cx - v.x) * (k / v.k), y: cy - (cy - v.y) * (k / v.k) }
  })

  // red thread: each child hangs from its parent on a line that sags a little, as thread does
  const edges = []
  nodes.forEach(n => {
    if (!n.parent || collapsed.has(n.parent)) return
    const a = pos.get(n.parent), b = pos.get(n.id)
    if (!a || !b) return
    const x1 = a.cx, x2 = b.cx
    const y1 = trunk ? a.y : a.y + a.h, y2 = trunk ? b.y + b.h : b.y
    const sag = trunk ? -Math.min(30, Math.abs(x2 - x1) * 0.06 + 10) : Math.min(40, Math.abs(x2 - x1) * 0.08 + 14)
    const lit = chain.has(n.id) && chain.has(n.parent)
    const faded = dimmed && dimmed.has(n.type)
    edges.push(<path key={n.id} d={`M${x1},${y1} C${x1},${y1 + (y2 - y1) * 0.55 + sag} ${x2},${y2 - (y2 - y1) * 0.45 + sag} ${x2},${y2}`}
      fill="none" stroke={lit ? LQ.gilt : LQ.thread} strokeWidth={lit ? 2.4 : 1.3} strokeOpacity={faded ? 0.18 : lit ? 1 : 0.75} />)
  })

  return (
    <div ref={wrap} style={{ position: 'relative', flex: 1, minHeight: 440, overflow: 'hidden', borderRadius: 'var(--radius-lg)', touchAction: 'none',
      background: `radial-gradient(ellipse at 50% 0%, ${LQ.lacquerHi} 0%, ${LQ.lacquer} 70%)`, border: `1px solid ${LQ.lacquerHi}`,
      cursor: drag.current ? 'grabbing' : 'grab' }}
      onPointerDown={e => {
        if (e.target.closest('button')) return                   // the zoom buttons keep their taps
        pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
        // a drag may start anywhere, even on a slip; the pointer is only captured once it has moved, so a plain tap still opens the slip
        if (pts.current.size === 1) drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, el: e.currentTarget, id: e.pointerId, live: false }
        else if (pts.current.size === 2) {                         // second finger down: start a pinch
          const [p1, p2] = [...pts.current.values()], r = wrap.current.getBoundingClientRect()
          pinch.current = { d: Math.hypot(p1.x - p2.x, p1.y - p2.y) || 1, mx: (p1.x + p2.x) / 2 - r.left, my: (p1.y + p2.y) / 2 - r.top, v: view }
          drag.current = null
        }
      }}
      onPointerMove={e => {
        if (!pts.current.has(e.pointerId)) return
        pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
        if (touchPinch.current) return
        const pc = pinch.current
        if (pc && pts.current.size >= 2) {                         // pinch: zoom around the point between the two fingers
          const [p1, p2] = [...pts.current.values()]
          const k = Math.min(2.5, Math.max(0.1, pc.v.k * (Math.hypot(p1.x - p2.x, p1.y - p2.y) / pc.d)))
          const r = wrap.current.getBoundingClientRect()
          const mx = (p1.x + p2.x) / 2 - r.left, my = (p1.y + p2.y) / 2 - r.top
          setView({ k, x: mx - (pc.mx - pc.v.x) * (k / pc.v.k), y: my - (pc.my - pc.v.y) * (k / pc.v.k) })
          return
        }
        const d = drag.current
        if (!d) return
        if (!d.live) {
          if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6) return
          d.live = true
          try { d.el.setPointerCapture(d.id) } catch {}
        }
        setView(v => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }))
      }}
      onPointerUp={e => { pts.current.delete(e.pointerId); if (pts.current.size < 2) pinch.current = null; if (!pts.current.size) drag.current = null }}
      onPointerCancel={e => { pts.current.delete(e.pointerId); pinch.current = null; if (!pts.current.size) drag.current = null }}>
      <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0 }}>
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {bandRows.map(b => (
            <g key={b.arc}>
              <rect x={-40} y={b.y} width={width + 80} height={b.h} fill={arcColor(b.arc)} opacity={0.9} />
              <rect x={-40} y={b.y + b.h - 1} width={width + 80} height={1} fill="#000" opacity={0.35} />
              <text x={(-view.x + 14) / view.k} y={b.y + 22} fill={LQ.slip} opacity={0.9} style={{ fontFamily: SERIF, fontSize: 15 / Math.max(view.k, 0.5) }}>
                {`${arcsTotal ? '' : `Volume ${volumeOfArc(vols, b.arc)}, `}${arcsTotal ? 'Arc' : 'arc'} ${b.arc}${arcLabels && arcLabels[b.arc - 1] ? `: ${arcLabels[b.arc - 1]}` : ''}${b.arc === revealArc ? ' (the reveal begins)' : ''}`}
              </text>
            </g>
          ))}
          {edges}
        </g>
      </svg>
      {/* The slips are plain HTML in their own layer, zoomed by a CSS transform. (HTML inside an SVG foreignObject ignores the SVG's zoom
          on iPhone Safari, which left the slips full size while the lacquer shrank.) */}
      <div style={{ position: 'absolute', left: 0, top: 0, width: 0, height: 0, transformOrigin: '0 0', transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`, willChange: 'transform' }}>
          {nodes.map(n => {
            const p = pos.get(n.id)
            if (!p) return null
            const t = TYPES[n.type] || TYPES.scheme
            const nk = (kids.get(n.id) || []).length
            const sel = selected === n.id, onChain = chain.has(n.id)
            const isNew = pending && pending.has(n.id), dec = decisions && decisions[n.id]
            const faded = (dimmed && dimmed.has(n.type)) || dec === 'decline'
            const root = n.type === 'final_scheme'
            const line = truth ? n.text : (n.surface || n.text)
            const pin = n.chapter ? `Ch ${n.chapter}` : n.arc ? `Arc ${n.arc}` : ''
            return (
                <div key={n.id} data-node="1" onClick={() => onSelect(n.id)} title={line}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(n.id) } }} tabIndex={0} role="button" aria-label={`${t.label}: ${n.title}`}
                  style={{ position: 'absolute', left: p.x, top: p.y, width: p.w, height: p.h, boxSizing: 'border-box', padding: root ? '10px 14px 8px' : '8px 11px 7px', cursor: 'pointer', overflow: 'hidden',
                    background: n.status === 'revealed' ? LQ.slipDim : LQ.slip, color: LQ.ink, opacity: faded ? 0.28 : 1,
                    borderRadius: root ? 3 : 2, outline: isNew ? `2px dashed ${dec === 'accept' ? '#4f7d3a' : LQ.gilt}` : 'none', outlineOffset: 2,
                    boxShadow: sel ? `0 0 0 2px ${LQ.gilt}, 0 6px 18px rgba(0,0,0,0.55)` : onChain ? `0 0 0 1px ${LQ.gilt}, 0 3px 10px rgba(0,0,0,0.45)` : '0 3px 10px rgba(0,0,0,0.45)',
                    backgroundImage: 'repeating-linear-gradient(90deg, rgba(42,30,20,0.035) 0 1px, transparent 1px 7px)' }}>
                  {/* cord tab: the type, tied to the top of the slip */}
                  <span style={{ position: 'absolute', top: 0, left: root ? 14 : 11, width: 18, height: 5, background: t.color, borderRadius: '0 0 2px 2px' }} />
                  {isNew && <span style={{ position: 'absolute', top: 0, left: root ? 38 : 35, fontSize: 8, fontWeight: 700, color: LQ.ink, background: dec === 'accept' ? '#8fbf6a' : dec === 'decline' ? '#c98a8a' : LQ.gilt, padding: '0 4px', borderRadius: '0 0 2px 2px' }}>{dec === 'accept' ? 'accepted' : dec === 'decline' ? 'declined' : 'proposed'}</span>}
                  {!isNew && fresh && fresh.has(n.id) && <span style={{ position: 'absolute', top: 0, left: root ? 38 : 35, fontSize: 8, fontWeight: 700, color: LQ.slip, background: LQ.thread, padding: '0 4px', borderRadius: '0 0 2px 2px' }}>new</span>}
                  {root && <span aria-hidden style={{ position: 'absolute', right: 10, top: 10, width: 26, height: 26, borderRadius: '50%', background: LQ.thread, color: LQ.slip, fontFamily: SERIF, fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `inset 0 0 0 2px ${LQ.gilt}` }}>印</span>}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 6, paddingRight: root ? 30 : 0 }}>
                    <span style={{ fontSize: 9.5, color: LQ.inkSoft }}>{t.label}{pin && <span style={{ marginLeft: 6, color: LQ.thread, fontWeight: 600 }}>{pin}</span>}</span>
                    {nk > 0 && <span onClick={e => { e.stopPropagation(); onToggle(n.id) }} style={{ fontSize: 9.5, color: LQ.inkSoft, cursor: 'pointer', padding: '0 2px' }}
                      title={collapsed.has(n.id) ? 'Show what hangs from this' : 'Fold this branch'}>{collapsed.has(n.id) ? `+${nk}` : '–'}</span>}
                  </div>
                  <div style={{ fontFamily: SERIF, fontSize: root ? 14 : 12, fontWeight: 600, lineHeight: 1.22, marginTop: 2, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: root ? 2 : 1, WebkitBoxOrient: 'vertical' }}>{n.title || 'Untitled'}</div>
                  <div style={{ fontSize: 9.5, lineHeight: 1.3, marginTop: 2, color: truth ? LQ.thread : LQ.inkSoft, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: root ? 2 : (p.h > 64 ? 2 : 1), WebkitBoxOrient: 'vertical', fontStyle: truth ? 'normal' : 'italic' }}>{line}</div>
                </div>
            )
          })}
      </div>
      {!tiny && <div style={{ position: 'absolute', left: 12, top: 10, fontSize: 10.5, color: LQ.slipDim, fontFamily: SERIF, pointerEvents: 'none' }}>
        {trunk ? 'The branches: the start of the book, where the hero finds the clues' : 'The final scheme, revealed at the end'}
      </div>}
      {!tiny && <div style={{ position: 'absolute', left: 12, bottom: 10, right: 150, fontSize: 10.5, lineHeight: 1.35, color: LQ.slipDim, fontFamily: SERIF, pointerEvents: 'none' }}>
        {trunk ? 'The trunk: the end of the book, where the whole hierarchy is revealed' : 'The clues, found from the start of the book'}
        <span style={{ marginLeft: 10, fontStyle: 'italic', opacity: 0.8 }}>{truth ? 'Showing the truth' : 'Showing the cover story'}</span>
      </div>}
      <div style={{ position: 'absolute', right: 10, bottom: 10, display: 'flex', gap: 4 }}>
        {[['+', () => zoom(1.2), 'Zoom in'], ['–', () => zoom(1 / 1.2), 'Zoom out'], ['Fit', fit, 'Fit the whole board']].map(([l, f, a]) => (
          <button key={l} onClick={f} aria-label={a} style={{ minWidth: 44, height: 44, fontSize: 16, borderRadius: 4, background: LQ.lacquerHi, color: LQ.slip, border: `1px solid ${LQ.thread}`, touchAction: 'manipulation' }}>{l}</button>
        ))}
      </div>
    </div>
  )
}

function ListView({ kids, selected, onSelect, collapsed, onToggle }) {
  const rows = []
  function rec(pid, depth) {
    (kids.get(pid) || []).forEach(n => {
      const t = TYPES[n.type] || TYPES.scheme
      const nk = (kids.get(n.id) || []).length
      rows.push(
        <div key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 6px', paddingLeft: 6 + depth * 14, borderBottom: '1px solid var(--border-soft)',
          background: selected === n.id ? 'var(--bg-elevated)' : 'transparent', cursor: 'pointer', minHeight: 40 }} onClick={() => onSelect(n.id)}>
          <span onClick={e => { e.stopPropagation(); nk && onToggle(n.id) }} style={{ width: 16, fontSize: 11, color: 'var(--text-muted)' }}>{nk ? (collapsed.has(n.id) ? '▸' : '▾') : ''}</span>
          <span style={{ width: 8, height: 8, borderRadius: 4, background: t.color, flexShrink: 0 }} />
          <span style={{ fontSize: 11.5, flex: 1, minWidth: 0 }}>{n.title || '(untitled)'}</span>
          <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{n.chapter ? `ch ${n.chapter}` : n.arc ? `arc ${n.arc}` : ''}</span>
        </div>)
      if (!collapsed.has(n.id)) rec(n.id, depth + 1)
    })
  }
  rec(null, 0)
  return <div style={{ border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', background: 'var(--bg-card)' }}>{rows}</div>
}

function NodeEditor({ node, onChange, onAddChild, onDelete, onExpand, busy }) {
  const [note, setNote] = useState('')
  const set = (k, v) => onChange({ ...node, [k]: v })
  const num = v => (v === '' ? null : parseInt(v, 10) || null)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <select style={{ ...field, flex: '1 1 120px' }} value={node.type} onChange={e => set('type', e.target.value)}>
          {Object.entries(TYPES).map(([k, t]) => <option key={k} value={k}>{t.label}</option>)}
        </select>
        <select style={{ ...field, flex: '1 1 100px' }} value={node.status} onChange={e => set('status', e.target.value)}>
          <option value="planned">planned</option><option value="planted">planted</option><option value="revealed">revealed</option>
        </select>
      </div>
      <label style={muted}>Title<input style={field} value={node.title} onChange={e => set('title', e.target.value)} /></label>
      <label style={muted}>The truth (secret)<textarea rows={3} style={field} value={node.text} onChange={e => set('text', e.target.value)} /></label>
      <label style={muted}>{['clue', 'breadcrumb', 'mistake'].includes(node.type) ? 'What the hero actually sees' : node.type === 'patsy' ? 'The public accusation' : node.type === 'agent' ? 'Their cover identity' : 'What people believe happened'}
        <textarea rows={2} style={field} value={node.surface} onChange={e => set('surface', e.target.value)} /></label>
      <label style={muted}>Who does it<input style={field} value={node.who} onChange={e => set('who', e.target.value)} /></label>
      <div style={{ display: 'flex', gap: 6 }}>
        <label style={{ ...muted, flex: 1 }}>Arc<input style={field} inputMode="numeric" value={node.arc ?? ''} onChange={e => set('arc', num(e.target.value))} /></label>
        <label style={{ ...muted, flex: 1 }}>Chapter<input style={field} inputMode="numeric" value={node.chapter ?? ''} onChange={e => set('chapter', num(e.target.value))} /></label>
      </div>
      {node.sources?.length > 0 && <div style={muted}>Corpus inspiration: {node.sources.join(' · ')}</div>}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button style={btn} onClick={onAddChild}>＋ Child</button>
        <button style={btn} onClick={onDelete}>✕ Delete branch</button>
      </div>
      <input style={field} value={note} onChange={e => setNote(e.target.value)} placeholder="Optional: what to grow here (e.g. three clues at the gate)" />
      <button style={primary} disabled={!!busy} onClick={() => onExpand(note)}>{busy === 'expand' ? '✦ Growing… (a few minutes)' : '✦ Grow this branch with AI'}</button>
    </div>
  )
}


// Generated content waits here until the author accepts or declines it. Declining a slip declines everything proposed beneath it.
function ReviewPanel({ proposal, decisions, setDecision, baseNodes, onPost, onDiscard, selected, onSelect, busy }) {
  const all = proposal.nodes
  const byId = new Map([...baseNodes, ...all].map(n => [n.id, n]))
  const accepted = all.filter(n => decisions[n.id] === 'accept').length
  const declined = all.filter(n => decisions[n.id] === 'decline').length
  const rowRef = useRef({})
  useEffect(() => { const el = rowRef.current[selected]; if (el) el.scrollIntoView({ block: 'nearest' }) }, [selected])
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
      <div style={{ fontFamily: SERIF, fontSize: 13, fontWeight: 600 }}>{proposal.replace ? 'A new tree is proposed' : `${all.length} new slips are proposed`}</div>
      <div style={muted}>{proposal.replace
        ? 'Accepting replaces the whole tree (the current one stays on Undo). Decline any slip you do not want first.'
        : 'Nothing is on the board for real until you post it. Accept the slips you want, decline the rest.'}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button style={btn} onClick={() => all.forEach(n => setDecision(n.id, 'accept'))}>Accept all</button>
        <button style={btn} onClick={() => all.forEach(n => setDecision(n.id, 'decline'))}>Decline all</button>
      </div>
      <div style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minHeight: 120 }}>
        {all.map(n => {
          const t = TYPES[n.type] || TYPES.scheme, d = decisions[n.id], parent = byId.get(n.parent)
          return (
            <div key={n.id} ref={el => { rowRef.current[n.id] = el }} onClick={() => onSelect(n.id)}
              style={{ padding: '8px 10px', borderRadius: 4, cursor: 'pointer', background: 'var(--bg-surface)',
                border: `1px solid ${selected === n.id ? 'var(--accent-light)' : 'var(--border-soft)'}`, opacity: d === 'decline' ? 0.5 : 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 12, height: 4, background: t.color, borderRadius: 1, flexShrink: 0 }} />
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{t.label}{n.chapter ? `, ch ${n.chapter}` : n.arc ? `, arc ${n.arc}` : ''}</span>
              </div>
              <div style={{ fontFamily: SERIF, fontSize: 12.5, fontWeight: 600, marginTop: 3, textDecoration: d === 'decline' ? 'line-through' : 'none' }}>{n.title}</div>
              {parent && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>under {parent.title}</div>}
              <div style={{ fontSize: 11, marginTop: 3, lineHeight: 1.45 }}>{n.text}</div>
              {n.surface && <div style={{ fontSize: 10.5, marginTop: 2, fontStyle: 'italic', color: 'var(--text-secondary)' }}>Seen as: {n.surface}</div>}
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <button onClick={e => { e.stopPropagation(); setDecision(n.id, 'accept') }} aria-pressed={d === 'accept'}
                  style={{ ...btn, ...(d === 'accept' ? { background: 'var(--green)', borderColor: 'var(--green)', color: '#fff', fontWeight: 700 } : {}) }}>Accept</button>
                <button onClick={e => { e.stopPropagation(); setDecision(n.id, 'decline') }} aria-pressed={d === 'decline'}
                  style={{ ...btn, ...(d === 'decline' ? { background: 'var(--red)', borderColor: 'var(--red)', color: '#fff', fontWeight: 700 } : {}) }}>Decline</button>
              </div>
            </div>)
        })}
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button style={primary} disabled={!!busy || !accepted} onClick={onPost}>{busy === 'post' ? 'Posting…' : `Post ${accepted} accepted`}</button>
        <button style={btn} disabled={!!busy} onClick={onDiscard}>Discard all</button>
        <span style={muted}>{accepted} accepted, {declined} declined, {all.length - accepted - declined} undecided</span>
      </div>
    </div>
  )
}

export default function ConspiracyTab({ projectId }) {
  const narrow = useNarrowLayout()
  const [tree, setTree] = useState(null)
  const rev = useRef(null)          // the tree's version when this copy was loaded; saves from a stale copy are refused
  const [dirty, setDirty] = useState(false)
  const [sel, setSel] = useState(null)
  const [collapsed, setCollapsed] = useState(() => new Set())
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [asList, setAsList] = useState(false)
  const [truth, setTruth] = useState(false)
  const [trunk, setTrunk] = useState(true)        // final scheme at the bottom, like a trunk; clues on the branches above
  const [cardOpen, setCardOpen] = useState(() => { try { const v = localStorage.getItem('nm-conspiracy-card'); return v ? v === 'open' : window.innerWidth >= 600 } catch { return true } })   // phones start folded
  const toggleCard = () => setCardOpen(v => { try { localStorage.setItem('nm-conspiracy-card', v ? 'closed' : 'open') } catch {} return !v })
  const [full, setFull] = useState(false)          // the board opened over the whole window
  const [bands, setBands] = useState(true)        // pyramid: one coloured band per arc
  const [arcLabels, setArcLabels] = useState([])
  const [fresh, setFresh] = useState(() => new Set())
  const [proposal, setProposal] = useState(null)      // { nodes, replace } waiting for accept / decline
  const [decisions, setDecisions] = useState({})
  const [dimmed, setDimmed] = useState(() => new Set())

  const load = useCallback(() => api.conspiracy(projectId).then(r => { rev.current = r.rev || null; const c = r.conspiracy || {}; setTree({ ...c, pending: null }); if (c.pending) { setProposal({ nodes: c.pending.nodes, replace: c.pending.replace }); setDecisions({}) } setArcLabels((r.arcs || []).map(a => a.label)); setDirty(false); setErr('') }).catch(e => setErr(e.message || 'Could not load the Conspiracy tab')), [projectId])
  useEffect(() => { load() }, [load])

  const nodes = tree?.nodes || []
  const kids = useKids(nodes)
  const shown = useMemo(() => (!proposal ? nodes : proposal.replace ? proposal.nodes : [...nodes, ...proposal.nodes]), [nodes, proposal])
  const shownKids = useKids(shown)
  const pending = useMemo(() => new Set((proposal?.nodes || []).map(n => n.id)), [proposal])
  const node = nodes.find(n => n.id === sel) || null
  const edit = n => { setTree(t => ({ ...t, nodes: t.nodes.map(x => (x.id === n.id ? n : x)) })); setDirty(true) }
  const toggle = id => setCollapsed(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  function addChild(parent) {
    const p = nodes.find(n => n.id === parent)
    const type = !p ? 'final_scheme' : p.type === 'final_scheme' ? 'scheme' : p.type === 'scheme' ? 'event' : p.type === 'false_flag' ? 'patsy' : p.type === 'agent' ? 'mistake' : 'clue'
    const n = { id: newId(), parent: parent || null, type, title: '', text: '', surface: '', who: '', arc: p?.arc ?? null, chapter: null, status: 'planned', sources: [] }
    setTree(t => ({ ...t, nodes: [...t.nodes, n] })); setSel(n.id); setDirty(true)
    if (parent) setCollapsed(s => { const x = new Set(s); x.delete(parent); return x })
  }
  function delBranch(id) {
    const gone = new Set([id]); let grew = true
    while (grew) { grew = false; nodes.forEach(n => { if (n.parent && gone.has(n.parent) && !gone.has(n.id)) { gone.add(n.id); grew = true } }) }
    setTree(t => ({ ...t, nodes: t.nodes.filter(n => !gone.has(n.id)) })); setSel(null); setDirty(true)
  }
  async function run(name, fn) {
    setBusy(name); setErr(''); setMsg('')
    try { await fn() } catch (e) { setErr(e.message || 'That failed') } finally { setBusy('') }
  }
  async function saveTree(t) {
    try {
      const r = await api.conspiracySave(projectId, t, rev.current)
      rev.current = r.rev || rev.current
      return r
    } catch (e) {
      if (String(e.message || '').includes('changed since you opened it')) load()
      throw e
    }
  }
  const withPending = t => ({ ...t, pending: proposal ? { nodes: proposal.nodes, replace: proposal.replace } : null })
  const save = () => run('save', async () => { const r = await saveTree(withPending(tree)); setTree({ ...r.conspiracy, pending: null }); setDirty(false); setMsg('✓ Saved. The planners see the whole tree; each chapter sees only what is pinned to it.') })
  const undo = () => run('undo', async () => { const r = await api.conspiracyUndo(projectId); if (r.rev) rev.current = r.rev; setTree(r.conspiracy); setDirty(false); setSel(null); setMsg('Undone.') })
  const build = () => run('build', async () => {
    const r = await api.conspiracyBuild(projectId, note); if (r.rev) rev.current = r.rev; propose(r, true)
    setMsg(`A new tree of ${r.proposed.length} slips is ready for review. Nothing has changed yet.`)
  })
  const grow = () => run('grow', async () => {
    if (dirty) { await saveTree(withPending(tree)); setDirty(false) }
    const r = await api.conspiracyGrow(projectId, note); if (r.rev) rev.current = r.rev; propose(r, false)
    setMsg(`${r.proposed.length} new slips are ready for review. Nothing is posted until you accept them.`)
  })
  const expand = n => run('expand', async () => {
    if (dirty) { await saveTree(withPending(tree)); setDirty(false) }
    const r = await api.conspiracyExpand(projectId, sel, n); if (r.rev) rev.current = r.rev; propose(r, false)
    setMsg(`${r.proposed.length} new slips are ready for review under this branch.`)
  })
  function propose(r, replace) {
    setProposal({ nodes: r.proposed || [], replace }); setDecisions({}); setSel(null)
  }
  function setDecision(id, d) {
    setDecisions(prev => {
      const next = { ...prev, [id]: d }
      if (d === 'decline') {            // a declined slip takes its proposed children with it
        let grew = true
        while (grew) { grew = false; proposal.nodes.forEach(n => { if (n.parent && next[n.parent] === 'decline' && next[n.id] !== 'decline') { next[n.id] = 'decline'; grew = true } }) }
      } else {                          // accepting a slip accepts the proposed parents it hangs from
        let cur = proposal.nodes.find(n => n.id === id)
        while (cur) { next[cur.id] = 'accept'; cur = proposal.nodes.find(n => n.id === cur.parent) }
      }
      return next
    })
  }
  const post = () => run('post', async () => {
    const keep = proposal.nodes.filter(n => decisions[n.id] === 'accept')
    const ids = new Set(keep.map(n => n.id))
    const fixed = keep.map(n => (proposal.replace && n.parent && !ids.has(n.parent) ? { ...n, parent: null } : n))
    const next = { ...tree, nodes: proposal.replace ? fixed : [...tree.nodes, ...fixed] }
    const r = await saveTree({ ...next, pending: null })
    setTree({ ...r.conspiracy, pending: null }); setDirty(false); setFresh(ids); setProposal(null); setDecisions({})
    setMsg(`✓ Posted ${keep.length} slips${proposal.replace ? ' as the new tree (the old one is on Undo)' : ''}. They are marked new until you reload.`)
  })

  if (err && !tree) return <div style={{ flex: 1, overflowY: 'auto', padding: 20, color: 'var(--red)', fontSize: 12 }}>{err}</div>
  if (!tree) return <div style={{ flex: 1, padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
  const winNarrow = typeof window !== 'undefined' && window.innerWidth < 768
  const list = full ? asList : (narrow || asList)
  const sheet = full && winNarrow && !asList        // phone board: panels open as a bottom sheet
  const counts = Object.keys(TYPES).map(k => [k, nodes.filter(n => n.type === k).length]).filter(([, c]) => c)

  const page = (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '12px 14px', gap: 10, minWidth: 0 }}>
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button onClick={toggleCard} aria-expanded={cardOpen} title={cardOpen ? 'Collapse' : 'Expand'}
              style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text-primary)' }}>
              <span aria-hidden style={{ display: 'inline-block', fontSize: 11, color: 'var(--text-muted)', transform: cardOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}>▶</span>
              <span style={{ fontFamily: SERIF, fontWeight: 600, fontSize: 15 }}>The conspiracy</span>
            </button>
            <button style={full ? btn : primary} onClick={() => setFull(v => !v)}>{full ? 'Close the board' : 'Open the board'}</button>
          </span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {cardOpen && <label style={{ ...muted, display: 'flex', alignItems: 'center', gap: 4 }} title="How long the book is planned to be. The tree is spread over volumes of about 150 chapters, each revealing one layer.">Book length
              <input style={{ ...field, width: 64 }} inputMode="numeric" value={tree.book_chapters ?? 1500} onChange={e => { setTree(t => ({ ...t, book_chapters: parseInt(e.target.value, 10) || 1500 })); setDirty(true) }} /> chapters</label>}
            {cardOpen && <label style={{ ...muted, display: 'flex', alignItems: 'center', gap: 4 }} title="Fix the number of arcs (each arc is a new district or sky layer of the city). Leave empty to plan volumes automatically.">Arcs
              <input style={{ ...field, width: 44 }} inputMode="numeric" value={tree.arcs_total ?? ''} placeholder="auto" onChange={e => { setTree(t => ({ ...t, arcs_total: parseInt(e.target.value, 10) || null })); setDirty(true) }} /></label>}
            {cardOpen && <label style={{ ...muted, display: 'flex', alignItems: 'center', gap: 4 }}>Revealed from arc
              <input style={{ ...field, width: 46 }} inputMode="numeric" value={tree.reveal_arc} onChange={e => { setTree(t => ({ ...t, reveal_arc: parseInt(e.target.value, 10) || 2 })); setDirty(true) }} /></label>}
            <div role="group" aria-label="What the slips show" style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
              {[[false, 'Cover story'], [true, 'Truth']].map(([v, l]) => (
                <button key={l} onClick={() => setTruth(v)} aria-pressed={truth === v}
                  style={{ fontSize: 10.5, padding: '4px 11px', border: 'none', background: truth === v ? (v ? '#9e2b25' : 'var(--bg-elevated)') : 'transparent', color: truth === v ? (v ? '#d8c79a' : 'var(--text-primary)') : 'var(--text-muted)', fontWeight: truth === v ? 700 : 400 }}>{l}</button>
              ))}
            </div>
            {(full || !narrow) && !asList && <button style={btn} onClick={() => setBands(v => !v)} aria-pressed={bands} title="Lay the tree out in one coloured band per arc">{bands ? 'Arc bands on' : 'Arc bands off'}</button>}
            {(full || !narrow) && !asList && <button style={btn} onClick={() => setTrunk(v => !v)} title="Flip the tree">{trunk ? 'Trunk at the bottom' : 'Final scheme at the top'}</button>}
            {(full || !narrow) && <button style={btn} onClick={() => setAsList(v => !v)}>{asList ? 'Board' : 'List'}</button>}
            {!nodes.length && <button style={btn} onClick={() => addChild(null)}>＋ Final scheme</button>}
            <button style={btn} disabled={!!busy} onClick={undo}>↶ Undo</button>
            <button style={primary} disabled={!!busy || !dirty} onClick={save}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
        {cardOpen && (<>
        {!full && <div style={muted}>
          The hidden scheme, worked backwards: the final scheme, the minor schemes that serve it, the events, false flags (each with the patsy framed for it) and cover-ups that carry them out, and the clues, breadcrumbs and mistakes the hero can find. The arc and chapter planners see the whole tree as a secret; each chapter's writer sees only what is pinned to that chapter.
        </div>}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <textarea rows={2} style={{ ...field, flex: '1 1 260px', resize: 'vertical' }} value={note} onChange={e => setNote(e.target.value)}
            placeholder="New material to weave in, or a direction (e.g. the garrison captain is being blackmailed; a second false flag at the postern gate)" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <button style={primary} disabled={!!busy || !nodes.length || !!(proposal && proposal.replace)} onClick={grow} title="Add new schemes, false flags, patsies and clues to the tree you have, keeping everything">
              {busy === 'grow' ? '✦ Growing… (a few minutes)' : '✦ Grow the tree'}</button>
            <button style={btn} disabled={!!busy || !!proposal} onClick={build} title="Throw the tree away and work it out again from the final scheme (the old tree stays on Undo)">
              {busy === 'build' ? 'Reverse-engineering… (several minutes)' : 'Rebuild from scratch'}</button>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {Object.entries(TYPES).map(([k, t]) => {
            const c = counts.find(x => x[0] === k), off = dimmed.has(k)
            return (
              <button key={k} aria-pressed={!off} title={off ? `Show ${t.label.toLowerCase()} slips` : `Fade ${t.label.toLowerCase()} slips`}
                onClick={() => setDimmed(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })}
                style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, padding: '3px 8px', borderRadius: 3, background: 'transparent', border: '1px solid var(--border-soft)', color: off ? 'var(--text-muted)' : 'var(--text-secondary)', opacity: off ? 0.55 : 1 }}>
                <span style={{ width: 12, height: 4, background: t.color, borderRadius: 1 }} />{t.label}{c ? <span style={{ color: 'var(--text-muted)' }}>{c[1]}</span> : null}
              </button>)
          })}
        </div>
        </>)}
        {cardOpen && (() => { const vs = bookVolumes(tree.book_chapters || 1500, tree.arcs_total); return (
          <div style={{ ...muted, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }} title="Each volume is a new map; volumes grow as the book goes on, then a shorter finale. One layer of the conspiracy is exposed per volume.">
            <span>{tree.arcs_total ? 'Arcs:' : 'Volumes:'}</span>
            {vs.map(v => <span key={v.volume} style={{ padding: '1px 6px', border: '1px solid var(--border-soft)', borderRadius: 3 }}>{v.volume}: ch {v.chapters[0]}-{v.chapters[1]}</span>)}
          </div>) })()}
        {msg && <div style={{ ...muted, color: 'var(--green)' }}>{msg}</div>}
        {err && <div style={{ ...muted, color: 'var(--red)' }}>{err}</div>}
        {dirty && <div style={muted}>Unsaved changes.</div>}
      </div>

      <div style={{ flex: 1, display: 'flex', gap: 10, minHeight: 0, flexDirection: list || (full && winNarrow) ? 'column' : 'row', overflowY: list || (full && winNarrow) ? 'auto' : 'hidden' }}>
        {!shown.length
          ? <div style={{ ...muted, padding: 20 }}>No conspiracy yet. Reverse-engineer one from your lore and secrets, or add the final scheme yourself and work down from it.</div>
          : list
            ? <ListView kids={shownKids} selected={sel} onSelect={setSel} collapsed={collapsed} onToggle={toggle} />
            : <Graph nodes={shown} kids={shownKids} selected={sel} onSelect={setSel} collapsed={collapsed} onToggle={toggle} truth={truth} dimmed={dimmed} fresh={fresh} pending={pending} decisions={decisions} trunk={trunk} bands={bands} revealArc={tree.reveal_arc} arcLabels={arcLabels} bookChapters={tree.book_chapters} arcsTotal={tree.arcs_total} />}
        {proposal && (
          <div style={{ ...(sheet ? SHEET : {}), width: list || sheet ? 'auto' : 340, flexShrink: 0, display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 12 }}>
            <ReviewPanel proposal={proposal} decisions={decisions} setDecision={setDecision} baseNodes={nodes} onPost={post}
              onDiscard={() => run('discard', async () => { const r = await saveTree({ ...tree, pending: null }); setTree({ ...r.conspiracy, pending: null }); setProposal(null); setDecisions({}); setMsg('Discarded. Nothing was changed.') })} selected={sel} onSelect={setSel} busy={busy} />
          </div>
        )}
        {!proposal && node && (
          <div style={{ ...(sheet ? SHEET : {}), width: list || sheet ? 'auto' : 300, flexShrink: 0, overflowY: 'auto', background: 'var(--bg-card)', border: '1px solid var(--border-soft)', borderRadius: 'var(--radius-lg)', padding: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: (TYPES[node.type] || TYPES.scheme).color }}>{(TYPES[node.type] || TYPES.scheme).label}</span>
              <button style={btn} onClick={() => setSel(null)}>✕</button>
            </div>
            <NodeEditor node={node} onChange={edit} onAddChild={() => addChild(node.id)} onDelete={() => delBranch(node.id)} onExpand={expand} busy={busy} />
          </div>
        )}
      </div>
    </div>
  )
  return full
    ? createPortal(<div role="dialog" aria-label="The conspiracy board" onKeyDown={e => { if (e.key === 'Escape') setFull(false) }}
        style={{ position: 'fixed', inset: 0, zIndex: 240, background: 'var(--bg-base, #0d0b12)', display: 'flex' }}>{page}</div>, document.body)
    : page
}
