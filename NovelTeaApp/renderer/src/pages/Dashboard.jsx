import { useEffect, useState } from 'react'
import useStore from '../store/useStore'
import { api, API_BASE } from '../api'
import { ExportMenu, ImportProjectButton } from '../components/shared/ProjectIO'

const STATUS_COLORS = {
  'Planning':          { bg: 'rgba(124,58,237,0.15)', color: '#9d6cf7', border: '#7c3aed' },
  'Planning Complete': { bg: 'rgba(16,185,129,0.15)', color: '#10b981', border: '#10b981' },
  'Writing':           { bg: 'rgba(14,165,233,0.15)', color: '#38bdf8', border: '#0ea5e9' },
  'Review':            { bg: 'rgba(245,158,11,0.15)', color: '#fbbf24', border: '#f59e0b' },
  'Complete':          { bg: 'rgba(16,185,129,0.15)', color: '#10b981', border: '#10b981' },
}

function ProgressRing({ value, max, size = 72, stroke = 6 }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  const r = (size - stroke * 2) / 2
  const c = 2 * Math.PI * r
  const dash = (pct / 100) * c
  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)', position: 'absolute' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none"
          stroke="rgba(255,255,255,0.06)" strokeWidth={stroke} />
        <circle cx={size/2} cy={size/2} r={r} fill="none"
          stroke="var(--accent)" strokeWidth={stroke}
          strokeDasharray={`${dash} ${c}`} strokeLinecap="round" />
      </svg>
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ fontSize: size < 80 ? 14 : 18, fontWeight: 800, color: 'var(--accent)', lineHeight: 1 }}>
          {pct}%
        </div>
        <div style={{ fontSize: 8, color: 'var(--text-muted)', marginTop: 1 }}>complete</div>
      </div>
    </div>
  )
}

function HealthBar({ value, color = 'var(--accent)' }) {
  return (
    <div style={{ width: '100%', height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${value}%`, background: color, borderRadius: 2, transition: 'width 0.4s' }} />
    </div>
  )
}

function ProjectCard({ project, onClick, onDelete }) {
  const status = STATUS_COLORS[project.status] || STATUS_COLORS['Planning']
  const health = project.health_score || 0
  const written = project.chapters_written || 0
  const target = project.target_chapters || 350
  const planPct = project.planning_progress || 0
  const words = project.words_written || 0

  const gradients = [
    'linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)',
    'linear-gradient(135deg, #0c1a2e 0%, #0f3460 100%)',
    'linear-gradient(135deg, #1a0a2e 0%, #44006b 100%)',
    'linear-gradient(135deg, #0a1f0a 0%, #0d4f1f 100%)',
    'linear-gradient(135deg, #1f0a0a 0%, #4f0d0d 100%)',
    'linear-gradient(135deg, #0a1a2e 0%, #0d3360 100%)',
  ]

  const gradient = project.cover_gradient
    ? `linear-gradient(${project.cover_gradient})`
    : gradients[Math.abs(project.id?.charCodeAt(0) || 0) % gradients.length]

  return (
    <div onClick={onClick} className="fade-in" style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border-soft)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      cursor: 'pointer',
      transition: 'transform 0.15s, border-color 0.15s, box-shadow 0.15s',
    }}
    onMouseEnter={e => {
      e.currentTarget.style.transform = 'translateY(-2px)'
      e.currentTarget.style.borderColor = 'var(--accent)'
      e.currentTarget.style.boxShadow = '0 8px 30px rgba(0,0,0,0.3)'
    }}
    onMouseLeave={e => {
      e.currentTarget.style.transform = 'translateY(0)'
      e.currentTarget.style.borderColor = 'var(--border-soft)'
      e.currentTarget.style.boxShadow = 'none'
    }}
    >
      {/* Cover — poster-style: a tall 2:3 book-cover proportion so the image
          is the dominant visual on the card (previously a thin 130px banner
          strip above a block of text — the image barely read as a cover at
          all). Title/tagline/status are overlaid on the image itself with a
          bottom scrim, the way a real book cover displays its title, instead
          of living in a separate text block below a short banner. */}
      <div style={{
        aspectRatio: '2 / 3',
        width: '100%',
        background: project.cover_image ? '#000' : gradient,
        position: 'relative',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        overflow: 'hidden',
      }}>
        {project.cover_image ? (
          <img src={`${API_BASE}${project.cover_image}`} alt="" loading="lazy"
            style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <div style={{
            fontSize: 'clamp(56px, 18vw, 84px)',
            filter: 'drop-shadow(0 4px 20px rgba(0,0,0,0.5))',
            textShadow: '0 0 40px rgba(255,255,255,0.15)',
          }}>{project.cover_emoji || '⚡'}</div>
        )}

        {/* Status badge */}
        <div style={{
          position: 'absolute', top: 10, right: 10,
          padding: '3px 9px',
          background: status.bg,
          border: `1px solid ${status.border}`,
          borderRadius: 20,
          fontSize: 10, fontWeight: 700, color: status.color,
        }}>{project.status}</div>

        {/* Health score */}
        {health > 0 && (
          <div style={{
            position: 'absolute', top: 10, left: 10,
            padding: '3px 9px',
            background: 'rgba(0,0,0,0.5)',
            backdropFilter: 'blur(4px)',
            borderRadius: 20,
            fontSize: 10, fontWeight: 700,
            color: health >= 85 ? 'var(--green)' : health >= 70 ? 'var(--amber)' : 'var(--red)',
          }}>◈ {health}%</div>
        )}

        {/* Bottom scrim + overlaid title/tagline */}
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0,
          padding: '28px 12px 10px',
          background: 'linear-gradient(transparent, rgba(0,0,0,0.85) 55%, rgba(0,0,0,0.92))',
        }}>
          <div style={{ fontWeight: 800, fontSize: 15, marginBottom: 3, lineHeight: 1.2, color: '#fff', textShadow: '0 1px 6px rgba(0,0,0,0.6)' }}>
            {project.title}
          </div>
          {project.tagline && (
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.75)', marginBottom: 4, fontStyle: 'italic', lineHeight: 1.3 }}>
              "{project.tagline}"
            </div>
          )}
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>
            {project.genre} · {target} ch
          </div>
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: '10px 14px 14px' }}>
        {words > 0 && (
          <div style={{ fontSize: 10, color: 'var(--teal)', marginBottom: 8, fontWeight: 600 }}>
            {written} chapters · {words.toLocaleString()} words written
          </div>
        )}

        {/* Progress stats */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Written</span>
              <span style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600 }}>{written}/{target}</span>
            </div>
            <HealthBar value={(written / target) * 100} color="var(--teal)" />
          </div>
          <div style={{ width: 12 }} />
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Planned</span>
              <span style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600 }}>{planPct}%</span>
            </div>
            <HealthBar value={planPct} color="var(--accent)" />
          </div>
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
          <button onClick={e => { e.stopPropagation(); onClick() }} style={{
            flex: 1, padding: '5px 10px',
            background: 'var(--accent-dim)', color: 'var(--accent-light)',
            border: '1px solid var(--accent)',
            borderRadius: 'var(--radius-sm)', fontSize: 11, fontWeight: 600,
            transition: 'all 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--accent)' && (e.currentTarget.style.color = '#fff')}
          onMouseLeave={e => { e.currentTarget.style.background = 'var(--accent-dim)'; e.currentTarget.style.color = 'var(--accent-light)' }}
          >Open →</button>
          <ExportMenu projectId={project.id} compact />
          <button onClick={e => { e.stopPropagation(); onDelete(project) }} style={{
            padding: '5px 10px',
            background: 'var(--bg-elevated)', color: 'var(--text-muted)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', fontSize: 11,
            transition: 'color 0.15s, border-color 0.15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.color = 'var(--red)'; e.currentTarget.style.borderColor = 'var(--red)' }}
          onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border)' }}
          title="Delete project">🗑</button>
        </div>
      </div>
    </div>
  )
}

function EmptyState({ onImported, openWizard, onDemo, demoBusy }) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      gap: 16, padding: 60,
    }}>
      <div style={{
        width: 80, height: 80, borderRadius: '50%',
        background: 'var(--accent-dim)', border: '1px solid var(--accent)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 36, marginBottom: 8,
      }}>✦</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-primary)' }}>
        No projects yet
      </div>
      <div style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'center', maxWidth: 380, lineHeight: 1.6 }}>
        Create your first novel project and plan it tab by tab (brief, cast, systems, arcs, chapter plans) before you write a single word. Or open the demo project to see a finished example.
      </div>
      <button onClick={openWizard} className="btn-primary" style={{
        padding: '10px 28px', fontSize: 14, marginTop: 8,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span>+</span> Create First Project
      </button>
      <button onClick={onDemo} disabled={demoBusy} style={{
        padding: '8px 22px', fontSize: 13, background: 'var(--bg-elevated)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
      }}>{demoBusy ? 'Loading the demo…' : '🏮 Open the demo project'}</button>
      <ImportProjectButton onImported={onImported} style={{ padding: '8px 22px', fontSize: 13 }} />
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
        Corpus research novels are in <b style={{ color: 'var(--text-secondary)' }}>Corpus Library</b>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { projects, projectsLoaded, loadProjects, openProject, openWizard, corpusStats, removeProject } = useStore()
  const [confirmDelete, setConfirmDelete] = useState(null) // project object
  const [deleting, setDeleting] = useState(false)

  // after an import: show the new project in the list and open it
  async function onImported(r) {
    await loadProjects()
    openProject(r.id)
  }
  const [demoBusy, setDemoBusy] = useState(false)

  // the fictional demo project that ships with the repository
  async function openDemo() {
    setDemoBusy(true)
    try {
      const r = await api.installDemo()
      await loadProjects()
      openProject(r.id)
    } catch (e) {
      alert('Could not load the demo project: ' + e.message)
    } finally {
      setDemoBusy(false)
    }
  }

  async function handleDelete() {
    if (!confirmDelete) return
    setDeleting(true)
    try {
      await api.deleteProject(confirmDelete.id)
      removeProject(confirmDelete.id)
      setConfirmDelete(null)
    } catch (e) {
      alert('Delete failed: ' + e.message)
    } finally {
      setDeleting(false)
    }
  }

  useEffect(() => {
    if (!projectsLoaded) loadProjects()
  }, [projectsLoaded])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Delete confirmation modal */}
      {confirmDelete && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }}>
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--red)', borderRadius: 'var(--radius-lg)', padding: 24, maxWidth: 360, width: '90%', textAlign: 'center' }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>🗑</div>
            <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 8 }}>Delete "{confirmDelete.title}"?</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 20 }}>
              This will permanently delete the project and all its generated chapters. This cannot be undone.
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
              <button onClick={() => setConfirmDelete(null)} className="btn-ghost" style={{ padding: '7px 20px' }}>Cancel</button>
              <button onClick={handleDelete} disabled={deleting} style={{
                padding: '7px 20px', fontWeight: 700, fontSize: 13,
                background: 'var(--red)', color: '#fff', borderRadius: 'var(--radius-sm)',
                opacity: deleting ? 0.6 : 1,
              }}>{deleting ? 'Deleting…' : 'Delete'}</button>
            </div>
          </div>
        </div>
      )}
      {/* Header */}
      <div style={{
        padding: '14px 16px 0',
        borderBottom: '1px solid var(--border-soft)',
        background: 'var(--bg-surface)',
        flexShrink: 0,
      }}>
        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 3 }}>My Projects</h1>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {projects.length} novel{projects.length !== 1 ? 's' : ''} in workspace
            </div>
          </div>
          <ImportProjectButton onImported={onImported} />
        </div>

        {/* Corpus summary pills — scrollable row */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, overflowX: 'auto', paddingBottom: 2 }}>
          {[
            { label: 'Novels', value: corpusStats?.novels ?? '—', color: 'var(--accent)' },
            { label: 'Chapters', value: corpusStats?.chapters ?? '—', color: 'var(--teal)' },
            { label: 'Patterns', value: corpusStats?.patterns ?? '—', color: 'var(--amber)' },
            { label: 'Entities', value: corpusStats?.characters ?? '—', color: 'var(--purple)' },
          ].map(s => (
            <div key={s.label} style={{
              padding: '5px 12px', flexShrink: 0,
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              textAlign: 'center',
            }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Filter tabs — scrollable */}
        <div className="tab-scroll" style={{ display: 'flex', gap: 1 }}>
          {['All', 'Planning', 'Writing', 'Review', 'Complete'].map((f, i) => (
            <button key={f} style={{
              padding: '5px 14px', flexShrink: 0,
              fontSize: 11, fontWeight: i === 0 ? 600 : 400,
              color: i === 0 ? 'var(--text-primary)' : 'var(--text-muted)',
              borderBottom: i === 0 ? '2px solid var(--accent)' : '2px solid transparent',
              borderRadius: 0,
              transition: 'color 0.12s',
            }}>{f}</button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {!projectsLoaded ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
            Loading projects...
          </div>
        ) : projects.length === 0 ? (
          <EmptyState onImported={onImported} openWizard={openWizard} onDemo={openDemo} demoBusy={demoBusy} />
        ) : (
          <div style={{ padding: '16px' }}>
            <div className="project-grid" style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
              gap: 16,
            }}>
              {projects.map(p => (
                <ProjectCard key={p.id} project={p} onClick={() => openProject(p.id)} onDelete={setConfirmDelete} />
              ))}

              {!projects.some(p => p.id === 'the_lantern_court') && (
                <div onClick={openDemo} style={{
                  background: 'transparent', border: '2px dashed var(--border)', borderRadius: 'var(--radius-lg)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  gap: 10, cursor: 'pointer', minHeight: 300,
                }}>
                  <div style={{ fontSize: 34 }}>🏮</div>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{demoBusy ? 'Loading the demo…' : 'Open the demo project'}</div>
                </div>
              )}

              {/* Add new card */}
              <div onClick={openWizard} style={{
                background: 'transparent',
                border: '2px dashed var(--border)',
                borderRadius: 'var(--radius-lg)',
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                gap: 10, cursor: 'pointer', minHeight: 300,
                transition: 'border-color 0.15s, background 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.background = 'var(--accent-dim)' }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'transparent' }}
              >
                <div style={{
                  width: 44, height: 44, borderRadius: '50%',
                  background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 22, color: 'var(--text-muted)',
                }}>+</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>
                  New Project
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
