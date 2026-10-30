

export const ARC_COLORS = ['#06b6d4','#a855f7','#f59e0b','#ec4899','#10b981','#3b82f6','#f97316','#ef4444','#8b5cf6']

// Editable repeatable list of plain strings — anti_patterns/reveals-shaped fields.
export function AdvStringList({ label, items, onChange, placeholder }) {
  const list = Array.isArray(items) ? items : []
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
      {list.map((v, i) => (
        <div key={i} style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
          <input value={v || ''} placeholder={placeholder}
            onChange={e => { const next = [...list]; next[i] = e.target.value; onChange(next) }}
            style={{ flex: 1, padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
          <button onClick={() => onChange(list.filter((_, idx) => idx !== i))}
            style={{ fontSize: 10, padding: '0 8px', borderRadius: 3, background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)' }}>✕</button>
        </div>
      ))}
      <button onClick={() => onChange([...list, ''])} style={{
        fontSize: 10, padding: '3px 10px', borderRadius: 'var(--radius-sm)',
        background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
      }}>+ Add</button>
    </div>
  )
}
