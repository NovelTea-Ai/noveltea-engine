import { useState } from 'react'
import useStore from '../../store/useStore'

// Same id → label/color mapping as SettingsPage's ENGINE_INFO, kept small and
// local here (icons omitted — this is a compact title-bar control, not a card).
const ENGINES = {
  claude:   { label: 'Claude', color: '#d97706' },
  codex:    { label: 'OpenAI', color: '#10a37f' },   // engine id stays "codex" (backend contract) — displayed as its parent brand
  gemini:   { label: 'Google', color: '#4285f4' },   // engine id "gemini" (Gemini CLI) — displayed as its parent brand, like the two above
  nemotron: { label: 'Nvidia', color: '#76b900' },   // engine id stays "nemotron" (backend contract) — displayed as its parent brand
  kimi:     { label: 'Kimi K3', color: '#1783ff' },   // runs on NVIDIA with the same key pool as Nemotron
  ollama:   { label: 'Ollama', color: '#0ea5e9' },
  colibri:  { label: 'Colibrì', color: '#14b8a6' },   // local CPU engine, text-only (no file tools)
}

// Persistent top-bar engine switcher — reads/writes the same shared store slice
// as SettingsPage's AgentEngineSection and ProjectView's AssistantTab picker,
// so a change from any one of the three is reflected live in the other two.
export default function AgentEngineDropdown() {
  const { agentEngines, setAgentEngine } = useStore()
  const [saving, setSaving] = useState(false)

  if (!agentEngines) return null

  const current = agentEngines.current || 'claude'
  const info = ENGINES[current] || ENGINES.claude

  async function onChange(e) {
    const id = e.target.value
    if (agentEngines[id]?.available === false) return
    setSaving(true)
    try { await setAgentEngine(id) } catch {}
    finally { setSaving(false) }
  }

  return (
    <select
      value={current}
      onChange={onChange}
      disabled={saving}
      title="Agent Engine — which CLI powers Discovery, Dialogue Shaping & agentic generation"
      style={{
        WebkitAppRegion: 'no-drag',
        fontSize: 11, fontWeight: 700, padding: '4px 8px', marginRight: 4,
        borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)',
        border: `1px solid ${info.color}`, color: info.color, cursor: 'pointer',
      }}
    >
      {Object.entries(ENGINES).map(([id, e]) => {
        const avail = agentEngines[id]?.available !== false
        const missing = /not found|not installed/i.test(agentEngines[id]?.note || '')
        return (
          <option key={id} value={id} disabled={!avail} title={agentEngines[id]?.note || ''}>
            {e.label}{!avail ? (missing ? ' (not found)' : ' (not set up)') : ''}
          </option>
        )
      })}
    </select>
  )
}
