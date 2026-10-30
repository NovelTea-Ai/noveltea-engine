import { ExportMenu } from '../shared/ProjectIO'
import { FieldSurveyButton, Panel, PanelTitle, coverImageUrl } from '../shared/projectUi'
import { ARC_COLORS } from './common'

export function ProgressRing({ value, max, size = 80, stroke = 7 }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  const r = (size - stroke * 2) / 2
  const c = 2 * Math.PI * r
  const dash = (pct / 100) * c
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)', position: 'absolute' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={stroke} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--accent)" strokeWidth={stroke}
          strokeDasharray={`${dash} ${c}`} strokeLinecap="round" />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ fontWeight: 800, fontSize: 16, color: 'var(--accent)', lineHeight: 1 }}>{pct}%</div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{value}/{max}</div>
      </div>
    </div>
  )
}

export function CheckItem({ done, label, action, onClick }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 12px', borderRadius: 'var(--radius-sm)',
      background: done ? 'rgba(16,185,129,0.06)' : 'var(--bg-elevated)',
      border: `1px solid ${done ? 'rgba(16,185,129,0.2)' : 'var(--border-soft)'}`,
      marginBottom: 6,
    }}>
      <div style={{
        width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
        background: done ? 'var(--green)' : 'transparent',
        border: `2px solid ${done ? 'var(--green)' : 'var(--border)'}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 10, color: '#fff',
      }}>{done ? '✓' : ''}</div>
      <span style={{ flex: 1, fontSize: 12, color: done ? 'var(--text-muted)' : 'var(--text-primary)' }}>{label}</span>
      {!done && action && (
        <button onClick={onClick} style={{
          fontSize: 10, fontWeight: 600, padding: '3px 10px',
          background: 'var(--accent-dim)', color: 'var(--accent-light)',
          border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)',
        }}>{action}</button>
      )}
    </div>
  )
}

export function ArcCard({ arc, index, color }) {
  const chapters = arc.chapters || []
  return (
    <div style={{
      background: 'var(--bg-elevated)', border: `1px solid ${color}33`,
      borderTop: `2px solid ${color}`, borderRadius: 'var(--radius)',
      padding: '12px 14px', minWidth: 170, maxWidth: 210, flexShrink: 0,
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, color, marginBottom: 3 }}>Arc {index + 1}</div>
      <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.3, marginBottom: 5 }}>
        {arc.label?.replace(/^Arc \d+:\s*/i, '') || `Arc ${index + 1}`}
      </div>
      {arc.description && (
        <div style={{ fontSize: 10, color: 'var(--text-secondary)', lineHeight: 1.4, marginBottom: 8 }}>
          {arc.description}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)' }}>
        <span>Ch. {chapters[0] ?? '?'}–{chapters[chapters.length - 1] ?? '?'}</span>
        <span>{chapters.length} ch</span>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════
   OVERVIEW TAB
══════════════════════════════════════ */
export function OverviewTab({ project, arcs, chapters, health, state, brief, overallHealth, gradient, hasPremise, hasThemes, hasArcs, hasChapters, hasCharacters, setTab, onCoverEdit, onTitleEdit, saveField, afterGenerate, projectId }) {
  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: 12 }}>

        {/* hero — cover column widened from the old 80-120px sliver (and the
            first-pass 160-220px, which was still too subtle) to a genuinely
            large poster: up to 320px wide at a 2:3 book-cover proportion, so
            it dominates the panel instead of reading as a small icon next to
            the text. Grid drops to a single stacked column under 560px. */}
        <Panel>
          <div className="hero-cover-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,320px) 1fr', gap: 18 }}>
            <button onClick={onCoverEdit} style={{
              background: coverImageUrl(project) ? '#000' : gradient, borderRadius: 'var(--radius)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 72, aspectRatio: '2 / 3', width: '100%', cursor: 'pointer',
              border: '2px solid transparent', transition: 'border-color 0.15s',
              position: 'relative', overflow: 'hidden',
            }}
            onMouseEnter={e => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.2)'}
            onMouseLeave={e => e.currentTarget.style.borderColor = 'transparent'}
            >
              {coverImageUrl(project)
                ? <img src={coverImageUrl(project)} alt="" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
                : (project.cover_emoji || '⚡')}
              <div style={{
                position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 12, color: '#fff', opacity: 0, transition: 'opacity 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.opacity = '1'}
              onMouseLeave={e => e.currentTarget.style.opacity = '0'}
              >✎ Edit Cover</div>
            </button>

            <div style={{ padding: '14px 18px' }}>
              <button onClick={onTitleEdit} style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 4 }}>
                <h2 style={{ fontSize: 20, fontWeight: 800, borderBottom: '1px dashed transparent', transition: 'border-color 0.15s' }}
                  onMouseEnter={e => e.currentTarget.style.borderBottomColor = 'var(--text-muted)'}
                  onMouseLeave={e => e.currentTarget.style.borderBottomColor = 'transparent'}
                >{project.title} <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 400 }}>✎</span></h2>
              </button>

              {project.tagline && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 8 }}>
                  "{project.tagline}"
                </div>
              )}

              {brief.premise ? (
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 10, maxWidth: 500 }}>
                  {brief.premise.slice(0, 200)}{brief.premise.length > 200 ? '…' : ''}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 10 }}>
                  No premise yet —
                  <button onClick={() => setTab('brief')} style={{ color: 'var(--accent-light)', marginLeft: 4, fontSize: 11 }}>write one</button>
                  {' or '}
                  <FieldSurveyButton field="premise" projectId={projectId} onDone={res => { afterGenerate(res); setTab('brief') }} small />
                </div>
              )}

              <div style={{ display: 'flex', gap: 14, fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap', marginBottom: 12 }}>
                <span>Genre: <b style={{ color: 'var(--text-secondary)' }}>{project.genre}</b></span>
                <span>Target: <b style={{ color: 'var(--text-secondary)' }}>{project.target_chapters} ch</b></span>
                <span>Arcs: <b style={{ color: 'var(--text-secondary)' }}>{arcs.length}</b></span>
                <span>Chapters planned: <b style={{ color: 'var(--text-secondary)' }}>{chapters.length}</b></span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap' }}>
                  <button className="btn-primary" onClick={() => setTab('brief')} style={{ padding: '6px 14px', fontSize: 11 }}>Edit Brief</button>
                  <button className="btn-ghost" onClick={() => setTab('arcs')} style={{ padding: '5px 12px', fontSize: 11 }}>Plan Arcs</button>
                  <button className="btn-ghost" onClick={() => setTab('generate')} style={{ padding: '5px 12px', fontSize: 11 }}>Generate</button>
                  <ExportMenu projectId={project.id} />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', fontWeight: 700 }}>PLANNING</div>
                  <ProgressRing value={project.planning_progress || 0} max={100} size={60} stroke={5} />
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{project.chapters_written || 0}/{project.target_chapters} ch</div>
                </div>
              </div>
            </div>
          </div>
        </Panel>

        {/* checklist */}
        <Panel>
          <PanelTitle>Planning Checklist</PanelTitle>
          <CheckItem done={hasPremise}    label="Write premise & creative brief"   action="Go →" onClick={() => setTab('brief')} />
          <CheckItem done={hasThemes}     label="Define themes & tone"             action="Go →" onClick={() => setTab('brief')} />
          <CheckItem done={hasArcs}       label="Plan story arcs"                  action="Go →" onClick={() => setTab('arcs')} />
          <CheckItem done={hasChapters}   label="Generate chapter skeleton"        action="Go →" onClick={() => setTab('generate')} />
          <CheckItem done={hasCharacters} label="Create main characters"           action="Go →" onClick={() => setTab('characters')} />
        </Panel>

        {/* arc timeline */}
        {arcs.length > 0 && (
          <Panel>
            <PanelTitle action={<button onClick={() => setTab('arcs')} style={{ fontSize: 10, color: 'var(--accent-light)' }}>Edit →</button>}>
              Arc Timeline ({arcs.length})
            </PanelTitle>
            <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 6 }}>
              {arcs.map((arc, i) => <ArcCard key={i} arc={arc} index={i} color={ARC_COLORS[i % ARC_COLORS.length]} />)}
            </div>
          </Panel>
        )}

        {/* story state */}
        <Panel>
          <PanelTitle>Story State</PanelTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {[
              { icon: '◔', label: 'Mysteries', value: state.active_mysteries || 0, color: 'var(--cyan)' },
              { icon: '◗', label: 'Schemes',   value: state.active_schemes   || 0, color: 'var(--amber)' },
              { icon: '◎', label: 'Gags',      value: state.running_gags     || 0, color: 'var(--green)' },
              { icon: '◐', label: 'Foreshadow',value: state.foreshadowing    || 0, color: 'var(--purple)' },
            ].map(s => (
              <div key={s.label} style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--radius)', padding: '10px 12px', textAlign: 'center' }}>
                <div style={{ fontSize: 18, marginBottom: 4 }}>{s.icon}</div>
                <div style={{ fontSize: 20, fontWeight: 800, color: s.color, lineHeight: 1 }}>{s.value}</div>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 3 }}>{s.label}</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

    </div>
  )
}
