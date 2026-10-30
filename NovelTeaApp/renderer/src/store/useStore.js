import { create } from 'zustand'
import { api } from '../api'

// ── Navigation persistence — a browser refresh (F5, or Safari's pull-to-
// refresh on iPhone, which is easy to trigger accidentally while reading)
// restores you to the same project + tab (e.g. the Reader on chapter 2)
// instead of dumping you back to the dashboard.
const NAV_KEY = 'nm-nav'
function savedNav() {
  try { return JSON.parse(localStorage.getItem(NAV_KEY)) || {} } catch { return {} }
}
function persistNav(patch) {
  try {
    localStorage.setItem(NAV_KEY, JSON.stringify({ ...savedNav(), ...patch }))
  } catch {}
}
const _nav = savedNav()

const useStore = create((set, get) => ({
  // Navigation (restored from the last session's position)
  activePage: _nav.page || 'dashboard',
  activeProjectId: _nav.projectId || null,
  activeProjectTab: _nav.tab || 'overview',
  setPage: (page) => { persistNav({ page, projectId: null, tab: 'overview' }); set({ activePage: page }) },
  settingsSection: null,   // one-shot: the Settings tab to open ('server', …); SettingsPage clears it once applied
  openSettings: (section) => { persistNav({ page: 'settings', projectId: null, tab: 'overview' }); set({ settingsSection: section, activeProjectId: null, activePage: 'settings' }) },
  openProject: (id) => { persistNav({ page: 'project', projectId: id, tab: 'overview' }); set({ activeProjectId: id, activePage: 'project', activeProjectTab: 'overview' }) },
  closeProject: () => { persistNav({ page: 'dashboard', projectId: null, tab: 'overview' }); set({ activeProjectId: null, activePage: 'dashboard', activeProjectTab: 'overview' }) },
  setProjectTab: (tab) => { persistNav({ tab }); set({ activeProjectTab: tab }) },
  // The workspace's two slide-out panels. ProjectWorkspace publishes which are open (so the title-bar buttons can
  // light up) and reacts to requests from those buttons.
  workspacePanels: { left: false, right: false, fixed: false },   // fixed: desktop, both panels always open, no title-bar buttons
  setWorkspacePanels: (p) => set({ workspacePanels: p }),
  workspaceToggle: null,   // { side, n } — n changes on every request, so asking for the same side twice still registers
  requestWorkspacePanel: (side) => set(s => ({ workspaceToggle: { side, n: (s.workspaceToggle?.n || 0) + 1 } })),

  // Projects (user-created novels being written)
  projects: [],
  projectsLoaded: false,
  loadProjects: async () => {
    try {
      const projects = await api.listProjects()
      set({ projects, projectsLoaded: true })
    } catch (e) {
      console.error('Failed to load projects', e)
      set({ projects: [], projectsLoaded: true })
    }
  },
  addProject: (project) => set(s => ({ projects: [...s.projects, project] })),
  removeProject: (id) => set(s => ({ projects: s.projects.filter(p => p.id !== id) })),

  // Full project data (per-project detail)
  projectData: {},
  loadProjectData: async (id) => {
    try {
      const data = await api.getProject(id)
      set(s => ({ projectData: { ...s.projectData, [id]: data } }))
    } catch (e) {
      console.error('Failed to load project', e)
    }
  },

  // Corpus global stats (from extracted novels)
  corpusStats: null,
  registry: null,
  loadCorpusStats: async () => {
    try {
      const [stats, reg] = await Promise.all([api.corpusStats(), api.registry()])
      set({ corpusStats: stats, registry: reg })
    } catch (e) {
      console.error('Failed to load corpus stats', e)
    }
  },

  // Engine state
  engineRunning: false,
  engineResult: null,
  runEngine: async (fn) => {
    set({ engineRunning: true, engineResult: null })
    try {
      const result = await fn()
      set({ engineRunning: false, engineResult: result })
      return result
    } catch (e) {
      set({ engineRunning: false })
      throw e
    }
  },

  // New project wizard
  wizardOpen: false,
  openWizard: () => set({ wizardOpen: true }),
  closeWizard: () => set({ wizardOpen: false }),

  // Backend health
  backendOnline: false,
  checkBackend: async () => {
    try {
      await api.health()
      set({ backendOnline: true })
    } catch {
      set({ backendOnline: false })
    }
  },

  // Agent engine (which CLI powers Discovery/Dialogue Shaping/agentic chapter
  // mode/etc) — shared here so the top-bar dropdown, Settings page, and the
  // project Assistant tab's own picker all stay in sync live, instead of each
  // independently polling and drifting apart.
  agentEngines: null,        // shape: { claude, gemini, qoder, kimi, nemotron, ollama, current, failover }
  agentEnginesLoading: false,
  loadAgentEngines: async () => {
    set({ agentEnginesLoading: true })
    try {
      const data = await api.listAgentEngines()
      set({ agentEngines: data, agentEnginesLoading: false })
    } catch (e) {
      console.error('Failed to load agent engines', e)
      set({ agentEnginesLoading: false })
    }
  },
  setAgentEngine: async (id) => {
    const prev = get().agentEngines
    if (!prev || id === prev.current) return
    set({ agentEngines: { ...prev, current: id } })   // optimistic
    try {
      await api.saveGenerationSettings({ agent_engine: id })
    } catch (e) {
      console.error('Failed to save agent engine', e)
      set({ agentEngines: prev })   // revert on failure
      throw e
    }
  },

  // CLI Model (models.anthropic in Settings) — which Claude model every app AI
  // button and the Claude engine (including the Ollama bridge, agentic paths,
  // arcs, chapters, fields) actually runs. Shared here, same reasoning as
  // agentEngines above, so the top-bar dropdown and SettingsPage's CLI Model
  // section stay in sync live.
  cliModel: null,             // e.g. "claude-sonnet-5-5"
  cliModelLoading: false,
  loadCliModel: async () => {
    set({ cliModelLoading: true })
    try {
      const s = await api.getSettings()
      set({ cliModel: (s.models || {}).anthropic || 'claude-haiku-4-5-20251001', cliModelLoading: false })
    } catch (e) {
      console.error('Failed to load CLI model', e)
      set({ cliModelLoading: false })
    }
  },
  setCliModel: async (id) => {
    const prev = get().cliModel
    if (id === prev) return
    set({ cliModel: id })   // optimistic
    try {
      await api.setModel('anthropic', id)
    } catch (e) {
      console.error('Failed to save CLI model', e)
      set({ cliModel: prev })   // revert on failure
      throw e
    }
  },

  // Codex Model (models.codex in Settings) — mirrors cliModel above exactly,
  // just for the Codex CLI engine (`codex exec -m <id>`).
  codexModel: null,             // e.g. "gpt-5.6-terra"
  codexModelLoading: false,
  loadCodexModel: async () => {
    set({ codexModelLoading: true })
    try {
      const s = await api.getSettings()
      set({ codexModel: (s.models || {}).codex || 'gpt-5.6-terra', codexModelLoading: false })
    } catch (e) {
      console.error('Failed to load Codex model', e)
      set({ codexModelLoading: false })
    }
  },
  setCodexModel: async (id) => {
    const prev = get().codexModel
    if (id === prev) return
    set({ codexModel: id })   // optimistic
    try {
      await api.setModel('codex', id)
    } catch (e) {
      console.error('Failed to save Codex model', e)
      set({ codexModel: prev })   // revert on failure
      throw e
    }
  },

  // Gemini CLI Model (models.gemini_cli — the key both the app's and the pipeline's Gemini
  // runners read) — mirrors codexModel above, for `gemini --model <id>`.
  geminiModel: null,            // e.g. "gemini-3.5-flash"
  geminiModelLoading: false,
  loadGeminiModel: async () => {
    set({ geminiModelLoading: true })
    try {
      const s = await api.getSettings()
      set({ geminiModel: (s.models || {}).gemini_cli || 'gemini-3.5-flash', geminiModelLoading: false })
    } catch (e) {
      console.error('Failed to load Gemini model', e)
      set({ geminiModelLoading: false })
    }
  },
  setGeminiModel: async (id) => {
    const prev = get().geminiModel
    if (id === prev) return
    set({ geminiModel: id })   // optimistic
    try {
      await api.setModel('gemini_cli', id)
    } catch (e) {
      console.error('Failed to save Gemini model', e)
      set({ geminiModel: prev })   // revert on failure
      throw e
    }
  },

  // ── Global engine console ──────────────────────────────────────────────
  // One console for the whole app, not per-tab. The backend already keeps a
  // SINGLE unified progress log per project (every generator tags its own
  // lines with an `engine` field) and a GET /generate/active/{id} endpoint
  // that reports whatever's in flight — so this just needs to poll those two
  // endpoints while a project is open; it doesn't need every generate button
  // in the app to explicitly "open" it. See consolePoll.js-equivalent logic
  // in startConsolePoller() below.
  consoleOpen: false,
  consoleCompact: true,
  consoleLines: [],          // [{msg, type, t}] — replaced wholesale from the backend's ordered log
  consoleRunning: null,      // display label (e.g. 'discovery', 'arc', 'characters') or null when idle
  consoleField: null,        // the (project_id, field) key's field half, for Abort — mirrors the old runningFieldRef
  // Set by a caller with NO project_id of its own (e.g. the Blueprint page's
  // paste-to-LLM extraction) alongside consoleRunning, instead of consoleField
  // — EngineConsole's Abort button calls THIS (via api.blueprintAbort) when
  // present rather than the project-scoped api.abandonGeneration, and clears
  // it in the same place consoleField gets cleared. null (the default) means
  // "route Abort the old project-scoped way", so every existing caller is
  // unaffected by this field existing.
  consoleAbortKey: null,
  consoleAbortFn: null,      // (abort_key) => Promise — which API call Abort should use; paired with consoleAbortKey
  // How many interactive/wizard popups currently have EngineConsoleMerged
  // mounted — the standalone floating EngineConsole (App.jsx) checks this and
  // renders nothing while it's > 0, so the console never shows as BOTH a
  // floating box AND merged into a popup card at the same time. A counter
  // (not a boolean) so two popups briefly overlapping during a transition
  // can't have one's unmount clobber the other's mount.
  consoleMergedCount: 0,
  registerConsoleMerged: () => set(s => ({ consoleMergedCount: s.consoleMergedCount + 1 })),
  unregisterConsoleMerged: () => set(s => ({ consoleMergedCount: Math.max(0, s.consoleMergedCount - 1) })),
  // Set true by the console's own Abort button (EngineConsole.jsx) — read by
  // a batch loop (e.g. GenerateTab's "AI Generate All") to stop advancing to
  // the next field. A plain component ref can't work here anymore since
  // Abort and the loop that needs to see it now live in different
  // components; a caller starting a NEW batch should reset it to false first.
  consoleAborted: false,
  setConsoleAborted: (v) => set({ consoleAborted: v }),
  openConsole: () => set({ consoleOpen: true }),
  closeConsole: () => set({ consoleOpen: false }),
  toggleConsoleCompact: () => set(s => ({ consoleCompact: !s.consoleCompact })),
  clearConsoleLines: () => set({ consoleLines: [] }),
  // Frontend-only synthetic line (e.g. "✓ Chapter complete") — the backend's
  // own lines arrive via the poller below and REPLACE consoleLines wholesale,
  // so this appends locally instead, same as the old per-tab addLog().
  appendConsoleLine: (msg, type = 'info') => set(s => ({
    consoleOpen: true,
    consoleLines: [...s.consoleLines, { msg, type, t: new Date().toLocaleTimeString() }],
  })),
  setConsoleRunning: (label, field = label) => set({ consoleRunning: label, consoleField: field, consoleOpen: true }),
  // Same as setConsoleRunning, for a caller with no project_id (no
  // consoleField makes sense) that still wants a real, working Abort button —
  // abortFn is called as abortFn(abortKey) by EngineConsole's Abort button.
  setConsoleRunningAbortable: (label, abortKey, abortFn) =>
    set({ consoleRunning: label, consoleField: null, consoleAbortKey: abortKey, consoleAbortFn: abortFn, consoleOpen: true }),
  clearConsoleRunning: () => set({ consoleRunning: null, consoleField: null, consoleAbortKey: null, consoleAbortFn: null }),

  // Global interactive-session resume affordance — a "Continue Session"
  // button (TitleBar) that lights up regardless of which page/tab is open,
  // since a survey's question/answer state used to live only in the local
  // React state of whichever tab started it: navigate away and the browser
  // had no way back in even though the server-side session was still alive
  // and fully resumable. Polled alongside the console (see startConsolePoller).
  interactiveResumeStatus: null,   // null | {active, session_id, kind, field, chapter_number, in_flight, ...}
  interactiveResumeOpen: false,
  openInteractiveResume: () => set({ interactiveResumeOpen: true }),
  closeInteractiveResume: () => set({ interactiveResumeOpen: false }),

  // Project Assistant chat — the backend endpoint is fully stateless (the
  // client resends the whole conversation every call), so the conversation
  // ONLY ever existed in whichever tab's local React state. Navigating away
  // mid-reply meant the response landed on an unmounted component (silently
  // dropped) and coming back reset the thread to empty. Keyed by project_id
  // here instead, so AssistantTab just reads/writes this rather than owning
  // its own useState — the conversation survives tab/page navigation exactly
  // like the console and the interactive-resume state already do.
  assistantChats: {},   // {[projectId]: {messages: [], loading: bool}}
  sendAssistantMessage: async (projectId, text, afterGenerate) => {
    const chat = get().assistantChats[projectId] || { messages: [], loading: false }
    if (!text.trim() || chat.loading) return
    const userMsg = { role: 'user', content: text.trim() }
    const history = [...chat.messages, userMsg]
    set(s => ({ assistantChats: { ...s.assistantChats, [projectId]: { messages: history, loading: true } } }))
    try {
      const apiMessages = history.map(m => ({ role: m.role, content: m.content }))
      const res = await api.projectChat(projectId, apiMessages, null)
      set(s => ({
        assistantChats: {
          ...s.assistantChats,
          [projectId]: {
            messages: [...(s.assistantChats[projectId]?.messages || history),
                        { role: 'assistant', content: res.reply, snapshot_id: res.snapshot_id }],
            loading: false,
          },
        },
      }))
      if (afterGenerate) afterGenerate({ field: 'project', provider: res.provider, undone: false, silent: true })
    } catch (e) {
      set(s => ({
        assistantChats: {
          ...s.assistantChats,
          [projectId]: {
            messages: [...(s.assistantChats[projectId]?.messages || history),
                        { role: 'assistant', content: `Error: ${e.message?.slice(0, 200) || 'Request failed'}`, error: true }],
            loading: false,
          },
        },
      }))
    }
  },
  undoAssistantMessage: async (projectId, msgIdx, snapshotId, afterGenerate) => {
    if (!snapshotId) return
    try {
      await api.projectChatUndo(projectId, snapshotId)
      set(s => {
        const chat = s.assistantChats[projectId]
        if (!chat) return {}
        const messages = chat.messages.map((msg, i) => i === msgIdx ? { ...msg, undone: true, snapshot_id: null } : msg)
        return { assistantChats: { ...s.assistantChats, [projectId]: { ...chat, messages } } }
      })
      if (afterGenerate) afterGenerate({ field: 'project', undone: true })
      return true
    } catch (e) {
      return e.message || 'Undo failed'
    }
  },
}))

// ── Console poller ──────────────────────────────────────────────────────
// Runs as one module-level interval (started once from App.jsx), not a
// per-component effect — a project can only be open once at a time
// (activeProjectId is a single store field), so there is only ever one
// thing to poll regardless of which page/tab is on screen. Idle cadence
// checks GET /generate/active/{project_id} (cheap, just a set membership
// check server-side) so a generation started by ANY button anywhere is
// discovered even though this component didn't start it; once something
// is active, switches to fast-polling the full progress log, matching the
// ~900ms cadence the old per-tab GenerateTab poller used.
let _consolePollTimer = null
const _IDLE_MS = 2000
const _ACTIVE_MS = 900

export function startConsolePoller() {
  if (_consolePollTimer) return   // already running — App.jsx only calls this once
  const tick = async () => {
    const { activeProjectId, consoleRunning } = useStore.getState()
    if (!activeProjectId) {
      _consolePollTimer = setTimeout(tick, _IDLE_MS)
      return
    }
    try {
      // Cheap — a dict lookup server-side, same cost class as getActiveGeneration
      // below. Independent of consoleRunning: an interactive survey can be
      // resumable even when nothing else is actively generating.
      const interactive = await api.interactiveStatus(activeProjectId)
      useStore.setState({ interactiveResumeStatus: interactive?.active ? interactive : null })
      if (!consoleRunning) {
        // Idle: just check whether anything is in flight for this project —
        // catches a generation started by a button the console has no
        // dedicated wiring for (e.g. a plain AIGenBtn click on any tab).
        const active = await api.getActiveGeneration(activeProjectId)
        if (active?.active && active.field) {
          useStore.setState({ consoleRunning: active.field, consoleField: active.field })
        }
      } else {
        const r = await api.generateProgress(activeProjectId, -1)
        const entries = r?.entries || []
        // Replace only the project-sourced lines — preserves any pipeline/
        // synthetic lines interleaved in the same log instead of wiping them
        // out every tick (this branch polls every ~900ms while active).
        useStore.setState(s => ({
          consoleLines: [
            ...s.consoleLines.filter(l => l.source && l.source !== 'project'),
            ...entries.map(e => ({
              msg: e.msg,
              type: e.kind === 'success' ? 'success' : e.kind === 'warn' ? 'warn' : 'info',
              t: e.t,
              source: 'project',
            })),
          ],
        }))
        // Re-check active state so the console clears itself once the
        // backend's own dedup lock releases, even if the button that
        // started it never explicitly calls clearConsoleRunning().
        const active = await api.getActiveGeneration(activeProjectId)
        if (!active?.active) {
          useStore.setState({ consoleRunning: null, consoleField: null })
        }
      }
    } catch { /* backend busy or between requests — keep quiet, try again next tick */ }
    const { consoleRunning: stillRunning } = useStore.getState()
    _consolePollTimer = setTimeout(tick, stillRunning ? _ACTIVE_MS : _IDLE_MS)
  }
  tick()
}

// ── Pipeline log poller ─────────────────────────────────────────────────
// Corpus Pipeline (Thread Typing / Symbol Filtering) activity used to render
// as a separate colored-dot status strip bolted above the console — not
// part of consoleLines at all, so it never showed which model was in use in
// any place you'd actually look, and Send Log/Copy never captured it either.
// This makes it real lines in the SAME log instead: same console, same
// Send Log export, no separate widget. Quiet by design — appends directly
// via setState rather than appendConsoleLine, so routine pipeline progress
// doesn't force the console open; only real errors (surfaced elsewhere, via
// the Corpus Pipeline page's own error handling) do that.
let _pipelinePollTimer = null
const _PIPELINE_POLL_MS = 6000
const _lastPipelineLiveTs = {}   // {[jobKey]: last-seen live.ts} — pure change-detection, not app state

export function startPipelineLogPoller() {
  if (_pipelinePollTimer) return   // already running — App.jsx only calls this once
  const tick = async () => {
    try {
      const res = await api.pipelineLive()     // running + doing-now only: the counts are never needed here
      for (const [key, job] of Object.entries(res.jobs || {})) {
        const live = job.live
        if (job.running && live?.ts && live.ts !== _lastPipelineLiveTs[key]) {
          _lastPipelineLiveTs[key] = live.ts
          const modelPart = live.model ? ` [${live.model}${live.batch_size ? `, batch ${live.batch_size}` : ''}]` : ''
          const kindPart = live.kind ? ` (${live.kind})` : ''
          const characterPart = live.character ? ` — ${live.character}` : ''
          // character_dna carries input volume (facts/quotes/chapters) instead
          // of a text preview — build the equivalent detail string for it
          // rather than printing "undefined" where live.preview would be for
          // every other job. Falls back to preview for jobs that DO set one.
          const detail = live.preview
            ?? (live.facts != null || live.quotes != null
                ? `${live.facts ?? 0} facts, ${live.quotes ?? 0} quotes` +
                  (live.chapters_read?.length ? `, ch.${live.chapters_read.join(',')}` : '')
                : null)
          useStore.setState(s => ({
            consoleLines: [...s.consoleLines, {
              msg: `${job.label}${modelPart}: ${live.novel}${characterPart}${kindPart}` + (detail ? ` — ${detail}` : ''),
              type: 'info', t: new Date().toLocaleTimeString(), source: 'pipeline',
            }],
          }))
        } else if (!job.running) {
          delete _lastPipelineLiveTs[key]
        }
      }
    } catch { /* backend busy or app not running — try again next tick */ }
    _pipelinePollTimer = setTimeout(tick, _PIPELINE_POLL_MS)
  }
  tick()
}

export default useStore
