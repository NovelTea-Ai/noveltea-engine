import { useEffect, useRef } from 'react'
import * as THREE from 'three'

/* NeuralBrain — the 3D node mesh, shaped like a teapot pouring into a teacup.
   One reusable Three.js scene:
     • data mode (corpus page): each corpus novel owns a contiguous cortex
       region; clicking any node fires that whole novel's region and reports
       it via onSelect. The teacup = the pipeline, the stream = the core.
     • ambient mode (boot screen): no data, just the teapot, autospin only.
   All assets are procedural (canvas textures) — nothing fetched, works offline. */

const LOBE_DESCRIPTIONS = {
  'Teapot Body': 'Where the story steeps: premise, cast and world, brewing before anything is poured.',
  'Teapot Lid': 'Kept closed on purpose: the secrets the reader is not meant to see yet.',
  'Teapot Spout': 'How the plan pours out, one scene at a time.',
  'Teapot Handle': 'Your hold on the whole book: voice, rules and direction.',
  Stream: 'The pour itself: each choice you make as the chapter flows.',
  Teacup: 'The finished page, ready to read.',
}

export default function NeuralBrain({ data = null, interactive = true, onSelect, style }) {
  const mountRef = useRef(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  useEffect(() => {
    const container = mountRef.current
    if (!container) return
    let disposed = false

    /* ---------- renderer / scene ---------- */
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    renderer.setSize(container.clientWidth || 1, container.clientHeight || 1)
    renderer.setClearColor(0x000000, 1)
    container.appendChild(renderer.domElement)
    renderer.domElement.style.display = 'block'
    renderer.domElement.style.touchAction = 'none'

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(
      45, (container.clientWidth || 1) / (container.clientHeight || 1), 0.1, 100)
    camera.position.set(0, 0.15, 4.6)

    const brainGroup = new THREE.Group()
    scene.add(brainGroup)
    // on the splash (no data) the boot log covers the lower part of the screen: lift the teapot and cup clear of it
    if (!data) { brainGroup.position.y = 0.55; brainGroup.scale.setScalar(0.88) }

    /* ---------- glow textures ---------- */
    function makeGlowTexture(inner, outer) {
      const c = document.createElement('canvas'); c.width = c.height = 128
      const g = c.getContext('2d')
      const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64)
      grad.addColorStop(0, inner)
      grad.addColorStop(0.25, outer)
      grad.addColorStop(1, 'rgba(0,0,0,0)')
      g.fillStyle = grad; g.fillRect(0, 0, 128, 128)
      return new THREE.CanvasTexture(c)
    }
    const nodeGlowTex = makeGlowTexture('rgba(220,245,255,1)', 'rgba(90,160,255,0.55)')
    const hazeTex = makeGlowTexture('rgba(120,40,200,0.30)', 'rgba(80,20,150,0.10)')
    const pulseTex = makeGlowTexture('rgba(255,255,255,1)', 'rgba(140,220,255,0.6)')

    const haze = new THREE.Sprite(new THREE.SpriteMaterial({
      map: hazeTex, blending: THREE.AdditiveBlending, depthWrite: false,
    }))
    haze.scale.set(7, 6, 1)
    scene.add(haze)

    /* ---------- the teapot pouring into a teacup (the mesh the nodes live on) ---------- */
    const V = (x, y, z) => new THREE.Vector3(x, y, z)
    const NODES = []
    const GOLDEN = Math.PI * (3 - Math.sqrt(5))
    // points spread evenly over a unit sphere, then shaped by `shape`
    function sphere(n, shape, kind, region) {
      for (let i = 0; i < n; i++) {
        const yy = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - yy * yy), th = GOLDEN * i
        NODES.push({ pos: shape(Math.cos(th) * r, yy, Math.sin(th) * r), kind, region })
      }
    }
    // a ring of n points around a centre, in the x/z plane
    function ring(n, cx, cy, cz, rx, rz, phase, kind, region) {
      for (let i = 0; i < n; i++) {
        const a = phase + (i / n) * Math.PI * 2
        NODES.push({ pos: V(cx + Math.cos(a) * rx, cy, cz + Math.sin(a) * rz), kind, region })
      }
    }

    // teapot body: a rounded, slightly flattened belly
    sphere(56, (x, y, z) => {
      let py = y
      if (py < -0.75) py = -0.75 + (py + 0.75) * 0.3
      return V(-0.55 + x * 0.66, 0.30 + py * 0.50, z * 0.52)
    }, 'cortex', 'Teapot Body')
    // lid and knob
    ring(8, -0.55, 0.80, 0, 0.26, 0.26, 0, 'cortex', 'Teapot Lid')
    NODES.push({ pos: V(-0.55, 0.93, 0), kind: 'cortex', region: 'Teapot Lid' })
    NODES.push({ pos: V(-0.55, 1.03, 0), kind: 'cortex', region: 'Teapot Lid' })
    // spout: four rings climbing out to the right, narrowing toward the tip
    for (let k = 0; k < 4; k++) {
      const t = k / 3, cx = -0.05 + 0.60 * t, cy = 0.18 + 0.50 * t, rad = 0.15 - 0.08 * t
      const dx = 0.60, dy = 0.50, len = Math.hypot(dx, dy), nx = -dy / len, ny = dx / len
      for (let j = 0; j < 5; j++) {
        const a = (j / 5) * Math.PI * 2 + k * 0.4
        NODES.push({ pos: V(cx + nx * rad * Math.cos(a), cy + ny * rad * Math.cos(a), rad * Math.sin(a)), kind: 'cortex', region: 'Teapot Spout' })
      }
    }
    // handle: a loop on the left
    for (let k = 0; k < 6; k++) {
      const th = (k / 5) * Math.PI
      for (const z of [-0.05, 0.05]) {
        NODES.push({ pos: V(-1.12 - 0.42 * Math.sin(th), 0.31 + 0.31 * Math.cos(th), z), kind: 'cortex', region: 'Teapot Handle' })
      }
    }
    // the pour: a thin stream falling from the spout tip into the cup
    for (let k = 0; k < 9; k++) {
      const t = k / 8
      NODES.push({ pos: V(0.54 + 0.20 * t * t, 0.68 - 0.98 * t, 0), kind: 'stem', region: 'Stream' })
    }
    // teacup: four rings narrowing toward the base, a saucer and a small handle
    ;[[-0.30, 0.42], [-0.48, 0.38], [-0.68, 0.30], [-0.86, 0.17]].forEach(([y, r], k) => ring(9, 0.74, y, 0, r, r, k * 0.35, 'cerebellum', 'Teacup'))
    ring(12, 0.74, -1.00, 0, 0.62, 0.62, 0.2, 'cerebellum', 'Teacup')
    for (let k = 0; k < 6; k++) {
      const th = -Math.PI / 2 + (k / 5) * Math.PI
      NODES.push({ pos: V(1.14 + 0.22 * Math.cos(th), -0.58 + 0.20 * Math.sin(th), 0), kind: 'cerebellum', region: 'Teacup' })
    }

    // a random point for the nebula dust: spread over the teapot, the teacup and the pour between them
    function teaPoint(u) {
      const r = Math.random(), k = 0.45 + Math.random() * 0.55
      if (r < 0.55) return V(-0.55 + u.x * 0.66 * k, 0.30 + u.y * 0.50 * k, u.z * 0.52 * k)
      if (r < 0.88) return V(0.74 + u.x * 0.46 * k, -0.65 + u.y * 0.36 * k, u.z * 0.46 * k)
      return V(0.35 + u.x * 0.30, 0.20 + u.y * 0.55, u.z * 0.10)
    }

    /* ---------- map corpus novels onto cortex regions ---------- */
    // Each novel owns a contiguous longitude slice of the cortex, sized by its
    // data richness. Cerebellum = pipeline, brainstem = core.
    const novels = data?.nodes?.length ? data.nodes : null
    if (novels) {
      const score = d => 1 + d.psych + d.reveals + d.prose * 0.05 + (d.schemes || 0) * 3 + (d.arcs || 0) * 2 + (d.genome_patterns || 0) * 5
      const total = novels.reduce((s, d) => s + score(d), 0)
      const cortex = NODES.filter(n => n.kind === 'cortex')
      cortex.sort((a, b) => a.pos.x - b.pos.x)      // left to right across the teapot
      let cursor = 0
      novels.forEach((d, ni) => {
        let count = Math.max(3, Math.round((score(d) / total) * cortex.length))
        if (ni === novels.length - 1) count = cortex.length - cursor
        for (let k = 0; k < count && cursor < cortex.length; k++, cursor++) {
          cortex[cursor].novelIdx = ni
        }
      })
      // any remainder → last novel
      for (; cursor < cortex.length; cursor++) cortex[cursor].novelIdx = novels.length - 1
    }

    /* ---------- edges ---------- */
    const EDGES = []
    const adjacency = NODES.map(() => [])
    {
      const K = 4, MAXD = 0.62, seen = new Set()
      for (let i = 0; i < NODES.length; i++) {
        const dists = []
        for (let j = 0; j < NODES.length; j++) {
          if (i === j) continue
          const d = NODES[i].pos.distanceTo(NODES[j].pos)
          if (d < MAXD) dists.push([d, j])
        }
        dists.sort((a, b) => a[0] - b[0])
        for (let k = 0; k < Math.min(K, dists.length); k++) {
          const j = dists[k][1]
          const key = i < j ? i + '_' + j : j + '_' + i
          if (seen.has(key)) continue
          seen.add(key)
          EDGES.push({ a: i, b: j })
          adjacency[i].push({ node: j, edge: EDGES.length - 1 })
          adjacency[j].push({ node: i, edge: EDGES.length - 1 })
        }
      }
    }

    const edgeGeo = new THREE.BufferGeometry()
    const ePos = new Float32Array(EDGES.length * 6)
    const eCol = new Float32Array(EDGES.length * 6)
    EDGES.forEach((e, i) => {
      const A = NODES[e.a].pos, B = NODES[e.b].pos
      ePos.set([A.x, A.y, A.z, B.x, B.y, B.z], i * 6)
    })
    edgeGeo.setAttribute('position', new THREE.BufferAttribute(ePos, 3))
    edgeGeo.setAttribute('color', new THREE.BufferAttribute(eCol, 3))
    const edgeMat = new THREE.LineBasicMaterial({
      vertexColors: true, blending: THREE.AdditiveBlending, transparent: true, opacity: 0.9, depthWrite: false,
    })
    brainGroup.add(new THREE.LineSegments(edgeGeo, edgeMat))

    const BASE_EDGE = new THREE.Color(0x6d1fb8)
    const HOT_EDGE = new THREE.Color(0x9fe8ff)
    const edgeHeat = new Float32Array(EDGES.length)

    /* ---------- node meshes + glows ---------- */
    const nodeCoreGeo = new THREE.SphereGeometry(0.028, 10, 10)
    const pickables = []
    NODES.forEach((n, i) => {
      const core = new THREE.Mesh(nodeCoreGeo, new THREE.MeshBasicMaterial({ color: 0xcfeaff }))
      core.position.copy(n.pos)
      core.userData.index = i
      brainGroup.add(core)
      pickables.push(core)

      const glow = new THREE.Sprite(new THREE.SpriteMaterial({
        map: nodeGlowTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0.85,
      }))
      glow.scale.set(0.16, 0.16, 1)
      glow.position.copy(n.pos)
      brainGroup.add(glow)

      n.core = core; n.glow = glow
      n.heat = 0
      n.baseGlow = 0.14 + Math.random() * 0.05
      n.twinkle = Math.random() * Math.PI * 2
    })

    /* ---------- nebula dust ---------- */
    const dustLayers = []
    {
      const randDir = () => new THREE.Vector3(Math.random() * 2 - 1, Math.random() * 2 - 1, Math.random() * 2 - 1).normalize()
      const CLUSTERS = 24, centers = []
      for (let c = 0; c < CLUSTERS; c++) {
        centers.push(teaPoint(randDir()))
      }
      const tmpP = new THREE.Vector3()
      const scatterPoint = (out) => {
        if (Math.random() < 0.72) {
          const c = centers[(Math.random() * CLUSTERS) | 0]
          out.copy(c).addScaledVector(randDir(), 0.22 * Math.pow(Math.random(), 1.7))
        } else {
          out.copy(teaPoint(randDir()))
        }
        return out
      }
      const makeLayer = (count, size, opacity) => {
        const pos = new Float32Array(count * 3)
        const col = new Float32Array(count * 3)
        const phase = new Float32Array(count)
        for (let i = 0; i < count; i++) {
          scatterPoint(tmpP)
          pos.set([tmpP.x, tmpP.y, tmpP.z], i * 3)
          phase[i] = Math.random()
        }
        const g = new THREE.BufferGeometry()
        g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
        g.setAttribute('color', new THREE.BufferAttribute(col, 3))
        const m = new THREE.PointsMaterial({
          vertexColors: true, size, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false,
        })
        brainGroup.add(new THREE.Points(g, m))
        // swarm flight state: start point, per-particle target offset, timing
        dustLayers.push({
          geo: g, col, phase, count, pos,
          start: pos.slice(),
          off: new Float32Array(count * 3),
          delay: new Float32Array(count),
          dur: new Float32Array(count),
          arrived: new Uint8Array(count),
        })
      }
      // slightly lighter than the standalone page — this runs inside the app
      makeLayer(1800, 0.010, 0.7)
      makeLayer(260, 0.026, 0.95)
    }

    /* ---------- dust swarm: every particle shoots like a meteor to one chosen
       node (vert). On impact the vert flares BLUE; when the swarm launches for
       the next vert it fades back to white. ---------- */
    const nodeBlue = new Float32Array(NODES.length)   // 0..1 blue-impact tint per node
    let swarmTarget = -1
    let cycleT = 0
    let cycleLen = 0
    function launchSwarm() {
      // new destination vert (never the same one twice in a row)
      let next = (Math.random() * NODES.length) | 0
      if (next === swarmTarget) next = (next + 1) % NODES.length
      swarmTarget = next
      cycleT = 0
      let maxEnd = 0
      for (const L of dustLayers) {
        for (let i = 0; i < L.count; i++) {
          const o = i * 3
          // launch from wherever the particle is right now
          L.start[o] = L.pos[o]; L.start[o + 1] = L.pos[o + 1]; L.start[o + 2] = L.pos[o + 2]
          // land in a small puff around the vert, not a single point
          const r = 0.03 + Math.random() * 0.14
          const dx = Math.random() * 2 - 1, dy = Math.random() * 2 - 1, dz = Math.random() * 2 - 1
          const dl = Math.hypot(dx, dy, dz) || 1
          L.off[o] = (dx / dl) * r; L.off[o + 1] = (dy / dl) * r; L.off[o + 2] = (dz / dl) * r
          // staggered launch + fast meteor flight
          L.delay[i] = Math.random() * 0.9
          L.dur[i] = 0.45 + Math.random() * 0.55
          L.arrived[i] = 0
          const end = L.delay[i] + L.dur[i]
          if (end > maxEnd) maxEnd = end
        }
      }
      cycleLen = maxEnd + 0.9 + Math.random() * 0.8   // dwell on the vert, then move on
    }
    launchSwarm()

    /* ---------- pulses ---------- */
    const pulses = []
    const pulsePool = []
    function spawnPulse(fromIdx, toIdx, hops) {
      let sprite = pulsePool.pop()
      if (!sprite) {
        sprite = new THREE.Sprite(new THREE.SpriteMaterial({
          map: pulseTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true,
        }))
        sprite.scale.set(0.12, 0.12, 1)
        brainGroup.add(sprite)
      }
      sprite.visible = true
      pulses.push({ sprite, from: NODES[fromIdx].pos, to: NODES[toIdx].pos, toIdx, t: 0, speed: 2.2 + Math.random(), hops })
    }
    function fireNode(i, hops) {
      const n = NODES[i]
      if (!n) return
      n.heat = 1
      adjacency[i].forEach(({ node, edge }) => {
        edgeHeat[edge] = 1
        if (hops > 0) spawnPulse(i, node, hops - 1)
      })
    }

    /* ---------- selection ---------- */
    let selected = -1
    let selectedNovel = -1
    function select(i) {
      selected = i
      const n = NODES[i]
      fireNode(i, 2)
      let payload
      if (novels && n.novelIdx != null) {
        selectedNovel = n.novelIdx
        // light up the whole novel region
        NODES.forEach((m, mi) => { if (m.novelIdx === n.novelIdx) { m.heat = Math.max(m.heat, 0.75) } })
        payload = {
          type: 'novel', novel: novels[n.novelIdx],
          nodeIndex: i, synapses: adjacency[i].length, pos: n.pos,
        }
      } else {
        selectedNovel = -1
        const region = novels
          ? (n.kind === 'cerebellum' ? 'Corpus Pipeline' : 'NovelTea Engine Core')
          : n.region
        const desc = novels
          ? (n.kind === 'cerebellum'
            ? 'Convert → extract → validate → merge → verify → genome. The movement coprocessor of the corpus.'
            : 'The always-on kernel: FastAPI engine, CLI agents, account rotation.')
          : LOBE_DESCRIPTIONS[n.region] || ''
        payload = { type: 'system', region, desc, nodeIndex: i, synapses: adjacency[i].length, pos: n.pos }
      }
      onSelectRef.current && onSelectRef.current(payload)
    }

    /* ---------- interaction ---------- */
    const ray = new THREE.Raycaster()
    const mouseNDC = new THREE.Vector2()
    let dragging = false, moved = 0, lastX = 0, lastY = 0
    let yaw = 0.5, pitch = 0.08, autoSpin = true, idleTimer = null
    let targetZoom = 4.6

    function onDown(e) {
      if (!interactive) return
      dragging = true; moved = 0
      lastX = e.clientX; lastY = e.clientY
      container.style.cursor = 'grabbing'
    }
    function onMove(e) {
      if (!dragging) return
      const dx = e.clientX - lastX, dy = e.clientY - lastY
      moved += Math.abs(dx) + Math.abs(dy)
      lastX = e.clientX; lastY = e.clientY
      yaw += dx * 0.005
      pitch = Math.max(-1.2, Math.min(1.2, pitch + dy * 0.004))
      autoSpin = false
      clearTimeout(idleTimer)
      idleTimer = setTimeout(() => { autoSpin = true }, 2600)
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
      if (hits.length) select(hits[0].object.userData.index)
      else { selected = -1; selectedNovel = -1; onSelectRef.current && onSelectRef.current(null) }
    }
    function onWheel(e) {
      if (!interactive) return
      e.preventDefault()
      targetZoom = Math.max(2.6, Math.min(8, targetZoom + e.deltaY * 0.0022))
    }
    let pinchDist = 0
    function onTouchMove(e) {
      if (!interactive) return
      if (e.touches.length === 2) {
        const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY)
        if (pinchDist) targetZoom = Math.max(2.6, Math.min(8, targetZoom - (d - pinchDist) * 0.01))
        pinchDist = d
      }
    }
    function onTouchEnd() { pinchDist = 0 }

    container.style.cursor = interactive ? 'grab' : 'default'
    container.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    container.addEventListener('wheel', onWheel, { passive: false })
    container.addEventListener('touchmove', onTouchMove, { passive: true })
    container.addEventListener('touchend', onTouchEnd)

    /* ---------- ambient firing ---------- */
    const firingTimer = setInterval(() => {
      if (document.hidden || disposed) return
      fireNode((Math.random() * NODES.length) | 0, 1)
    }, 1700)

    /* ---------- resize ---------- */
    const ro = new ResizeObserver(() => {
      const w = container.clientWidth || 1, h = container.clientHeight || 1
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    })
    ro.observe(container)

    /* ---------- main loop ---------- */
    const timer = new THREE.Timer()
    const tmpColor = new THREE.Color()
    let rafId = 0
    let frame = 0

    function animate() {
      if (disposed) return
      rafId = requestAnimationFrame(animate)
      timer.update()
      const dt = Math.min(timer.getDelta(), 0.05)
      const t = timer.getElapsed()
      frame++

      if (autoSpin) yaw += dt * 0.22
      brainGroup.rotation.y = yaw
      brainGroup.rotation.x = pitch
      camera.position.z += (targetZoom - camera.position.z) * 0.08

      for (let i = 0; i < NODES.length; i++) {
        const n = NODES[i]
        n.heat = Math.max(0, n.heat - dt * 1.4)
        // blue impact tint: held while the swarm dwells on this vert, fades
        // back to white fast once the swarm departs for the next one
        nodeBlue[i] = Math.max(0, nodeBlue[i] - dt * (i === swarmTarget ? 0.12 : 2.4))
        const blue = nodeBlue[i]
        const tw = 0.5 + 0.5 * Math.sin(t * 1.6 + n.twinkle)
        const inNovel = selectedNovel >= 0 && n.novelIdx === selectedNovel
        const s = 0.13 + n.baseGlow * tw + n.heat * 0.34 + blue * 0.22 + (i === selected ? 0.12 : 0) + (inNovel ? 0.05 : 0)
        n.glow.scale.set(s, s, 1)
        n.glow.material.opacity = 0.55 + 0.45 * Math.min(1, n.heat + blue + tw * 0.3)
        n.glow.material.color.setRGB(1 - blue * 0.65, 1 - blue * 0.35, 1)
        n.core.material.color.setRGB(
          (0.75 + n.heat * 0.25) * (1 - blue) + 0.12 * blue,
          (0.88 + n.heat * 0.12) * (1 - blue) + 0.45 * blue,
          1.0,
        )
        const cs = 1 + n.heat * 1.6 + blue * 0.9 + (i === selected ? 0.5 : 0)
        n.core.scale.set(cs, cs, cs)
      }

      for (let e = 0; e < EDGES.length; e++) {
        edgeHeat[e] = Math.max(0, edgeHeat[e] - dt * 1.1)
        const shimmer = 0.75 + 0.25 * Math.sin(t * 2.2 + e * 0.7)
        tmpColor.copy(BASE_EDGE).multiplyScalar(shimmer).lerp(HOT_EDGE, edgeHeat[e])
        const o = e * 6
        eCol[o] = eCol[o + 3] = tmpColor.r
        eCol[o + 1] = eCol[o + 4] = tmpColor.g
        eCol[o + 2] = eCol[o + 5] = tmpColor.b
      }
      edgeGeo.attributes.color.needsUpdate = true

      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i]
        p.t += dt * p.speed
        if (p.t >= 1) {
          fireNode(p.toIdx, p.hops)
          p.sprite.visible = false
          pulsePool.push(p.sprite)
          pulses.splice(i, 1)
        } else {
          p.sprite.position.lerpVectors(p.from, p.to, p.t)
          p.sprite.material.opacity = 1 - p.t * 0.4
        }
      }

      // dust swarm: meteor flight toward the target vert
      cycleT += dt
      {
        const tp = NODES[swarmTarget].pos
        for (const L of dustLayers) {
          const pos = L.pos, start = L.start, off = L.off, delay = L.delay, dur = L.dur, arrived = L.arrived, phase = L.phase
          for (let i = 0; i < L.count; i++) {
            const o = i * 3
            const p = (cycleT - delay[i]) / dur[i]
            if (p <= 0) continue                      // waiting to launch
            const txp = tp.x + off[o], typ = tp.y + off[o + 1], tzp = tp.z + off[o + 2]
            if (p >= 1) {
              if (!arrived[i]) {
                arrived[i] = 1
                nodeBlue[swarmTarget] = 1             // IMPACT → vert flares blue
                NODES[swarmTarget].heat = Math.max(NODES[swarmTarget].heat, 0.9)
              }
              // settled: tiny shimmer around the vert
              const j = Math.sin(t * 3 + phase[i] * 40) * 0.008
              pos[o] = txp + j; pos[o + 1] = typ - j; pos[o + 2] = tzp + j
            } else {
              // shooting star: accelerate in, slight ease at the end
              const e = p * p * (3 - 2 * p)
              pos[o]     = start[o]     + (txp - start[o]) * e
              pos[o + 1] = start[o + 1] + (typ - start[o + 1]) * e
              pos[o + 2] = start[o + 2] + (tzp - start[o + 2]) * e
            }
          }
          L.geo.attributes.position.needsUpdate = true
        }
        if (cycleT > cycleLen) launchSwarm()          // depart → old vert fades to white
      }

      // dust colors are expensive — update every 2nd frame
      if (frame % 2 === 0) {
        const hueBase = t * 0.055
        for (const L of dustLayers) {
          for (let i = 0; i < L.count; i++) {
            const ph = L.phase[i]
            tmpColor.setHSL((hueBase + ph * 0.22) % 1, 1, 0.52 + 0.2 * Math.sin(t * 2.3 + ph * 40))
            const o = i * 3
            L.col[o] = tmpColor.r; L.col[o + 1] = tmpColor.g; L.col[o + 2] = tmpColor.b
          }
          L.geo.attributes.color.needsUpdate = true
        }
      }

      const hs = 6.6 + Math.sin(t * 0.5) * 0.35
      haze.scale.set(hs, hs * 0.85, 1)

      renderer.render(scene, camera)
    }
    animate()

    /* ---------- cleanup ---------- */
    return () => {
      disposed = true
      cancelAnimationFrame(rafId)
      clearInterval(firingTimer)
      clearTimeout(idleTimer)
      ro.disconnect()
      container.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      container.removeEventListener('wheel', onWheel)
      container.removeEventListener('touchmove', onTouchMove)
      container.removeEventListener('touchend', onTouchEnd)
      scene.traverse(o => {
        if (o.geometry) o.geometry.dispose()
        if (o.material) {
          if (o.material.map) o.material.map.dispose()
          o.material.dispose()
        }
      })
      renderer.dispose()
      if (renderer.domElement.parentNode === container) container.removeChild(renderer.domElement)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, interactive])

  return <div ref={mountRef} style={{ width: '100%', height: '100%', ...style }} />
}
