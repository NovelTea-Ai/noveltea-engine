import { useEffect } from 'react'
import useStore from '../../store/useStore'

export default function StoryBrainPage() {
  const { novelData = {}, activeNovelId, loadNovelDashboard } = useStore()   // novelData/loadNovelDashboard no longer exist in the store — default so the page renders instead of crashing
  const dash = novelData[activeNovelId]
  const state = dash?.story_state || {}

  useEffect(() => {
    if (activeNovelId && !dash && typeof loadNovelDashboard === 'function') loadNovelDashboard(activeNovelId)
  }, [activeNovelId])

  const metrics = [
    { label: 'Active Schemes',            value: state.active_schemes || 0,     color: 'var(--amber)' },
    { label: 'Open Mysteries',            value: state.open_mysteries || 0,      color: 'var(--cyan)' },
    { label: 'Running Gags',              value: state.running_gags || 0,        color: 'var(--green)' },
    { label: 'Pending Reveals',           value: state.pending_reveals || 0,     color: 'var(--accent)' },
    { label: 'Patterns Discovered',       value: state.patterns_discovered || 0, color: 'var(--teal)' },
  ]

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <h2 style={{ fontSize: 18, fontWeight: 700 }}>Story Brain — Control Room</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 12 }}>
        {metrics.map(m => (
          <div key={m.label} style={{
            background: 'var(--bg-surface)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '16px 14px', textAlign: 'center',
          }}>
            <div style={{ fontSize: 28, fontWeight: 800, color: m.color }}>{m.value}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{m.label}</div>
          </div>
        ))}
      </div>
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)', padding: 20,
        color: 'var(--text-muted)', fontSize: 12, textAlign: 'center',
      }}>
        Full Story Brain console coming soon — real-time narrative state, AI recommendations, and conflict detection.
      </div>
    </div>
  )
}
