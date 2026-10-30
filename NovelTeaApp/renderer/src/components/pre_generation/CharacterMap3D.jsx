import { useEffect, useRef } from 'react'
import * as THREE from 'three'

/* CharacterMap3D — a 3D character web, not a location map.
   One dot per character, clustered by relationship (role + faction similarity
   pull characters who'd realistically interact close together), revealed in
   layers as the selected chapter's dropdown advances — characters not yet
   introduced by that chapter are hidden entirely, not just dimmed.
   Click a dot to select that character; drag to orbit, wheel/pinch to zoom. */

const ROLE_COLOR = {
  protagonist: '#f59e0b', antagonist: '#ef4444', minor_antagonist: '#f97316',
  ally: '#10b981', rival: '#eab308', mentor: '#8b5cf6', love_interest: '#ec4899',
  side: '#3b82f6', beast: '#14b8a6',
}
const DEFAULT_COLOR = '#6366f1'

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

export default function CharacterMap3D({ characters, onSelect, style }) {
  // characters: [{ name, role, faction, firstChapter, visible (already
  // filtered by caller for the selected chapter layer) }]
  const mountRef = useRef(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const charsRef = useRef(characters)
  charsRef.current = characters

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
    const camera = new THREE.PerspectiveCamera(50, (container.clientWidth || 1) / (container.clientHeight || 1), 0.1, 100)
    camera.position.set(0, 0, 7)

    const group = new THREE.Group()
    scene.add(group)

    // faint starfield backdrop so orbiting reads as genuinely 3D
    const starGeo = new THREE.BufferGeometry()
    const starCount = 300
    const starPos = new Float32Array(starCount * 3)
    for (let i = 0; i < starCount; i++) {
      const r = 20 + Math.random() * 15
      const theta = Math.random() * Math.PI * 2, phi = Math.acos(2 * Math.random() - 1)
      starPos[i * 3] = r * Math.sin(phi) * Math.cos(theta)
      starPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      starPos[i * 3 + 2] = r * Math.cos(phi)
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3))
    scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0x334, size: 0.05, transparent: true, opacity: 0.5 })))

    const glowCache = {}
    function glowTex(color) {
      if (!glowCache[color]) glowCache[color] = makeGlowTexture(color)
      return glowCache[color]
    }

    // ---- layout: relationship clustering via a tiny force simulation ----
    // Same faction pulls together; protagonist anchors center; everything
    // else repels so dots don't overlap. Computed once per character-set.
    function layout(chars) {
      const n = chars.length
      const pos = chars.map((c, i) => {
        const a = (i / Math.max(n, 1)) * Math.PI * 2
        return new THREE.Vector3(Math.cos(a) * 2.4, Math.sin(a) * 2.4, (Math.random() - 0.5) * 1.5)
      })
      const factionKey = c => (c.faction || '').split('(')[0].trim().toLowerCase()
      for (let iter = 0; iter < 200; iter++) {
        const disp = pos.map(() => new THREE.Vector3())
        for (let a = 0; a < n; a++) {
          for (let b = a + 1; b < n; b++) {
            const delta = pos[a].clone().sub(pos[b])
            let dist = delta.length() || 0.01
            const sameFaction = factionKey(chars[a]) && factionKey(chars[a]) === factionKey(chars[b])
            const restLen = sameFaction ? 1.1 : 2.6
            const force = (restLen - dist) * 0.02
            delta.normalize().multiplyScalar(force)
            disp[a].add(delta); disp[b].sub(delta)
          }
          // protagonist gravity well at center
          if (chars[a].role === 'protagonist') {
            disp[a].add(pos[a].clone().multiplyScalar(-0.03))
          }
        }
        for (let i = 0; i < n; i++) pos[i].add(disp[i])
      }
      return pos
    }

    let nodes = []      // { mesh, glow, char, basePos }
    let pickables = []

    function buildNodes(chars) {
      // clear old
      nodes.forEach(nd => { group.remove(nd.mesh); group.remove(nd.glow); group.remove(nd.label) })
      nodes = []; pickables = []
      const positions = layout(chars)
      chars.forEach((c, i) => {
        const color = ROLE_COLOR[c.role] || DEFAULT_COLOR
        const p = positions[i]

        const core = new THREE.Mesh(
          new THREE.SphereGeometry(0.11, 16, 16),
          new THREE.MeshBasicMaterial({ color })
        )
        core.position.copy(p)
        core.userData.charName = c.name
        group.add(core)
        pickables.push(core)

        const glow = new THREE.Sprite(new THREE.SpriteMaterial({
          map: glowTex(color), blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.85,
        }))
        glow.position.copy(p)
        glow.scale.set(0.55, 0.55, 1)
        group.add(glow)

        // sprite-based text label (canvas texture) above the dot
        const labelCanvas = document.createElement('canvas')
        labelCanvas.width = 256; labelCanvas.height = 64
        const lctx = labelCanvas.getContext('2d')
        lctx.font = '600 28px system-ui, sans-serif'
        lctx.fillStyle = '#fff'
        lctx.textAlign = 'center'
        lctx.shadowColor = 'rgba(0,0,0,0.9)'
        lctx.shadowBlur = 6
        lctx.fillText(c.name.length > 18 ? c.name.slice(0, 16) + '…' : c.name, 128, 40)
        const labelTex = new THREE.CanvasTexture(labelCanvas)
        const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: labelTex, transparent: true, depthWrite: false }))
        label.position.copy(p).add(new THREE.Vector3(0, 0.28, 0))
        label.scale.set(1.1, 0.28, 1)
        group.add(label)

        nodes.push({ mesh: core, glow, label, char: c, basePos: p })
      })
    }
    buildNodes(charsRef.current.filter(c => c.visible))

    let lastCharKey = charsRef.current.filter(c => c.visible).map(c => c.name).join('|')
    const rebuildInterval = setInterval(() => {
      if (disposed) return
      const visible = charsRef.current.filter(c => c.visible)
      const key = visible.map(c => c.name).join('|')
      if (key !== lastCharKey) {
        lastCharKey = key
        buildNodes(visible)
      }
    }, 300)

    // ---- interaction: drag to orbit, wheel/pinch to zoom, click to select ----
    const ray = new THREE.Raycaster()
    const mouseNDC = new THREE.Vector2()
    let dragging = false, moved = 0, lastX = 0, lastY = 0
    let yaw = 0.4, pitch = 0.1, autoSpin = true, idleTimer = null
    let targetZoom = 7
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
      pitch = Math.max(-1.3, Math.min(1.3, pitch + dy * 0.005))
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
        selectedName = hits[0].object.userData.charName
        const nd = nodes.find(n => n.char.name === selectedName)
        onSelectRef.current && onSelectRef.current(nd ? nd.char : null)
      } else {
        selectedName = null
        onSelectRef.current && onSelectRef.current(null)
      }
    }
    function onWheel(e) {
      e.preventDefault()
      targetZoom = Math.max(3, Math.min(14, targetZoom + e.deltaY * 0.004))
    }
    let pinchDist = 0
    function onTouchMove(e) {
      if (e.touches.length === 2) {
        const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY)
        if (pinchDist) targetZoom = Math.max(3, Math.min(14, targetZoom - (d - pinchDist) * 0.02))
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

      if (autoSpin) yaw += dt * 0.12
      group.rotation.y = yaw
      group.rotation.x = pitch
      camera.position.z += (targetZoom - camera.position.z) * 0.08

      nodes.forEach(nd => {
        const isSel = nd.char.name === selectedName
        const tw = 0.85 + 0.15 * Math.sin(t * 2 + nd.basePos.x * 3)
        const s = (isSel ? 0.85 : 0.55) * tw
        nd.glow.scale.set(s, s, 1)
        nd.mesh.scale.setScalar(isSel ? 1.3 : 1)
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

  return <div ref={mountRef} style={{ width: '100%', height: 420, borderRadius: 8, overflow: 'hidden', ...style }} />
}
