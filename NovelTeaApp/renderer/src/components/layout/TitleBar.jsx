import useStore from '../../store/useStore'
import AgentEngineDropdown from '../shared/AgentEngineDropdown'

const NAV = [
  { id: 'dashboard',      label: 'Dashboard' },
  { id: 'corpus',         label: 'Corpus' },
  { id: 'corpusbuilder',  label: 'Corpus Builder' },
  { id: 'settings',       label: 'Settings' },
]

export default function TitleBar({ onMenuClick }) {
  const { activePage, activeProjectId, setPage, openSettings, closeProject, backendOnline,
          consoleOpen, consoleRunning, openConsole, closeConsole,
          interactiveResumeStatus, openInteractiveResume } = useStore()

  const currentNav = activeProjectId ? null : activePage
  const workspaceMode = !!activeProjectId && activePage === 'project'
  const panels = useStore(s => s.workspacePanels)
  const requestPanel = useStore(s => s.requestWorkspacePanel)

  return (
    <div style={{
      height: 'var(--titlebar-h)',
      background: 'var(--bg-surface)',
      borderBottom: '1px solid var(--border-soft)',
      display: 'flex',
      alignItems: 'center',
      flexShrink: 0,
      userSelect: 'none',
    }}>
      {/* Hamburger — mobile only */}
      <button
        onClick={onMenuClick}
        className="mobile-only"
        style={{
          padding: '0 14px', height: '100%',
          fontSize: 18, color: 'var(--text-secondary)',
          flexShrink: 0,
        }}
      >☰</button>

      {/* Logo */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '0 14px',
        flexShrink: 0,
        height: '100%',
      }}>
        {/* the logo goes home: the Dashboard */}
        <button onClick={() => { closeProject(); setPage('dashboard') }} title="Dashboard"
          style={{ WebkitAppRegion: 'no-drag', display: 'flex', alignItems: 'center', gap: 8, padding: 0,
                   background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', textAlign: 'left' }}>
          <div style={{
            width: 24, height: 24,
            background: 'linear-gradient(135deg, var(--accent) 0%, #06b6d4 100%)',
            borderRadius: 7,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 800, color: '#fff',
            boxShadow: '0 0 12px var(--accent-glow)',
            flexShrink: 0,
          }}>N</div>
          <div className="desktop-only">
            <div style={{ fontWeight: 700, fontSize: 13, lineHeight: 1.1 }}>NovelTea<span style={{ color: 'var(--accent)' }}> Engine</span></div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)', lineHeight: 1 }}>Novel creation engine · v1.1</div>
          </div>
        </button>
        <button
          onClick={() => window.location.reload()}
          title="Refresh the browser"
          style={{
            WebkitAppRegion: 'no-drag',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 24, height: 24, marginLeft: 2,
            fontSize: 13, color: 'var(--text-secondary)',
            borderRadius: 'var(--radius-sm)', border: '1px solid transparent',
            flexShrink: 0,
          }}
          onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--border)' }}
          onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'transparent' }}
        >⟳</button>
      </div>

      {/* Nav tabs — hidden on mobile */}
      <nav className="desktop-only" style={{
        display: 'flex', alignItems: 'center', height: '100%',
        padding: '0 4px', flex: 1, gap: 1,
      }}>
        {NAV.map(n => {
          const active = currentNav === n.id
          return (
            <button key={n.id} onClick={() => { closeProject(); setPage(n.id) }} style={{
              padding: '0 14px', height: '100%', fontSize: 12,
              fontWeight: active ? 600 : 400,
              color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
              borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
              borderRadius: 0, transition: 'color 0.15s', whiteSpace: 'nowrap',
            }}
            onMouseEnter={e => { if (!active) e.currentTarget.style.color = 'var(--text-primary)' }}
            onMouseLeave={e => { if (!active) e.currentTarget.style.color = 'var(--text-secondary)' }}
            >{n.label}</button>
          )
        })}
      </nav>

      {/* Inside a project's workspace layout the tools are the two slide-out panels; their buttons live up here on
          desktop (on a phone they get a bar of their own under the project header). */}
      {workspaceMode && !panels.fixed && (
        <div className="desktop-only" style={{ WebkitAppRegion: 'no-drag', display: 'flex', alignItems: 'center', gap: 8, margin: '0 8px' }}>
          {[['left', '◀ Pre-generation', 'Pre-generation'], ['right', 'Post-generation ▶', 'Post-generation']].map(([side, text, label]) => (
            <button key={side} onClick={() => requestPanel(side)} aria-label={label} aria-expanded={panels[side]}
              style={{
                fontSize: 12, fontWeight: 700, padding: '0 14px', height: 28, borderRadius: 'var(--radius-sm)', whiteSpace: 'nowrap',
                background: panels[side] ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                border: `1px solid ${panels[side] ? 'var(--accent)' : 'var(--border)'}`,
                color: panels[side] ? 'var(--accent-light)' : 'var(--text-primary)',
              }}>{text}</button>
          ))}
        </div>
      )}

      {/* Drag region — the window has frame:false, so this is the only way to
          move it. Buttons above/below opt back out via WebkitAppRegion:'no-drag'. */}
      <div style={{ flex: 1, height: '100%', WebkitAppRegion: 'drag' }} />

      {/* Provider switcher (Nvidia/Claude/Ollama) — visible on mobile too, not desktop-only */}
      <div style={{ WebkitAppRegion: 'no-drag', display: 'flex' }}>
        <AgentEngineDropdown />
      </div>

      {/* Continue Session — app-wide affordance for a resumable interactive
          survey/chapter session (arc wizard, etc.). Greyed out/inert with
          nothing to resume; lights up the moment the poller finds one,
          regardless of which tab started it or which page is on screen now —
          this is what makes navigating away no longer strand the session. */}
      <button
        onClick={() => interactiveResumeStatus && openInteractiveResume()}
        disabled={!interactiveResumeStatus}
        title={interactiveResumeStatus
          ? `Resume: ${interactiveResumeStatus.field || `Chapter ${interactiveResumeStatus.chapter_number}`}`
              + (interactiveResumeStatus.in_flight ? ' (still working…)' : '')
          : 'No interactive session in progress'}
        style={{
          WebkitAppRegion: 'no-drag', position: 'relative',
          display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', marginRight: 4,
          fontSize: 11, fontWeight: 700, borderRadius: 'var(--radius-sm)',
          background: 'transparent',
          border: `1px solid ${interactiveResumeStatus ? '#f59e0b' : 'var(--border)'}`,
          color: interactiveResumeStatus ? '#f59e0b' : 'var(--text-muted)',
          opacity: interactiveResumeStatus ? 1 : 0.5,
          cursor: interactiveResumeStatus ? 'pointer' : 'default',
        }}>
        ▶
        <span className="desktop-only">{interactiveResumeStatus?.in_flight ? 'Working…' : 'Continue'}</span>
        {interactiveResumeStatus && !interactiveResumeStatus.in_flight && (
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: '#f59e0b',
            boxShadow: '0 0 6px #f59e0b', animation: 'pulse-glow 1.4s ease-in-out infinite',
          }} />
        )}
      </button>

      {/* Engine console toggle — app-wide, so a generation started on any
          tab/page stays visible/abortable no matter where you navigate to. */}
      <button
        onClick={() => (consoleOpen ? closeConsole() : openConsole())}
        title={consoleRunning ? `Engine console — ${consoleRunning} running` : 'Engine console'}
        style={{
          WebkitAppRegion: 'no-drag', position: 'relative',
          display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', marginRight: 4,
          fontSize: 11, fontWeight: 700, borderRadius: 'var(--radius-sm)',
          background: consoleOpen ? 'var(--bg-elevated)' : 'transparent',
          border: `1px solid ${consoleRunning ? '#38bdf8' : 'var(--border)'}`,
          color: consoleRunning ? '#38bdf8' : 'var(--text-secondary)',
        }}>
        ⧉
        {consoleRunning && (
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: '#38bdf8',
            boxShadow: '0 0 6px #38bdf8', animation: 'pulse-glow 1.4s ease-in-out infinite',
          }} />
        )}
      </button>

      {/* Backend status dot — click for the Server page (CPU / RAM / the app's processes) */}
      <button
        onClick={() => openSettings('server')}
        title="Server status — CPU, memory and the processes NovelTea Engine has started"
        style={{
          WebkitAppRegion: 'no-drag', display: 'flex', alignItems: 'center', gap: 5, padding: '0 12px', height: '100%',
          background: currentNav === 'server' ? 'var(--bg-elevated)' : 'transparent', borderRadius: 0, cursor: 'pointer',
        }}>
        <div style={{
          width: 6, height: 6, borderRadius: '50%',
          background: backendOnline ? 'var(--green)' : 'var(--red)',
          boxShadow: backendOnline ? '0 0 6px var(--green)' : 'none',
        }} />
        <span className="desktop-only" style={{ fontSize: 10, color: backendOnline ? 'var(--green)' : 'var(--red)' }}>
          {backendOnline ? 'Online' : 'Offline'}
        </span>
      </button>

      <WindowControls />
    </div>
  )
}

// Minimize / maximize / close. Only rendered under Electron — in a plain browser
// tab window.electron is undefined and these would do nothing.
function WindowControls() {
  if (typeof window === 'undefined' || !window.electron) return null

  const base = {
    width: 44, height: '100%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 13, color: 'var(--text-secondary)',
    borderRadius: 0, transition: 'background 0.12s, color 0.12s',
    WebkitAppRegion: 'no-drag',
  }

  const hover = (bg, fg) => ({
    onMouseEnter: e => { e.currentTarget.style.background = bg; e.currentTarget.style.color = fg },
    onMouseLeave: e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)' },
  })

  return (
    <div style={{ display: 'flex', alignItems: 'center', height: '100%', flexShrink: 0 }}>
      <button title="Minimize" onClick={() => window.electron.minimize()}
        style={base} {...hover('var(--bg-elevated)', 'var(--text-primary)')}>─</button>
      <button title="Maximize" onClick={() => window.electron.maximize()}
        style={base} {...hover('var(--bg-elevated)', 'var(--text-primary)')}>▢</button>
      <button title="Close" onClick={() => window.electron.close()}
        style={base} {...hover('#e81123', '#fff')}>✕</button>
    </div>
  )
}
