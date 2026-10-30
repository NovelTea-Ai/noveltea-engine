import { useState } from 'react'
import useStore from '../../store/useStore'
import { api } from '../../api'

/* ── Global nav (shown when no project is open) ── */
const GLOBAL_NAV = [
  { id: 'dashboard',     label: 'Dashboard',           icon: '⊞' },
  { id: 'corpus',        label: 'Corpus',              icon: '▣' },
  { id: 'corpusbuilder', label: 'Corpus Builder',      icon: '✦' },
  { id: 'corpuspipeline', label: 'Corpus Pipeline',    icon: '⟳' },
  { id: 'corpusreader',  label: 'Corpus Reader',       icon: '◫' },
  { id: 'corpuswiki',    label: 'Corpus Wiki',       icon: '⟐', disabled: true, disabledTitle: 'Parked for now' },
  { id: 'standards',     label: 'Blueprint',           icon: '⎔' },
  { id: 'settings',      label: 'Settings',            icon: '◈' },
  { id: 'aicoder',       label: 'Workspace Assistant', icon: '⌘' },
]

/* ── Project nav tabs (mirror of ProjectView tabs) ── */
const PROJECT_NAV = [
  { id: 'overview',   label: 'Overview',         icon: '⊞' },
  { id: 'brief',      label: 'Creative Brief',   icon: '◈' },
  { id: 'arcs',       label: 'Arc Planner',      icon: '◐' },
  { id: 'chapters',   label: 'Chapter Skeleton', icon: '◎' },
  { id: 'characters', label: 'Characters',       icon: '◕' },
  { id: 'world',      label: 'World Bible',      icon: '◉' },
  { id: 'systems',    label: 'Systems',          icon: '⚙' },
  { id: 'generate',   label: 'Generate',         icon: '◨' },
  { id: 'reader',     label: 'Reader',           icon: '◫' },
  { id: 'editor',     label: 'Editor',           icon: '◧' },
]

function NavItem({ icon, label, active, badge, onClick, disabled, disabledTitle }) {
  return (
    <button onClick={disabled ? undefined : onClick} disabled={disabled} title={disabled ? disabledTitle : undefined} style={{
      width: '100%',
      display: 'flex', alignItems: 'center', gap: 9,
      padding: '6px 10px',
      borderRadius: 'var(--radius-sm)',
      fontSize: 12,
      fontWeight: active ? 500 : 400,
      color: disabled ? 'var(--text-muted)' : active ? 'var(--text-primary)' : 'var(--text-secondary)',
      background: active ? 'var(--bg-elevated)' : 'transparent',
      textAlign: 'left',
      transition: 'all 0.1s',
      border: active ? '1px solid var(--border-soft)' : '1px solid transparent',
      opacity: disabled ? 0.45 : 1,
      cursor: disabled ? 'not-allowed' : 'pointer',
    }}
    onMouseEnter={e => { if (!active && !disabled) { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.color = 'var(--text-primary)' } }}
    onMouseLeave={e => { if (!active && !disabled) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-secondary)' } }}
    >
      <span style={{
        width: 16, textAlign: 'center', fontSize: 12,
        color: disabled ? 'var(--text-muted)' : active ? 'var(--accent-light)' : 'var(--text-muted)',
        flexShrink: 0,
      }}>{icon}</span>
      <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {label}
      </span>
      {badge != null && badge > 0 && (
        <span style={{
          fontSize: 9, padding: '1px 5px', borderRadius: 8,
          background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          color: 'var(--text-muted)', fontWeight: 700, flexShrink: 0,
        }}>{badge}</span>
      )}
    </button>
  )
}

function SectionLabel({ label }) {
  return (
    <div style={{
      fontSize: 9, fontWeight: 700, letterSpacing: '0.1em',
      color: 'var(--text-muted)', padding: '10px 10px 4px',
      textTransform: 'uppercase',
    }}>{label}</div>
  )
}

export default function Sidebar({ onNav, activeTab, onTabChange }) {
  const { activePage, activeProjectId, projectData, setPage, closeProject, openWizard, corpusStats, removeProject } = useStore()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light')
  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768

  function toggleTheme() {
    const next = theme === 'light' ? 'dark' : 'light'
    document.documentElement.dataset.theme = next
    localStorage.setItem('nm-theme', next)
    setTheme(next)
  }

  async function deleteProject() {
    setDeleting(true)
    try {
      await api.deleteProject(activeProjectId)
      removeProject(activeProjectId)
      closeProject()
      onNav?.()
    } catch (e) {
      alert('Delete failed: ' + e.message)
    } finally {
      setDeleting(false)
      setShowDeleteConfirm(false)
    }
  }

  const project = projectData[activeProjectId]
  const arcs = project?.arcs || []
  const chapters = project?.chapter_skeletons || []
  const health = project?.planning_health || {}
  const brief = project?.creative_brief || {}
  const overallHealth = Object.values(health).some(v => v > 0)
    ? Math.round(Object.values(health).reduce((a, b) => a + b, 0) / Object.keys(health).length)
    : 0

  // Badges for project nav
  const BADGES = {
    arcs: arcs.length || undefined,
    chapters: chapters.length || undefined,
    characters: project?.character_count || undefined,
  }

  function goGlobal(id) {
    closeProject()
    setPage(id)
    onNav?.()
  }

  function goTab(id) {
    onTabChange?.(id)
    onNav?.()
  }

  return (
    <aside style={{
      width: 'var(--sidebar-w)',
      height: '100%',
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border-soft)',
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden', flexShrink: 0,
    }}>

      {activeProjectId ? (
        /* ── PROJECT MODE ── */
        <>
          {/* Back to projects */}
          <div style={{ padding: '10px 10px 6px' }}>
            <button onClick={() => { closeProject(); onNav?.() }} style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 7,
              padding: '7px 10px', borderRadius: 'var(--radius-sm)',
              fontSize: 11, color: 'var(--text-muted)',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              transition: 'color 0.12s',
            }}
            onMouseEnter={e => e.currentTarget.style.color = 'var(--text-primary)'}
            onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
            >
              <span>←</span>
              <span>All Projects</span>
            </button>
          </div>

          {/* Project name + delete */}
          {project && (
            <div style={{ padding: '0 12px 8px', borderBottom: '1px solid var(--border-soft)' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 6 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{
                    fontSize: 13, fontWeight: 700, color: 'var(--text-primary)',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>{project.title}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 1 }}>
                    {project.genre} · {project.status}
                  </div>
                </div>
                <button onClick={() => setShowDeleteConfirm(s => !s)} title="Delete project" style={{
                  fontSize: 12, color: 'var(--text-muted)', flexShrink: 0, padding: '2px 4px',
                  borderRadius: 'var(--radius-sm)', border: '1px solid transparent',
                  transition: 'color 0.15s, border-color 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.color = 'var(--red)'; e.currentTarget.style.borderColor = 'var(--red)' }}
                onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'transparent' }}
                >🗑</button>
              </div>

              {/* inline confirm */}
              {showDeleteConfirm && (
                <div style={{ marginTop: 8, padding: '8px 10px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 'var(--radius-sm)' }}>
                  <div style={{ fontSize: 10, color: 'var(--red)', fontWeight: 600, marginBottom: 6 }}>Delete this project?</div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button onClick={deleteProject} disabled={deleting} style={{
                      flex: 1, padding: '4px 0', fontSize: 10, fontWeight: 700,
                      background: 'var(--red)', color: '#fff', borderRadius: 'var(--radius-sm)',
                    }}>{deleting ? '…' : 'Delete'}</button>
                    <button onClick={() => setShowDeleteConfirm(false)} style={{
                      flex: 1, padding: '4px 0', fontSize: 10,
                      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
                    }}>Cancel</button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Project tabs */}
          <nav style={{ flex: 1, overflowY: 'auto', padding: '6px 6px 8px' }}>
            <SectionLabel label="Project" />
            {PROJECT_NAV.map(item => (
              <NavItem
                key={item.id}
                icon={item.icon}
                label={item.label}
                active={activeTab === item.id}
                badge={BADGES[item.id]}
                onClick={() => goTab(item.id)}
              />
            ))}
          </nav>

          {/* Stats panel — health + themes + reader exp */}
          <div style={{ borderTop: '1px solid var(--border-soft)', overflowY: 'auto', flexShrink: 0 }}>
            {/* Mobile toggle */}
            {isMobile && (
              <button onClick={() => setShowStats(s => !s)} style={{
                width: '100%', padding: '8px 12px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                color: 'var(--text-muted)', textTransform: 'uppercase',
                background: 'transparent', border: 'none',
              }}>
                <span>Planning Health</span>
                <span>{showStats ? '▲' : '▼'}</span>
              </button>
            )}
          <div style={{ padding: '10px 12px', display: isMobile && !showStats ? 'none' : 'block' }}>

            {/* Planning Health */}
            <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 8 }}>Planning Health</div>
            {[
              ['World Depth',       health.world_depth],
              ['Character Depth',   health.character_depth],
              ['Arc Pacing',        health.arc_pacing],
              ['Power Scaling',     health.power_scaling],
              ['Mystery Density',   health.mystery_density],
              ['Comedy Balance',    health.comedy_balance],
              ['Theme Consistency', health.theme_consistency],
              ['Reader Hooks',      health.reader_hooks],
            ].map(([label, val]) => {
              const v = val || 0
              const color = v >= 80 ? 'var(--green)' : v >= 60 ? 'var(--amber)' : v > 0 ? 'var(--red)' : 'rgba(255,255,255,0.08)'
              return (
                <div key={label} style={{ marginBottom: 5 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginBottom: 2 }}>
                    <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                    <span style={{ color, fontWeight: 600 }}>{v > 0 ? `${v}%` : '—'}</span>
                  </div>
                  <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2 }}>
                    <div style={{ height: '100%', width: `${v}%`, background: color, borderRadius: 2, transition: 'width 0.4s' }} />
                  </div>
                </div>
              )
            })}

            {/* Overall */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 6, marginTop: 4, borderTop: '1px solid var(--border-soft)', marginBottom: 10 }}>
              <span style={{ fontSize: 10, fontWeight: 700 }}>Overall</span>
              <span style={{ fontSize: 12, fontWeight: 800, color: overallHealth >= 80 ? 'var(--green)' : overallHealth > 0 ? 'var(--amber)' : 'var(--text-muted)' }}>
                {overallHealth > 0 ? `${overallHealth}%` : '—'}
              </span>
            </div>

            {/* Themes */}
            {brief.themes?.length > 0 && (
              <>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 6 }}>Themes</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
                  {brief.themes.map(t => (
                    <span key={t} style={{ padding: '2px 7px', borderRadius: 20, fontSize: 9, fontWeight: 600, background: 'var(--accent-dim)', color: 'var(--accent-light)', border: '1px solid var(--accent)' }}>{t}</span>
                  ))}
                </div>
              </>
            )}

            {/* Reader Experience */}
            {brief.reader_experience && Object.keys(brief.reader_experience).length > 0 && (
              <>
                <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 6 }}>Reader Experience</div>
                {Object.entries(brief.reader_experience).filter(([, v]) => v > 0).slice(0, 8).map(([k, v]) => (
                  <div key={k} style={{ marginBottom: 5 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginBottom: 2 }}>
                      <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</span>
                      <span style={{ fontWeight: 600 }}>{v}/10</span>
                    </div>
                    <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2 }}>
                      <div style={{ height: '100%', width: `${v * 10}%`, background: 'var(--accent)', borderRadius: 2 }} />
                    </div>
                  </div>
                ))}
              </>
            )}

            {/* Corpus dot */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border-soft)' }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>Corpus</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--green)', boxShadow: '0 0 5px var(--green)' }} />
                <span style={{ color: 'var(--green)', fontWeight: 700, fontSize: 9 }}>{corpusStats?.novels ?? '—'} novels</span>
              </div>
            </div>
          </div>
          </div>
        </>
      ) : (
        /* ── GLOBAL MODE ── */
        <>
          {/* New Project */}
          <div style={{ padding: '10px 10px 8px' }}>
            <button onClick={() => { openWizard(); onNav?.() }} className="btn-primary" style={{
              width: '100%', display: 'flex', alignItems: 'center',
              justifyContent: 'center', gap: 7, padding: '8px 12px',
            }}>
              <span style={{ fontSize: 16, lineHeight: 1 }}>+</span>
              <span>New Project</span>
            </button>
          </div>

          {/* Global nav */}
          <nav style={{ flex: 1, overflowY: 'auto', padding: '0 6px 8px' }}>
            <SectionLabel label="Navigation" />
            {GLOBAL_NAV.map(item => (
              <NavItem
                key={item.id}
                icon={item.icon}
                label={item.label}
                active={activePage === item.id}
                onClick={() => goGlobal(item.id)}
                disabled={item.disabled}
                disabledTitle={item.disabledTitle}
              />
            ))}
          </nav>

          {/* Corpus status footer — hidden on mobile */}
          <div style={{
            padding: '10px 12px',
            borderTop: '1px solid var(--border-soft)',
            fontSize: 11,
            display: isMobile ? 'none' : 'block',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span className="section-title">Corpus Status</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--green)', boxShadow: '0 0 5px var(--green)' }} />
                <span style={{ fontSize: 9, color: 'var(--green)', fontWeight: 700 }}>READY</span>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px' }}>
              {[
                ['Novels',   corpusStats?.novels   ?? '—'],
                ['Chapters', corpusStats?.chapters ?? '—'],
                ['Entities', corpusStats?.characters ?? '—'],
                ['Patterns', corpusStats?.patterns ?? '—'],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 10 }}>{v}</span>
                </div>
              ))}
            </div>
            <button onClick={() => goGlobal('corpus')} style={{
              width: '100%', marginTop: 8,
              padding: '5px', fontSize: 10, fontWeight: 600,
              background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--accent)' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.borderColor = 'var(--border)' }}
            >Corpus Manager →</button>
          </div>
        </>
      )}

      {/* Theme toggle — always visible, both project and global modes */}
      <div style={{ padding: '8px 10px', borderTop: '1px solid var(--border-soft)' }}>
        <button onClick={toggleTheme} title="Switch between dark and light mode" style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          padding: '6px', fontSize: 10, fontWeight: 600,
          background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)',
        }}>
          {theme === 'light' ? '🌙 Dark mode' : '☀️ Light mode'}
        </button>
      </div>
    </aside>
  )
}
