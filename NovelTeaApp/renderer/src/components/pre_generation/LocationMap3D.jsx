import { useEffect, useRef } from 'react'
import * as THREE from 'three'

/* LocationMap3D — a real 3D gridded wireframe of local geography, replacing
   the flat 2D SVG. Locations float above a wireframe floor grid; connections
   are drawn as colored 3D lines (color = relation type, same legend as
   before); drag to orbit, wheel/pinch to zoom, click a node for its info.
   Layout is a force-directed graph extended into 3D (adjacency drives
   position, not hand-placed coordinates) — still built purely from
   location_map data, nothing invented. */

function classifyRelation(relation) {
  const r = (relation || '').toLowerCase()
  if (r.includes('wall') || r.includes('adjacent') || r.includes('same building') || r.includes('same complex'))
    return { color: '#10b981', label: 'Adjacent' }
  if (r.includes('visible') || r.includes('sightline') || r.includes('overlook'))
    return { color: '#06b6d4', label: 'Visible from' }
  if (r.match(/\d+\s*(min|hour)/) || r.includes('walk') || r.includes('path') || r.includes('switchback') || r.includes('downhill') || r.includes('uphill'))
    return { color: '#f59e0b', label: 'Walking distance' }
  return { color: '#9ca3af', label: 'Related' }
}

function nodeColor(degree, maxDegree) {
  if (maxDegree <= 0) return '#7c3aed'
  const t = degree / maxDegree
  if (t >= 0.66) return '#ef4444'
  if (t >= 0.33) return '#f59e0b'
  return '#3b82f6'
}

function makeGlowTexture(color) {
  const c = document.createElement('canvas'); c.width = c.height = 128
  const g = c.getContext('2d')
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64)
  grad.addColorStop(0, 'rgba(255,255,255,1)')
  grad.addColorStop(0.35, color)
  grad.addColorStop(1, 'rgba(0,0,0,0)')
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128)
  return new THREE.CanvasTexture(c)
}

export default function LocationMap3D({ locations, asOfChapter = null, onSelect, style }) {
  const mountRef = useRef(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const dataRef = useRef({ locations, asOfChapter })
  dataRef.current = { locations, asOfChapter }

  useEffect(() => {
    const container = mountRef.current
    if (!container) return
    let disposed = false

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    renderer.setSize(container.clientWidth || 1, container.clientHeight || 1)
    renderer.setClearColor(0x05050a, 1)
    container.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'
    renderer.domElement.style.touchAction = 'none'

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(50, (container.clientWidth || 1) / (container.clientHeight || 1), 0.1, 200)
    camera.position.set(6, 5, 9)

    const group = new THREE.Group()
    scene.add(group)

    // wireframe floor grid — the literal "gridded 3D wireframe" ask
    const grid = new THREE.GridHelper(20, 20, 0x7c3aed, 0x22222e)
    grid.position.y = -2.2
    grid.material.transparent = true
    grid.material.opacity = 0.35
    group.add(grid)
    // secondary vertical grid walls for depth cues
    const gridBack = new THREE.GridHelper(20, 20, 0x334, 0x1a1a24)
    gridBack.rotation.x = Math.PI / 2
    gridBack.position.z = -10
    gridBack.material.transparent = true
    gridBack.material.opacity = 0.12
    group.add(gridBack)

    const glowCache = {}
    function glowTex(color) {
      if (!glowCache[color]) glowCache[color] = makeGlowTexture(color)
      return glowCache[color]
    }

    let nodeObjs = []       // { core, glow, label, loc, discovered }
    let edgeObjs = []       // { line, dot, discovered }
    let pickables = []

    function layout(locs) {
      const n = locs.length
      const nameIdx = Object.fromEntries(locs.map((l, i) => [l.name, i]))
      const edges = []
      locs.forEach((l, i) => {
        (l.connections || []).forEach(c => {
          const j = nameIdx[c.to]
          if (j != null && j !== i) edges.push({ i, j })
        })
      })
      let pos = locs.map((_, i) => {
        const a = (i / Math.max(n, 1)) * Math.PI * 2
        return new THREE.Vector3(Math.cos(a) * 3, (Math.random() - 0.5) * 2, Math.sin(a) * 3)
      })
      for (let iter = 0; iter < 220; iter++) {
        const disp = pos.map(() => new THREE.Vector3())
        for (let a = 0; a < n; a++) {
          for (let b = a + 1; b < n; b++) {
            const delta = pos[a].clone().sub(pos[b])
            let dist = delta.length() || 0.01
            const force = (2.6 * 2.6) / (dist * dist) * 0.4
            delta.normalize().multiplyScalar(force)
            disp[a].add(delta); disp[b].sub(delta)
          }
        }
        edges.forEach(e => {
          const delta = pos[e.i].clone().sub(pos[e.j])
          let dist = delta.length() || 0.01
          const force = (dist - 2.2) * 0.05
          delta.normalize().multiplyScalar(force)
          disp[e.i].sub(delta); disp[e.j].add(delta)
        })
        pos = pos.map((p, i) => {
          const np = p.clone().add(disp[i])
          np.y = Math.max(-1.6, Math.min(3, np.y))
          return np
        })
      }
      return { pos, edges }
    }

    function buildScene(locs, asOf) {
      nodeObjs.forEach(o => { group.remove(o.core); group.remove(o.glow); group.remove(o.label) })
      edgeObjs.forEach(o => { group.remove(o.line); group.remove(o.dot) })
      nodeObjs = []; edgeObjs = []; pickables = []

      const { pos, edges } = layout(locs)
      const degree = locs.map((_, i) => edges.filter(e => e.i === i || e.j === i).length)
      const maxDegree = Math.max(1, ...degree)

      edges.forEach(e => {
        const a = locs[e.i], b = locs[e.j]
        const conn = (a.connections || []).find(c => c.to === b.name)
        const cls = classifyRelation(conn?.relation)
        const discovered = asOf == null || (conn?.chapter ?? 0) <= asOf
        const geo = new THREE.BufferGeometry().setFromPoints([pos[e.i], pos[e.j]])
        const mat = new THREE.LineBasicMaterial({ color: cls.color, transparent: true, opacity: discovered ? 0.8 : 0.06 })
        const line = new THREE.Line(geo, mat)
        group.add(line)
        const mid = pos[e.i].clone().add(pos[e.j]).multiplyScalar(0.5)
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 8), new THREE.MeshBasicMaterial({ color: cls.color, transparent: true, opacity: discovered ? 1 : 0.08 }))
        dot.position.copy(mid)
        group.add(dot)
        edgeObjs.push({ line, dot, discovered })
      })

      locs.forEach((l, i) => {
        const discovered = asOf == null || (l.chapter ?? 0) <= asOf
        const color = discovered ? nodeColor(degree[i], maxDegree) : '#444455'
        const rad = 0.14 + Math.min(degree[i], 6) * 0.02

        const core = new THREE.Mesh(new THREE.SphereGeometry(rad, 20, 20), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: discovered ? 1 : 0.15 }))
        core.position.copy(pos[i])
        core.userData.locName = l.name
        group.add(core)
        if (discovered) pickables.push(core)

        const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(color), blending: THREE.AdditiveBlending, depthWrite: false, opacity: discovered ? 0.8 : 0.08 }))
        glow.position.copy(pos[i])
        glow.scale.set(0.9, 0.9, 1)
        group.add(glow)

        const labelCanvas = document.createElement('canvas')
        labelCanvas.width = 256; labelCanvas.height = 64
        const lctx = labelCanvas.getContext('2d')
        lctx.font = '600 24px system-ui, sans-serif'
        lctx.fillStyle = discovered ? '#fff' : '#666'
        lctx.textAlign = 'center'
        lctx.shadowColor = 'rgba(0,0,0,0.9)'
        lctx.shadowBlur = 6
        lctx.fillText(l.name.length > 24 ? l.name.slice(0, 22) + '…' : l.name, 128, 40)
        const labelTex = new THREE.CanvasTexture(labelCanvas)
        const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: labelTex, transparent: true, depthWrite: false, opacity: discovered ? 1 : 0.3 }))
        label.position.copy(pos[i]).add(new THREE.Vector3(0, 0.35, 0))
        label.scale.set(1.4, 0.35, 1)
        group.add(label)

        // vertical drop-line to the floor grid for spatial grounding
        const dropGeo = new THREE.BufferGeometry().setFromPoints([pos[i], new THREE.Vector3(pos[i].x, -2.2, pos[i].z)])
        const dropLine = new THREE.Line(dropGeo, new THREE.LineBasicMaterial({ color: 0x444455, transparent: true, opacity: discovered ? 0.25 : 0.04 }))
        group.add(dropLine)

        nodeObjs.push({ core, glow, label, dropLine, loc: l, discovered })
      })
    }

    let lastKey = ''
    buildScene(dataRef.current.locations, dataRef.current.asOfChapter)
    lastKey = dataRef.current.locations.map(l => l.name).join('|') + '@' + dataRef.current.asOfChapter

    const rebuildInterval = setInterval(() => {
      if (disposed) return
      const { locations: locs, asOfChapter: asOf } = dataRef.current
      const key = locs.map(l => l.name).join('|') + '@' + asOf
      if (key !== lastKey) {
        lastKey = key
        buildScene(locs, asOf)
      }
    }, 300)

    const ray = new THREE.Raycaster()
    const mouseNDC = new THREE.Vector2()
    let dragging = false, moved = 0, lastX = 0, lastY = 0
    let yaw = 0.6, pitch = 0.35, autoSpin = true, idleTimer = null
    let targetZoom = 11
    let selectedName = null

    function onDown(e) {
      dragging = true; moved = 0
      lastX = e.clientX; lastY = e.clientY
      container.style.cursor = 'grabbing'
    }
    function onMove(e) {
      if (!dragging) return
      const dx = e.clientX - lastX, dy = e.clientY - lastY
      moved += Math.abs(dx) + Math.abs(dy)
      lastX = e.clientX; lastY = e.clientY
      yaw += dx * 0.006
      pitch = Math.max(-0.1, Math.min(1.4, pitch + dy * 0.005))
      autoSpin = false
      clearTimeout(idleTimer)
      idleTimer = setTimeout(() => { autoSpin = true }, 3200)
    }
    function onUp(e) {
      container.style.cursor = 'grab'
      if (!dragging) return
      dragging = false
      if (moved < 6) pick(e.clientX, e.clientY)
    }
    function pick(cx, cy) {
      const r = renderer.domElement.getBoundingClientRect()
      mouseNDC.x = ((cx - r.left) / r.width) * 2 - 1
      mouseNDC.y = -((cy - r.top) / r.height) * 2 + 1
      ray.setFromCamera(mouseNDC, camera)
      const hits = ray.intersectObjects(pickables, false)
      if (hits.length) {
        selectedName = hits[0].object.userData.locName
        const nd = nodeObjs.find(n => n.loc.name === selectedName)
        onSelectRef.current && onSelectRef.current(nd ? nd.loc : null)
      } else {
        selectedName = null
        onSelectRef.current && onSelectRef.current(null)
      }
    }
    function onWheel(e) {
      e.preventDefault()
      targetZoom = Math.max(4, Math.min(22, targetZoom + e.deltaY * 0.006))
    }
    let pinchDist = 0
    function onTouchMove(e) {
      if (e.touches.length === 2) {
        const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY)
        if (pinchDist) targetZoom = Math.max(4, Math.min(22, targetZoom - (d - pinchDist) * 0.03))
        pinchDist = d
      }
    }
    function onTouchEnd() { pinchDist = 0 }

    container.style.cursor = 'grab'
    container.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    container.addEventListener('wheel', onWheel, { passive: false })
    container.addEventListener('touchmove', onTouchMove, { passive: true })
    container.addEventListener('touchend', onTouchEnd)

    const ro = new ResizeObserver(() => {
      const w = container.clientWidth || 1, h = container.clientHeight || 1
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    })
    ro.observe(container)

    const timer = new THREE.Timer()
    let rafId = 0
    function animate() {
      if (disposed) return
      rafId = requestAnimationFrame(animate)
      timer.update()
      const dt = Math.min(timer.getDelta(), 0.05)
      const t = timer.getElapsed()

      if (autoSpin) yaw += dt * 0.1
      const camDist = targetZoom
      camera.position.x += ((Math.sin(yaw) * Math.cos(pitch)) * camDist - camera.position.x) * 0.08
      camera.position.y += ((Math.sin(pitch)) * camDist - camera.position.y) * 0.08
      camera.position.z += ((Math.cos(yaw) * Math.cos(pitch)) * camDist - camera.position.z) * 0.08
      camera.lookAt(0, 0, 0)

      nodeObjs.forEach(nd => {
        const isSel = nd.loc.name === selectedName
        const tw = 0.85 + 0.15 * Math.sin(t * 2 + nd.core.position.x * 3)
        const s = (isSel ? 1.4 : 0.9) * tw
        nd.glow.scale.set(s, s, 1)
        nd.core.scale.setScalar(isSel ? 1.35 : 1)
      })

      renderer.render(scene, camera)
    }
    animate()

    return () => {
      disposed = true
      cancelAnimationFrame(rafId)
      clearInterval(rebuildInterval)
      clearTimeout(idleTimer)
      ro.disconnect()
      container.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      container.removeEventListener('wheel', onWheel)
      container.removeEventListener('touchmove', onTouchMove)
      container.removeEventListener('touchend', onTouchEnd)
      renderer.dispose()
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <div ref={mountRef} style={{ width: '100%', height: 460, borderRadius: 8, overflow: 'hidden', ...style }} />
}
