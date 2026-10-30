// The backend serves the UI, so API calls are same-origin (a relative base): this holds on any host or port, over http or https, behind a
// proxy such as Tailscale, and inside the desktop client (which just loads the server's own address). The only exception is a Vite dev
// server (5173 / 5175), which talks to the backend on 7432 at the same host. file:// (an index.html opened from disk) falls back to localhost.
const LOC = window.location
const BASE = (() => {
  if (LOC.protocol === 'file:') return 'http://localhost:7432'
  if (LOC.port === '5173' || LOC.port === '5175') return `http://${LOC.hostname || 'localhost'}:7432`
  return ''
})()

// Exported so components can build <img src> URLs for backend-served files
// (e.g. project cover images) without duplicating the same-origin/dev-host logic.
export const API_BASE = BASE

async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json()
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`POST ${path} failed: ${res.status} ${err}`)
  }
  return res.json()
}

// Long jobs (narration, an interview step) run on the PC as background jobs: the app starts one, gets its id back at
// once, then checks on it every few seconds (and straight away when you come back to the app). Nothing is held open
// for minutes, so a phone switching apps can't cut it; a check that fails is simply tried again.
function waitOrVisible(ms) {
  return new Promise(resolve => {
    let done = false
    const finish = () => { if (done) return; done = true; clearTimeout(t); document.removeEventListener('visibilitychange', vis); resolve() }
    const vis = () => { if (document.visibilityState === 'visible') finish() }
    const t = setTimeout(finish, ms)
    document.addEventListener('visibilitychange', vis)
  })
}
async function runJob(path, body) {
  const job = await post(path, body)
  for (;;) {
    await waitOrVisible(3000)
    let s
    try { s = await get(`/api/jobs/${job.id}`) }
    catch (e) {
      if (/failed: 404/.test(e.message || '')) throw new Error('The job was lost (did the app restart?). What was written so far is safe.')
      continue                                   // dropped check: try again
    }
    if (s.status === 'done') return s.result
    if (s.status === 'error') throw new Error(s.error || 'The job failed')
  }
}

// Older projects were saved before the current schema: an arc's `chapters` is a
// range string ("1-5", "1-5, 8") instead of a list of numbers, and
// systems.custom_engines is a {name: text} object instead of a list of engine
// defs. The UI calls .filter/.map on both, so an old project used to throw during
// render and blank the whole window. Convert on load; nothing is dropped (each
// legacy engine's text becomes that engine's overview).
function expandChapterRange(v) {
  if (Array.isArray(v)) return v
  if (typeof v !== 'string') return []
  const out = []
  for (const part of v.split(',')) {
    const m = part.trim().match(/^(\d+)\s*[-–—]\s*(\d+)$/)
    if (m) { for (let n = +m[1]; n <= +m[2] && out.length < 5000; n++) out.push(n) }
    else if (/^\d+$/.test(part.trim())) out.push(+part.trim())
  }
  return out
}

function normalizeProject(p) {
  if (!p || typeof p !== 'object') return p
  if (Array.isArray(p.arcs)) {
    p.arcs = p.arcs.map(a => (a && !Array.isArray(a.chapters) ? { ...a, chapters: expandChapterRange(a.chapters) } : a))
  }
  const s = p.systems
  if (s && typeof s === 'object') {
    if (s.custom_engines && !Array.isArray(s.custom_engines)) {
      const legacy = typeof s.custom_engines === 'object' ? s.custom_engines : {}
      const defs = []
      const next = { ...s }
      for (const [name, text] of Object.entries(legacy)) {
        let key = String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'engine'
        while (defs.some(d => d.key === key)) key += '_2'
        defs.push({ key, label: name, icon: '⚙', color: '#8b5cf6', desc: '', listKey: 'entries', listLabel: 'Entries', fields: ['name', 'type', 'description', 'effect'] })
        if (!next[key]) next[key] = { overview: typeof text === 'string' ? text : JSON.stringify(text), rules: [], entries: [] }
      }
      next.custom_engines = defs
      p.systems = next
    } else if (s.custom_engines == null) {
      // leave absent — the UI already defaults to []
    }
    if (s.character_power_systems && typeof s.character_power_systems !== 'object') {
      p.systems = { ...p.systems, character_power_systems: {} }
    }
  }
  return p
}

export const api = {
  health: () => get('/api/health'),

  // Server page — live machine stats + the processes this app is responsible for
  serverMetrics: () => get('/api/server/metrics'),
  serverProcesses: () => get('/api/server/processes'),
  serverKill: (pid) => post('/api/server/processes/kill', { pid }),
  serverKillStale: () => post('/api/server/processes/kill-stale', {}),
  serverUnloadOllama: () => post('/api/server/ollama/unload', {}),
  serverUnloadColibri: () => post('/api/server/colibri/unload', {}),

  // Corpus
  corpusStats: () => get('/api/corpus/stats'),
  registry: () => get('/api/corpus/registry'),
  metadata: (id) => get(`/api/corpus/${id}/metadata`),
  arcs: (id) => get(`/api/corpus/${id}/arcs`),
  pipelineCached: () => get('/api/corpus/pipeline-status/cached'),        // every card's last saved values (instant)
  pipelineJob: (key, check = false) => get(`/api/corpus/pipeline-status/job/${key}${check ? '?check=true' : ''}`),  // one card computed fresh; check = also diagnose + repair
  pipelineLive: () => get('/api/corpus/pipeline-live'),                   // running + doing-now only (cheap, for polling)
  // Delta quality scan — the "Scan for upgrades" button on the Delta Upgrade card
  deltaAuditStatus: () => get('/api/corpus/delta-audit'),
  deltaAuditRun: () => post('/api/corpus/delta-audit/run', {}),
  // Hard-lock the Delta Upgrade job to a gated fast model ("auto" | "haiku" | "nemotron_lightning") — takes effect on the job's NEXT launch.
  deltaUpgradeConfigGet: () => get('/api/corpus/delta-upgrade/config'),
  // The Delta Upgrade card's "Claude: low effort" checkbox: 'low' or null (the CLI's default)
  deltaUpgradeEffortSet: (claude_effort) => post('/api/corpus/delta-upgrade/effort', { claude_effort }),
  deltaUpgradeConfigSet: (lock) => post('/api/corpus/delta-upgrade/config', { lock }),
  pipelineRestart: (job) => post('/api/corpus/pipeline-restart', { job }),
  pipelineStop: (job) => post('/api/corpus/pipeline-stop', { job }),
  // opts: { novel_id, chapter_from, chapter_to } — filters applied before ranking (a chapter range leaves out chunks with no chapter)
  // Chapter Mechanics corpus data (routers/reference_mechanics.py): search with kind / novel / chapter filters, the raw
  // passage around a quote, and how the reference novel runs a moment like a timeline event.
  referenceSearch: (query, opts = {}) => post('/api/reference/search', { query, top_k: opts.top_k || 10,
    ...(opts.kind ? { kind: opts.kind } : {}), ...(opts.novel_id ? { novel_id: opts.novel_id } : {}),
    ...(opts.chapter_from != null && opts.chapter_from !== '' ? { chapter_from: Number(opts.chapter_from) } : {}),
    ...(opts.chapter_to != null && opts.chapter_to !== '' ? { chapter_to: Number(opts.chapter_to) } : {}) }),
  rawContext: (novel, chapter, quote = '', around = 3) =>
    get(`/api/reference/raw-context?novel=${encodeURIComponent(novel)}&chapter=${chapter}&quote=${encodeURIComponent(quote)}&around=${around}`),
  referenceChapterCheck: (project_id, chapter) => get(`/api/reference/chapter-check/${project_id}/${chapter}`),
  timelineReference: (project_id, chapter, title, text) => post('/api/reference/timeline-event', { project_id, chapter, title, text }),
  knowledgeSearch: (query, top_k = 8, category = null, opts = {}) =>
    post('/api/corpus/knowledge-search', { query, top_k, ...(category ? { category } : {}),
      ...(opts.novel_id ? { novel_id: opts.novel_id } : {}),
      ...(opts.chapter_from != null && opts.chapter_from !== '' ? { chapter_from: Number(opts.chapter_from) } : {}),
      ...(opts.chapter_to != null && opts.chapter_to !== '' ? { chapter_to: Number(opts.chapter_to) } : {}) }),
  psychology: (id) => get(`/api/corpus/${id}/reader_psychology`),
  patterns: (id) => get(`/api/corpus/${id}/patterns`),
  schemes: (id) => get(`/api/corpus/${id}/schemes`),
  knowledge: (id) => get(`/api/corpus/${id}/knowledge_state`),
  humor: (id) => get(`/api/corpus/${id}/humor`),
  entities: (id) => get(`/api/corpus/${id}/entities`),
  entity: (novelId, entityId) => get(`/api/corpus/${novelId}/entity/${entityId}`),
  reveals: (id) => get(`/api/corpus/${id}/reveals`),
  // Character DNA Picker — corpus character_dna/ files, pre-flattened server-side
  // into the four fields CharactersTab's own schema already has (see
  // PHASE6_CHARACTER_DNA_PICKER.md). role/novel_id both optional filters.
  characterDna: (role = null, novelId = null) => {
    const params = new URLSearchParams()
    if (role) params.set('role', role)
    if (novelId) params.set('novel_id', novelId)
    const qs = params.toString()
    return get(`/api/corpus/character-dna${qs ? `?${qs}` : ''}`)
  },
  // One-click action behind the Corpus Pipeline tab's "N stale" badge —
  // backgrounded (a single rebuild can take 20-230s, confirmed live, too
  // slow to block on), poll characterDnaRebuildStatus with the returned id.
  characterDnaRebuild: (novel_id, character_id) =>
    post('/api/corpus/character-dna-rebuild', { novel_id, character_id }),
  characterDnaRebuildStatus: (rebuild_id) =>
    get(`/api/corpus/character-dna-rebuild-status?rebuild_id=${encodeURIComponent(rebuild_id)}`),

  // Novel dashboard

  // Engines
  planChapter: (novelId, chapter, opts = {}) =>
    post('/api/engines/plan', { novel_id: novelId, chapter_number: chapter, ...opts }),
  generateChapter: (novelId, chapter) =>
    post('/api/engines/generate', { novel_id: novelId, chapter_number: chapter }),
  extractChapters: (novelId, start, end) =>
    post('/api/engines/extract', { novel_id: novelId, start_chapter: start, end_chapter: end }),
  validateNovel: (novelId) =>
    post('/api/engines/validate', { novel_id: novelId }),
  getGenerated: (novelId, chapter) => get(`/api/engines/generated/${novelId}/${chapter}`),
  listGenerated: (novelId) => get(`/api/engines/generated/${novelId}`),
  narrateChapter: (project_id, chapter_number, voice = null) =>
    runJob('/api/jobs/narrate', { project_id, chapter_number, ...(voice ? { voice } : {}) }),
  narrateStatus: (project_id, chapter_number, voice = null) =>
    get(`/api/generate/narrate-status/${project_id}/${chapter_number}${voice ? `?voice=${encodeURIComponent(voice)}` : ''}`),
  chapterVersions: (novelId, ch) => get(`/api/engines/generated/${novelId}/${ch}/versions`),
  chapterVersion: (novelId, ch, v) => get(`/api/engines/generated/${novelId}/${ch}/version/${v}`),
  restoreChapterVersion: (novelId, ch, v) => post(`/api/engines/generated/${novelId}/${ch}/version/${v}/restore`, {}),
  clearChapterVersions: (novelId, ch) =>
    fetch(`${BASE}/api/engines/generated/${novelId}/${ch}/versions`, { method: 'DELETE' }).then(r => r.json()),
  saveGenerated: (novelId, chapter, text) =>
    post(`/api/engines/generated/${novelId}/${chapter}/save`, { text }),
  getInfluences: (novelId, chapter) => get(`/api/engines/generated/${novelId}/${chapter}/influences`),
  deleteGenerated: (novelId, chapter) => fetch(`${BASE}/api/engines/generated/${novelId}/${chapter}`, { method: 'DELETE' }).then(r => r.json()),

  // Setup
  setCorpusPath: (path) => post('/api/setup/corpus-path', { path }),

  // Projects (separate from corpus)
  listProjects: () => get('/api/projects'),
  createProject: (data) => post('/api/projects', data),
  // Project import / export (the "noveltea-project" bundle shared by NovelMind and NovelTea Engine)
  projectExport: async (id, format = 'bundle') => {
    const res = await fetch(`${BASE}/api/project-io/export/${encodeURIComponent(id)}?format=${format}`)
    if (!res.ok) {
      let msg = `Export failed (${res.status})`
      try { msg = (await res.json()).detail || msg } catch { /* not JSON */ }
      throw new Error(msg)
    }
    const cd = res.headers.get('Content-Disposition') || ''
    const name = (cd.match(/filename="([^"]+)"/) || [])[1] || `${id}.zip`
    return { blob: await res.blob(), name }
  },
  projectImportPreview: async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/api/project-io/import/preview`, { method: 'POST', body: fd })
    if (!res.ok) {
      let msg = `Import failed (${res.status})`
      try { msg = (await res.json()).detail || msg } catch { /* not JSON */ }
      throw new Error(msg)
    }
    return res.json()
  },
  projectImportCommit: (token, title = null) => post('/api/project-io/import/commit', { token, ...(title ? { title } : {}) }),
  installDemo: () => post('/api/projects/demo/install', {}),
  getProject: (id) => get(`/api/projects/${id}`).then(normalizeProject),
  updateProject: (id, data) => fetch(`${BASE}/api/projects/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  deleteProject: (id) => fetch(`${BASE}/api/projects/${id}`, { method: 'DELETE' }).then(r => r.json()),
  uploadCoverImage: async (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/api/projects/${id}/cover-image`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(`Cover upload failed: ${res.status} ${await res.text()}`)
    return res.json()
  },
  removeCoverImage: (id) => fetch(`${BASE}/api/projects/${id}/cover-image`, { method: 'DELETE' }).then(r => r.json()),
  generateCover: (project_id) => post('/api/generate/cover', { project_id }),

  // Settings
  getSettings: () => get('/api/settings'),
  saveApiKey: (provider, api_key, model) => post('/api/settings/api-key', { provider, api_key, model }),
  setModel: (provider, model) => post('/api/settings/model', { provider, model }),
  deleteApiKey: (provider) => fetch(`${BASE}/api/settings/api-key/${provider}`, { method: 'DELETE' }).then(r => r.json()),
  saveGenerationSettings: (data) => post('/api/settings/generation', data),

  // AI Generation
  getChapterSummaries: (project_id) => get(`/api/generate/chapter-summaries/${project_id}`),
  syncSkeleton: (project_id) => post(`/api/generate/sync-skeleton/${project_id}`, {}),
  // Sequential arc generation — one arc per call, each seeing every prior arc in
  // full. Replaces the single call that produced all 3-8 arcs at once (and gave
  // each one roughly two sentences).
  generateArc: (project_id, arc_index = null, total_arcs = null, regenerate = false) =>
    post('/api/generate/arc', {
      project_id,
      ...(arc_index != null ? { arc_index } : {}),
      ...(total_arcs != null ? { total_arcs } : {}),
      ...(regenerate ? { regenerate } : {}),
    }),
  // Skeleton wizard — 7 guided steps, each pre-answered from positional corpus
  // data. First call opens a session; later calls pass the answer.
  // Round-trip validation — measure a written chapter against the skeleton
  // that specified it (scene count, word budget, style DNA, reveals placed).
  validateChapter: (project_id, chapter) =>
    post('/api/generate/validate-chapter', { project_id, chapter }),
  // Auto-fix ONE validate-chapter finding with a localized, tailored patch —
  // see fix_validation_check's docstring (generate.py) for which checks are
  // fixable (everything except Scene count / Word count, which need a real
  // rewrite). Returns { archived_version, validation: <fresh result> }.
  fixValidationCheck: (project_id, chapter, check, planned, actual) =>
    post('/api/generate/fix-validation-check', { project_id, chapter, check,
      planned: planned != null ? String(planned) : null, actual: actual != null ? String(actual) : null }),
  // Author profile — the project's writing DNA (style, psychology, voice,
  // genre contracts), seeded from the corpus and fed into every generation.
  getAuthorProfile: (project_id) => get(`/api/generate/author-profile/${project_id}`),
  // voice_source: {mode: 'corpus'|'novel'|'mix', novels: [...]}; reseed_style re-averages only the style DNA
  saveAuthorProfile: (project_id, profile, reseed = false, voice_source = null, reseed_style = false) =>
    post('/api/generate/author-profile', { project_id, profile, ...(reseed ? { reseed } : {}),
      ...(voice_source ? { voice_source } : {}), ...(reseed_style ? { reseed_style } : {}) }),
  // Corpus voice-match score for a chapter — text = the Reader's current draft (unsaved edits included)
  voiceMatch: (project_id, chapter_number, text = null) =>
    post('/api/generate/voice-match', { project_id, chapter_number, ...(text ? { text } : {}) }),
  // This book's running gags (seeded from the craft notes, kept current by the
  // end-of-chapter humor check). Each op saves at once: add {name} | update {id, name?, status?} | delete {id}
  gagLedgerOp: (project_id, op, fields = {}) => post('/api/generate/gag-ledger', { project_id, op, ...fields }),
  // Humor tab: overview (Humor DNA, gags, chapters + scans, index status), Humor DNA
  // save, one-chapter AI scan, apply/dismiss a suggestion, corpus gag search (no AI call).
  humorOverview: (project_id) => get(`/api/generate/humor/${project_id}`),
  saveHumorDna: (project_id, humor_dna) => post('/api/generate/humor/dna', { project_id, humor_dna }),
  humorScan: (project_id, chapter_number) => post('/api/generate/humor/scan', { project_id, chapter_number }),
  humorSuggestion: (project_id, chapter_number, suggestion_id, action, lines = null) =>
    post('/api/generate/humor/suggestion', { project_id, chapter_number, suggestion_id, action, ...(lines != null ? { lines } : {}) }),
  humorCorpusSearch: (query, top_k = 12, running_only = false, face_slaps_only = false) =>
    post('/api/generate/humor/corpus-search', { query, top_k, running_only, face_slaps_only }),
  // Tracked face slaps: add {name, target?, plan?} | update {id, name?, target?, plan?, status?} | delete {id}
  slapOp: (project_id, op, fields = {}) => post('/api/generate/humor/slaps', { project_id, op, ...fields }),
  // Picked corpus humor instances: add {source} | update {id, adapted} | delete {id} | adapt {id} | to_gag {id}
  humorPickOp: (project_id, op, fields = {}) => post('/api/generate/humor/picks', { project_id, op, ...fields }),
  // Combat tab: overview (Combat DNA, every chapter's free fight check), Combat DNA save,
  // corpus fight search over the labelled prose samples (no AI call).
  combatOverview: (project_id) => get(`/api/generate/combat/${project_id}`),
  saveCombatDna: (project_id, combat_dna) => post('/api/generate/combat/dna', { project_id, combat_dna }),
  combatCorpusSearch: (query, types = null, top_k = 12) =>
    post('/api/generate/combat/corpus-search', { query, top_k, ...(types ? { types } : {}) }),
  // Picked corpus fight moves: add {source} | update {id, adapted?, chapter?, status?} | delete {id} | adapt {id}
  fightPickOp: (project_id, op, fields = {}) => post('/api/generate/combat/picks', { project_id, op, ...fields }),
  // Antagonists tab: the standing plan of everyone who gets in the hero's way, researched from the corpus's antagonist templates.
  antagonists: (project_id) => get(`/api/antagonists/${project_id}`),
  antagonistsSave: (project_id, roster) => post('/api/antagonists/save', { project_id, roster }),
  antagonistsUndo: (project_id) => post('/api/antagonists/undo', { project_id }),
  antagonistsGenerate: (project_id, mode = 'replace', count = 12, selected = null, first_chapter = null, last_chapter = null) =>
    post('/api/antagonists/generate', { project_id, mode, count, ...(selected ? { selected } : {}), ...(first_chapter ? { first_chapter, last_chapter } : {}) }),
  antagonistsDecide: (project_id, accept, decline) => post('/api/antagonists/decide', { project_id, accept, decline }),
  antagonistsCatalogue: () => get('/api/antagonists/catalogue/all'),
  antagonistsSearch: (query, top_k = 8) => post('/api/antagonists/search', { query, top_k }),
  antagonistsProfile: (name, novel = '') => post('/api/antagonists/profile', { name, novel }),
  // Lore tab: a chapter's WHY card. Draft from the plan, edit/approve; after reading, feedback -> proposed card change -> apply (rewrites only the touched paragraphs).
  lore: (project_id) => get(`/api/lore/${project_id}`),
  loreDraft: (project_id, chapter) => post('/api/lore/draft', { project_id, chapter }),
  loreSave: (project_id, chapter, card, approve = false) => post('/api/lore/save', { project_id, chapter, card, approve }),
  loreUndo: (project_id, chapter) => post('/api/lore/undo', { project_id, chapter }),
  loreFeedback: (project_id, chapter, feedback) => post('/api/lore/feedback', { project_id, chapter, feedback }),
  loreApply: (project_id, chapter, card, feedback) => post('/api/lore/apply', { project_id, chapter, card, feedback }),
  loreWorldSave: (project_id, entries) => post('/api/lore/world/save', { project_id, entries }),
  loreWorldDraft: (project_id, note = '') => post('/api/lore/world/draft', { project_id, note }),
  // Conspiracy tab: the hidden scheme tree (final scheme -> schemes -> events/false flags/cover-ups -> clues/breadcrumbs/mistakes).
  conspiracy: (project_id) => get(`/api/conspiracy/${project_id}`),
  conspiracySave: (project_id, conspiracy, base_rev = null) => post('/api/conspiracy/save', { project_id, conspiracy, base_rev }),
  conspiracyUndo: (project_id) => post('/api/conspiracy/undo', { project_id }),
  conspiracyBuild: (project_id, note = '') => post('/api/conspiracy/build', { project_id, note }),
  conspiracyExpand: (project_id, node_id, note = '') => post('/api/conspiracy/expand', { project_id, node_id, note }),
  conspiracyGrow: (project_id, note = '') => post('/api/conspiracy/grow', { project_id, note }),
  // Timeline tab: the book chapter by chapter from the hero's point of view.
  timeline: (project_id) => get(`/api/timeline/${project_id}`),
  timelineSave: (project_id, events, arcs = null) => post('/api/timeline/save', { project_id, events, arcs }),
  timelineUndo: (project_id) => post('/api/timeline/undo', { project_id }),
  // the author's brain proposes the hero's events for a stretch (nothing saved until the author accepts them)
  timelineSuggest: (project_id, first, last, note = '') => post('/api/timeline/suggest', { project_id, first, last, note }),
  // Cast roster: non-enemy characters planned at the style novel's pace.
  castRoster: (project_id) => get(`/api/castroster/${project_id}`),
  castSave: (project_id, cast, pending = [], base_rev = null) => post('/api/castroster/save', { project_id, cast, pending, base_rev }),
  castUndo: (project_id) => post('/api/castroster/undo', { project_id }),
  castGenerate: (project_id, first_chapter, last_chapter, count = null, note = '') => post('/api/castroster/generate', { project_id, first_chapter, last_chapter, count, note }),
  castLikeness: (project_id, query) => post('/api/castroster/likeness', { project_id, query }),
  castJourneys: (project_id, names = null) => post('/api/castroster/journeys/generate', { project_id, names }),
  castJourneyDecide: (project_id, accept, decline, base_rev = null) => post('/api/castroster/journeys/decide', { project_id, accept, decline, base_rev }),
  castVoices: (project_id, names = null) => post('/api/castroster/voices/generate', { project_id, names }),
  castVoiceDecide: (project_id, accept, decline, base_rev = null) => post('/api/castroster/voices/decide', { project_id, accept, decline, base_rev }),
  // Fight plan (Combat tab): a short interview that plans one chapter's fight beat by beat against a word budget
  fightPlan: (project_id) => get(`/api/fightplan/${project_id}`),
  fightPlanBudget: (project_id, chapter, budget = null) => post('/api/fightplan/budget', { project_id, chapter, ...(budget ? { budget } : {}) }),
  fightPlanStart: (project_id, chapter, foe = null, budget = null) => post('/api/fightplan/start', { project_id, chapter, ...(foe ? { foe } : {}), ...(budget ? { budget } : {}) }),
  fightPlanAnswer: (project_id, session_id, body) => post('/api/fightplan/answer', { project_id, session_id, ...body }),
  fightPlanDecide: (project_id, chapter, action) => post('/api/fightplan/decide', { project_id, chapter, action }),
  // Scene plans: the same interview for conversations, discoveries, learning, places and fallout
  scenePlan: (project_id) => get(`/api/sceneplan/${project_id}`),
  scenePlanBudget: (project_id, chapter, scene = null, kind = null, words = null) => post('/api/sceneplan/budget', { project_id, chapter, ...(scene ? { scene } : {}), ...(kind ? { kind } : {}), ...(words ? { words } : {}) }),
  scenePlanStart: (project_id, chapter, scene = null, kind = null, words = null, people = []) => post('/api/sceneplan/start', { project_id, chapter, ...(scene ? { scene } : {}), ...(kind ? { kind } : {}), ...(words ? { words } : {}), people }),
  scenePlanAnswer: (project_id, session_id, body) => post('/api/sceneplan/answer', { project_id, session_id, ...body }),
  scenePlanDecide: (project_id, chapter, slot, action) => post('/api/sceneplan/decide', { project_id, chapter, slot, action }),
  fightPlanMoves: (project_id, chapter, foe = null, beat = null) => post('/api/fightplan/moves', { project_id, chapter, ...(foe ? { foe } : {}), ...(beat ? { beat } : {}) }),
  // Sequential chapter skeletons — one chapter per call, inside its arc's
  // contract, with the previous chapter in full context.
  // Per-engine progress stream (omit `engine` for the combined view).
  generateField: (project_id, field, corpus_count = 3, provider = null, chapter_summaries = null, grep_mode = null, author_notes = null) =>
    post('/api/generate/field', { project_id, field, corpus_count, ...(provider ? { provider } : {}), ...(chapter_summaries ? { chapter_summaries } : {}), ...(grep_mode ? { grep_mode } : {}), ...(author_notes ? { author_notes } : {}) }),
  abandonGeneration: (project_id, field) => post('/api/generate/abandon', { project_id, field }),
  getActiveGeneration: (project_id) => get(`/api/generate/active/${project_id}`),
  interactiveStatus: (project_id) => get(`/api/generate/interactive-status/${project_id}`),
  undoField: (project_id, field) => post('/api/generate/undo', { project_id, field }),
  undoStatus: (project_id) => get(`/api/generate/undo-status/${project_id}`),
  // back: true = one step back; a number = jump straight to that step index (breadcrumb click)
  interactiveChapter: (project_id, chapter_number, session_id = null, choice = null, target_words = null, back = false, model = null) =>
    runJob('/api/jobs/chapter-interactive', { project_id, chapter_number, ...(session_id ? { session_id } : {}), ...(choice ? { choice } : {}), ...(target_words ? { target_words } : {}), ...(back === true ? { back: true } : {}), ...(typeof back === 'number' ? { back_to: back } : {}), ...(model ? { model } : {}) }),
  interactiveField: (project_id, field, session_id = null, choice = null, chapter_summaries = null, back = false, chapter_number = null, critique_text = null, force_pattern = false) =>
    post('/api/generate/field-interactive', { project_id, field, ...(session_id ? { session_id } : {}), ...(choice ? { choice } : {}), ...(chapter_summaries ? { chapter_summaries } : {}), ...(back === true ? { back: true } : {}), ...(typeof back === 'number' ? { back_to: back } : {}), ...(chapter_number ? { chapter_number } : {}), ...(critique_text ? { critique_text } : {}), ...(force_pattern ? { force_pattern: true } : {}) }),
  interactiveFieldAbandon: (project_id, field, session_id = null) =>
    post('/api/generate/field-interactive-abandon', { project_id, field, ...(session_id ? { session_id } : {}) }),
  // Chapter workspace: all parts of a chapter (live interview or saved), gate marks per paragraph, and a
  // one-paragraph gate fix
  interactiveDraft: (project_id, chapter_number) => get(`/api/generate/interactive-draft/${project_id}/${chapter_number}`),
  // Continue: finds the chapter's stored interview (memory, file or recycle bin) and returns the question it was on.
  // Rewind: back to the question that followed part N (later parts are dropped after a backup).
  interactiveRecover: (project_id, chapter_number, force = false) =>
    post('/api/generate/interactive-recover', { project_id, chapter_number, ...(force ? { force: true } : {}) }),
  // Regenerate from a part (also for a finished chapter): keeps parts 1..part, deletes the rest, asks that part's question again
  interactiveRegenerate: (project_id, chapter_number, part, page_part_text = '') =>
    post('/api/generate/interactive-regenerate', { project_id, chapter_number, part, ...(page_part_text ? { page_part_text } : {}) }),
  interactiveRewind: (project_id, chapter_number, part) =>
    post('/api/generate/interactive-rewind', { project_id, chapter_number, part }),
  // ids: lets the server also mark segments the author kept over their word budget (saved parts only)
  gateReport: (parts, earlier = [], ids = null, flagged = []) => post('/api/generate/gate-report', { parts, ...(earlier.length ? { earlier } : {}), ...(flagged.length ? { flagged } : {}), ...(ids ? { project_id: ids.projectId, chapter_number: ids.chapterNum } : {}) }),
  gateFixParagraph: (body) => post('/api/generate/gate-fix-paragraph', body),
  // the author's own edit of a flagged paragraph: saved as written, then checked by the gate
  gateSaveParagraph: (body) => post('/api/generate/gate-save-paragraph', body),
  interactiveChapterAbandon: (project_id, chapter_number, session_id = null) =>
    post('/api/generate/chapter-interactive-abandon', { project_id, chapter_number, ...(session_id ? { session_id } : {}) }),
  polishAnswer: (project_id, question, draft_answer, chapter_number = null) =>
    post('/api/generate/polish-answer', { project_id, question, draft_answer, ...(chapter_number ? { chapter_number } : {}) }),
  pronMarks: (project_id, text) => post('/api/generate/pron-marks', { project_id, text }),
  ttsVoices: () => get('/api/generate/tts-voices'),
  pushInfo: () => get('/api/jobs/push/key'),
  pushSubscribe: (subscription, label) => post('/api/jobs/push/subscribe', { subscription, label }),
  pushUnsubscribe: (subscription) => post('/api/jobs/push/unsubscribe', { subscription }),
  pushTest: () => post('/api/jobs/push/test', {}),
  speak: (text, voice = null, project_id = null) =>
    post('/api/generate/speak', { text, ...(voice ? { voice } : {}), ...(project_id ? { project_id } : {}) }),
  // Reference gauge: the Author DNA novel's chapter measured beside this chapter's plan; Apply writes suggested budgets
  referenceGauge: (project_id, chapter_number) => get(`/api/generate/reference-gauge/${project_id}/${chapter_number}`),
  referenceGaugeApply: (project_id, chapter_number, budgets) =>
    post('/api/generate/reference-gauge/apply', { project_id, chapter_number, budgets }),
  // Fix the orange warning on a chapter plan: the AI re-plans it, remixing Blueprint + patterns + corpus chapters (long call)
  skeletonFix: (project_id, chapter) => post('/api/generate/skeleton-fix', { project_id, chapter }),
  getChapterPlan: (project_id, chapter_number) =>
    get(`/api/generate/chapter-plan/${project_id}/${chapter_number}`),
  reviseChapters: (project_id, provider = null, note = null) =>
    post('/api/generate/revise', { project_id, ...(provider ? { provider } : {}), ...(note ? { note } : {}) }),
  shortenChapter: (project_id, chapter_number, text, target_words) =>
    post('/api/generate/shorten-chapter', { project_id, chapter_number, text, target_words }),
  // Voice deviation — compares a written chapter's voice_fingerprint against
  // a CHOSEN corpus novel's own (not a blind/fixed baseline), signal by
  // signal. Not an "AI detector" — see voice_deviation's docstring.
  voiceDeviation: (project_id, chapter_number, novel_id, text = null) =>
    post('/api/generate/voice-deviation', { project_id, chapter_number, novel_id, ...(text ? { text } : {}) }),
  // Targeted rewrite fixing ONLY the specific signals a prior voiceDeviation
  // call flagged (pass its `findings` array back in) — same stateless
  // "returns text for the textarea, Save to keep it" shape as shortenChapter.
  voiceDeviationFix: (project_id, chapter_number, text, findings) =>
    post('/api/generate/voice-deviation-fix', { project_id, chapter_number, text, findings }),
  applyPatch: (project_id, old_text, new_text, note = null) =>
    post('/api/generate/apply-patch', { project_id, old_text, new_text, note }),
  logMemory: (project_id, kind, text) =>
    post('/api/generate/memory-log', { project_id, kind, text }),
  discover: (project_id, full = false) => post('/api/generate/discover', { project_id, full }),
  generateProgress: (project_id, since = -1) => get(`/api/generate/progress/${project_id}?since=${since}`),
  factsExtract: (project_id, full = false) => post('/api/generate/facts-extract', { project_id, full }),
  factsUpdate: (project_id, facts_log) => post('/api/generate/facts-update', { project_id, facts_log }),
  factsFix: (project_id, contradiction_id) => post('/api/generate/facts-fix', { project_id, contradiction_id }),
  critiqueNotesUpdate: (project_id, critique_notes) => post('/api/generate/critique-notes-update', { project_id, critique_notes }),
  locationMapExtract: (project_id, full = false) => post('/api/generate/location-map-extract', { project_id, full }),
  locationMapUpdate: (project_id, location_map) => post('/api/generate/location-map-update', { project_id, location_map }),
  locationMapFix: (project_id, contradiction_id) => post('/api/generate/location-map-fix', { project_id, contradiction_id }),
  continuityReview: (project_id) => post('/api/generate/continuity-review', { project_id }),

  // Revision Intelligence — craft-quality pass (pacing, flat dialogue, weak
  // stakes, exposition dumps, repetition), persisted as a per-item checklist.
  revisionCheck: (project_id, chapter_range = null) =>
    post('/api/generate/revision-check', { project_id, ...(chapter_range ? { chapter_range } : {}) }),
  revisionChecklistUpdate: (project_id, item_id, status) =>
    post('/api/generate/revision-checklist-update', { project_id, item_id, status }),

  // Promise Check — zero-LLM drift detection over chapter_skeletons, walked as
  // A/B choices. Status is read-only; the POST drives the wizard session.
  promiseCheckStatus: (project_id) => get(`/api/generate/promise-check-status?project_id=${encodeURIComponent(project_id)}`),
  promiseCheck: (project_id, session_id = null, choice = null) =>
    post('/api/generate/promise-check', { project_id, ...(session_id ? { session_id } : {}), ...(choice ? { choice } : {}) }),
  corpusSuggestions: (project_id, full = false) =>
    post('/api/generate/corpus-suggestions', { project_id, full }),
  projectChat: (project_id, messages, model = null) =>
    post('/api/generate/project-chat', { project_id, messages, ...(model ? { model } : {}) }),
  projectChatUndo: (project_id, snapshot_id) =>
    post('/api/generate/project-chat/undo', { project_id, snapshot_id }),

  // Corpus Wiki — saves one clicked link's pasted content to
  // wiki/{novel_id}/{tag}/{link_name}.txt (or temp/ when untagged), with the
  // source URL + tag written as a header at the top of the file.
  corpusWikiSaveLinkContent: (novel_id, link_name, content, tag = '', source_url = '') =>
    post('/api/corpus-wiki/save-link-content', { novel_id, link_name, content, tag, source_url }),
  // Every source URL already saved for a novel (read from each file's own
  // header) — used on page load so already-saved links show red immediately.
  corpusWikiSavedUrls: (novel_id) =>
    get(`/api/corpus-wiki/saved-urls?novel_id=${encodeURIComponent(novel_id)}`),

  // Blueprint — reference-backed generation (renamed from "Standard" — same
  // feature/storage, clearer name: a reusable template a project builds
  // FROM, not a fixed requirement it must conform TO). A saved blueprint is
  // meant to be used verbatim, interactively adapted, or ignored entirely
  // (fresh generation) — this API only covers building/browsing the library.
  blueprintSystemTypes: () => get('/api/blueprints/system-types'),
  blueprintActiveModel: () => get('/api/blueprints/active-model'),
  blueprintList: (system_type = null) =>
    get(`/api/blueprints/list${system_type ? `?system_type=${encodeURIComponent(system_type)}` : ''}`),
  blueprintGet: (system_type, standard_id) =>
    get(`/api/blueprints/${encodeURIComponent(system_type)}/${encodeURIComponent(standard_id)}`),
  blueprintExtract: (system_type, { html = null, text = null, hint = null, bulk = false, abort_key = null } = {}) =>
    post('/api/blueprints/extract', { system_type, html, text, hint, bulk, abort_key }),
  blueprintAbort: (abort_key) => post('/api/blueprints/abort', { abort_key }),
  blueprintSave: (payload) => post('/api/blueprints/save', payload),
  blueprintDelete: (system_type, standard_id) =>
    fetch(`${API_BASE}/api/blueprints/${encodeURIComponent(system_type)}/${encodeURIComponent(standard_id)}`, { method: 'DELETE' }).then(r => r.json()),

  // System / network
  systemInfo: () => get('/api/system/info'),
  brainGraph: () => get('/api/system/brain'),
  restartServer: () => post('/api/system/restart', {}),

  // Agent engine (which CLI powers Discovery/Dialogue Shaping/Fix buttons/AGENTIC mode)
  listAgentEngines: () => get('/api/settings/agent-engines'),

  // Local Ollama models — served from this machine, nothing leaves it
  listOllamaModels: () => get('/api/aicoder/ollama-models'),
  // Colibrì: local CPU-only engine (text-only). The gateway runs as a child process of the app.
  colibriStatus: () => get('/api/aicoder/colibri'),
  colibriStart: () => post('/api/aicoder/colibri/start', {}),
  colibriStop: () => post('/api/aicoder/colibri/stop', {}),

  // Gemini CLI pool — signed-in Google accounts (like the Claude/Codex pools) plus API keys, one
  // rotation for both. The pool lives in corpus/llm_client.py, shared by the app and the pipeline.
  listGeminiAccounts: () => get('/api/settings/gemini-accounts'),
  useGemini: (kind, { name, keyIndex } = {}) => post('/api/settings/gemini-accounts/use', { kind, name, key_index: keyIndex }),
  removeGeminiAccount: (name) => post(`/api/settings/gemini-accounts/remove/${encodeURIComponent(name)}`, {}),
  launchGeminiLogin: (label, relogin) => post('/api/settings/gemini-accounts/login', { label: label || null, relogin: relogin || null }),
  geminiLoginStatus: () => get('/api/settings/gemini-accounts/login/status'),
  cancelGeminiLogin: () => post('/api/settings/gemini-accounts/login/cancel', {}),
  addGeminiKey: (api_key, label) => post('/api/settings/gemini-keys/add', { api_key, label }),
  removeGeminiKey: (index) => post(`/api/settings/gemini-keys/remove/${index}`, {}),

  // Qoder Personal Access Token pool (rotates on billing/quota failure)

  // Kimi Code (Moonshot AI) key pool (rotates on billing/membership failure)

  // Nemotron API key pool (rotates on rate-limit)
  listNemotronKeys: () => get('/api/settings/nemotron-keys'),
  addNemotronKey: (api_key, label) => post('/api/settings/nemotron-keys/add', { api_key, label }),
  removeNemotronKey: (index) => post(`/api/settings/nemotron-keys/remove/${index}`, {}),

  // Nemotron bash agent. A turn runs query → approve → approve → … until the
  // response comes back with status "complete".
  nemotronHealth: () => get('/api/nemotron/health'),

  // CLI subscription account pool
  listAccounts: () => get('/api/settings/accounts'),
  addAccount: (label) => post('/api/settings/accounts/add', { label }),
  removeAccount: (name) => post(`/api/settings/accounts/remove/${name}`, {}),
  useAccount: (name) => post(`/api/settings/accounts/use/${name}`, {}),
  launchLogin: () => post('/api/settings/accounts/login', {}),
  claudeLoginStatus: () => get('/api/settings/accounts/login/status'),
  submitClaudeLoginCode: (code) => post('/api/settings/accounts/login/submit-code', { code }),
  cancelClaudeLogin: () => post('/api/settings/accounts/login/cancel', {}),

  // Codex CLI (OpenAI) account pool — mirrors the Claude accounts endpoints
  // above exactly, pointed at ~/.codex/auth.json instead of ~/.claude/.credentials.json.
  listCodexAccounts: () => get('/api/settings/codex-accounts'),
  addCodexAccount: (label) => post('/api/settings/codex-accounts/add', { label }),
  removeCodexAccount: (name) => post(`/api/settings/codex-accounts/remove/${name}`, {}),
  useCodexAccount: (name) => post(`/api/settings/codex-accounts/use/${name}`, {}),
  launchCodexLogin: () => post('/api/settings/codex-accounts/login', {}),
  codexLoginStatus: () => get('/api/settings/codex-accounts/login/status'),
  cancelCodexLogin: () => post('/api/settings/codex-accounts/login/cancel', {}),

  // Corpus Builder — add novels + run the extraction pipeline
  cbNovels: () => get('/api/corpus-builder/novels'),
  cbCreateNovel: (title, novel_id = '') => post('/api/corpus-builder/novel/create', { title, novel_id }),
  cbUpload: async (novel_id, fileList) => {
    const fd = new FormData()
    for (const f of fileList) fd.append('files', f)
    const res = await fetch(`${BASE}/api/corpus-builder/novel/${novel_id}/upload`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
    return res.json()
  },
  // Chapters this novel doesn't have: plain gaps plus corrupt (null-byte)
  // downloads. `upto` extends the range past what's on disk, so holes at the
  // END of a novel are reported instead of falling outside the known range.
  cbRun: (opts) => post('/api/corpus-builder/run', opts),
  cbJob: (job_id) => get(`/api/corpus-builder/job/${job_id}`),
  cbJobs: () => get('/api/corpus-builder/jobs'),
  cbAbort: (job_id) => post(`/api/corpus-builder/job/${job_id}/abort`, {}),
  cbQueue: () => get('/api/corpus-builder/queue'),
  cbQueueAdd: (item) => post('/api/corpus-builder/queue/add', item),
  cbQueueRemove: (item_id) => post(`/api/corpus-builder/queue/remove/${item_id}`, {}),
  cbQueueRun: () => post('/api/corpus-builder/queue/run', {}),

  // Corpus Reader (routers/corpus_reader.py): the corpus novels' raw chapters, read-only
  crNovels: () => get('/api/corpus-reader/novels'),
  crChapters: (novel) => get(`/api/corpus-reader/novel/${encodeURIComponent(novel)}/chapters`),
  crChapter: (novel, n) => get(`/api/corpus-reader/novel/${encodeURIComponent(novel)}/chapter/${n}`),
  crRollingSummary: (novel) => get(`/api/corpus-reader/novel/${encodeURIComponent(novel)}/rolling-summary`),

  // Workspace Assistant — whole-workspace-root IDE chat (Claude Code CLI, same
  // login/model as Settings), with a lazy-expand file tree browser.
  aicoderStatus: () => get('/api/aicoder/status'),
  // Workspace Assistant's own engine dropdown (kimi | nemotron | ollama), overriding the system engine
  aicoderSetEngine: (engine) => post('/api/aicoder/engine', { engine }),
  // Build button: Build-NovelTea.ps1 rebuilds frontend + backend exe, then relaunches the app
  aicoderBuild: () => post('/api/aicoder/build', {}),
  aicoderBuildStatus: () => get('/api/aicoder/build/status'),
  aicoderTree: (path = '') => get(`/api/aicoder/tree?path=${encodeURIComponent(path)}`),
  aicoderFile: (path) => get(`/api/aicoder/file?path=${encodeURIComponent(path)}`),
  aicoderChat: (session_id, message) => post('/api/aicoder/chat', { session_id, message }),
  aicoderAbort: (session_id) => post(`/api/aicoder/abandon/${session_id}`, {}),
  aicoderProgress: (session_id, since = -1) => get(`/api/aicoder/progress/${session_id}?since=${since}`),
  aicoderSaveLog: (content, label = '') => post('/api/aicoder/save-log', { content, label }),
}
