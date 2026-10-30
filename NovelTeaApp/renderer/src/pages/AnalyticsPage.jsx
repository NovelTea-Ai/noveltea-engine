import useStore from '../store/useStore'
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'

export default function AnalyticsPage() {
  const { novelData = {}, activeNovelId } = useStore()   // novelData no longer exists in the store — default so the page renders instead of crashing
  const dash = novelData[activeNovelId]
  const curve = dash?.tension_curve || []

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <h2 style={{ fontSize: 18, fontWeight: 700 }}>Analytics</h2>
      {curve.length > 0 ? (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 20 }}>
          <div style={{ fontWeight: 600, marginBottom: 12 }}>Tension Curve — Full Novel</div>
          <div style={{ height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={curve}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="chapter" stroke="var(--text-muted)" tick={{ fontSize: 10 }} />
                <YAxis stroke="var(--text-muted)" tick={{ fontSize: 10 }} domain={[0, 100]} />
                <Tooltip contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 11 }} />
                <Line type="monotone" dataKey="peak" stroke="var(--accent)" dot={false} strokeWidth={2} name="Peak Tension" />
                <Line type="monotone" dataKey="end" stroke="var(--teal)" dot={false} strokeWidth={1.5} strokeDasharray="4 2" name="End Tension" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
          Extract chapters to see analytics
        </div>
      )}
    </div>
  )
}
