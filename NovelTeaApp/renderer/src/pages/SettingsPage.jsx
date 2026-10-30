import { useState, useEffect, useRef } from 'react'
import { api } from '../api'
import useStore from '../store/useStore'
import ServerPage from './ServerPage'
import VoiceSamples from '../components/shared/VoiceSamples'
import PhoneSetup from '../components/shared/PhoneSetup'
import { CLI_MODELS, CODEX_MODELS, GEMINI_MODELS, NEMOTRON_MODELS } from '../constants/agentModels'

function Spinner({ size = 14 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size,
      border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    }} />
  )
}

const PROVIDERS = [
  {
    id: 'anthropic',
    label: 'Anthropic',
    icon: '◈',
    color: '#d97706',
    models: ['claude-sonnet-5-5', 'claude-haiku-4-5-20251001', 'claude-opus-5-5', 'claude-fable-5'],
    placeholder: 'sk-ant-api03-...',
    desc: 'Best results. Claude Haiku is fast for planning; Sonnet for prose.',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    icon: '◎',
    color: '#10b981',
    models: ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'],
    placeholder: 'sk-...',
    desc: 'Good alternative. GPT-4o-mini is fast and affordable.',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    icon: '◐',
    color: '#6366f1',
    models: ['anthropic/claude-haiku-4-5', 'openai/gpt-4o-mini', 'meta-llama/llama-3.1-70b-instruct'],
    placeholder: 'sk-or-...',
    desc: 'Access many models via one key. Good for trying different models.',
  },
]

function Section({ title, children }) {
  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border-soft)',
      borderRadius: 'var(--radius-lg)', padding: 20, marginBottom: 16,
    }}>
      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 14, color: 'var(--text-primary)' }}>{title}</div>
      {children}
    </div>
  )
}

function FieldRow({ label, hint, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 3 }}>{label}</div>
      {hint && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 6 }}>{hint}</div>}
      {children}
    </div>
  )
}

// Grip-intensity picker (Fast → Targeted → Agentic). Reused in Settings
// (global default) and next to each Generate/Update button (per-button override).
export const GREP_MODES = [
  { id: 'fast',     label: 'Fast',     desc: 'Random corpus samples injected. Quickest.', color: '#38bdf8' },
  { id: 'targeted', label: 'Targeted', desc: 'Retrieves corpus beats relevant to this project. Better quality.', color: '#22c55e' },
  { id: 'agentic',  label: 'Agentic',  desc: 'The CLI greps the corpus files freely, plus the full Ollama semantic-search block over the whole corpus. Richest, slower.', color: '#a78bfa' },
]

function GrepSlider({ value, onChange, compact }) {
  const idx = Math.max(0, GREP_MODES.findIndex(m => m.id === value))
  const cur = GREP_MODES[idx] || GREP_MODES[0]
  return (
    <div>
      <div style={{ display: 'flex', gap: compact ? 3 : 5 }}>
        {GREP_MODES.map(m => {
          const on = m.id === value
          return (
            <button key={m.id} onClick={() => onChange(m.id)} title={m.desc} style={{
              flex: 1, padding: compact ? '4px 4px' : '7px 6px', fontSize: compact ? 10 : 11, fontWeight: on ? 700 : 500,
              borderRadius: 'var(--radius-sm)',
              background: on ? m.color : 'var(--bg-elevated)',
              color: on ? '#0b1220' : 'var(--text-secondary)',
              border: `1px solid ${on ? m.color : 'var(--border)'}`,
              transition: 'all 0.12s', whiteSpace: 'nowrap',
            }}>{m.label}</button>
          )
        })}
      </div>
      {!compact && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6 }}>{cur.desc}</div>}
    </div>
  )
}

function ApiKeyCard({ provider, savedKeys, models, onSave, onDelete }) {
  const [key, setKey] = useState('')
  const [model, setModel] = useState(models[0])
  const [show, setShow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const hasKey = !!savedKeys[provider.id]

  async function handleSave() {
    if (!key.trim()) return
    setSaving(true)
    setMsg(null)
    try {
      await onSave(provider.id, key.trim(), model)
      setMsg({ type: 'success', text: '✓ Key saved' })
      setKey('')
    } catch (e) {
      setMsg({ type: 'error', text: e.message })
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    await onDelete(provider.id)
    setMsg({ type: 'info', text: 'Key removed' })
  }

  return (
    <div style={{
      border: `1px solid ${hasKey ? provider.color + '44' : 'var(--border-soft)'}`,
      borderRadius: 'var(--radius)',
      padding: '14px 16px',
      marginBottom: 10,
      background: hasKey ? `${provider.color}08` : 'var(--bg-elevated)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: provider.color, fontSize: 16 }}>{provider.icon}</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{provider.label}</div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{provider.desc}</div>
          </div>
        </div>
        {hasKey && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <div style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 10,
              background: `${provider.color}20`, color: provider.color,
              border: `1px solid ${provider.color}`, fontWeight: 700,
            }}>● Connected · {savedKeys[provider.id]}</div>
            <button onClick={handleDelete} style={{
              fontSize: 10, padding: '3px 10px', color: 'var(--red)',
              border: '1px solid var(--red)', borderRadius: 'var(--radius-sm)',
              background: 'var(--red-dim)',
            }}>Remove</button>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
            {hasKey ? 'Enter new key to replace:' : 'API Key:'}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              type={show ? 'text' : 'password'}
              value={key}
              onChange={e => setKey(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSave()}
              placeholder={provider.placeholder}
              style={{
                flex: 1, padding: '6px 10px', fontSize: 12,
                borderRadius: 'var(--radius-sm)', fontFamily: 'monospace',
                minWidth: 0,
              }}
            />
            <button onClick={() => setShow(s => !s)} style={{
              padding: '5px 10px', fontSize: 11, flexShrink: 0,
              background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
            }}>{show ? 'Hide' : 'Show'}</button>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 140 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>Default model:</div>
            <select value={model} onChange={e => setModel(e.target.value)} style={{
              width: '100%', padding: '6px 8px', fontSize: 11,
              borderRadius: 'var(--radius-sm)',
            }}>
              {provider.models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <button onClick={handleSave} disabled={!key.trim() || saving} style={{
            padding: '7px 20px', fontSize: 12, fontWeight: 600, flexShrink: 0,
            background: key.trim() ? provider.color : 'var(--bg-elevated)',
            color: key.trim() ? '#fff' : 'var(--text-muted)',
            border: 'none', borderRadius: 'var(--radius-sm)',
            transition: 'all 0.15s',
          }}>
            {saving ? '…' : 'Save'}
          </button>
        </div>
      </div>

      {msg && (
        <div style={{
          marginTop: 8, fontSize: 11,
          color: msg.type === 'success' ? 'var(--green)' : msg.type === 'error' ? 'var(--red)' : 'var(--text-muted)',
        }}>{msg.text}</div>
      )}
    </div>
  )
}

const ENGINE_INFO = {
  claude: { label: 'Claude Code CLI', icon: '◈', color: '#d97706',
    desc: 'Full tool-path scoping (per-glob allow/deny), corpus-wide grep access. Powers all agentic features today.' },
  codex: { label: 'Codex CLI', icon: '✦', color: '#10a37f',
    desc: 'OpenAI Codex CLI via `codex exec` (non-interactive mode) — same subscription-account-pool setup as Claude below, just pointed at ~/.codex/auth.json instead of ~/.claude/.credentials.json. Requires `codex` on PATH (npm install -g @openai/codex) and a ChatGPT sign-in (`codex login`).' },
  gemini: { label: 'Gemini CLI', icon: '✦', color: '#4285f4',
    desc: 'Google Gemini CLI (`@google/gemini-cli`) — same account-pool setup as Claude and Codex: sign in with one or more Google accounts (and/or add API keys) under CLI Accounts → Gemini, and it rotates to the next one when an account hits its limit. Requires `gemini` on PATH (npm install -g @google/gemini-cli; npx works too, but slower).' },
  nemotron: { label: 'Nemotron Agent', icon: '▲', color: '#76b900',
    desc: 'NVIDIA Nemotron via direct API — no CLI to install, just an nvapi- key in the pool below. Structured read_file/write_file tools sandboxed to novels/projects/generated, with the corpus read-only; whole-file writes keep Undo snapshots working. Also has an allowlisted bash tool for grep, with rm/mv/sudo hard-blocked.' },
  kimi: { label: 'Kimi K3 Agent', icon: '☾', color: '#1783ff',
    desc: 'Moonshot Kimi K3 via NVIDIA\'s API — same setup as Nemotron: no CLI to install and it shares the nvapi- key pool below (one key powers both). Same sandboxed read_file/write_file tools and allowlisted bash grep. Thinking is always on, with a 1M-token context.' },
  colibri: { label: 'Colibrì (local CPU)', icon: '✦', color: '#14b8a6',
    desc: 'Runs a local model on this PC\'s CPU with Colibrì — fully offline, no key, no cost. Same file tools as the other agents (the app speaks Qwen\'s own tool-call format to it), but a small CPU model: a few tokens per second, and every prompt token takes seconds, so a tool-using turn takes minutes and a small model makes more mistakes than Claude or Kimi. The app starts and stops the Colibrì server for you.' },
  ollama: { label: 'Ollama (local)', icon: '◐', color: '#0ea5e9',
    desc: 'Runs a local Ollama model through the real Claude Code CLI — full Read/Grep/Glob/Edit tool loop, same as the Claude engine, just pointed at Ollama\'s endpoint instead of Anthropic\'s servers. Fully offline, no API key, no per-token cost, nothing leaves the machine. Requires both `claude` on PATH and a tool-calling-capable model pulled in Ollama (qwen2.5-coder, gemma3/4 and llama3.1 all work); a model without tool support can still be used for plain generation, but agentic features (Discovery, Dialogue Shaping, etc.) need one that does.' },
}

function AgentEngineSection() {
  const { agentEngines, loadAgentEngines, setAgentEngine } = useStore()
  const engines = agentEngines || { claude: { available: true }, codex: { available: false }, gemini: { available: false }, nemotron: { available: false }, kimi: { available: false }, ollama: { available: false }, colibri: { available: false }, current: 'claude', failover: false }
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { if (!agentEngines) loadAgentEngines() }, [])

  async function pick(engineId) {
    if (!engines[engineId]?.available) return
    setSaving(true)
    try {
      await setAgentEngine(engineId)
      setMsg(`✓ Agent engine set to ${ENGINE_INFO[engineId]?.label || engineId}`)
    } catch (e) { setMsg(e.message || 'Failed to save') }
    finally { setSaving(false); setTimeout(() => setMsg(''), 3000) }
  }

  async function toggleFailover() {
    const next = !engines.failover
    setSaving(true)
    try {
      await api.saveGenerationSettings({ agent_engine_failover: next })
      await loadAgentEngines()
    } catch (e) { setMsg(e.message || 'Failed to save') }
    finally { setSaving(false); setTimeout(() => setMsg(''), 3000) }
  }

  return (
    <Section title="Agent Engine — which CLI powers Discovery, Dialogue Shaping, Fix buttons & AGENTIC chapter mode">
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12, lineHeight: 1.6 }}>
        Requires the CLI to be installed/authenticated (Claude: <code style={codeStyle}>claude /login</code>;
        Codex: <code style={codeStyle}>codex login</code>;
        Gemini: <b>Sign in with Google</b> under CLI Accounts (or add an API key);
        Nemotron &amp; Kimi K3: no CLI needed, just an API key in the shared pool; Ollama: run <code style={codeStyle}>ollama serve</code> and pull a model; Colibrì: an install plus a model folder, see Colibrì Model below).
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        {Object.entries(ENGINE_INFO).map(([id, info]) => {
          const avail = engines[id]?.available !== false
          const active = engines.current === id
          return (
            <button key={id} onClick={() => pick(id)} disabled={saving || !avail} title={avail ? '' : engines[id]?.note}
              style={{
                flex: '1 1 260px', textAlign: 'left', padding: '12px 14px', borderRadius: 'var(--radius-lg)',
                border: `1px solid ${active ? info.color : 'var(--border-soft)'}`,
                background: active ? `${info.color}14` : 'var(--bg-elevated)',
                opacity: avail ? 1 : 0.45, cursor: avail ? 'pointer' : 'not-allowed',
              }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 16, color: info.color }}>{info.icon}</span>
                <span style={{ fontWeight: 700, fontSize: 13 }}>{info.label}</span>
                {active && <span style={{ fontSize: 9, fontWeight: 700, color: info.color, marginLeft: 'auto' }}>ACTIVE</span>}
                {/* "NOT FOUND" only when the tool itself is missing; installed-but-needs-a-sign-in/key is "NOT SET UP" */}
                {!avail && <span style={{ fontSize: 9, color: 'var(--red)', marginLeft: 'auto' }}>
                  {/not found|not installed/i.test(engines[id]?.note || '') ? 'NOT FOUND' : 'NOT SET UP'}</span>}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{info.desc}</div>
              {!avail && engines[id]?.note && (
                <div style={{ fontSize: 10.5, color: 'var(--amber)', marginTop: 4 }}>{engines[id].note}</div>
              )}
            </button>
          )
        })}
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, cursor: 'pointer' }}>
        <input type="checkbox" checked={engines.failover} onChange={toggleFailover} disabled={saving} />
        <span>
          <b>Auto-failover</b> — if the active engine fails mid-task (spending cap, repeated timeout, no paid plan),
          automatically retry the same task on the next available engine instead of erroring out.
        </span>
      </label>
      {msg && <div style={{ marginTop: 10, fontSize: 12, color: 'var(--green)' }}>{msg}</div>}
    </Section>
  )
}


function NemotronModelSection() {
  const [model, setModelState] = useState('nvidia/nemotron-3-ultra-550b-a55b')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.getSettings().then(s => {
      const m = (s.models || {}).nemotron
      if (m) setModelState(m)
    }).catch(() => {})
  }, [])

  async function pick(id) {
    setModelState(id)
    try {
      await api.setModel('nemotron', id)
      setMsg('✓ Saved — applies to the next Nemotron agent call')
    } catch (e) { setMsg(e.message || 'Failed to save') }
    setTimeout(() => setMsg(''), 4000)
  }

  return (
    <Section title="Nemotron Model">
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
        The NVIDIA model the Nemotron agent engine runs when it's active or picks up a failover task.
        All options are verified to support tool calling.
      </div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {NEMOTRON_MODELS.map(m => {
          const on = m.id === model
          return (
            <button key={m.id} onClick={() => pick(m.id)} title={m.desc} style={{
              flex: '1 1 130px', padding: '7px 6px', fontSize: 11, fontWeight: on ? 700 : 500,
              borderRadius: 'var(--radius-sm)',
              background: on ? m.color : 'var(--bg-elevated)',
              color: on ? '#fff' : 'var(--text-secondary)',
              border: `1px solid ${on ? m.color : 'var(--border)'}`,
            }}>{m.label}</button>
          )
        })}
      </div>
      {msg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 8 }}>{msg}</div>}
    </Section>
  )
}

const KIMI_MODELS = [
  { id: 'moonshotai/kimi-k3', label: 'Kimi K3', color: '#1783ff',
    desc: '2.8T-param MoE (104B active), 1M context, always-on thinking — long-horizon coding and agentic work' },
]

function KimiModelSection() {
  const [model, setModelState] = useState('moonshotai/kimi-k3')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.getSettings().then(s => {
      const m = (s.models || {}).kimi
      if (m) setModelState(m)
    }).catch(() => {})
  }, [])

  async function pick(id) {
    setModelState(id)
    try {
      await api.setModel('kimi', id)
      setMsg('✓ Saved — applies to the next Kimi K3 agent call')
    } catch (e) { setMsg(e.message || 'Failed to save') }
    setTimeout(() => setMsg(''), 4000)
  }

  return (
    <Section title="Kimi K3 Model">
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
        The NVIDIA-hosted model the Kimi K3 agent engine runs when it's active or picks up a failover task.
        Uses the same NVIDIA key pool as Nemotron (below).
      </div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {KIMI_MODELS.map(m => {
          const on = m.id === model
          return (
            <button key={m.id} onClick={() => pick(m.id)} title={m.desc} style={{
              flex: '1 1 130px', padding: '7px 6px', fontSize: 11, fontWeight: on ? 700 : 500,
              borderRadius: 'var(--radius-sm)',
              background: on ? m.color : 'var(--bg-elevated)',
              color: on ? '#fff' : 'var(--text-secondary)',
              border: `1px solid ${on ? m.color : 'var(--border)'}`,
            }}>{m.label}</button>
          )
        })}
      </div>
      {msg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 8 }}>{msg}</div>}
    </Section>
  )
}

function ColibriModelSection() {
  const [st, setSt] = useState(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    try { setSt(await api.colibriStatus()) } catch {}
  }
  useEffect(() => { refresh() }, [])
  // poll while the model is loading, so the button flips to "running" by itself
  useEffect(() => {
    if (!st?.starting) return
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [st?.starting])

  async function pick(path) {
    setBusy(true)
    try {
      await api.setModel('colibri', path)
      setSt(s => ({ ...s, model: path }))
      setMsg('✓ Saved — the next Colibrì call uses it (a different running model is replaced)')
    } catch (e) { setMsg(e.message || 'Failed to save') }
    finally { setBusy(false); setTimeout(() => setMsg(''), 4000) }
  }
  async function act(fn, ok) {
    setBusy(true)
    try { await fn(); setMsg(ok) } catch (e) { setMsg(e.message || 'Failed') }
    finally { setBusy(false); await refresh(); setTimeout(() => setMsg(''), 5000) }
  }

  const models = st?.models || []
  const gb = b => (b / 1e9).toFixed(1) + ' GB'
  return (
    <Section title="Colibrì Model — local CPU, offline">
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10, lineHeight: 1.6 }}>
        Model folders found on this PC (a folder with <code style={codeStyle}>config.json</code> + <code style={codeStyle}>.safetensors</code> under
        <code style={codeStyle}>C:\</code> or <code style={codeStyle}>~/Models</code>). Pick <b>Colibrì (local CPU)</b> as the Agent Engine above, or in the
        Workspace Assistant's own dropdown. The model is kept in RAM while the server runs — use <b>Stop</b> to free it.
      </div>

      {st && !st.installed && (
        <div style={{ fontSize: 12, color: 'var(--amber)', marginBottom: 10 }}>
          Colibrì isn't installed where I looked (<code style={codeStyle}>C:\colibri-src\c</code>, <code style={codeStyle}>C:\colibri</code>).
          Set <code style={codeStyle}>colibri_dir</code> in <code style={codeStyle}>~/.noveltea-engine/config.json</code> if it's elsewhere.
        </div>
      )}
      {st?.installed && !models.length && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 10 }}>
          No model folders found — download one, e.g. <code style={codeStyle}>hf download Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64 --local-dir C:\qwen36_i4_gs64</code>.
        </div>
      )}

      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {models.map(m => {
          const on = m.path === st.model
          return (
            <button key={m.path} onClick={() => pick(m.path)} disabled={busy}
              title={`${m.path}${m.model_type ? ' · ' + m.model_type : ''}`}
              style={{
                flex: '1 1 170px', padding: '7px 6px', fontSize: 11, fontWeight: on ? 700 : 500,
                borderRadius: 'var(--radius-sm)',
                background: on ? '#14b8a6' : 'var(--bg-elevated)',
                color: on ? '#fff' : 'var(--text-secondary)',
                border: `1px solid ${on ? '#14b8a6' : 'var(--border)'}`,
              }}>
              {m.name}
              <div style={{ fontSize: 9, opacity: 0.75, fontWeight: 500 }}>{m.size ? gb(m.size) : ''}</div>
            </button>
          )
        })}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: st?.running ? 'var(--green)' : st?.starting ? 'var(--amber)' : 'var(--text-muted)' }}>
          {st?.running ? `● running · ${st.model_id || ''}` : st?.starting ? '◌ loading the model…' : '○ stopped'}
        </span>
        {!st?.running && !st?.starting && (
          <button className="btn-ghost" disabled={busy || !st?.installed || !st?.model}
            onClick={() => act(() => api.colibriStart(), 'Starting — the model takes a while to load')}
            style={{ padding: '4px 12px', fontSize: 11 }}>▶ Start</button>
        )}
        {(st?.running || st?.starting) && (
          <button className="btn-ghost" disabled={busy}
            onClick={() => act(() => api.colibriStop(), 'Stopped — RAM freed')}
            style={{ padding: '4px 12px', fontSize: 11 }}>■ Stop</button>
        )}
        <button className="btn-ghost" onClick={refresh} disabled={busy} style={{ padding: '4px 12px', fontSize: 11 }}>↻ Refresh</button>
      </div>
      {msg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 8 }}>{msg}</div>}
    </Section>
  )
}

function OllamaModelSection() {
  const [data, setData] = useState({ running: false, models: [], current: '', endpoint: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    try { setData(await api.listOllamaModels()) } catch {}
  }
  useEffect(() => { refresh() }, [])

  async function pick(name) {
    setBusy(true)
    try {
      await api.setModel('ollama', name)
      setData(d => ({ ...d, current: name }))
      setMsg(`✓ Saved — the assistant will use ${name}`)
    } catch (e) { setMsg(e.message || 'Failed to save') }
    finally { setBusy(false); setTimeout(() => setMsg(''), 4000) }
  }

  return (
    <Section title="Ollama Model — local, offline">
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10, lineHeight: 1.6 }}>
        Models installed on this PC. Pick <b>Ollama (local)</b> as the Agent Engine above to use one.
        Runs entirely offline — no key, no cost, nothing leaves the machine.
        Pull more with <code style={codeStyle}>ollama pull qwen2.5-coder</code>.
      </div>

      {!data.running && (
        <div style={{ fontSize: 12, color: 'var(--amber)', marginBottom: 10 }}>
          Ollama isn't answering on <code style={codeStyle}>{data.endpoint || 'http://127.0.0.1:11434'}</code> —
          start it, then Refresh.
        </div>
      )}

      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {(data.models || []).map(m => {
          const on = m.name === data.current
          return (
            <button key={m.name} onClick={() => pick(m.name)} disabled={busy}
              title={`${m.family || ''} · ${m.size ? (m.size / 1e9).toFixed(1) + ' GB' : ''}`}
              style={{
                flex: '1 1 150px', padding: '7px 6px', fontSize: 11, fontWeight: on ? 700 : 500,
                borderRadius: 'var(--radius-sm)',
                background: on ? '#0ea5e9' : 'var(--bg-elevated)',
                color: on ? '#fff' : 'var(--text-secondary)',
                border: `1px solid ${on ? '#0ea5e9' : 'var(--border)'}`,
              }}>
              {m.name}
              <div style={{ fontSize: 9, opacity: 0.75, fontWeight: 500 }}>
                {m.size ? (m.size / 1e9).toFixed(1) + ' GB' : ''}
              </div>
            </button>
          )
        })}
        {data.running && !(data.models || []).length && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No models pulled yet — run <code style={codeStyle}>ollama pull qwen2.5-coder</code>.
          </div>
        )}
      </div>

      <button className="btn-ghost" onClick={refresh} disabled={busy}
        style={{ marginTop: 10, padding: '5px 12px', fontSize: 11 }}>↻ Refresh</button>
      {msg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 8 }}>{msg}</div>}
    </Section>
  )
}

function NemotronKeyPoolSection() {
  const [data, setData] = useState({ keys: [], active_index: -1 })
  const [keyInput, setKeyInput] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [health, setHealth] = useState(null)

  async function refresh() {
    try { setData(await api.listNemotronKeys()) } catch {}
    try { setHealth(await api.nemotronHealth()) } catch {}
  }
  useEffect(() => { refresh() }, [])

  async function add() {
    if (!keyInput.trim()) return
    setBusy(true)
    try {
      const r = await api.addNemotronKey(keyInput.trim(), label.trim() || undefined)
      setMsg(r.already_pooled ? 'Already in pool' : `Added "${r.label}"`)
      setKeyInput(''); setLabel('')
      await refresh()
    } catch (e) { setMsg(e.message || 'Failed to add') }
    finally { setBusy(false); setTimeout(() => setMsg(''), 3000) }
  }
  async function remove(index) {
    try {
      await api.removeNemotronKey(index);
      await refresh()
    } catch (e) {
      setMsg(e.message || 'Failed to remove')
    }
  }

  return (
    <Section title="Nemotron Key Pool — NVIDIA key shared by the Nemotron and Kimi K3 agents">
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12, lineHeight: 1.6 }}>
        Powers the Nemotron bash agent, which turns plain-English requests into shell commands.
        The same keys also power the Kimi K3 agent, so there's no separate Kimi pool.
        Get a key at <code style={codeStyle}>build.nvidia.com</code> (starts with{' '}
        <code style={codeStyle}>nvapi-</code>). Every command is checked against a 45-command
        allowlist, destructive commands (<code style={codeStyle}>rm</code>,{' '}
        <code style={codeStyle}>mv</code>, <code style={codeStyle}>sudo</code>…) are always blocked,
        and <b>you approve each command before it runs</b>.
      </div>
      {health && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10, fontFamily: 'monospace' }}>
          model: {health.default_model}
        </div>
      )}

      {/* Key adder — always visible */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <input
          type="text"
          value={keyInput}
          onChange={e => setKeyInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="nvapi-..."
          style={{
            flex: 1, minWidth: 200, padding: '6px 10px', fontSize: 12,
            borderRadius: 'var(--radius-sm)', fontFamily: 'monospace',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          }}
        />
        <input
          type="text"
          value={label}
          onChange={e => setLabel(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="Label (optional)"
          style={{
            width: 140, padding: '6px 10px', fontSize: 12,
            borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          }}
        />
        <button onClick={add} disabled={busy || !keyInput.trim()} style={{
          padding: '6px 14px', fontSize: 12, fontWeight: 600,
          borderRadius: 'var(--radius-sm)',
          background: keyInput.trim() ? 'var(--accent)' : 'var(--bg-elevated)',
          color: keyInput.trim() ? '#0b1220' : 'var(--text-muted)',
          border: '1px solid var(--border)', cursor: keyInput.trim() ? 'pointer' : 'not-allowed',
        }}>
          {busy ? 'Adding…' : '＋ Add Key'}
        </button>
      </div>

      {(data.keys || []).length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>No keys pooled yet — add your first NVIDIA Nemotron key above.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {(data.keys || []).map((k, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
              borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)',
              border: `1px solid ${i === data.active_index ? '#76b900' : 'var(--border-soft)'}`,
            }}>
              <span style={{ fontSize: 12, fontWeight: 600 }}>{k.label}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>{k.masked}</span>
              {i === data.active_index && <span style={{ fontSize: 9, fontWeight: 700, color: '#76b900' }}>ACTIVE</span>}
              <button onClick={() => remove(i)} style={{
                marginLeft: 'auto', padding: '3px 10px', fontSize: 11, borderRadius: 'var(--radius-sm)',
                background: 'transparent', color: 'var(--red)', border: '1px solid var(--red)',
              }}>Remove</button>
            </div>
          ))}
        </div>
      )}
      {msg && <div style={{ fontSize: 11, marginTop: 8, color: msg.startsWith('✓') || msg.startsWith('Added') ? 'var(--green)' : 'var(--red)' }}>{msg}</div>}
    </Section>
  )
}

function AccountsSection() {
  const [data, setData] = useState({ accounts: [], logged_in: false, live_fingerprint: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [label, setLabel] = useState('')
  // Shared store slice (cliModel/loadCliModel/setCliModel in useStore.js) —
  // no longer surfaced in the TitleBar (per-model picking was removed there
  // in favor of provider-only selection via AgentEngineDropdown), but this
  // Settings page still exposes the specific-model picker.
  const { cliModel, loadCliModel, setCliModel } = useStore()
  const [modelMsg, setModelMsg] = useState('')
  // Headless login flow — see CodexAccountsSection's identical pattern below.
  // Claude's flow additionally may ask for a pasted-back code (awaiting_code).
  const [loginFlow, setLoginFlow] = useState({ status: 'idle', url: null, output: '', awaiting_code: false })
  const [pasteCode, setPasteCode] = useState('')
  const loginPollRef = useRef(null)

  async function refresh() {
    try {
      const accountData = await api.listAccounts()
      setData(accountData)
    } catch (e) {
      setMsg(e.message || 'Failed to load accounts')
    }
  }
  useEffect(() => {
    refresh()
    if (!cliModel) loadCliModel()
    return () => stopLoginPoll()
  }, [])

  function stopLoginPoll() {
    if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null }
  }
  async function login() {
    setMsg('')
    stopLoginPoll()
    setPasteCode('')
    setLoginFlow({ status: 'running', url: null, output: '', awaiting_code: false })
    try {
      await api.launchLogin()
    } catch (e) {
      setLoginFlow({ status: 'failed', url: null, output: e.message || 'Could not start login', awaiting_code: false })
      return
    }
    loginPollRef.current = setInterval(async () => {
      try {
        const s = await api.claudeLoginStatus()
        setLoginFlow(s)
        if (s.status === 'success' || s.status === 'failed') {
          stopLoginPoll()
          if (s.status === 'success') {
            // Auto-add: the whole point of the headless flow is one click
            // instead of "log in, then remember to also click Add Current
            // Account" — so pool it immediately rather than waiting on a
            // second manual step.
            try {
              const r = await api.addAccount(label.trim() || null)
              setMsg(r.already_pooled ? `✓ Logged in — already in pool as "${r.name}"` : `✓ Logged in and added to pool as "${r.name}"`)
              setLabel('')
            } catch (e) {
              setMsg(`✓ Logged in, but couldn't auto-add to pool: ${e.message || 'unknown error'}`)
            }
            await refresh()
          }
        }
      } catch (e) {
        stopLoginPoll()
        setLoginFlow({ status: 'failed', url: null, output: e.message || 'Lost connection to login status', awaiting_code: false })
      }
    }, 1000)
  }
  async function cancelLogin() {
    stopLoginPoll()
    try { await api.cancelClaudeLogin() } catch (e) { /* best-effort */ }
    setLoginFlow({ status: 'idle', url: null, output: '', awaiting_code: false })
  }
  async function submitCode() {
    if (!pasteCode.trim()) return
    try {
      await api.submitClaudeLoginCode(pasteCode.trim())
      setPasteCode('')
      setLoginFlow(f => ({ ...f, awaiting_code: false }))
    } catch (e) { setMsg(e.message || 'Could not submit code') }
  }

  async function pickModel(id) {
    try {
      await setCliModel(id)
      setModelMsg('✓ Saved — applies to the next AI call, no restart needed')
    } catch (e) { setModelMsg(e.message || 'Failed to save') }
    setTimeout(() => setModelMsg(''), 4000)
  }

  async function add() {
    setBusy(true); setMsg('')
    try {
      const r = await api.addAccount(label.trim() || null)
      setMsg(r.already_pooled ? `Already in pool as "${r.name}"` : `Added "${r.name}"`)
      setLabel('')
      await refresh()
    } catch (e) { setMsg(e.message || 'Failed') }
    finally { setBusy(false); setTimeout(() => setMsg(''), 3000) }
  }
  async function use(name) {
    setMsg('')
    try {
      await api.useAccount(name);
      await refresh()
      setMsg(`✓ Switched to account "${name}"`)
    } catch (e) {
      setMsg(e.message || 'Failed to switch account')
    }
  }
  async function remove(name) {
    setMsg('')
    try {
      await api.removeAccount(name);
      await refresh()
      setMsg(`✓ Removed account "${name}"`)
    } catch (e) {
      setMsg(e.message || 'Failed to remove account')
    }
  }
  return (
    <>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>CLI Subscription Accounts</h2>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Add multiple Claude accounts. When one hits its usage limit during extraction, the pipeline
          rotates to the next account with a <b>still-valid</b> token. Expired snapshots are skipped
          (re-add them). OAuth tokens are short-lived, so accounts need occasional re-adding.
        </div>
      </div>

      <AgentEngineSection />
      <OllamaModelSection />
      <ColibriModelSection />
      <NemotronModelSection />
      <KimiModelSection />
      <NemotronKeyPoolSection />

      <Section title="CLI Model">
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
          The Claude model for every app AI button <b>and</b> the corpus extraction pipeline
          (whenever the Claude engine handles the call). Heavier models burn subscription quota faster.
        </div>
        <div style={{ display: 'flex', gap: 5 }}>
          {CLI_MODELS.map(m => {
            const on = m.id === cliModel
            return (
              <button key={m.id} onClick={() => pickModel(m.id)} title={m.desc} style={{
                flex: 1, padding: '7px 6px', fontSize: 11, fontWeight: on ? 700 : 500,
                borderRadius: 'var(--radius-sm)',
                background: on ? m.color : 'var(--bg-elevated)',
                color: on ? '#0b1220' : 'var(--text-secondary)',
                border: `1px solid ${on ? m.color : 'var(--border)'}`,
                transition: 'all 0.12s', whiteSpace: 'nowrap',
              }}>{m.label}</button>
            )
          })}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6 }}>
          {(CLI_MODELS.find(m => m.id === cliModel) || CLI_MODELS[0]).desc}
        </div>
        {modelMsg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 6 }}>{modelMsg}</div>}
      </Section>

      <Section title="How to add an account">
        <ol style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8, paddingLeft: 18, margin: 0 }}>
          <li>Click <b>Log in to Claude</b>, then sign in at the link that appears below — it's added to the pool the moment you paste the code back in (next step), no extra click needed.</li>
          <li>On this PC a browser tab opens by itself too, but that tab opens <i>on this PC</i> — if you're signing in from a phone or another device, use the link instead, not the auto-opened tab.</li>
          <li><b>After you approve the sign-in, the page shows a code.</b> Copy it and paste it into the box that appears here — this is required, the login can't finish without it.</li>
          <li>Repeat for each additional account you want in the rotation.</li>
        </ol>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          <button onClick={login} disabled={loginFlow.status === 'running'} style={{
            padding: '8px 16px', fontWeight: 700, fontSize: 12, borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--accent)',
            opacity: loginFlow.status === 'running' ? 0.6 : 1,
          }}>{loginFlow.status === 'running' ? '⏳ Waiting for login…' : '⛒ Log in to Claude'}</button>
          {loginFlow.status === 'running' && (
            <button onClick={cancelLogin} style={{
              padding: '8px 14px', fontWeight: 600, fontSize: 12, borderRadius: 'var(--radius-sm)',
              background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)',
            }}>Cancel</button>
          )}
        </div>
        {loginFlow.status === 'running' && (
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 10, padding: '10px 12px',
                       background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
            {loginFlow.url ? (
              <>
                On this PC a tab may have opened by itself — that tab is local to this PC, so on another
                device use this link instead:{' '}
                <a href={loginFlow.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>click here to sign in</a>.
              </>
            ) : 'Starting login…'}
            {loginFlow.awaiting_code && (
              <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 'var(--radius-sm)',
                           background: 'rgba(217,119,6,0.12)', border: '1px solid var(--accent)' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)', marginBottom: 6 }}>
                  ⏸ Waiting for the code — after you approve in the browser, it shows you a code. Paste it here:
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input value={pasteCode} onChange={e => setPasteCode(e.target.value)} autoFocus
                    placeholder="Paste the code shown after signing in"
                    style={{ flex: 1, padding: '7px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)',
                             background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} />
                  <button onClick={submitCode} disabled={!pasteCode.trim()} style={{
                    padding: '7px 14px', fontWeight: 700, fontSize: 12, borderRadius: 'var(--radius-sm)',
                    background: 'var(--accent)', color: '#fff', border: 'none', opacity: pasteCode.trim() ? 1 : 0.6,
                  }}>Submit</button>
                </div>
              </div>
            )}
          </div>
        )}
        {loginFlow.status === 'failed' && (
          <div style={{ fontSize: 12, color: 'var(--red)', marginTop: 10, padding: '10px 12px',
                       background: 'var(--red-dim)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--red)' }}>
            Login failed or was cancelled.{loginFlow.output ? ` (${loginFlow.output.slice(-200)})` : ''}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <input value={label} onChange={e => setLabel(e.target.value)} placeholder="label (optional, e.g. work)"
            style={{ flex: 1, minWidth: 160, padding: '8px 11px', fontSize: 12, borderRadius: 'var(--radius-sm)',
                     background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} />
          <button onClick={add} disabled={busy || !data.logged_in} style={{
            padding: '8px 16px', fontWeight: 700, fontSize: 12, borderRadius: 'var(--radius-sm)',
            background: data.logged_in ? 'linear-gradient(135deg,#059669,#0891b2)' : 'var(--bg-elevated)',
            color: data.logged_in ? '#fff' : 'var(--text-muted)', border: 'none',
          }}>{busy ? 'Adding…' : '＋ Add Current Account'}</button>
        </div>
        {!data.logged_in && (
          <div style={{ fontSize: 11, color: 'var(--amber)', marginTop: 8 }}>
            No Claude login detected — click <b>Log in to Claude</b> above first.
          </div>
        )}
        {msg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 8 }}>{msg}</div>}
      </Section>

      <Section title={`Account Pool (${(data.accounts || []).length})`}>
        {(data.accounts || []).length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>No accounts pooled yet.</div>
        )}
        {(data.accounts || []).map(a => (
          <div key={a.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px',
            border: `1px solid ${a.is_live ? 'var(--accent)' : 'var(--border-soft)'}`, borderRadius: 'var(--radius-sm)', marginBottom: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{a.name}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>…{a.fingerprint}</span>
            {a.is_live && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent-light)',
              border: '1px solid var(--accent)', padding: '1px 7px', borderRadius: 10 }}>ACTIVE</span>}
            {a.expired && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)',
              border: '1px solid var(--amber)', padding: '1px 7px', borderRadius: 10 }}
              title="Token expired — re-add this account to refresh it">EXPIRED</span>}
            <div style={{ flex: 1 }} />
            {!a.is_live && !a.expired && <button onClick={() => use(a.name)} style={miniBtn}>Use</button>}
            <button onClick={() => remove(a.name)} style={{ ...miniBtn, color: 'var(--red)', borderColor: 'var(--red)' }}>Remove</button>
          </div>
        ))}
      </Section>
    </>
  )
}

const codeStyle = { background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 6px', fontFamily: 'monospace' }
const miniBtn = { fontSize: 11, padding: '3px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }

// Mirrors AccountsSection above line-for-line, pointed at the Codex CLI's
// account pool (~/.codex/auth.json + corpus/codex_accounts/*.json) instead
// of Claude's. Kept as its own component (rather than parameterizing
// AccountsSection) so each stays simple to read independently.
function CodexAccountsSection() {
  const [data, setData] = useState({ accounts: [], logged_in: false, live_fingerprint: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [label, setLabel] = useState('')
  const { codexModel, loadCodexModel, setCodexModel } = useStore()
  const [modelMsg, setModelMsg] = useState('')
  // Headless login flow — replaces the old "opens a terminal window" button.
  // loginFlow.status mirrors the backend's _CODEX_LOGIN_STATE: 'idle' | 'running' | 'success' | 'failed'.
  const [loginFlow, setLoginFlow] = useState({ status: 'idle', url: null, output: '' })
  const loginPollRef = useRef(null)

  async function refresh() {
    try {
      const accountData = await api.listCodexAccounts()
      setData(accountData)
    } catch (e) {
      setMsg(e.message || 'Failed to load accounts')
    }
  }
  useEffect(() => {
    refresh()
    if (!codexModel) loadCodexModel()
  }, [])

  async function pickModel(id) {
    try {
      await setCodexModel(id)
      setModelMsg('✓ Saved — applies to the next AI call, no restart needed')
    } catch (e) { setModelMsg(e.message || 'Failed to save') }
    setTimeout(() => setModelMsg(''), 4000)
  }

  async function add() {
    setBusy(true); setMsg('')
    try {
      const r = await api.addCodexAccount(label.trim() || null)
      setMsg(r.already_pooled ? `Already in pool as "${r.name}"` : `Added "${r.name}"`)
      setLabel('')
      await refresh()
    } catch (e) { setMsg(e.message || 'Failed') }
    finally { setBusy(false); setTimeout(() => setMsg(''), 3000) }
  }
  async function use(name) {
    setMsg('')
    try {
      await api.useCodexAccount(name);
      await refresh()
      setMsg(`✓ Switched to account "${name}"`)
    } catch (e) {
      setMsg(e.message || 'Failed to switch account')
    }
  }
  async function remove(name) {
    setMsg('')
    try {
      await api.removeCodexAccount(name);
      await refresh()
      setMsg(`✓ Removed account "${name}"`)
    } catch (e) {
      setMsg(e.message || 'Failed to remove account')
    }
  }
  // Headless login: no terminal window — start `codex login` hidden in the
  // background, then poll /login/status every second for the auth URL (in
  // case the browser didn't auto-open) and for success/failure, exactly like
  // watching the old terminal window but rendered right in Settings instead.
  function stopLoginPoll() {
    if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null }
  }
  useEffect(() => () => stopLoginPoll(), [])   // stop polling if the user navigates away mid-login

  async function login() {
    setMsg('')
    stopLoginPoll()
    setLoginFlow({ status: 'running', url: null, output: '' })
    try {
      await api.launchCodexLogin()
    } catch (e) {
      setLoginFlow({ status: 'failed', url: null, output: e.message || 'Could not start login' })
      return
    }
    loginPollRef.current = setInterval(async () => {
      try {
        const s = await api.codexLoginStatus()
        setLoginFlow(s)
        if (s.status === 'success' || s.status === 'failed') {
          stopLoginPoll()
          if (s.status === 'success') {
            // Auto-add — same reasoning as the Claude section above.
            try {
              const r = await api.addCodexAccount(label.trim() || null)
              setMsg(r.already_pooled ? `✓ Logged in — already in pool as "${r.name}"` : `✓ Logged in and added to pool as "${r.name}"`)
              setLabel('')
            } catch (e) {
              setMsg(`✓ Logged in, but couldn't auto-add to pool: ${e.message || 'unknown error'}`)
            }
            await refresh()
          }
        }
      } catch (e) {
        stopLoginPoll()
        setLoginFlow({ status: 'failed', url: null, output: e.message || 'Lost connection to login status' })
      }
    }, 1000)
  }
  async function cancelLogin() {
    stopLoginPoll()
    try { await api.cancelCodexLogin() } catch (e) { /* best-effort — the flow is being abandoned either way */ }
    setLoginFlow({ status: 'idle', url: null, output: '' })
  }

  return (
    <>
      <div style={{ marginBottom: 20, marginTop: 28 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Codex CLI (OpenAI) Accounts</h2>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Add multiple ChatGPT accounts signed into the Codex CLI. When one hits its usage limit,
          the pipeline rotates to the next account with a <b>still-valid</b> token. Expired snapshots
          are skipped (re-add them). Requires <code style={codeStyle}>codex</code> on PATH
          (<code style={codeStyle}>npm install -g @openai/codex</code>).
        </div>
      </div>

      <Section title="Codex Model">
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
          The model passed to <code style={codeStyle}>codex exec -m</code> whenever the Codex engine handles a call.
        </div>
        <div style={{ display: 'flex', gap: 5 }}>
          {CODEX_MODELS.map(m => {
            const on = m.id === codexModel
            return (
              <button key={m.id} onClick={() => pickModel(m.id)} title={m.desc} style={{
                flex: 1, padding: '7px 6px', fontSize: 11, fontWeight: on ? 700 : 500,
                borderRadius: 'var(--radius-sm)',
                background: on ? m.color : 'var(--bg-elevated)',
                color: on ? '#0b1220' : 'var(--text-secondary)',
                border: `1px solid ${on ? m.color : 'var(--border)'}`,
                transition: 'all 0.12s', whiteSpace: 'nowrap',
              }}>{m.label}</button>
            )
          })}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6 }}>
          {(CODEX_MODELS.find(m => m.id === codexModel) || CODEX_MODELS[0]).desc}
        </div>
        {modelMsg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 6 }}>{modelMsg}</div>}
      </Section>

      <Section title="How to add a Codex account">
        <ol style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8, paddingLeft: 18, margin: 0 }}>
          <li>Click <b>Log in to Codex</b> and sign into a ChatGPT account in the browser tab that opens — it's added to the pool automatically the moment login succeeds, no extra click needed.</li>
          <li>Repeat for each additional account you want in the rotation.</li>
        </ol>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          <button onClick={login} disabled={loginFlow.status === 'running'} style={{
            padding: '8px 16px', fontWeight: 700, fontSize: 12, borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--accent)',
            opacity: loginFlow.status === 'running' ? 0.6 : 1,
          }}>{loginFlow.status === 'running' ? '⏳ Waiting for login…' : '⛒ Log in to Codex'}</button>
          {loginFlow.status === 'running' && (
            <button onClick={cancelLogin} style={{
              padding: '8px 14px', fontWeight: 600, fontSize: 12, borderRadius: 'var(--radius-sm)',
              background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)',
            }}>Cancel</button>
          )}
        </div>
        {loginFlow.status === 'running' && (
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 10, padding: '10px 12px',
                       background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
            {loginFlow.url ? (
              <>
                A browser tab should have opened automatically. If not,{' '}
                <a href={loginFlow.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>click here to sign in</a>.
              </>
            ) : 'Starting login…'}
          </div>
        )}
        {loginFlow.status === 'failed' && (
          <div style={{ fontSize: 12, color: 'var(--red)', marginTop: 10, padding: '10px 12px',
                       background: 'var(--red-dim)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--red)' }}>
            Login failed or was cancelled.{loginFlow.output ? ` (${loginFlow.output.slice(-200)})` : ''}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <input value={label} onChange={e => setLabel(e.target.value)} placeholder="label (optional, e.g. work)"
            style={{ flex: 1, minWidth: 160, padding: '8px 11px', fontSize: 12, borderRadius: 'var(--radius-sm)',
                     background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} />
          <button onClick={add} disabled={busy || !data.logged_in} style={{
            padding: '8px 16px', fontWeight: 700, fontSize: 12, borderRadius: 'var(--radius-sm)',
            background: data.logged_in ? 'linear-gradient(135deg,#059669,#0891b2)' : 'var(--bg-elevated)',
            color: data.logged_in ? '#fff' : 'var(--text-muted)', border: 'none',
          }}>{busy ? 'Adding…' : '＋ Add Current Account'}</button>
        </div>
        {!data.logged_in && (
          <div style={{ fontSize: 11, color: 'var(--amber)', marginTop: 8 }}>
            No Codex login detected — run <code style={codeStyle}>codex login</code> in a terminal first.
          </div>
        )}
        {msg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 8 }}>{msg}</div>}
      </Section>

      <Section title={`Account Pool (${(data.accounts || []).length})`}>
        {(data.accounts || []).length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>No accounts pooled yet.</div>
        )}
        {(data.accounts || []).map(a => (
          <div key={a.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px',
            border: `1px solid ${a.is_live ? 'var(--accent)' : 'var(--border-soft)'}`, borderRadius: 'var(--radius-sm)', marginBottom: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{a.name}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>…{a.fingerprint}</span>
            {a.is_live && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent-light)',
              border: '1px solid var(--accent)', padding: '1px 7px', borderRadius: 10 }}>ACTIVE</span>}
            {a.expired && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)',
              border: '1px solid var(--amber)', padding: '1px 7px', borderRadius: 10 }}
              title="Token expired — re-add this account to refresh it">EXPIRED</span>}
            <div style={{ flex: 1 }} />
            {!a.is_live && !a.expired && <button onClick={() => use(a.name)} style={miniBtn}>Use</button>}
            <button onClick={() => remove(a.name)} style={{ ...miniBtn, color: 'var(--red)', borderColor: 'var(--red)' }}>Remove</button>
          </div>
        ))}
      </Section>
    </>
  )
}

// ── Gemini CLI account pool ───────────────────────────────────────────────────
// Same shape as the Claude and Codex sections above: Sign in with Google, the account lands in the
// pool, and the app + corpus pipeline rotate to the next account when one hits its limit. API keys
// are the optional second half of the same rotation (tried after every signed-in account). The pool
// itself lives in corpus/llm_client.py; each account keeps its own Gemini CLI home folder.
function GeminiAccountsSection() {
  const [data, setData] = useState({ accounts: [], keys: [], cli: {}, model: '' })
  const [label, setLabel] = useState('')
  const [keyInput, setKeyInput] = useState('')
  const [keyLabel, setKeyLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [modelMsg, setModelMsg] = useState('')
  // Headless sign-in, mirrors the Codex flow: 'idle' | 'running' | 'success' | 'failed'.
  const [loginFlow, setLoginFlow] = useState({ status: 'idle', url: null, output: '' })
  const loginPollRef = useRef(null)
  const { geminiModel, loadGeminiModel, setGeminiModel, loadAgentEngines } = useStore()

  function stopLoginPoll() {
    if (loginPollRef.current) { clearInterval(loginPollRef.current); loginPollRef.current = null }
  }
  function flash(text, ms = 3500) { setMsg(text); setTimeout(() => setMsg(''), ms) }

  async function refresh() {
    try {
      const d = await api.listGeminiAccounts()
      setData(d)
      if (d.login?.status === 'running' && !loginPollRef.current) resumePoll()   // sign-in started before this page opened
    } catch (e) { setMsg(e.message || 'Failed to load Gemini accounts') }
  }
  useEffect(() => {
    refresh()
    if (!geminiModel) loadGeminiModel()
    return () => stopLoginPoll()
  }, [])

  async function pickModel(id) {
    try {
      await setGeminiModel(id)
      setModelMsg('✓ Saved — applies to the next Gemini call, no restart needed')
    } catch (e) { setModelMsg(e.message || 'Failed to save') }
    setTimeout(() => setModelMsg(''), 4000)
  }

  function resumePoll(relogin) {
    stopLoginPoll()
    loginPollRef.current = setInterval(async () => {
      try {
        const s = await api.geminiLoginStatus()
        setLoginFlow(s)
        if (s.status !== 'running') {
          stopLoginPoll()
          if (s.status === 'success') {
            setLabel('')
            flash(`✓ Signed in — "${s.account}" is ${relogin ? 'working again' : 'now in the pool'}`, 6000)
            await refresh()
            loadAgentEngines?.()
          }
        }
      } catch (e) {
        stopLoginPoll()
        setLoginFlow({ status: 'failed', url: null, output: e.message || 'Lost connection to sign-in status' })
      }
    }, 1000)
  }

  async function login(relogin) {
    setMsg('')
    setLoginFlow({ status: 'running', url: null, output: '' })
    try {
      await api.launchGeminiLogin(label.trim(), relogin)
    } catch (e) {
      setLoginFlow({ status: 'failed', url: null, output: e.message || 'Could not start sign-in' })
      return
    }
    resumePoll(relogin)
  }
  async function cancelLogin() {
    stopLoginPoll()
    try { await api.cancelGeminiLogin() } catch (e) { /* best-effort — the flow is being abandoned either way */ }
    setLoginFlow({ status: 'idle', url: null, output: '' })
  }

  async function use(kind, opts, what) {
    try { await api.useGemini(kind, opts); flash(`✓ Now using ${what}`); await refresh() }
    catch (e) { flash(e.message || 'Failed to switch') }
  }
  async function removeAccount(name) {
    if (!window.confirm(`Remove Google account "${name}" from the pool? Its Gemini sign-in is deleted from this PC.`)) return
    try { await api.removeGeminiAccount(name); flash(`✓ Removed "${name}"`); await refresh(); loadAgentEngines?.() }
    catch (e) { flash(e.message || 'Failed to remove') }
  }
  async function addKey() {
    const k = keyInput.trim()
    if (!k) return
    setBusy(true)
    try {
      const r = await api.addGeminiKey(k, keyLabel.trim() || undefined)
      setKeyInput(''); setKeyLabel('')
      flash(r.already_pooled ? 'That key is already in the pool.' : `✓ Added key "${r.label}"`)
      await refresh(); loadAgentEngines?.()
    } catch (e) { flash(e.message || 'Failed to add key') }
    finally { setBusy(false) }
  }
  async function removeKey(idx, lbl) {
    if (!window.confirm(`Remove API key "${lbl}" from the pool?`)) return
    try { await api.removeGeminiKey(idx); flash('✓ Removed key'); await refresh(); loadAgentEngines?.() }
    catch (e) { flash(e.message || 'Failed to remove key') }
  }

  const running = loginFlow.status === 'running'
  const accounts = data.accounts || []
  const keys = data.keys || []
  const badge = (text, color, title) => (
    <span title={title} style={{ fontSize: 10, fontWeight: 700, color, border: `1px solid ${color}`, padding: '1px 7px', borderRadius: 10 }}>{text}</span>
  )
  const inputStyle = { padding: '8px 11px', fontSize: 12, borderRadius: 'var(--radius-sm)',
                       background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-primary)' }

  return (
    <>
      <div style={{ marginBottom: 20, marginTop: 28 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Gemini CLI (Google) Accounts</h2>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Sign in with one or more Google accounts. When one hits its usage limit, the app and the corpus
          pipeline rotate to the next account — then to any API keys below. An account whose sign-in stops
          working is skipped (marked <b>NEEDS SIGN-IN</b>) instead of stalling a job. Requires the Gemini CLI
          (<code style={codeStyle}>npm install -g @google/gemini-cli</code>).
        </div>
        {!data.cli?.global && (
          <div style={{ fontSize: 11, marginTop: 8, color: data.cli?.npx ? 'var(--amber)' : 'var(--red)' }}>
            {data.cli?.npx
              ? <>The Gemini CLI isn't installed globally, so it runs through <code style={codeStyle}>npx</code> — works, but every call is slower. Install it with <code style={codeStyle}>npm install -g @google/gemini-cli</code>.</>
              : <>The Gemini CLI isn't installed and <code style={codeStyle}>npx</code> isn't available — install Node.js, then <code style={codeStyle}>npm install -g @google/gemini-cli</code>.</>}
          </div>
        )}
      </div>

      <Section title="Gemini Model">
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
          The model passed to <code style={codeStyle}>gemini --model</code> whenever the Gemini engine handles a call.
        </div>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          {GEMINI_MODELS.map(m => {
            const on = m.id === geminiModel
            return (
              <button key={m.id} onClick={() => pickModel(m.id)} title={m.desc} style={{
                flex: 1, minWidth: 110, padding: '7px 6px', fontSize: 11, fontWeight: on ? 700 : 500,
                borderRadius: 'var(--radius-sm)',
                background: on ? m.color : 'var(--bg-elevated)',
                color: on ? '#0b1220' : 'var(--text-secondary)',
                border: `1px solid ${on ? m.color : 'var(--border)'}`,
                transition: 'all 0.12s', whiteSpace: 'nowrap',
              }}>{m.label}</button>
            )
          })}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6 }}>
          {(GEMINI_MODELS.find(m => m.id === geminiModel) || GEMINI_MODELS[0]).desc}
        </div>
        {modelMsg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 6 }}>{modelMsg}</div>}
      </Section>

      <Section title="How to add a Google account">
        <ol style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8, paddingLeft: 18, margin: 0 }}>
          <li>Click <b>Sign in with Google</b> and choose an account in the browser tab that opens on this PC — it's added to the pool the moment the sign-in finishes, no extra click needed.</li>
          <li>Repeat for each additional Google account you want in the rotation.</li>
        </ol>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          <input value={label} onChange={e => setLabel(e.target.value)} disabled={running}
            placeholder="name (optional — defaults to the account's email)" style={{ ...inputStyle, flex: 1, minWidth: 200 }} />
          <button onClick={() => login()} disabled={running} style={{
            padding: '8px 16px', fontWeight: 700, fontSize: 12, borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid #4285f4',
            opacity: running ? 0.6 : 1,
          }}>{running ? '⏳ Waiting for sign-in…' : '✦ Sign in with Google'}</button>
          {running && (
            <button onClick={cancelLogin} style={{
              padding: '8px 14px', fontWeight: 600, fontSize: 12, borderRadius: 'var(--radius-sm)',
              background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)',
            }}>Cancel</button>
          )}
        </div>
        {running && (
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 10, padding: '10px 12px',
                       background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
            {loginFlow.url ? (
              <>
                A browser tab should have opened on this PC. If not,{' '}
                <a href={loginFlow.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>click here to sign in</a>.
              </>
            ) : 'Starting the Gemini CLI…'}
          </div>
        )}
        {loginFlow.status === 'failed' && (
          <div style={{ fontSize: 12, color: 'var(--red)', marginTop: 10, padding: '10px 12px',
                       background: 'var(--red-dim)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--red)' }}>
            Sign-in failed or was cancelled.{loginFlow.output ? ` (${loginFlow.output.slice(-240)})` : ''}
          </div>
        )}
        {msg && <div style={{ fontSize: 11, color: 'var(--green)', marginTop: 8 }}>{msg}</div>}
      </Section>

      <Section title={`Account Pool (${accounts.length} account${accounts.length === 1 ? '' : 's'}${keys.length ? ` + ${keys.length} API key${keys.length === 1 ? '' : 's'}` : ''})`}>
        {accounts.length === 0 && keys.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>No Google accounts signed in yet.</div>
        )}
        {accounts.map(a => (
          <div key={a.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', flexWrap: 'wrap',
            border: `1px solid ${a.is_active ? 'var(--accent)' : a.needs_login ? 'var(--amber)' : 'var(--border-soft)'}`,
            borderRadius: 'var(--radius-sm)', marginBottom: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{a.name}</span>
            {a.email && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{a.email}</span>}
            {a.is_active && badge('ACTIVE', 'var(--accent-light)')}
            {a.needs_login && badge('NEEDS SIGN-IN', 'var(--amber)', 'Its sign-in stopped working — it is skipped in the rotation until you sign in again')}
            <div style={{ flex: 1 }} />
            {a.needs_login
              ? <button onClick={() => login(a.name)} disabled={running} style={{ ...miniBtn, color: 'var(--amber)', borderColor: 'var(--amber)' }}>Sign in again</button>
              : !a.is_active && <button onClick={() => use('account', { name: a.name }, `"${a.name}"`)} style={miniBtn}>Use</button>}
            <button onClick={() => removeAccount(a.name)} style={{ ...miniBtn, color: 'var(--red)', borderColor: 'var(--red)' }}>Remove</button>
          </div>
        ))}

        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)', margin: '14px 0 6px' }}>
          API keys <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>— optional, tried after the signed-in accounts
          (free keys from <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>Google AI Studio</a>)</span>
        </div>
        {keys.map(k => (
          <div key={k.index} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px',
            border: `1px solid ${k.is_active ? 'var(--accent)' : 'var(--border-soft)'}`, borderRadius: 'var(--radius-sm)', marginBottom: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{k.label}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>{k.masked}</span>
            {k.is_active && badge('ACTIVE', 'var(--accent-light)')}
            <div style={{ flex: 1 }} />
            {!k.is_active && <button onClick={() => use('key', { keyIndex: k.index }, `key "${k.label}"`)} style={miniBtn}>Use</button>}
            <button onClick={() => removeKey(k.index, k.label)} style={{ ...miniBtn, color: 'var(--red)', borderColor: 'var(--red)' }}>Remove</button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
          <input value={keyLabel} onChange={e => setKeyLabel(e.target.value)} placeholder="key label (optional)"
            style={{ ...inputStyle, width: 170 }} />
          <input type="password" value={keyInput} onChange={e => setKeyInput(e.target.value)} placeholder="AI Studio API key (AIza…)"
            style={{ ...inputStyle, flex: 1, minWidth: 200 }} />
          <button onClick={addKey} disabled={busy || !keyInput.trim()} className="btn-primary" style={{ padding: '7px 16px', fontSize: 12 }}>
            {busy ? 'Adding…' : '＋ Add API Key'}
          </button>
        </div>
      </Section>
    </>
  )
}

export default function SettingsPage() {
  const [corpusPath, setCorpusPath] = useState('')
  const [pathNote, setPathNote] = useState('')
  const [savedKeys, setSavedKeys] = useState({})
  const [savedModels, setSavedModels] = useState({})
  const [genCfg, setGenCfg] = useState({ default_provider: 'anthropic', temperature: 0.85, max_tokens: 4096, grep_mode: 'fast', verbatim_splice: false })
  const [pathSaved, setPathSaved] = useState(false)
  const [pathError, setPathError] = useState(null)
  const [genSaved, setGenSaved] = useState(false)
  const [activeSection, setActiveSection] = useState(() => {
    const want = useStore.getState().settingsSection   // e.g. the title-bar status dot asks for 'server'
    if (want) { useStore.setState({ settingsSection: null }); return want }
    try { return localStorage.getItem('nm-settings-section') || 'accounts' } catch { return 'accounts' }   // the section last open
  })
  useEffect(() => { try { localStorage.setItem('nm-settings-section', activeSection) } catch { /* private mode */ } }, [activeSection])
  // Settings can already be open when the dot is clicked — apply the request then too
  const wantSection = useStore(s => s.settingsSection)
  useEffect(() => {
    if (wantSection) { setActiveSection(wantSection); useStore.setState({ settingsSection: null }) }
  }, [wantSection])
  const [restartState, setRestartState] = useState('idle')  // idle | confirm | restarting | back | timeout
  const [restartElapsed, setRestartElapsed] = useState(0)

  async function doRestart() {
    setRestartState('restarting')
    setRestartElapsed(0)
    let oldPid = null
    try {
      oldPid = (await api.restartServer())?.pid ?? null
    } catch {
      // The request itself may fail to complete a clean response if the
      // server exits mid-response — that's expected, not an error.
    }
    // Poll /api/health until the fresh process answers, then reload the page
    // so the whole app (not just Settings) is talking to the new instance.
    // A packaged one-file exe re-unpacks itself on every launch, which was
    // observed taking 60-90s on this machine — a short timeout here gave up
    // and told the user something was wrong while the app was still booting.
    const start = Date.now()
    const poll = setInterval(async () => {
      const elapsed = Date.now() - start
      setRestartElapsed(Math.round(elapsed / 1000))
      if (elapsed > 120000) { clearInterval(poll); setRestartState('timeout'); return }
      try {
        const h = await api.health()
        // the old instance can still answer for a moment while it shuts down: wait for a different one
        if (oldPid != null && h?.pid === oldPid) return
        clearInterval(poll)
        setRestartState('back')
        setTimeout(() => window.location.reload(), 600)
      } catch { /* still down, keep polling */ }
    }, 1000)
  }

  useEffect(() => {
    api.getSettings().then(s => {
      setCorpusPath(s.corpus_path || '')
      setSavedKeys(s.api_keys || {})
      setSavedModels(s.models || {})
      if (s.generation) setGenCfg(s.generation)
    }).catch(() => {})
  }, [])

  async function savePath() {
    setPathError(null)
    try {
      const r = await api.setCorpusPath(corpusPath)
      setPathNote(r && r.restart_required ? 'Saved. The folder was prepared (raw, novels, projects, generated and the pipeline scripts). Restart the app to use it.' : '')
      setPathSaved(true)
      setTimeout(() => setPathSaved(false), 2500)
    } catch (e) {
      setPathError(e.message)
    }
  }

  async function handleSaveKey(provider, key, model) {
    await api.saveApiKey(provider, key, model)
    const s = await api.getSettings()
    setSavedKeys(s.api_keys || {})
    setSavedModels(s.models || {})
  }

  async function handleDeleteKey(provider) {
    await api.deleteApiKey(provider)
    const s = await api.getSettings()
    setSavedKeys(s.api_keys || {})
  }

  async function saveGenSettings() {
    await api.saveGenerationSettings(genCfg)
    setGenSaved(true)
    setTimeout(() => setGenSaved(false), 2500)
  }

  const NAV = [
    { id: 'ai',       label: 'AI & API Keys',  icon: '◈', disabled: true },
    { id: 'accounts', label: 'CLI Accounts',   icon: '⛒' },
    { id: 'corpus',   label: 'Corpus & Paths', icon: '▣' },
    { id: 'backend',  label: 'Backend',        icon: '⊞' },
    { id: 'server',   label: 'Server',         icon: '▤' },   // CPU / RAM / the app's processes, shown inside Settings
    { id: 'voices',   label: 'Voice Samples',  icon: '♪' },
    { id: 'phone',    label: 'Phone & Notifications', icon: '🔔' },
  ]

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Tab bar — works on both desktop and mobile */}
      <div style={{
        display: 'flex', flexShrink: 0,
        borderBottom: '1px solid var(--border-soft)',
        background: 'var(--bg-surface)',
        overflowX: 'auto', scrollbarWidth: 'none',
      }}>
        {NAV.map(n => (
          <button
            key={n.id}
            onClick={() => n.disabled ? null : setActiveSection(n.id)}
            disabled={n.disabled}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
              padding: '10px 16px', fontSize: 12,
              fontWeight: activeSection === n.id ? 600 : 400,
              color: n.disabled
                ? 'var(--text-muted)'
                : activeSection === n.id
                  ? 'var(--text-primary)'
                  : 'var(--text-secondary)',
              borderBottom: activeSection === n.id ? '2px solid var(--accent)' : '2px solid transparent',
              borderRadius: 0, transition: 'color 0.12s',
              opacity: n.disabled ? 0.45 : 1,
              cursor: n.disabled ? 'not-allowed' : 'pointer',
            }}
          >
            <span style={{ color: n.disabled ? 'var(--text-muted)' : activeSection === n.id ? 'var(--accent-light)' : 'var(--text-muted)' }}>{n.icon}</span>
            {n.label}
            {n.disabled && <span style={{ fontSize: 9, marginLeft: 6, color: 'var(--text-muted)' }}>⤫</span>}
          </button>
        ))}
      </div>

      {/* Server tab: the whole Server page, in place — it scrolls itself and wants the full width */}
      {activeSection === 'server' && <ServerPage />}

      {/* content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px', maxWidth: 780, display: activeSection === 'server' ? 'none' : undefined }}>

        {activeSection === 'voices' && <VoiceSamples />}
        {activeSection === 'phone' && <PhoneSetup />}

        {activeSection === 'ai' && (
          <>
            <div style={{ marginBottom: 20 }}>
              <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>AI & API Keys</h2>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Keys are stored locally in <code style={{ background: 'var(--bg-elevated)', padding: '1px 5px', borderRadius: 3 }}>~/.noveltea-engine/config.json</code> and never sent anywhere except the provider's API.
              </div>
            </div>

            {/* Claude Code CLI zero-config banner */}
            <div style={{
              display: 'flex', alignItems: 'flex-start', gap: 12,
              padding: '14px 16px', marginBottom: 16,
              background: 'rgba(16,185,129,0.08)',
              border: '1px solid rgba(16,185,129,0.3)',
              borderRadius: 'var(--radius-lg)',
            }}>
              <div style={{ fontSize: 24, flexShrink: 0 }}>◈</div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--green)', marginBottom: 4 }}>
                  Claude Code CLI — Zero Config
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  <b>No API key needed.</b> If no key is configured below, all generation automatically uses your
                  Claude Code subscription via the <code style={{ background: 'var(--bg-elevated)', padding: '1px 5px', borderRadius: 3 }}>claude -p</code>
                  that's already running this app. Add an API key below only if you want to use a different provider or bypass the CLI.
                </div>
              </div>
            </div>

            <Section title="API Keys (optional — leave blank to use Claude Code CLI)">
              {PROVIDERS.map(p => (
                <ApiKeyCard
                  key={p.id}
                  provider={p}
                  savedKeys={savedKeys}
                  models={p.models}
                  onSave={handleSaveKey}
                  onDelete={handleDeleteKey}
                />
              ))}
            </Section>

            <Section title="Generation Settings">
              <FieldRow label="Default Provider" hint="Which AI provider to use for generating novel content.">
                <select value={genCfg.default_provider} onChange={e => setGenCfg(g => ({ ...g, default_provider: e.target.value }))}
                  style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
                  {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </FieldRow>

              <FieldRow label="Temperature" hint={`Controls creativity (0 = precise, 1 = creative). Current: ${genCfg.temperature}`}>
                <input type="range" min={0} max={1} step={0.05} value={genCfg.temperature}
                  onChange={e => setGenCfg(g => ({ ...g, temperature: Number(e.target.value) }))}
                  style={{ width: '100%', accentColor: 'var(--accent)' }} />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                  <span>Precise (0)</span>
                  <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{genCfg.temperature}</span>
                  <span>Creative (1)</span>
                </div>
              </FieldRow>

              <FieldRow label="Max Tokens" hint="Maximum tokens per generation call. Higher = longer output.">
                <select value={genCfg.max_tokens} onChange={e => setGenCfg(g => ({ ...g, max_tokens: Number(e.target.value) }))}
                  style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
                  {[1024, 2048, 4096, 8192].map(n => <option key={n} value={n}>{n.toLocaleString()} tokens</option>)}
                </select>
              </FieldRow>

              <FieldRow label="Corpus Grep Intensity" hint="How generation pulls from the corpus. Applies to all Generate & Update buttons (each can override).">
                <GrepSlider value={genCfg.grep_mode || 'fast'} onChange={v => setGenCfg(g => ({ ...g, grep_mode: v }))} />
              </FieldRow>

              <button onClick={saveGenSettings} className="btn-primary" style={{ padding: '7px 20px', fontSize: 12 }}>
                {genSaved ? '✓ Saved' : 'Save Generation Settings'}
              </button>
            </Section>
          </>
        )}

        {activeSection === 'accounts' && (
          <>
            <AccountsSection />
            <CodexAccountsSection />
            <GeminiAccountsSection />
          </>
        )}

        {activeSection === 'corpus' && (
          <>
            <div style={{ marginBottom: 20 }}>
              <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Corpus & Paths</h2>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Point NovelTea Engine at your corpus directory.</div>
            </div>
            <Section title="Corpus Path">
              <FieldRow label="NovelTea Engine Corpus Directory" hint="Root folder containing novels/, projects/, character_dna/, narrative_patterns/.">
                <input
                  value={corpusPath}
                  onChange={e => setCorpusPath(e.target.value)}
                  placeholder="C:\path\to\your\corpus (created if it does not exist)"
                  style={{ width: '100%', padding: '7px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', marginBottom: 8 }}
                />
                {pathError && <div style={{ color: 'var(--red)', fontSize: 11, marginBottom: 6 }}>{pathError}</div>}
                {pathNote && <div style={{ color: 'var(--green)', fontSize: 11, marginBottom: 6 }}>{pathNote}</div>}
                <button onClick={savePath} className="btn-primary" style={{ padding: '6px 18px', fontSize: 12 }}>
                  {pathSaved ? '✓ Saved' : 'Save Path'}
                </button>
              </FieldRow>
            </Section>
          </>
        )}

        {activeSection === 'backend' && (
          <>
            <div style={{ marginBottom: 20 }}>
              <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Backend</h2>
            </div>
            <Section title="FastAPI Backend">
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
                Running at <span style={{ color: 'var(--accent)', fontFamily: 'monospace' }}>http://127.0.0.1:7432</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
                Start manually:
                <div style={{ marginTop: 6, padding: '8px 12px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', fontFamily: 'monospace', fontSize: 11, color: 'var(--teal)' }}>
                  cd NovelTeaApp/backend<br/>
                  pip install fastapi uvicorn pydantic<br/>
                  python main.py
                </div>
              </div>
              <div style={{ padding: '10px 14px', background: 'var(--bg-elevated)', borderRadius: 'var(--radius)', fontSize: 11 }}>
                <div style={{ fontWeight: 600, marginBottom: 8, color: 'var(--text-secondary)' }}>Registered Routes</div>
                {[
                  ['GET/POST', '/api/projects', 'Project CRUD'],
                  ['POST',     '/api/generate/field', 'AI field generation'],
                  ['GET/POST', '/api/settings', 'App settings & API keys'],
                  ['GET',      '/api/corpus/stats', 'Corpus overview'],
                  ['POST',     '/api/engines/plan', 'Chapter planner'],
                  ['POST',     '/api/engines/generate', 'Chapter writer'],
                ].map(([method, path, desc]) => (
                  <div key={path} style={{ display: 'flex', gap: 10, padding: '3px 0', borderBottom: '1px solid var(--border-soft)', alignItems: 'center' }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 9, color: 'var(--amber)', minWidth: 70 }}>{method}</span>
                    <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--teal)', flex: 1 }}>{path}</span>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{desc}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="Restart Server">
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
                Restarts the whole app — useful after it's become slow or unresponsive without closing and
                reopening it yourself. The app briefly goes offline (a few seconds) and this page reloads
                automatically once it's back. Anything unsaved (an open generation, an unsent chat message) will
                be lost, same as if you closed the app normally.
              </div>
              {restartState === 'idle' && (
                <button onClick={() => setRestartState('confirm')} style={{
                  padding: '8px 16px', fontSize: 12, fontWeight: 600,
                  background: 'var(--bg-elevated)', border: '1px solid var(--red, #ef4444)',
                  borderRadius: 'var(--radius-sm)', color: 'var(--red, #ef4444)',
                }}>⟳ Restart Server</button>
              )}
              {restartState === 'confirm' && (
                <div style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid var(--red, #ef4444)', borderRadius: 'var(--radius)' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>Restart now? Unsaved work in progress will be lost.</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={doRestart} style={{ padding: '6px 14px', fontSize: 11, fontWeight: 700, background: 'var(--red, #ef4444)', color: '#fff', borderRadius: 'var(--radius-sm)' }}>Yes, restart</button>
                    <button onClick={() => setRestartState('idle')} style={{ padding: '6px 14px', fontSize: 11, background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)' }}>Cancel</button>
                  </div>
                </div>
              )}
              {restartState === 'restarting' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
                  <Spinner size={12} /> Restarting — waiting for the server to come back… ({restartElapsed}s
                  {restartElapsed > 20 ? ' — a packaged app can take a while to re-unpack and boot, this is normal' : ''})
                </div>
              )}
              {restartState === 'back' && (
                <div style={{ fontSize: 12, color: 'var(--green, #10b981)', fontWeight: 600 }}>✓ Back online — reloading…</div>
              )}
              {restartState === 'timeout' && (
                <div style={{ padding: '10px 14px', background: 'var(--amber-dim)', border: '1px solid var(--amber, #f59e0b)', borderRadius: 'var(--radius)' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Still not responding after 2 minutes. It may still be starting, or it may need a manual relaunch.
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button onClick={() => window.location.reload()} style={{ padding: '6px 14px', fontSize: 11, fontWeight: 700, background: 'var(--accent)', color: '#fff', borderRadius: 'var(--radius-sm)' }}>Try reloading</button>
                    <button onClick={() => setRestartState('idle')} style={{ padding: '6px 14px', fontSize: 11, background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)' }}>Dismiss</button>
                  </div>
                </div>
              )}
            </Section>
          </>
        )}
      </div>
    </div>
  )
}