import { Component, useEffect, useState } from 'react'
import useStore, { startConsolePoller, startPipelineLogPoller } from './store/useStore'
import BootScreen from './components/layout/BootScreen'
import TitleBar from './components/layout/TitleBar'
import Sidebar from './components/layout/Sidebar'
import EngineConsole from './components/layout/EngineConsole'
import InteractiveResume from './components/generation/InteractiveResume'
import useKeepAwake from './hooks/useKeepAwake'
import Dashboard from './pages/Dashboard'
import ProjectView from './pages/ProjectView'
import CorpusPage from './pages/corpus/CorpusPage'
import CorpusBuilderPage from './pages/corpus/CorpusBuilderPage'
import CorpusPipelinePage from './pages/corpus/CorpusPipelinePage'
import CorpusReaderPage from './pages/corpus/CorpusReaderPage'
import CorpusWikiPage from './pages/corpus/CorpusWikiPage'
import BlueprintsPage from './pages/corpus/BlueprintsPage'
import StoryBrainPage from './pages/corpus/StoryBrainPage'
import AnalyticsPage from './pages/AnalyticsPage'
import AIStudioPage from './pages/AIStudioPage'
import SettingsPage from './pages/SettingsPage'
import AICoderPage from './pages/AICoderPage'
import ServerPage from './pages/ServerPage'
import NewProjectWizard from './components/generation/NewProjectWizard'

const PAGES = {
  dashboard: Dashboard,
  project: ProjectView,
  corpus: CorpusPage,
  corpusbuilder: CorpusBuilderPage,
  corpuspipeline: CorpusPipelinePage,
  corpusreader: CorpusReaderPage,
  corpuswiki: CorpusWikiPage,
  standards: BlueprintsPage,
  storybrain: StoryBrainPage,
  analytics: AnalyticsPage,
  aistudio: AIStudioPage,
  settings: SettingsPage,
  aicoder: AICoderPage,
  server: ServerPage,   // opened from the green status dot in the title bar (and Settings → Server)
}

// A page that throws while rendering used to unmount the whole app (blank window,
// and the saved page/project/tab in localStorage brought the same crash back on
// every launch). Contain it: show the error, keep the sidebar/title bar usable,
// and let the user reset the saved navigation.
class PageErrorBoundary extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  componentDidCatch(error, info) { console.error('Page crashed:', error, info?.componentStack) }
  componentDidUpdate(prev) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }
  reset = () => {
    try { localStorage.removeItem('nm-nav') } catch {}
    this.props.onReset?.()
    this.setState({ error: null })
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div style={{ flex: 1, padding: 24, overflow: 'auto' }}>
        <div style={{ maxWidth: 640, margin: '40px auto', padding: 20, borderRadius: 10,
          background: 'var(--bg-surface)', border: '1px solid var(--red, #f87171)' }}>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>This page hit an error</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
            The rest of the app is fine — use the sidebar, or go back to the dashboard.
          </div>
          <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '0 0 14px',
            padding: 10, borderRadius: 6, background: 'var(--bg-elevated)', maxHeight: 160, overflow: 'auto' }}>
            {String(this.state.error?.message || this.state.error)}
          </pre>
          <button onClick={this.reset} className="btn-primary" style={{ padding: '7px 18px', fontSize: 12 }}>
            Back to Dashboard
          </button>
        </div>
      </div>
    )
  }
}

export default function App() {
  const { activePage, activeProjectId, activeProjectTab, wizardOpen, checkBackend, loadCorpusStats, loadProjects, setProjectTab, loadAgentEngines, loadCliModel } = useStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  // the screen stays on while anything is generating (the console label, or an interview write in flight)
  const generating = useStore(st => !!st.consoleRunning || !!st.interactiveResumeStatus?.in_flight)
  useKeepAwake(generating)
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' && window.innerWidth < 768)
  // Show the NovelTea Engine boot screen once per browser session
  const [booted, setBooted] = useState(() => {
    try { return sessionStorage.getItem('nm_booted') === '1' } catch { return false }
  })

  function finishBoot() {
    try { sessionStorage.setItem('nm_booted', '1') } catch {}
    setBooted(true)
  }

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  useEffect(() => {
    checkBackend()
    loadCorpusStats()
    loadProjects()
    loadAgentEngines()
    loadCliModel()
    startConsolePoller()   // one module-level poller for the whole app, not per-page
    startPipelineLogPoller()   // corpus pipeline activity, as real lines in the same console
    const interval = setInterval(checkBackend, 10000)
    return () => clearInterval(interval)
  }, [])

  // Close sidebar on page change (mobile)
  useEffect(() => { setSidebarOpen(false) }, [activePage])

  const Page = PAGES[activePage] || Dashboard
  // In a project's workspace layout everything is in the two slide-out panels, so desktop needs no side navigation
  // (the title bar still has Dashboard / Corpus / Settings, and the project header has "← Projects").
  const hideSidebar = !isMobile && activePage === 'project' && !!activeProjectId

  if (!booted) return <BootScreen onReady={finishBoot} />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100dvh', overflow: 'hidden' }}>
      <TitleBar onMenuClick={() => setSidebarOpen(s => !s)} />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative' }}>
        {/* Mobile overlay */}
        {sidebarOpen && (
          <div
            onClick={() => setSidebarOpen(false)}
            style={{
              position: 'fixed', inset: 0, zIndex: 40,
              background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(2px)',
            }}
          />
        )}
        {/* Sidebar — slides in on mobile; hidden on desktop inside a workspace project */}
        {!hideSidebar && <div style={{
          position: isMobile ? 'fixed' : 'relative',
          top: isMobile ? 0 : undefined,
          left: isMobile ? (sidebarOpen ? 0 : '-100%') : undefined,
          height: isMobile ? '100%' : undefined,
          zIndex: isMobile ? 50 : undefined,
          transition: isMobile ? 'left 0.25s ease' : undefined,
          flexShrink: 0,
        }}>
          <Sidebar onNav={() => setSidebarOpen(false)} activeTab={activeProjectTab} onTabChange={setProjectTab} />
        </div>}
        <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <PageErrorBoundary resetKey={`${activePage}:${activeProjectTab}`} onReset={() => useStore.getState().setPage('dashboard')}>
            <Page />
          </PageErrorBoundary>
        </main>
      </div>
      {wizardOpen && <NewProjectWizard />}
      <EngineConsole />
      <InteractiveResume />
    </div>
  )
}
